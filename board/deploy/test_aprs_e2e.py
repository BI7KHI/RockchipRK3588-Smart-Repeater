#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APRS 端到端集成验证：不碰声卡，直接按采集中枢的喂法把合成波形灌进
AprsService.feed()，验证「解码 -> 解析 -> 入库 -> 查询接口」整条链路。

覆盖：
  - 5 种报文类型都能入库且字段正确
  - 去重窗口生效（同内容重复注入只入库一次）
  - 位置点进入 packets_geo（地图数据）
  - stats_payload 统计正确
  - 错误/无关噪声不产生脏数据
  - 发射报文构造（build_packet）字段与路径正确
"""
import json
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '/tmp')
import aprs_service as A


def synth(info, sr=16000, src='BI7KHI', ssid=10):
    fr = A.build_frame(src, 'APRS', [('WIDE1', 1)], info, src_ssid=ssid)   # 注意：路径元组是 (呼号, SSID)
    return A.build_afsk(fr, sr=sr), fr


def feed_service(svc, wave, chunk=1024, noise=0.0):
    """完全模拟 app.py 采集中枢：S16_LE 立体声、每块 4096 字节。"""
    n = 0
    for i in range(0, len(wave), chunk):
        seg = wave[i:i + chunk]
        pcm = np.clip(seg, -1, 1)
        left = (pcm * 32767).astype('<i2')
        if noise:
            left = np.clip(left.astype(np.float32) +
                           np.random.randn(len(left)) * noise * 32767,
                           -32768, 32767).astype('<i2')
        stereo = np.empty(len(left) * 2, dtype='<i2')
        stereo[0::2] = left
        stereo[1::2] = left
        n += svc.feed(stereo.tobytes(), time.time())
    return n


def main():
    db = os.path.join(tempfile.mkdtemp(), 'aprs_test.db')
    svc = A.AprsService(db)
    svc.configure(setting_getter=lambda k, d='': A.DEFAULTS.get(k, d))
    svc.run_flag = False          # 关掉调度线程的定时发射
    ok = True

    cases = [
        ('position', A.aprs_position(22.5333, 114.0500, '/', '-', 'Relay test')),
        ('weather', A.aprs_weather({'wind_ms': 3.5, 'wind_dir': 220, 'gust_ms': 6.0,
                                    'temp_c': 28.4, 'humidity': 65,
                                    'pressure_hpa': 1013.2, 'rain_1h_mm': 0.5,
                                    'rain_today_mm': 2.0},
                                   22.5333, 114.0500, '/', '_', 'WX')),
        ('status', A.aprs_status('relay online')),
        ('telemetry', A.aprs_telemetry(7, [138, 120, 78, 200, 35], '10110000')),
        ('message', A.aprs_message('BI7KHI-7', 'hello de relay', 3)),
    ]

    print('=== 1) 五种报文端到端入库 ===')
    for name, info in cases:
        wave, fr = synth(info)
        got = feed_service(svc, wave)
        rows = svc.list_packets(limit=50)
        hit = [r for r in rows if r['dtype'] == name] if name != 'weather' else \
              [r for r in rows if r['dtype'] in ('weather', 'position')]
        mark = 'OK ' if got and hit else 'FAIL'
        if not got:
            ok = False
        print('   %-10s feed返回=%d  %s  库内共 %d 条' % (name, got, mark, len(rows)))

    print('=== 2) 字段正确性 ===')
    w = [r for r in svc.list_packets(limit=50) if r['dtype'] == 'weather']
    if w:
        r = w[0]
        wx = json.loads(r['wx_json'] or '{}')
        print('   weather: lat=%.6f lon=%.6f wind=%s%%  temp=%s℃  压=%shPa  湿=%s%%'
              % (r['lat'], r['lon'], wx.get('wind_ms'), wx.get('temp_c'),
                 wx.get('pressure_hpa'), wx.get('humidity')))
        exp = {'wind_ms': 3.58, 'temp_c': 28.3, 'pressure_hpa': 1013.2, 'humidity': 65}
        bad = {k: (wx.get(k), v) for k, v in exp.items() if abs((wx.get(k) or 0) - v) > 0.6}
        ok = ok and not bad
        print('   与写入值偏差超限的字段：%s' % (bad or '无'))
        if 'symbol_code' in r:
            print('   符号 %s%s 帧长 %s 路径 %s' % (r['symbol_table'], r['symbol_code'],
                                                  r['frame_len'], r['path']))
    else:
        ok = False
        print('   FAIL: 没有 weather 记录')

    t = [r for r in svc.list_packets(limit=50) if r['dtype'] == 'telemetry']
    if t:
        tel = json.loads(t[0]['telemetry_json'] or '{}')
        print('   telemetry: seq=%s analogs=%s digital=%s'
              % (tel.get('seq'), tel.get('analogs'), tel.get('digital')))
        ok = ok and tel.get('seq') == '007' and tel.get('digital') == '10110000'
    else:
        ok = False
        print('   FAIL: 没有 telemetry 记录')

    m = [r for r in svc.list_packets(limit=50) if r['dtype'] == 'message']
    if m:
        print('   message: to=%s text=%r id=%s' % (m[0]['msg_to'], m[0]['msg_text'],
                                                   m[0]['msg_id']))
        ok = ok and m[0]['msg_to'] == 'BI7KHI-7' and m[0]['msg_id'] == '3'
    else:
        ok = False
        print('   FAIL: 没有 message 记录')

    print('=== 3) 去重窗口 ===')
    before = len(svc.list_packets(limit=100))
    wave, _ = synth(cases[2][1])
    n1 = feed_service(svc, wave)
    after = len(svc.list_packets(limit=100))
    print('   同一 status 再灌一次：feed返回=%d，库内 %d -> %d（应不增加）'
          % (n1, before, after))
    ok = ok and after == before and n1 == 0

    print('=== 4) 地图数据（packets_geo）===')
    geo = svc.packets_geo(minutes=60)
    # 注：home 由路由层补（/api/aprs/geo），packets_geo 本身只返回 stations/tracks/count
    print('   stations=%d tracks=%d count=%d'
          % (len(geo['stations']), len(geo['tracks']), geo['count']))
    ok = ok and len(geo['stations']) >= 1 and geo['count'] >= 1

    print('=== 5) 噪声不产生脏数据 ===')
    noise = (np.random.randn(16000 * 4) * 0.08).astype(np.float32)
    n_before = len(svc.list_packets(limit=200))
    feed_service(svc, noise)
    n_after = len(svc.list_packets(limit=200))
    print('   4 秒白噪声：库内 %d -> %d（应不增加）' % (n_before, n_after))
    ok = ok and n_after == n_before

    print('=== 6) 发射报文构造 ===')
    # 气象源离线时必须拒绝发射「空气象包」，而不是发一条没有测量值的 _WX
    _nofake = A.AprsService.__new__(A.AprsService)
    _nofake.store = svc.store; _nofake.cfg = dict(svc.cfg)
    _nofake.cfg['wx_getter'] = None
    _nofake.lock = svc.lock; _nofake._settings_cache = {'aprs_telemetry_map': '{}'}
    _nofake._settings_ts = time.time(); _nofake.stats = svc.stats
    _nofake.telemetry_seq = 0; _nofake.position = svc.position
    try:
        _nofake.build_packet('weather')
        print('   FAIL: 气象源离线时竟然没有拦截')
        ok = False
    except ValueError as e:
        print('   OK   气象源离线被拦截：%s' % e)

    for pt in ('position', 'weather', 'telemetry', 'status'):
        fake = A.AprsService.__new__(A.AprsService)
        fake.store = svc.store
        fake.cfg = dict(svc.cfg)
        fake.cfg['wx_getter'] = lambda: {'wind_ms': 3.5, 'temp_c': 28.4, 'humidity': 65}
        fake.cfg['power_getter'] = lambda: {'battery_v': 13.8, 'pv_v': 18.2}
        fake.cfg['temp_getter'] = lambda: 57.0
        fake.lock = svc.lock
        fake._settings_cache = {}
        fake._settings_ts = time.time()
        fake.stats = svc.stats
        fake.telemetry_seq = 0
        fake.position = svc.position
        fr, info_text, _to = fake.build_packet(pt, text='test')
        rec = A.parse_packet(fr)
        good = bool(fr) and rec is not None and rec['src'].startswith('BI7KHI')
        print('   %-10s len=%-3d 可以回读=%s  %s' % (pt, len(fr), good, info_text[:64]))
        ok = ok and good

    print('=== 7) 统计接口 ===')
    sp = svc.stats_payload()
    print('   rx_total=%s stations=%s by_type=%s'
          % (sp['stats']['rx_total'], sp['stats']['stations'],
             [(x['dtype'], x['n']) for x in sp['by_type']]))
    ok = ok and sp['stats']['rx_total'] >= 5

    print('\n=== 集成验证结果：%s ===' % ('全部通过' if ok else '存在失败'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
