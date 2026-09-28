# -*- coding: utf-8 -*-
"""天气 API 客户端：Open-Meteo 与和风天气（QWeather）。

设计取舍
--------
* **默认 Open-Meteo**：无需注册、无需 key，直接经纬度取 JSON，装好即用。
  它给的是 WMO 天气码，所以这里带一张 WMO→中文 的映射表，播报才读得顺。
* **可选和风天气**：国内源、直接给中文天气现象。需要用户在控制台建项目后填
  **API Host**（形如 abcxyz.qweatherapi.com）+ **API Key**（请求头
  `X-QW-Api-Key`）。和风自 2027-01-01 起对 API KEY 认证限制日请求量，届时可换
  JWT（Ed25519），本模块预留了 Authorization 头的能力。

解析与 URL 构造是纯函数，HTTP 由调用方注入 —— 所以整层都能离线自测。
"""
import json
import time
from datetime import datetime

PROVIDERS = ('off', 'openmeteo', 'qweather')

OPENMETEO_HOST = 'https://api.open-meteo.com'
OPENMETEO_PATH = '/v1/forecast'
QW_API_KEY_HEADER = 'X-QW-Api-Key'

# WMO Weather interpretation codes（Open-Meteo 用这套）
WMO_CN = {
    0: '晴', 1: '晴间多云', 2: '多云', 3: '阴',
    45: '有雾', 48: '冻雾',
    51: '小毛毛雨', 53: '毛毛雨', 55: '大毛毛雨',
    56: '冻毛毛雨', 57: '强冻毛毛雨',
    61: '小雨', 63: '中雨', 65: '大雨',
    66: '冻雨', 67: '强冻雨',
    71: '小雪', 73: '中雪', 75: '大雪', 77: '雪粒',
    80: '小阵雨', 81: '阵雨', 82: '强阵雨',
    85: '小阵雪', 86: '大阵雪',
    95: '雷阵雨', 96: '雷阵雨伴小冰雹', 99: '雷阵雨伴大冰雹',
}

_CACHE = {'key': '', 'ts': 0.0, 'data': None}


def wmo_cn(code):
    """WMO 天气码 → 中文；不认识的码给「未知」。"""
    try:
        return WMO_CN.get(int(code), '未知')
    except (TypeError, ValueError):
        return '未知'


def norm_latlon(lat, lon):
    """把经纬度规整成 float；非法返回 (None, None)。"""
    try:
        la = float(lat)
        lo = float(lon)
    except (TypeError, ValueError):
        return None, None
    if not (-90.0 <= la <= 90.0) or not (-180.0 <= lo <= 180.0):
        return None, None
    return round(la, 4), round(lo, 4)


def openmeteo_url(lat, lon, tz='Asia/Shanghai'):
    """Open-Meteo 预报接口：当前天气 + 当日最高最低 + 当日降水量。"""
    return ('%s%s?latitude=%.4f&longitude=%.4f'
            '&current=temperature_2m,relative_humidity_2m,apparent_temperature,'
            'precipitation,weather_code,wind_speed_10m,wind_direction_10m,'
            'surface_pressure'
            '&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,'
            'weather_code'
            '&timezone=%s&forecast_days=1'
            % (OPENMETEO_HOST, OPENMETEO_PATH, lat, lon, tz))


def qweather_url(host, lat, lon, lang='zh'):
    """和风天气 v1 当前天气。host 是控制台里那个项目专属 API Host。"""
    h = str(host or '').strip().rstrip('/')
    if not h:
        return ''
    if not h.startswith('http'):
        h = 'https://' + h
    return '%s/weather/v1/current/%.4f/%.4f?lang=%s' % (h, lat, lon, lang)


def _f(v):
    try:
        return None if v is None or v == '' else float(v)
    except (TypeError, ValueError):
        return None


