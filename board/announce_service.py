# -*- coding: utf-8 -*-
"""定时播报：文案组装、整点表解析、中文时间读法。

**不依赖 Flask、不碰硬件、不发声** —— 纯计算，便于离线自测。
真正的合成与受控发射留在 app.py（要碰 TTS、PTT 与信道忙判据）。

三类内容各自独立：时间 / 中继台状态 / 气象。
"""
import re
from datetime import datetime

# 三类播报内容，(键, 中文名, 默认模板)。模板里的 {xxx} 由 app 的变量展开器代入。
MODULES = (
    ('time', '时间'),
    ('status', '中继台状态'),
    ('weather', '气象'),
)

DEFAULTS = {
    'time': '现在是{time_cn}。',
    'status': '中继台运行正常，电池电压{battery}伏特，机内温度{cpu_temp}摄氏度。',
    'weather': '当前风速{wind}米每秒，今日累计降水{rain_today}毫米。',
}

_CN_DIGITS = '零一二三四五六七八九'
# 播报文本上限：TTS 越长越慢，而且占用信道的时间是硬成本
TEXT_LIMIT = 200


def cn_num(n):
    """0..99 的中文读法：10→十、14→十四、20→二十、59→五十九。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n < 0 or n > 99:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return '十' + (_CN_DIGITS[n - 10] if n > 10 else '')
    tens, ones = divmod(n, 10)
    return _CN_DIGITS[tens] + '十' + (_CN_DIGITS[ones] if ones else '')


def cn_minute(m):
    """分钟的读法：1..9 前面要补「零」——「八点零五分」，不能读成「八点五分」。"""
    try:
        m = int(m)
    except (TypeError, ValueError):
        return str(m)
    if 0 < m < 10:
        return '零' + _CN_DIGITS[m]
    return cn_num(m)


def clock_vars(now=None):
    """整点播报要用的中文时间变量，喂给模板展开器。

    额外提供 {time_cn} / {hour_cn} / {minute_cn}，与 app 既有的 {time} {date}
    这些并存——模板里用哪个都行。
    """
    now = now or datetime.now()
    h, m = int(now.hour), int(now.minute)
    if m == 0:
        phrase = '北京时间%s点整' % cn_num(h)
    else:
        phrase = '北京时间%s点%s分' % (cn_num(h), cn_minute(m))
    return {'hour': h, 'minute': m, 'hour_cn': cn_num(h),
            'minute_cn': cn_minute(m), 'time_cn': phrase}


def parse_hours(raw):
    """'8,10,12' / '08 10 12' / '8、10' → 升序元组；无有效值 → 空元组。

    整点播报要播哪几个整点是**用户自己勾的**，所以空就是空，不替用户兜默认值。
    """
    out = set()
    for x in re.split(r'[,;、\s]+', str(raw or '')):
        if not x.strip():
            continue
        try:
            v = int(float(x))
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 23:
            out.add(v)
    return tuple(sorted(out))


def hours_to_str(hours):
    """元组 → 存储用的逗号串。"""
    return ','.join(str(int(h)) for h in sorted(set(hours or ())) if 0 <= int(h) <= 23)


def enabled_modules(flags):
    """flags: {'time': bool, 'status': bool, 'weather': bool} → 有序键列表。"""
    return [k for k, _label in MODULES if flags.get(k)]


def compose(flags, templates, vars_map=None, expand=None):
    """按开关把各类模板展开并拼成一段播报文本（空串表示没内容可播）。

    expand 由调用方注入（app 的变量展开器），这样本模块不必依赖 Flask。
    每个模板末尾统一补句号，避免几段连读时黏在一起。
    """
    vars_map = vars_map or {}
    parts = []
    for key in enabled_modules(flags):
        tpl = (templates.get(key) or DEFAULTS.get(key) or '').strip()
        if not tpl:
            continue
        txt = tpl
        if expand is not None:
            try:
                txt = expand(tpl, vars_map)
            except TypeError:
                txt = expand(tpl)          # 兼容只收一个参数的展开器
            except Exception:
                txt = tpl
        txt = str(txt or '').strip()
        if not txt:
            continue
        if not txt.endswith(('。', '！', '？', '.', '!', '?')):
            txt += '。'
        parts.append(txt)
    return clamp_text(''.join(parts))


def clamp_text(text, limit=TEXT_LIMIT):
    """播报文本上限。宁可少说一句，也别让信道被占太久。"""
    return str(text or '').strip()[:int(limit)]


def due_hour(now, hours, fired, grace=90):
    """此刻该播的整点 key（'YYYY-MM-DD HH'）；不该播返回 None。

    fired 由调用方持有（已播过的 key 集合）。
    只在 [整点, 整点+grace) 内触发：服务重启后**不会**把今天错过的整点全部
    补播出来 —— 那会连着一串过期播报，比不播更糟。
    """
    try:
        h = int(now.hour)
    except (AttributeError, TypeError, ValueError):
        return None
    if h not in set(hours or ()):
        return None
    key = now.strftime('%Y-%m-%d %H')
    if key in (fired or ()):
        return None
    try:
        due = now.replace(minute=0, second=0, microsecond=0)
        delta = (now - due).total_seconds()
    except (AttributeError, ValueError):
        return None
    if 0 <= delta < float(grace):
        return key
    return None


def in_quiet_hours(spec, now=None):
    """禁发时段判定（与助手同语义，支持跨零点与多段）。

    放在这里是为了让「定时播报」不依赖 assistant_service；实现与
    assistant_service.in_quiet_hours 保持一致。
    """
    now = now or datetime.now()
    spec = str(spec or '').strip()
    if not spec:
        return False
    mins = now.hour * 60 + now.minute
    for seg in re.split(r'[,;，；]+', spec):
        seg = seg.strip()
        m = re.match(r'^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$', seg)
        if not m:
            continue
        try:
            a = int(m.group(1)) * 60 + int(m.group(2))
            b = int(m.group(3)) * 60 + int(m.group(4))
        except ValueError:
            continue
        if a <= b:
            if a <= mins < b:
                return True
        elif mins >= a or mins < b:      # 跨零点
            return True
    return False
