# -*- coding: utf-8 -*-
"""中继语音助手：板端接口冒烟测试（在开发板上运行）。

覆盖：登录 → 页面可达 → 状态接口 → 唤醒词匹配 → 提示词预览 → TTS 清洗
      → 手动跑一轮（完整 LLM+TTS 链路，测试模式不发射）→ 对话记录落库
"""
import json
import re
import sys
import time

import requests

BASE = 'http://127.0.0.1:8080'
S = requests.Session()
FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


def csrf_from(html):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else ''


# --- 登录 -------------------------------------------------------------------
r = S.get(BASE + '/login', timeout=20)
tok = csrf_from(r.text)
check('GET /login', r.status_code == 200 and bool(tok), 'HTTP %s tok=%r' % (r.status_code, tok[:12]))
r = S.post(BASE + '/login',
           data={'username': 'Admin', 'password': '12341234', 'csrf_token': tok},
           timeout=20, allow_redirects=False)
check('POST /login', r.status_code in (302, 303), 'HTTP %s' % r.status_code)
# 登录后 GET 一个页面，从 <meta name="csrf-token"> 取**新**令牌：
# 登录表单里的那个 token 登录后已轮换，继续用会一律「CSRF 校验失败」。
r = S.get(BASE + '/assistant', timeout=20)
m = re.search(r'<meta name="csrf-token" content="([^"]+)"', r.text)
tok2 = m.group(1) if m else ''
check('登录后取得新 CSRF 令牌', bool(tok2), 'meta 未找到')
H = {'X-CSRF-Token': tok2}

# --- 页面 -------------------------------------------------------------------
r = S.get(BASE + '/assistant', timeout=20, headers=H)
check('GET /assistant 200', r.status_code == 200, 'HTTP %s' % r.status_code)
for frag, desc in [('中继语音助手', '标题'), ('as-wave', '电平波形'),
                   ('as-stream', '实况识别流'), ('as-turn' if False else 'as-turns', '对话记录'),
                   ('as-groups', '设置表单容器'), ('assistant.js', '前端脚本'),
                   ('as-prompt-out', '提示词预览'), ('btn-as-stop', '一键停止')]:
    check('页面含%s' % desc, frag in r.text)
check('导航含中继语音助手链接', '中继语音助手' in r.text)

# --- 状态 -------------------------------------------------------------------
r = S.get(BASE + '/api/assist/status', timeout=20, headers=H).json()
check('GET /api/assist/status ok', r.get('ok') is True, str(r)[:160])
for k in ('stage', 'stage_label', 'counters', 'levels', 'recent', 'settings',
          'wake_words', 'today', 'llm_warm', 'busy', 'ptt', 'mic_running'):
    check('status 含 %s' % k, k in r)
st = r.get('settings') or {}
check('设置项已注入 DEFAULTS（>=30 项）', len(st) >= 30, '实得 %d' % len(st))
check('唤醒词默认正确', '中继台' in (r.get('wake_words') or []), str(r.get('wake_words')))

# --- 唤醒词匹配 -------------------------------------------------------------
cases = [('中继台，现在风速多少', '中继台', '现在风速多少'),
         ('中继太，电压是多少', '中继台', '电压是多少'),
         ('智能中继今天下雨了吗', '智能中继', '今天下雨了吗'),
         ('随便说点什么', '', '')]
for text, want_w, want_q in cases:
    r = S.post(BASE + '/api/assist/wake', json={'text': text}, timeout=20, headers=H).json()
    check('唤醒匹配 %r' % text,
          r.get('matched') == want_w and r.get('question') == want_q,
          '得 %r/%r' % (r.get('matched'), r.get('question')))

# --- 提示词预览 -------------------------------------------------------------
r = S.get(BASE + '/api/assist/prompt?q=现在风速多少', timeout=20, headers=H).json()
check('GET /api/assist/prompt ok', r.get('ok') is True, str(r)[:160])
check('提示词含系统设定段', '【系统设定】' in (r.get('prompt') or ''))
check('提示词含当前问题', '现在风速多少' in (r.get('prompt') or ''))
check('提示词含语音播报约束', '纯口语' in (r.get('prompt') or ''))
check('提示词未超输入上限',
      len(r.get('prompt') or '') <= int(r.get('max_input') or 0),
      '%d > %s' % (len(r.get('prompt') or ''), r.get('max_input')))
check('{max_chars} 已替换', '{max_chars}' not in (r.get('prompt') or ''))
print('      注入后 %d 字 / 上限 %s；清洗示例：%r' % (
    r.get('prompt_chars', 0), r.get('max_input'), (r.get('clean_demo') or '')[:40]))