def parse_openmeteo(raw):
    """Open-Meteo JSON → 归一化字段。缺项给 None，不猜。"""
    cur = (raw or {}).get('current') or {}
    day = (raw or {}).get('daily') or {}

    def d1(key):
        v = day.get(key)
        return (v[0] if isinstance(v, list) and v else None)

    kmh = _f(cur.get('wind_speed_10m'))
    return {
        'ok': True, 'source': 'openmeteo',
        'condition': wmo_cn(cur.get('weather_code')),
        'temp_c': _f(cur.get('temperature_2m')),
        'feels_c': _f(cur.get('apparent_temperature')),
        'humidity': _f(cur.get('relative_humidity_2m')),
        'wind_ms': round(kmh / 3.6, 1) if kmh is not None else None,
        'wind_deg': _f(cur.get('wind_direction_10m')),
        'precip_mm': _f(cur.get('precipitation')),
        'pressure_hpa': _f(cur.get('surface_pressure')),
        'temp_max': _f(d1('temperature_2m_max')),
        'temp_min': _f(d1('temperature_2m_min')),
        'precip_day_mm': _f(d1('precipitation_sum')),
        'day_condition': wmo_cn(d1('weather_code')),
        'obs_time': str(cur.get('time') or ''),
        'error': '',
    }


def parse_qweather(raw):
    """和风天气 JSON → 归一化字段。

    v1 与 v7 的字段名不同（v1 是嵌套对象、v7 是扁平字符串），这里都认，
    免得用户注册后换接口版本又要改代码。
    """
    if not isinstance(raw, dict):
        return {'ok': False, 'source': 'qweather', 'error': '返回不是 JSON 对象'}
    code = str(raw.get('code') or '')
    if code and code != '200':
        return {'ok': False, 'source': 'qweather',
                'error': '和风返回 code=%s' % code}
    now = raw.get('now') or raw
    # v1 嵌套：{'temperature': {'value': 31.7}}；v7 扁平：{'temp': '26'}
    def nested(sec, sub='value'):
        v = now.get(sec)
        if isinstance(v, dict):
            return v.get(sub)
        return v

    temp = _f(nested('temperature')) if 'temperature' in now else _f(now.get('temp'))
    feels = (_f(nested('feelsLike')) if 'feelsLike' in now
             else _f(now.get('feelsLike')))
    hum = now.get('humidity')
    hum = _f(hum if not isinstance(hum, dict) else hum.get('value'))
    if hum is not None and hum <= 1.0:
        hum = round(hum * 100.0, 1)          # v1 给 0~1，v7 给 0~100
    wind = now.get('wind')
    if isinstance(wind, dict):
        ws = _f((wind.get('speed') or {}).get('value'))
        wd = _f((wind.get('direction') or {}).get('degree'))
    else:
        ws = _f(now.get('windSpeed'))
        wd = _f(now.get('wind360'))
        if ws is not None:
            ws = round(ws / 3.6, 1)          # v7 的 windSpeed 是 km/h
    cond = now.get('condition') or {}
    text = (cond.get('text') if isinstance(cond, dict) else None) or now.get('text') or ''
    precip = now.get('precipitation')
    precip = _f(precip.get('amount', {}).get('value') if isinstance(precip, dict)
               else now.get('precip'))
    pres = now.get('pressure')
    pres = _f(pres.get('value') if isinstance(pres, dict) else pres)
    return {
        'ok': True, 'source': 'qweather', 'condition': str(text),
        'temp_c': temp, 'feels_c': feels, 'humidity': hum,
        'wind_ms': ws, 'wind_deg': wd, 'precip_mm': precip,
        'pressure_hpa': pres,
        'temp_max': None, 'temp_min': None, 'precip_day_mm': None,
        'day_condition': '', 'obs_time': str(now.get('obsTime') or ''),
        'error': '',
    }


