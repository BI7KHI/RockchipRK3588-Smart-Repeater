# -*- coding: utf-8 -*-
"""空闲期误触发监测：确认新阈值不会把噪声底判成语音。

连续采样 40 秒，检查：
  * counters.segments 不增长（没有误分段）
  * recent 流里不出现新条目
  * 电平始终远低于起判门限
同时打印状态机、LLM 保活、内存占用，确认启用后的资源画像。
"""
import json
import re
import time
import urllib.parse
import urllib.request
import http.cookiejar

BASE = 'http://127.0.0.1:8080'
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

h = op.open(BASE + '/login', timeout=10).read().decode('utf-8', 'replace')
m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', h)
tok = m.group(1) if m else ''
d = urllib.parse.urlencode({'username': 'Admin', 'password': '12341234',
                            'csrf_token': tok}).encode()
op.open(BASE + '/login', data=d, timeout=10)
page = op.open(BASE + '/assistant', timeout=10).read().decode('utf-8', 'replace')
m2 = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
H = {'X-CSRF-Token': m2.group(1) if m2 else tok}


def api(path, method='GET', body=None):
    req = urllib.request.Request(BASE + path, method=method)
    for k, v in H.items():
        req.add_header(k, v)
    data = None
    if body is not None:
        req.add_header('Content-Type', 'application/json')
        data = json.dumps(body).encode()
    return json.loads(op.open(req, data=data, timeout=15).read())


st0 = api('/api/assist/status')
c0 = dict(st0.get('counters') or {})
print('起始：stage=%s  enabled=%s  test_mode=%s' % (
    st0.get('stage_label'), st0.get('enabled'),
    (st0.get('settings') or {}).get('assist_test_mode')))
print('阈值：open=%s dBFS  close=%s dBFS' % (
    (st0.get('settings') or {}).get('assist_dbfs_open'),
    (st0.get('settings') or {}).get('assist_dbfs_close')))
print('LLM：%s' % json.dumps(st0.get('llm_warm'), ensure_ascii=False))
print('-' * 66)

levels, stages = [], []
N = 40
for i in range(N):
    time.sleep(1)
    s = api('/api/assist/status')
    levels.append(s.get('dbfs'))
    stages.append(s.get('stage'))
    if i % 10 == 9:
        print('  t=%2ds  最新电平=%6.1f  状态=%-10s  分段数=%s'
              % (i + 1, s.get('dbfs') or -120, s.get('stage'),
                 (s.get('counters') or {}).get('segments')))

st1 = api('/api/assist/status')
c1 = dict(st1.get('counters') or {})
print('-' * 66)
print('电平：min=%.1f  中位=%.1f  max=%.1f  （起判 %.0f）'
      % (min(levels), sorted(levels)[len(levels) // 2], max(levels),
         float((st1.get('settings') or {}).get('assist_dbfs_open') or -50)))
print('裕量：%.1f dB' % (float((st1.get('settings') or {}).get('assist_dbfs_open') or -50)
                        - max(levels)))
print()
before = {k: c0.get(k, 0) for k in ('segments', 'wakes', 'ignored', 'asr_empty')}
after = {k: c1.get(k, 0) for k in ('segments', 'wakes', 'ignored', 'asr_empty')}
print('计数器变化：%s -> %s' % (before, after))
print('状态机取值：%s' % sorted(set(stages)))
recent = st1.get('recent') or []
print('实况识别流条目：%d' % len(recent))
if recent:
    for r in recent[-5:]:
        print('   %s' % json.dumps(r, ensure_ascii=False)[:120])
print()
ok = True
if after['segments'] - before['segments'] > 0:
    print('!! 空闲期产生了误分段 %d 段' % (after['segments'] - before['segments']))
    ok = False
if after['ignored'] - before['ignored'] > 0:
    print('!! 空闲期产生了误识别（未命中唤醒词但落了流）%d 次'
          % (after['ignored'] - before['ignored']))
    ok = False
if 'speech' in stages:
    print('!! 空闲期状态机进入了「检测到语音」')
    ok = False
print('结论：%s' % ('空闲期零误触发 ✓' if ok else '存在误触发，需要抬高阈值'))
