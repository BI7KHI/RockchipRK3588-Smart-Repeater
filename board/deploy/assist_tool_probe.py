# -*- coding: utf-8 -*-
"""稳定性探针 v3：严格镜像生产配置（只读工具集）跑工具选择。

与生产一致的三点：
  1. 工具清单来自 agent_service.tools_prompt(只读工具名列表)；
  2. 提示词 = 库里的 assist_prompt_suffix + 【当前问题】；
  3. 解析用 parse_tool_calls(valid=只读工具名列表)。
"""
import json
import sqlite3
import sys

import requests

sys.path.insert(0, '/www')
import agent_service
import voice_service

# 持住租约：voice_service 的维护线程会卸载「空闲」的 LLM，
# 探针直接打 HTTP 不经过 llm_lease，不持租约就会被卸载（实测踩过）。
voice_service.llm_start(wait=90)

DB = '/www/relay.db'
URL = 'http://127.0.0.1:8001/v1/chat/completions'
TRIALS = 4

c = sqlite3.connect(DB)
st = {k: v for k, v in c.execute("SELECT key,value FROM settings")}

# 生产口径：只读工具（speak 是 action=True，助手不允许用）
RO = [t['name'] for t in agent_service.enabled_tools(None) if not t.get('action')]
base = (st.get('llm_system_prompt') or '').strip()
suffix = (st.get('assist_prompt_suffix') or '').strip().replace('{max_chars}', '80')
tp = agent_service.tools_prompt(RO)
head = '\n'.join([x for x in (base, suffix) if x])

CASES = [
    ('现在风速多少', ['get_weather']),
    ('风速风向如何', ['get_weather']),
    ('今天下雨了吗', ['get_rain']),
    ('电池电压是多少', ['get_power']),
    ('板子温度正常吗', ['get_system']),
    ('内存还剩多少', ['get_system']),
    ('你现在在发射吗', ['get_radio']),
    ('现在几点了', ['get_time']),
    ('中继台的气象和电压', ['get_weather', 'get_power']),
]


def ask(q, temperature=0.3):
    prompt = ('【系统设定】\n' + head if head else '') + '\n\n【当前问题】\n' + q
    content = prompt + '\n\n' + tp + '\n现在只输出一行读取指令（格式 READ 名称 {}），不要回答用户。'
    body = {'model': 'qwen2.5-1.5b', 'messages': [{'role': 'user', 'content': content}],
            'max_tokens': 256, 'temperature': temperature, 'stream': False}
    voice_service.llm_lease(300)
    try:
        r = requests.post(URL, json=body, timeout=180)
        raw = (r.json()['choices'][0]['message']['content'] or '').strip()
    except Exception:
        # 被卸载了就重新拉起再试一次
        voice_service.llm_start(wait=90)
        r = requests.post(URL, json=body, timeout=180)
        raw = (r.json()['choices'][0]['message']['content'] or '').strip()
    finally:
        voice_service.llm_lease(300)
    return raw, [x['name'] for x in agent_service.parse_tool_calls(raw, valid=RO)]


first = ('【系统设定】\n' + head if head else '') + '\n\n【当前问题】\n现在风速多少'
print('生产口径第一轮提示词总长 = %d 字（system %d + tools %d + 收尾指令 32）'
      % (len(first) + len(tp) + 32, len(head), len(tp)))
print('只读工具：%s' % RO)
print('=' * 74)
bad = []
for q, expect in CASES:
    got, raws = [], []
    for _ in range(TRIALS):
        raw, names = ask(q)
        raws.append(raw[:26].replace('\n', ' '))
        got.append(names[0] if names else '(无)')
    hit = sum(1 for g in got if g in expect)
    ok = (hit == TRIALS)
    if not ok:
        bad.append((q, expect, got))
    print('%s %-14s 期望 %-18s 实得 %s' % (
        'OK  ' if ok else 'WARN', q, ','.join(expect), got))
    if not ok:
        for r_ in raws:
            print('        原文：%s' % r_)

print('=' * 74)
print('稳定命中 %d/%d，不稳定 %d 个' % (len(CASES) - len(bad), len(CASES), len(bad)))

# ---- 端到端：真实取数 + 总结 ----
print('\n=== 端到端（真实取数 → 总结）===')
for q, tool in (('现在风速多少', 'get_weather'), ('电池电压是多少', 'get_power')):
    raw, names = ask(q)
    if not names:
        print('  %s：第一轮未给出指令（%r）' % (q, raw[:40]))
        continue
    res = None
    if names[0] == 'get_weather':
        import weather_service
        rt = weather_service.WeatherService(DB).realtime()
        res = {'wind_ms': rt.get('last_speed'), 'running': bool(rt.get('running'))}
    elif names[0] == 'get_power':
        import subprocess
        try:
            b = open('/sys/bus/iio/devices/iio:device0/in_voltage0_raw').read().strip()
            res = {'raw': b}
        except Exception as e:
            res = {'error': str(e)[:60]}
    content2 = ('设备实时数据：' + json.dumps([{names[0]: res}], ensure_ascii=False)[:280] +
                '\n请用中文 1~3 句回答：' + q)
    body = {'model': 'qwen2.5-1.5b', 'messages': [{'role': 'user', 'content': content2}],
            'max_tokens': 256, 'temperature': 0.3, 'stream': False}
    r = requests.post(URL, json=body, timeout=180)
    ans = (r.json()['choices'][0]['message']['content'] or '').strip()
    print('  %-14s %s -> %s' % (q, json.dumps(res, ensure_ascii=False)[:48], ans[:70]))