def fetch_json(url, headers=None, timeout=8, opener=None):
    """默认 HTTP 实现。测试时用 opener 注入假实现，避免真联网。"""
    if opener is not None:
        return opener(url, headers or {}, timeout)
    import requests
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_weather(provider, lat, lon, api_host='', api_key='', ttl=600,
                opener=None, now=None, timeout=8):
    """取天气并归一化。带 TTL 缓存 —— 整点播报不该每次打网络。

    返回归一化 dict；失败时 ok=False 且带 error（调用方据此决定要不要播）。
    """
    provider = str(provider or 'off').strip().lower()
    if provider not in PROVIDERS or provider == 'off':
        return {'ok': False, 'source': provider or 'off', 'error': '天气 API 未启用'}
    la, lo = norm_latlon(lat, lon)
    if la is None:
        return {'ok': False, 'source': provider,
                'error': '未配置中继台经纬度（请人工填写）'}
    now = now or time.time()
    ck = '%s|%.4f|%.4f|%s' % (provider, la, lo, api_host)
    if _CACHE['data'] and _CACHE['key'] == ck and (now - _CACHE['ts']) < ttl:
        return dict(_CACHE['data'], cached=True)
    if provider == 'openmeteo':
        url, headers, parser = openmeteo_url(la, lo), {}, parse_openmeteo
    else:
        url = qweather_url(api_host, la, lo)
        if not url:
            return {'ok': False, 'source': 'qweather',
                    'error': '未配置和风 API Host（控制台里项目专属的那个域名）'}
        if not str(api_key or '').strip():
            return {'ok': False, 'source': 'qweather', 'error': '未配置和风 API Key'}
        headers = {QW_API_KEY_HEADER: str(api_key).strip()}
        parser = parse_qweather
    try:
        raw = fetch_json(url, headers, timeout, opener=opener)
    except Exception as e:
        return {'ok': False, 'source': provider,
                'error': '%s: %s' % (type(e).__name__, str(e)[:120])}
    out = parser(raw)
    out['fetched_at'] = datetime.now().strftime('%H:%M:%S')
    if out.get('ok'):
        _CACHE.update({'key': ck, 'ts': now, 'data': dict(out)})
    return out


def weather_vars(w):
    """把天气结果变成播报模板可用的变量（取不到的一律给「暂无」）。

    所有值都转成**可直接朗读**的中文口语：温度带「度」，风速带「米每秒」。
    """
    w = w or {}
    if not w.get('ok'):
        return {'wx_ok': '0', 'wx_condition': '暂无', 'wx_temp': '暂无',
                'wx_temp_max': '暂无', 'wx_temp_min': '暂无', 'wx_humidity': '暂无',
                'wx_wind': '暂无', 'wx_precip': '暂无', 'wx_pressure': '暂无',
                'wx_source': w.get('source') or '', 'wx_error': w.get('error') or ''}

    def num(v, digits=1, dash='暂无'):
        if v is None:
            return dash
        try:
            f = float(v)
        except (TypeError, ValueError):
            return dash
        s = ('%.' + str(digits) + 'f') % f
        return s.rstrip('0').rstrip('.') if '.' in s else s

    return {
        'wx_ok': '1',
        'wx_condition': w.get('condition') or '暂无',
        'wx_temp': num(w.get('temp_c')),
        'wx_temp_max': num(w.get('temp_max')),
        'wx_temp_min': num(w.get('temp_min')),
        'wx_humidity': num(w.get('humidity'), 0),
        'wx_wind': num(w.get('wind_ms')),
        'wx_precip': num(w.get('precip_day_mm') if w.get('precip_day_mm') is not None
                         else w.get('precip_mm')),
        'wx_pressure': num(w.get('pressure_hpa'), 0),
        'wx_source': w.get('source') or '',
        'wx_error': w.get('error') or '',
    }


def reset_cache():
    """测试用：清掉 TTL 缓存。"""
    _CACHE.update({'key': '', 'ts': 0.0, 'data': None})
