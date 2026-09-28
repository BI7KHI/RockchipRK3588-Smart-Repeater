# -*- coding: utf-8 -*-
"""板端·自主回答「实况路径」探针：拿**真实收到的一段录音**跑一遍 _handle → 自主决策。

为什么需要它：`/api/assist/auto/test` 走的是 test_decide，绕过了
feed → _segment → _handle → _auto_try 这条真正的实况链路。而历史上真出问题的地方
恰恰在这条链路上（tx_match AttributeError、KeyError: 'note'）。这个探针把一段真实
的 vlog_rx 录音直接喂进 feed()，用**真的 ASR + 真的本地 LLM**跑完整判定。

安全边界（都是硬保证，不靠设置巧合）：
  * `play_fn` 直接抛异常 —— 只要有任何一处想发射，探针立刻暴露；
  * 影子锁（AUTO_MODES_OPEN 只含 shadow）本就不发射；
  * 库是 /www/relay.db 的**副本**，不污染线上对话记录；
  * `assist_wake_mode` 临时改成 level：喂文件没有真实 BUSY 沿，busy 模式会开不了段。

用法（板端）：python3 /www/deploy/probe_auto_live.py [wav 路径]
"""
import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.request
import wave

sys.path.insert(0, '/www')
import numpy as np                      # noqa: E402
import assistant_service as A           # noqa: E402

DB_SRC = '/www/relay.db'
DB = '/tmp/auto_probe.db'
SR = 16000
PLAY = {'n': 0}
FEED = {'blocks': 0}


def log(msg):
    print(msg, flush=True)


def pick_wav():
    if len(sys.argv) > 1:
        return sys.argv[1]
    days = sorted([d for d in os.listdir('/opt/ai/relay_voice')
                   if d.startswith('20')])
    for day in reversed(days):
        d = os.path.join('/opt/ai/relay_voice', day)
        ws = [os.path.join(d, f) for f in os.listdir(d)
              if f.endswith('.wav') and '_rx_' in f]
        if ws:
            ws.sort(key=os.path.getmtime)
            return ws[-1]
    raise SystemExit('没有找到任何 rx 录音')


def read_settings():
    c = sqlite3.connect(DB)
    out = {}
    try:
        for k, v in c.execute('SELECT key, value FROM settings'):
            out[str(k)] = '' if v is None else str(v)
    except Exception as e:
        log('读设置失败：%s' % e)
    c.close()
    return out


def load_wav(path):
    w = wave.open(path)
    ch, sr, sw, n = w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()
    raw = w.readframes(n)
    w.close()
    log('录音：%s  %d 声道 %d Hz %d bit %.1f 秒'
        % (os.path.basename(path), ch, sr, sw * 8, n / float(sr)))
    if sw != 2:
        raise SystemExit('只支持 16bit')
    a = np.frombuffer(raw, dtype=np.int16)
    if ch == 2:
        mono = a.reshape(-1, 2)[:, 0].copy()
    else:
        mono = a.copy()
    if sr != SR:
        # 线性重采样到 16k（探针用，精度够）
        idx = np.linspace(0, len(mono) - 1, int(len(mono) * SR / float(sr)))
        mono = np.interp(idx, np.arange(len(mono)), mono).astype(np.int16)
        log('  已重采样 %d → %d Hz' % (sr, SR))
    return mono


def ask_raw(msgs, temperature=0.1, max_tokens=48, timeout=60):
    """决策用的纯文本调用：直接打本机 rkllm-server（与 app._assist_ask_raw 同构）。"""
    t0 = time.time()
    url = os.environ.get('PROBE_LLM_URL', 'http://127.0.0.1:8001/v1/chat/completions')
    body = json.dumps({'model': 'qwen2.5-1.5b', 'messages': msgs,
                       'temperature': temperature, 'max_tokens': int(max_tokens),
                       'stream': False}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={'Content-Type': 'application/json'})
    out = {'ok': False, 'text': '', 'ms': 0, 'provider': 'probe', 'model': 'local',
           'error': ''}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode('utf-8', 'ignore'))
        out['text'] = ((d.get('choices') or [{}])[0].get('message') or {}).get(
            'content') or ''
        out['text'] = out['text'].strip()
        out['ok'] = bool(out['text'])
        if not out['ok']:
            out['error'] = '模型空输出'
    except Exception as e:
        out['error'] = '%s: %s' % (type(e).__name__, e)
    out['ms'] = int((time.time() - t0) * 1000)
    return out


