# -*- coding: utf-8 -*-
"""天气 API 客户端自测：URL 构造、两家响应解析、TTL 缓存、错误路径。

全程离线 —— HTTP 由 get_weather(opener=...) 注入假实现。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import weather_api as W

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


print('\n=== 1. WMO 码 → 中文 ===')
check('0 → 晴', W.wmo_cn(0) == '晴')
check('3 → 阴', W.wmo_cn(3) == '阴')
check('61 → 小雨', W.wmo_cn(61) == '小雨')
check('95 → 雷阵雨', W.wmo_cn(95) == '雷阵雨')
check('未知码 → 未知（不编）', W.wmo_cn(12345) == '未知')
check('垃圾输入 → 未知', W.wmo_cn('abc') == '未知' and W.wmo_cn(None) == '未知')

print('\n=== 2. 经纬度规整 ===')
check('正常值四舍五入到 4 位', W.norm_latlon('23.056412', 113.367891) == (23.0564, 113.3679))
check('越界纬度被判非法', W.norm_latlon(91, 113) == (None, None))
check('越界经度被判非法', W.norm_latlon(23, 181) == (None, None))
check('垃圾输入判非法', W.norm_latlon('x', '') == (None, None))
check('空值判非法', W.norm_latlon(None, None) == (None, None))

print('\n=== 3. URL 构造 ===')
u = W.openmeteo_url(23.0564, 113.368)
check('Open-Meteo 用经纬度', 'latitude=23.0564' in u and 'longitude=113.3680' in u, u)
check('Open-Meteo 请求当前天气字段', 'current=temperature_2m' in u)
check('Open-Meteo 请求当日最高最低', 'daily=temperature_2m_max' in u)
check('Open-Meteo 指定时区（否则日期会差一天）', 'timezone=Asia/Shanghai' in u)
check('Open-Meteo 只要 1 天', 'forecast_days=1' in u)
check('Open-Meteo 是 https', u.startswith('https://'), u[:24])

q = W.qweather_url('abcxyz.qweatherapi.com', 23.0564, 113.368)
check('和风自动补 https', q.startswith('https://abcxyz.qweatherapi.com/'), q)
check('和风用 v1 路径 + 经纬度', '/weather/v1/current/23.0564/113.3680' in q, q)
check('和风要中文', 'lang=zh' in q)
check('和风 host 带尾斜杠也认',
      W.qweather_url('https://h.com/', 1, 2).startswith('https://h.com/weather'))
check('和风 host 为空 → 空串（调用方据此报错）', W.qweather_url('', 1, 2) == '')

print('\n=== 4. Open-Meteo 解析 ===')
OM = {'current': {'time': '2026-09-27T14:00', 'temperature_2m': 28.4,
                  'relative_humidity_2m': 65, 'apparent_temperature': 30.1,
                  'precipitation': 0.0, 'weather_code': 2,
                  'wind_speed_10m': 11.52, 'wind_direction_10m': 226,
                  'surface_pressure': 1005.2},
      'daily': {'temperature_2m_max': [31.2], 'temperature_2m_min': [24.8],
                'precipitation_sum': [2.4], 'weather_code': [61]}}
d = W.parse_openmeteo(OM)
check('解析成功', d['ok'] is True and d['source'] == 'openmeteo')
check('天气现象译成中文', d['condition'] == '多云', d['condition'])
check('当日天气现象也译', d['day_condition'] == '小雨', d['day_condition'])
check('气温', d['temp_c'] == 28.4)
check('体感', d['feels_c'] == 30.1)
check('**风速 km/h → m/s 换算**（11.52 km/h = 3.2 m/s）',
      d['wind_ms'] == 3.2, str(d['wind_ms']))
check('风向度数', d['wind_deg'] == 226.0)
check('当日最高/最低', d['temp_max'] == 31.2 and d['temp_min'] == 24.8)
check('当日降水', d['precip_day_mm'] == 2.4)
d2 = W.parse_openmeteo({})
check('空响应不崩，字段给 None', d2['ok'] is True and d2['temp_c'] is None)
check('缺天气码时给「未知」', d2['condition'] == '未知')

print('\n=== 5. 和风解析（v1 嵌套 / v7 扁平都认）===')
QW1 = {'code': '200', 'condition': {'text': '多云'},
       'temperature': {'value': 31.71}, 'feelsLike': {'value': 33.64},
       'humidity': 0.69, 'wind': {'direction': {'degree': 226},
                                  'speed': {'value': 4.74}},
       'precipitation': {'amount': {'value': 0}},
       'pressure': {'value': 1001.5}}
q1 = W.parse_qweather(QW1)
check('v1 解析成功', q1['ok'] is True)
check('v1 中文天气现象直接取', q1['condition'] == '多云')
check('v1 气温', q1['temp_c'] == 31.71)
check('v1 湿度 0~1 → 百分比', q1['humidity'] == 69.0, str(q1['humidity']))
check('v1 风速已是 m/s', q1['wind_ms'] == 4.74)
check('v1 气压', q1['pressure_hpa'] == 1001.5)

QW7 = {'code': '200', 'now': {'temp': '26', 'feelsLike': '28', 'text': '雾',
                              'wind360': '180', 'windSpeed': '5',
                              'humidity': '74', 'precip': '0.0',
                              'pressure': '1004'}}
q7 = W.parse_qweather(QW7)
check('v7 解析成功', q7['ok'] is True)
check('v7 中文天气现象', q7['condition'] == '雾')
check('v7 气温（字符串转数字）', q7['temp_c'] == 26.0)
check('**v7 风速 km/h → m/s**（5 km/h ≈ 1.4 m/s）', q7['wind_ms'] == 1.4,
      str(q7['wind_ms']))
check('v7 湿度已是百分比，不再乘 100', q7['humidity'] == 74.0)
qbad = W.parse_qweather({'code': '401'})
check('非 200 码报错且带码', qbad['ok'] is False and '401' in qbad['error'])
check('非对象输入不崩', W.parse_qweather('xx')['ok'] is False)

print('\n=== 6. get_weather 的取数与缓存 ===')
W.reset_cache()
calls = []


def fake_ok(url, headers, timeout):
    calls.append((url, dict(headers)))
    return OM


r = W.get_weather('openmeteo', 23.0564, 113.368, opener=fake_ok, now=1000.0)
check('Open-Meteo 取数成功', r['ok'] is True and r['temp_c'] == 28.4)
check('未带多余请求头', calls and calls[-1][1] == {}, str(calls[-1][1]))
r2 = W.get_weather('openmeteo', 23.0564, 113.368, opener=fake_ok, now=1001.0)
check('TTL 内命中缓存（不再打网络）', len(calls) == 1 and r2.get('cached') is True,
      'calls=%d' % len(calls))
r3 = W.get_weather('openmeteo', 23.0564, 113.368, opener=fake_ok, now=1000.0 + 601)
check('超过 TTL 会重新取', len(calls) == 2, 'calls=%d' % len(calls))
r4 = W.get_weather('openmeteo', 22.0, 113.0, opener=fake_ok, now=1000.0 + 602)
check('换坐标不吃旧缓存', len(calls) == 3)

check('provider=off 直接拒绝', W.get_weather('off', 1, 2)['ok'] is False)
check('未知 provider 也拒绝', W.get_weather('nonsense', 1, 2)['ok'] is False)
check('未填经纬度时明确报错（人工填写那步没做）',
      '经纬度' in W.get_weather('openmeteo', '', '')['error'])
check('和风缺 Host 时明确报错',
      'Host' in W.get_weather('qweather', 23, 113)['error'])
check('和风缺 Key 时明确报错',
      'Key' in W.get_weather('qweather', 23, 113, api_host='h.com')['error'])

qw_calls = []


def fake_qw(url, headers, timeout):
    qw_calls.append((url, dict(headers)))
    return QW1


q = W.get_weather('qweather', 23.0564, 113.368, api_host='abc.qweatherapi.com',
                  api_key='K123', opener=fake_qw, now=2000.0)
check('和风取数成功', q['ok'] is True and q['condition'] == '多云')
check('和风把 key 放在 X-QW-Api-Key 头里',
      qw_calls and qw_calls[-1][1].get(W.QW_API_KEY_HEADER) == 'K123',
      str(qw_calls[-1][1]))
check('key 不出现在 URL 里（避免写进日志/审计）', 'K123' not in qw_calls[-1][0],
      qw_calls[-1][0])


def fake_boom(url, headers, timeout):
    raise RuntimeError('connection refused')


b = W.get_weather('openmeteo', 23.0, 113.0, opener=fake_boom, now=3000.0)
check('网络异常返回 ok=False 且带原因',
      b['ok'] is False and 'connection refused' in b['error'], str(b)[:120])

print('\n=== 7. 播报变量 ===')
v = W.weather_vars(d)
check('ok 标记', v['wx_ok'] == '1')
check('天气现象', v['wx_condition'] == '多云')
check('气温给纯数字（单位由模板写）', v['wx_temp'] == '28.4', v['wx_temp'])
check('风速给纯数字', v['wx_wind'] == '3.2', v['wx_wind'])
check('最高/最低', v['wx_temp_max'] == '31.2' and v['wx_temp_min'] == '24.8')
check('湿度取整', v['wx_humidity'] == '65', v['wx_humidity'])
vn = W.weather_vars({'ok': False, 'error': 'x'})
check('取不到时全给「暂无」（播报不会念出 None）',
      vn['wx_temp'] == '暂无' and vn['wx_condition'] == '暂无' and vn['wx_ok'] == '0')
check('取不到时保留错误原因供排查', vn['wx_error'] == 'x')
check('空输入不崩', W.weather_vars(None)['wx_temp'] == '暂无')

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  ✗ %s' % f)
sys.exit(1 if FAIL else 0)
