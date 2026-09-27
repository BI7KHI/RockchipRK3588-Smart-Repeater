# -*- coding: utf-8 -*-
"""把文本里的数值改写成**能直接念出来**的中文口语（纯函数，无依赖）。

为什么必须有这一层（板端实测，不是洁癖）：

1. **Piper 对阿拉伯小数的念法不可控**。工具给的原始值是 4 位小数（如 12.1957），
   合成出来到底念成「十二点一九五七」还是别的，取决于前端自己的解析：
   音频实测「12.1957伏特」2.35s ≈ 「12.2伏特」2.35s ≈ 「十二点二伏特」2.38s，
   而与「十二点一九五七伏特」3.11s 差 0.76s；用板端 ASR 反听同一段音频，两次分别
   得到「121957」和「12.2」。**精度与读法都不在我们手里。**
   写成显式口语后，念什么由我们决定：板端 ASR 反听 4/4 与真值一致。
2. **板端 1.5B 只会照抄，不会转换**。把「数字一律用中文口语」写成最后一条强制规则，
   它仍然输出「12.1957伏特」（2/2）；只有当数据本身已经是「十二点二零伏特」时才照抄正确。
   → 「数值怎么念」不能靠提示词，只能在这里确定性地做。

规则（用户定的）：
  * 最多两位小数、四舍五入、**不补零**：12.2446 → 十二点二四；48.1 → 四十八点一。
  * 小数点读「点」，负号读「负」，百分比读「百分之…」，区间连接符读「到」。
  * 变量本身仍是数值（`{battery}` = 12.2446），只在**文本出口**转口语 —— 这样模型看到
    的仍是数字（能比较、能判断），模板一个字都不用改。

只改「看得出是计量」的地方，其余一律不动：
  * 数字紧跟单位（伏特/摄氏度/米每秒/公里/毫米/吉字节/%/瓦/毫秒…）；
  * 或者数字前面是量词（电压/温度/风速/负载/内存/剩余/距离/信号…）。
明确不碰：字母数字混排的 token（呼号 `BG7LTG-7`、型号 `ELF2`/`RK3588`/`qwen2.5`）、
日期（`2026年9月27日`）、冒号时间（`19:09:22`）、经纬度、频率、GPIO/SSID。
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CN_DIGITS = '零一二三四五六七八九'
BIG_UNITS = ('', '万', '亿', '兆')
SMALL_UNITS = ('', '十', '百', '千')

# 数字后面直接跟这些 → 认定是计量，读成中文
UNITS = (
    '摄氏度', '华氏度', '米每秒', '米/秒', '公里每小时', '千米每小时', '公里/小时',
    '伏特', '毫伏', '千伏', '吉字节', '兆字节', '千字节', '字节',
    '毫秒', '分钟', '小时', '天', '秒', '分贝', '赫兹', '千赫', '兆赫', '百帕',
    '帕', '千瓦', '瓦特', '瓦', '毫安', '安培', '安', '千米', '公里', '厘米',
    '毫米', '米', '克', '千克', '公斤', '吨', '升', '毫升',
    '个', '次', '段', '条', '台', '人', '岁', '倍', '成', '折',
    '℃', '°C', 'km/h', 'm/s', 'km', 'mm', 'cm', 'GB', 'MB', 'KB', 'ms', 'kHz',
    'MHz', 'Hz', 'dB', 'hPa', 'kW', 'mA', 'V', 'W', 'A', 'm',
    # 单字缩写：模型常写「13.4441伏」而不是「伏特」（实测漏网过，验收脚本抓到的）
    '伏', '欧',
)

# 数字前面出现这些词 → 认定这个数字是计量值（没有单位也要读中文）
TRIGGERS = (
    '电压', '电池', '光伏', '电源', '电量', '电流', '功率', '电阻',
    '温度', '机内', '气温', '室温', '核心', 'CPU', 'cpu', 'CPU温度',
    '风速', '降水', '降雨', '雨量', '湿度', '气压', '海拔',
    '距离', '方位', '速度', '时长', '负载', '内存', '占用', '剩余', '磁盘', '存储',
    '容量', '信号', '信噪', '报告', '大约', '约为', '约', '共', '总计', '范围', '区间',
)

# 数字前面出现这些词 → 数字是坐标/编号，绝不改（改了会丢精度或念错）
NEVER_BEFORE = (
    '北纬', '南纬', '东经', '西经', '纬度', '经度', '坐标', '经纬',
    '频道', '频率', 'GPIO', 'SSID', '端口', '编号', '版本', '户型', '第',
)

# 数字本身是这些形式 → 不是计量（日期、冒号时间）
_NEVER_AFTER = ('年', '月', '日', '号', ':', '：', '/')

_UNIT_ALT = '|'.join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
# 守卫只用 ASCII 字母数字：汉字在 Python 里也算 \w，用 \w 会把「电压12.3V」这种
# 紧跟中文的数字整片挡掉（实测踩过：电池电压12.1957伏特一个字都没换）
_NUM_RE = re.compile(r'(?<![0-9A-Za-z_])(-?\d+(?:\.\d+)?)\s*(%s)?(?![0-9A-Za-z_])'
                     % _UNIT_ALT)
_PCT_RE = re.compile(r'(?<![0-9A-Za-z_])(-?\d+(?:\.\d+)?)\s*[%％](?![0-9A-Za-z_])')
# 改写后两个中文数之间的连接符读「到」（区间：25.5-35.0 → 二十五点五到三十五）
_CN_RANGE_RE = re.compile(r'([零一二三四五六七八九十百千万亿兆点负]+)\s*[-~－—–]\s*'
                          r'([零一二三四五六七八九十百千万亿兆点负]+)')


def cn_int(n):
    """整数 → 中文（支持到「兆」，处理万/亿分组与组间补零）。"""
    n = int(n)
    if n == 0:
        return '零'
    neg = n < 0
    digits = str(abs(n))
    groups = []
    while digits:
        groups.append(digits[-4:])
        digits = digits[:-4]
    out = ''
    for gi in range(len(groups) - 1, -1, -1):
        raw = groups[gi]
        g = raw.lstrip('0')
        if not g:
            continue
        # 组间补零：低位组不足四位且不是零（100200 → 十万零二百）
        if out and len(raw) == 4 and raw[0] == '0' and not out.endswith('零'):
            out += '零'
        out += _four(g, leading=(not out)) + BIG_UNITS[gi]
    return ('负' if neg else '') + out


def _four(s, leading=False):
    """四位以内（无前导零）→ 中文。leading=True 时 10~19 读作「十几」而不是「一十几」。"""
    if leading and len(s) == 2 and s[0] == '1':
        return '十' + (CN_DIGITS[int(s[1])] if s[1] != '0' else '')
    out = ''
    n = len(s)
    for i, ch in enumerate(s):
        d = int(ch)
        pos = n - i - 1
        if d:
            out += CN_DIGITS[d] + SMALL_UNITS[pos]
        elif out and not out.endswith('零'):
            out += '零'
    return out.rstrip('零')


def cn_number(value, max_dp=2):
    """数值文本 → 口语中文。返回 None 表示不是纯数字（原样保留）。

    `max_dp` 位小数四舍五入、**不补零**：12.2446 → 十二点二四；48.1 → 四十八点一。
    带前导零的整数按位读（'09' → 零九），因为那是时刻/编号而不是数量。
    """
    t = str(value).strip()
    if not re.match(r'^[+-]?\d+(?:\.\d+)?$', t):
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    q = Decimal(1).scaleb(-max_dp)                    # 0.01
    d = d.quantize(q, rounding=ROUND_HALF_UP)
    neg = d < 0
    s = format(abs(d), 'f')
    ip, _, fp = s.partition('.')
    fp = fp.rstrip('0')
    raw_ip = t.lstrip('+-').split('.')[0]
    if len(raw_ip) > 1 and raw_ip.startswith('0') and int(ip) == int(raw_ip):
        body = ''.join(CN_DIGITS[int(c)] for c in raw_ip)   # 09 → 零九（时刻/编号）
    else:
        body = cn_int(int(ip))
    if fp:
        body += '点' + ''.join(CN_DIGITS[int(c)] for c in fp)
    return ('负' if neg else '') + body


def _unit_at(rest):
    """rest 开头是不是单位；是则返回 (单位, 中文读法)。"""
    for u in UNITS:
        if rest.startswith(u):
            return u, _unit_cn(u)
    return None, None


_UNIT_CN = {
    '℃': '摄氏度', '°C': '摄氏度', 'm/s': '米每秒', 'km/h': '公里每小时',
    'km': '公里', 'mm': '毫米', 'cm': '厘米', 'GB': '吉字节', 'MB': '兆字节',
    'KB': '千字节', 'ms': '毫秒', 'kHz': '千赫', 'MHz': '兆赫', 'Hz': '赫兹',
    'dB': '分贝', 'hPa': '百帕', 'kW': '千瓦', 'mA': '毫安', 'V': '伏特',
    'W': '瓦', 'A': '安', 'm': '米',
}


def _unit_cn(u):
    return _UNIT_CN.get(u, u)


def _never(pre):
    return any(pre.rstrip().endswith(w) for w in NEVER_BEFORE)


def _triggered(pre):
    return any(pre.rstrip().endswith(w) for w in TRIGGERS)


def speakable(text, max_dp=2):
    """把计量数值改写成中文口语；不认识的数字一律原样保留。幂等。

    例：
        电池电压12.1957伏特，机内温度52.7摄氏度。
        → 电池电压十二点二伏特，机内温度五十二点七摄氏度。
        内存占用92.1%，剩余15.6GB
        → 内存占用百分之九十二点一，剩余十五点六吉字节
    """
    if not text:
        return text or ''
    s = str(text)

    # 百分比先处理：85.5% → 百分之八十五点五
    def _pct(m):
        cn = cn_number(m.group(1), max_dp)
        return m.group(0) if cn is None else '百分之' + cn
    s = _PCT_RE.sub(_pct, s)

    def _rep(m):
        tok, unit = m.group(1), m.group(2)
        start = m.start()
        pre = s[:start]
        nxt = s[m.end():m.end() + 1]
        # 紧跟「年/月/日/:」等 → 日期或时刻，不动
        if nxt and nxt in _NEVER_AFTER:
            return m.group(0)
        if _never(pre):
            return m.group(0)
        if unit is None and not _triggered(pre):
            return m.group(0)                      # 看不出是计量，原样保留
        cn = cn_number(tok, max_dp)
        if cn is None:
            return m.group(0)
        # 单位写成中文读法（12V → 十二伏特），本来就是中文的单位原样留着
        return cn + (_unit_cn(unit) if unit else '')

    out = _NUM_RE.sub(_rep, s)
    # 两个中文数之间的连接符读「到」
    prev = None
    while prev != out:
        prev = out
        out = _CN_RANGE_RE.sub(r'\1到\2', out)
    return out