def tts(text, voice=''):
    p = '/tmp/auto_probe_tts.wav'
    with wave.open(p, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b'\x00\x00' * SR)      # 1 秒静音，探针不关心内容
    return p


def play(path, max_seconds=30.0):
    PLAY['n'] += 1
    raise RuntimeError('探针禁止发射（play_fn 被调用 = 有地方想发射）')


def ask_fn(prompt, question='', max_tokens=256, temperature=0.3, use_tools=True,
           max_iters=2, sysprompt=''):
    return {'ok': True, 'reply': '探针：这是影子试答的假回复喵', 'ms': 1,
            'provider': 'probe', 'model': 'probe', 'iters': 1, 'tools': ''}


def main():
    if not os.path.exists(DB_SRC):
        raise SystemExit('找不到 %s' % DB_SRC)
    for suffix in ('', '-wal', '-shm'):
        if os.path.exists(DB_SRC + suffix):
            shutil.copy2(DB_SRC + suffix, DB + suffix)
        elif os.path.exists(DB + suffix):
            os.unlink(DB + suffix)
    log('库副本：%s' % DB)

    st = read_settings()
    log('线上设置：wake_mode=%s auto=%s/%s 测试模式=%s 禁发=%r 白名单=%r'
        % (st.get('assist_wake_mode'), st.get('assist_auto_enabled'),
           st.get('assist_auto_mode'), st.get('assist_test_mode'),
           st.get('assist_quiet_hours'), st.get('assist_auto_whitelist')))
    # 探针覆盖：只动这三项，其余照用线上值（要验的就是线上配置下的行为）
    st['assist_wake_mode'] = 'level'        # 喂文件没有 BUSY 沿
    # 唤醒词换成一个不可能命中的：这段真实录音里就有人喊「中继台」，唤醒路会正常
    # 发射（那是**原有**行为，不是影子该负责的），会把自主层那条路整个盖过去。
    # 换掉之后，同一段音频就只剩「没命中唤醒词 → 自主决策」这一条路可走。
    st['assist_wake_words'] = '探针占位唤醒词'
    st['assist_enabled'] = '1'
    st['assist_auto_enabled'] = '1'
    st['assist_auto_dry_answer'] = '0'      # 省一轮 LLM；试答链路另有本地套件覆盖
    st['assist_auto_whitelist'] = ''        # 白名单不参与，验的是判定+影子

    mono = load_wav(pick_wav())
    stereo = np.repeat(mono, 2).tobytes()

    svc = A.AssistantService(DB)
    svc.configure(lambda: dict(st), lambda: False, lambda: False,
                  ask_fn, tts, play, lambda: '', None, None, ask_raw)
    svc.start()

    t0 = time.time()
    step = int(0.2 * SR) * 4                # 0.2 秒一块（立体声 → 每块 4 字节/样本对）
    # 末尾补 1 秒静音：录音文件是「一段话」直接切下来的，最后一个段在真实信道里
    # 是靠后续静音收段的；不补就永远停在 speech，工作线程什么也拿不到（实测踩到）。
    stream = stereo + b'\x00\x00\x00\x00' * int(1.0 * SR)
    for i in range(0, len(stream), step):
        svc.feed(stream[i:i + step], ts=t0 + (i / float(step)) * 0.2)
        FEED['blocks'] += 1
        time.sleep(0.01)
    log('已喂入 %d 块（%.1f 秒音频 +1 秒静音收尾）'
        % (FEED['blocks'], len(mono) / float(SR)))

    # 等实况链路跑完：队列空 + 不在识别/思考/合成中，且这个「闲」要连续保持 3 秒
    # （只看一瞬会误判：段已入队但工作线程还没开始跑时，队列恰好是空的）。
    base_recent = len(svc.recent)
    deadline = time.time() + 180
    settled = 0
    while time.time() < deadline:
        pending = ((not svc.q.empty())
                   or svc.stage in ('asr', 'think', 'synth', 'wait', 'tx', 'auto')
                   or svc.auto_dry_running)
        settled = 0 if pending else settled + 1
        if settled >= 6 and len(svc.recent) > base_recent:
            break
        if settled >= 60:               # 30 秒都没东西可处理：别再耗着
            break
        time.sleep(0.5)

    c = dict(svc.counters)
    rows = svc.store.query("SELECT id,kind,action,dry,decision,reason,confidence,"
                           "would_reply,think,heard,tx_seconds FROM assist_turns "
                           "ORDER BY id DESC LIMIT 8")
    log('\n=== 结果 ===')
    log('阶段：%s（%s）' % (svc.stage, svc.stage_detail))
    log('ASR：%r（%sms）' % (((svc.asr_last or {}).get('text') or '（无）'),
                            (svc.asr_last or {}).get('ms')))
    log('计数：segments=%s ignored=%s auto_decided=%s auto_skipped=%s '
        'auto_answered=%s auto_silent=%s auto_shadow_blocked=%s auto_echo_skipped=%s'
        % (c.get('segments'), c.get('ignored'), c.get('auto_decided'),
           c.get('auto_skipped'), c.get('auto_answered'), c.get('auto_silent'),
           c.get('auto_shadow_blocked'), c.get('auto_echo_skipped')))
    log('发射：tx=%s tx_seconds=%s play_fn 调用=%d'
        % (c.get('tx'), c.get('tx_seconds'), PLAY['n']))
    log('最近记录：')
    for r in rows:
        if r['kind'] not in ('auto', 'auto-test'):
            continue
        log('  #%s kind=%s action=%s dry=%s decision=%s reason=%s 信=%s would=%s '
            'tx=%s 想=%r' % (r['id'], r['kind'], r['action'], r['dry'],
                             r['decision'], r['reason'], r['confidence'],
                             r['would_reply'], r['tx_seconds'], (r['think'] or '')[:40]))
    log('错误：%r' % svc.last_error)

    ok = True

    def chk(name, cond, extra=''):
        nonlocal ok
        if cond:
            log('  OK   %s' % name)
        else:
            ok = False
            log('  FAIL %s %s' % (name, extra))

    log('\n=== 断言 ===')
    chk('实况链路真的跑了（有分段）', (c.get('segments') or 0) >= 1, c.get('segments'))
    chk('识别出了内容', bool((svc.asr_last or {}).get('text')),
        (svc.asr_last or {}).get('error'))
    chk('**一次都没调用 play_fn（没发射）**', PLAY['n'] == 0, PLAY['n'])
    chk('tx 计数为 0', not c.get('tx'), c.get('tx'))
    chk('没有被唤醒路径截胡（唤醒词已换成占位词）',
        (c.get('wakes') or 0) == 0, c.get('wakes'))
    chk('自主层参与过（判定或预筛）',
        (c.get('auto_decided') or 0) + (c.get('auto_skipped') or 0) >= 1,
        (c.get('auto_decided'), c.get('auto_skipped')))
    chk('影子期不变式：shadow_blocked == answered',
        c.get('auto_shadow_blocked') == c.get('auto_answered'),
        (c.get('auto_shadow_blocked'), c.get('auto_answered')))
    auto_rows = [r for r in svc.store.query(
        "SELECT * FROM assist_turns WHERE kind IN ('auto','auto-answer')")]
    for r in auto_rows:
        chk('影子行 #%s dry=1' % r['id'], r['dry'] == 1)
        chk('影子行 #%s 没发射（tx_seconds=0）' % r['id'], not r['tx_seconds'])
        chk('影子行 #%s 有判定与结论码' % r['id'],
            r['decision'] in ('answer', 'silent') and bool(r['reason']),
            (r['decision'], r['reason']))
        chk('影子行 #%s 结论只能是 shadow/silent' % r['id'],
            r['reason'] in ('shadow', 'silent'), r['reason'])
    if (c.get('auto_decided') or 0) >= 1:
        chk('真的叫了决策模型并落了库（不是只走预筛）', len(auto_rows) >= 1,
            len(auto_rows))
    log('\n%s' % ('探针通过' if ok else '探针失败'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