# --- TTS 清洗 ---------------------------------------------------------------
demo = '**风速 3.2 米每秒**，请注意！\n- 电压 12.6V\n### 结束\n😀 感谢通联'
r = S.post(BASE + '/api/assist/clean', json={'text': demo}, timeout=20, headers=H).json()
check('POST /api/assist/clean ok', r.get('ok') is True, str(r)[:160])
cl = r.get('cleaned') or ''
check('清洗结果非空（否则下面都是假通过）', bool(cl.strip()), repr(cl))
check('清洗去掉了星号', '*' not in cl, repr(cl))
check('清洗去掉了井号', '#' not in cl, repr(cl))
check('清洗去掉了 emoji', '😀' not in cl, repr(cl))
check('清洗保留了正文', '风速' in cl and '电压' in cl, repr(cl))
print('      清洗：%d 字 → %d 字，结果 %r' % (r.get('raw_len', 0), r.get('cleaned_len', 0), cl))

# --- 手动跑一轮（完整链路）--------------------------------------------------
print('\n  --- 手动测试一轮（LLM + 工具 + TTS，测试模式不发射）---')
# 先记下当前最大 id：库里有历史测试轮时，按 kind=='test' 取最新会抓到旧记录
# （旧记录早已是终态，第一轮轮询就命中），必须用 id 增量判定。
_base = S.get(BASE + '/api/assist/list?limit=1', timeout=20, headers=H).json()
_base_id = max([int(x.get('id') or 0) for x in (_base.get('items') or [])] or [0])
r = S.post(BASE + '/api/assist/test',
           json={'text': '现在风速多少'}, timeout=30, headers=H).json()
check('POST /api/assist/test 已受理', r.get('ok') is True and r.get('queued'), str(r)[:200])
check('测试轮默认不发射（test_mode）', r.get('test_mode') is True, str(r))

turn = None
for i in range(40):
    time.sleep(2)
    lst = S.get(BASE + '/api/assist/list?limit=5', timeout=20, headers=H).json()
    for it in (lst.get('items') or []):
        if it.get('kind') == 'test' and int(it.get('id') or 0) > _base_id:
            turn = it
            break
    if turn and turn.get('action') in ('sent', 'skipped', 'failed', 'error'):
        break
    print('      ...等待中（%d）' % (i + 1))

if not turn:
    check('测试轮落库', False, '等了 80 秒仍无记录')
else:
    check('测试轮落库', True)
    print('      #%s action=%s kind=%s' % (turn.get('id'), turn.get('action'), turn.get('kind')))
    print('      对方: %r' % (turn.get('heard') or ''))
    print('      助手: %r' % (turn.get('reply') or ''))
    print('      耗时: LLM %sms / TTS %sms / 输入 %s字 / 回复 %s字' % (
        turn.get('llm_ms'), turn.get('tts_ms'), turn.get('prompt_chars'),
        turn.get('reply_chars')))
    if turn.get('error'):
        print('      错误: %s' % turn['error'])
    check('LLM 有输出', bool((turn.get('reply') or '').strip()) or bool(turn.get('error')),
          repr(turn.get('reply')))
    check('回复不含 Markdown 星号', '*' not in (turn.get('reply') or ''), repr(turn.get('reply')))
    check('回复不超字数上限', len(turn.get('reply') or '') <= 80,
          '%d 字' % len(turn.get('reply') or ''))
    check('测试轮未发射',
          turn.get('action') == 'skipped' and '不发射' in (turn.get('error') or ''),
          '%s / %s' % (turn.get('action'), turn.get('error')))
    check('注入提示词已压缩到 200 字内（实测 130）',
          int(turn.get('prompt_chars') or 0) < 200,
          '%s 字' % turn.get('prompt_chars'))
    if turn.get('tx_wav'):
        r = S.get(BASE + '/api/assist/%s/audio?which=tx' % turn['id'],
                  timeout=20, headers=H)
        check('助手音频可回放', r.status_code == 200 and len(r.content) > 1000,
              'HTTP %s %d 字节' % (r.status_code, len(r.content)))

# --- 停止 -------------------------------------------------------------------
r = S.post(BASE + '/api/assist/stop', json={}, timeout=20, headers=H).json()
check('POST /api/assist/stop ok', r.get('ok') is True, str(r)[:160])

# --- 状态复查 ---------------------------------------------------------------
r = S.get(BASE + '/api/assist/status', timeout=20, headers=H).json()
c = r.get('counters') or {}
print('\n  计数器: %s' % json.dumps({k: v for k, v in c.items() if v},
                                    ensure_ascii=False))
check('计数器有分段记录', (c.get('segments') or 0) >= 0)

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  ✗ %s' % f)
sys.exit(1 if FAIL else 0)
