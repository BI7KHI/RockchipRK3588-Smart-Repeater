#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板上 PTT 自动验证：登录网页 -> 触发 TTS -> 轮询 GPIO97 电平。"""
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
print('login', r.status_code, r.url)
html = s.get(BASE + '/', timeout=5).text
m = re.search(r'name="csrf-token" content="([^"]+)"', html)
tok = m.group(1) if m else csrf

st = s.get(BASE + '/api/ptt/status', timeout=5).json()
print('idle ptt', st.get('ptt'))

log = []
stop = False


def poll():
    last = None
    t0 = time.time()
    while not stop and time.time() - t0 < 20:
        try:
            with open('/sys/class/gpio/gpio97/value') as f:
                v = f.read().strip()
        except Exception as e:
            v = 'ERR:' + str(e)
        if v != last:
            log.append((round(time.time() - t0, 2), v))
            last = v
        time.sleep(0.05)


th = threading.Thread(target=poll)
th.start()
r = s.post(BASE + '/api/tts/speak',
           json={'text': '这是一次PTT自动测试，请确认发射指示灯亮起。'},
           headers={'X-CSRF-Token': tok}, timeout=30)
print('tts', r.status_code, r.text[:300])
time.sleep(7)
stop = True
th.join()
print('gpio transitions', log)
st = s.get(BASE + '/api/ptt/status', timeout=5).json()
print('final ptt', st.get('ptt'))
