#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板上流式 TTS PTT 自动验证。"""
import re
import threading
import time

import requests

BASE = 'http://127.0.0.1:8080'
USER = 'Admin'
PASSWORD = '12341234'

s = requests.Session()
r = s.get(BASE + '/login', timeout=5)
csrf = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
r = s.post(BASE + '/login', data={'username': USER, 'password': PASSWORD, 'csrf_token': csrf}, timeout=5)
html = s.get(BASE + '/', timeout=5).text
m = re.search(r'name="csrf-token" content="([^"]+)"', html)
tok = m.group(1) if m else csrf

log = []
stop = False


def poll():
    last = None
    t0 = time.time()
    while not stop and time.time() - t0 < 25:
        try:
            with open('/sys/class/gpio/gpio97/value') as f:
                v = f.read().strip()
        except Exception as e:
            v = 'ERR'
        if v != last:
            log.append((round(time.time() - t0, 2), v))
            last = v
        time.sleep(0.05)


th = threading.Thread(target=poll)
th.start()
h = {'X-CSRF-Token': tok, 'Content-Type': 'application/json'}
sid = s.post(BASE + '/api/tts/stream/start', json={}, headers=h, timeout=10).json().get('session_id')
print('sid', sid)
s.post(BASE + '/api/tts/stream/chunk', json={'session_id': sid, 'text': '这是流式PTT测试第一段。'}, headers=h, timeout=10)
time.sleep(1.0)
s.post(BASE + '/api/tts/stream/chunk', json={'session_id': sid, 'text': '第二段继续发射测试。'}, headers=h, timeout=10)
s.post(BASE + '/api/tts/stream/end', json={'session_id': sid}, headers=h, timeout=10)
time.sleep(10)
stop = True
th.join()
print('gpio transitions', log)
print('ptt', s.get(BASE + '/api/ptt/status', timeout=5).json().get('ptt'))
