#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 aprs_service.py 加入 Mic-E 解码。

算法完全对照 direwolf `src/decode_aprs.c` 的 `aprs_mic_e()` / `mic_e_digit()`
（社区久经考验的参考实现），并用两个独立来源交叉验证：

 1. **真实报文**（操作者手台发出的 Mic-E）：
    dest=RSPRV4  info=`\`)3Hlg})/7.20V"4'}`
    -> 23.0423N / 113.3907E，与中继所在广州（23.0564N/113.3680E）相距约 2.3 km。
       注意：若按「A-J/P-Y 各从 1 起算」的错误映射会解成南半球，可用作反向判据。

 2. 极性是本格式最容易记反的地方，direwolf 明确：
      dest[3] 在 '0'-'9'/'L' -> 南；在 'P'-'Z' -> 北
      dest[5] 在 '0'-'9'/'L' -> 东；在 'P'-'Z' -> 西
    两边不对称，不是笔误。
"""
import re
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else '/www/aprs_service.py'
with open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if '_mic_e_digit' in src:
    print('已实现过 Mic-E，跳过（幂等）')
    sys.exit(0)

E = []

# ---------------------------------------------------------------- A. Mic-E 实现
NEW_CODE = '''# --- Mic-E（APRS 101 §10）------------------------------------------------
# 编码要点：6 个目的地址字符承载纬度 DDMMhh 与三个消息位、南北半球、经度 +100
# 偏移、东西半球；信息字段前 8 字节承载经度(3)、速度/航向(3)、符号码、符号表。
# 逐位算法对照 direwolf `mic_e_digit()` / `aprs_mic_e()`。
MIC_E_STD_MSG = ['紧急 Emergency', '优先 Priority', '特别 Special', '待命 Committed',
                 '返程 Returning', '值勤 In Service', '在途 En Route', '下班 Off Duty']
MIC_E_CUST_MSG = ['紧急 Emergency', '自定义-6', '自定义-5', '自定义-4',
                  '自定义-3', '自定义-2', '自定义-1', '自定义-0']


def _mic_e_digit(c, mask, std_msg, cust_msg):
    """目的地址字符 -> (纬度数字, std_msg, cust_msg)。

    只有 'K'（自定义集）与 'Z'（标准集）会点亮对应的消息位；
    '0'-'9' / 'A'-'J' / 'P'-'Y' 三段的数字都是各自段的 0..9。
    """
    o = ord(c) if c else 0
    if 0x30 <= o <= 0x39:                      # '0'-'9'
        return o - 0x30, std_msg, cust_msg
    if 0x41 <= o <= 0x4A:                      # 'A'-'J'
        return o - 0x41, std_msg, cust_msg
    if 0x50 <= o <= 0x59:                      # 'P'-'Y'
        return o - 0x50, std_msg, cust_msg
    if c == 'K':
        return 0, std_msg, cust_msg | mask
    if c == 'Z':
        return 0, std_msg | mask, cust_msg
    if c == 'L':
        return 0, std_msg, cust_msg
    return 0, std_msg, cust_msg                # 非法字符按 0 处理并继续


def parse_mic_e(dest, s):
    """解析 Mic-E：dest 为目的地址呼号（纬度来源），s 为完整信息字段。

    返回 dict（含 lat/lon/symbol/速度航向/消息位），无法定位时 lat/lon 为 None。
    """
    dest = (dest or '').upper().ljust(6)
    out = {'dtype': 'mice', 'comment': '', 'mice_dest': dest.strip()}
    if len(s) < 9:
        return out
    out['mice_dti'] = s[0]
    out['mice_msg_capable'] = (s[0] == '`')    # ` = 支持消息, ' = 单向追踪器

    std_msg = cust_msg = 0
    dg = []
    for i, mask in enumerate((4, 2, 1)):
        d, std_msg, cust_msg = _mic_e_digit(dest[i], mask, std_msg, cust_msg)
        dg.append(d)
    for i in range(3, 6):
        d, std_msg, cust_msg = _mic_e_digit(dest[i], 0, std_msg, cust_msg)
        dg.append(d)

    # 纬度 = DD + MMhh/6000（digits[2:6] 组成 MMhh 四位）
    lat = dg[0] * 10 + dg[1] + (dg[2] * 1000 + dg[3] * 100 + dg[4] * 10 + dg[5]) / 6000.0
    # 南北：'0'-'9' / 'L' 为南，'P'-'Z' 为北（与东西方向相反，是 Mic-E 的固有约定）
    if (dest[3].isdigit() or dest[3] == 'L'):
        lat = -lat
    out['mice_lat_ns'] = 'S' if (dest[3].isdigit() or dest[3] == 'L') else 'N'

    # 经度 +100 偏移位：dest[4] 在 'P'-'Z' 时为 1
    offset = 1 if ('P' <= dest[4] <= 'Z') else 0
    out['mice_lon_offset'] = offset

    lon = None
    ch = ord(s[1])
    if offset and 118 <= ch <= 127:
        lon = ch - 118
    elif (not offset) and 38 <= ch <= 127:
        lon = (ch - 38) + 10
    elif offset and 108 <= ch <= 117:
        lon = (ch - 108) + 100
    elif offset and 38 <= ch <= 107:
        lon = (ch - 38) + 110
    out['mice_lon'] = lon

    if lon is not None:
        ch = ord(s[2])
        if 88 <= ch <= 97:
            lon += (ch - 88) / 60.0
        elif 38 <= ch <= 87:
            lon += ((ch - 38) + 10) / 60.0
        else:
            lon = None
    if lon is not None:
        ch = ord(s[3])
        if 28 <= ch <= 127:
            lon += (ch - 28) / 6000.0
        else:
            lon = None
    # 东西：'0'-'9' / 'L' 为东，'P'-'Z' 为西
    out['mice_lon_ew'] = 'W' if ('P' <= dest[5] <= 'Z') else 'E'
    if lon is not None and out['mice_lon_ew'] == 'W':
        lon = -lon

    if lon is not None:
        out['lat'] = round(lat, 6)
        out['lon'] = round(lon, 6)

    # 速度/航向：两段各 3 字节交错，需做 800 / 400 回绕修正
    sc = [ord(s[4]), ord(s[5]), ord(s[6])]
    n = (sc[0] - 28) * 10 + (sc[1] - 28) // 10
    if n >= 800:
        n -= 800
    out['speed_kt'] = n
    n2 = ((sc[1] - 28) % 10) * 100 + (sc[2] - 28)
    if n2 >= 400:
        n2 -= 400
    out['course'] = None if n2 == 0 else (0 if n2 == 360 else n2)

    # 符号：Mic-E 里「符号码在前、符号表在后」，与常规位置报文相反
    out['symbol_code'] = s[7]
    out['symbol_table'] = s[8]
    text = s[9:]

    # 可选高度：文本最前面是 3 个 base-91 字符 + '}'（单位米，基值 10000）
    m = re.match(r'^([\\x21-\\x7b]{3})\\}', text)
    if m:
        v = 0
        for ch2 in m.group(1):
            v = v * 91 + (ord(ch2) - 33)
        out['alt_m'] = v - 10000
        text = text[m.end():]

    out['comment'] = text
    out['mice_std_msg'] = std_msg
    out['mice_cust_msg'] = cust_msg
    if std_msg == 0 and cust_msg == 0:
        out['mice_status'] = '未指定（消息位全 0）'
    elif std_msg and not cust_msg:
        out['mice_status'] = MIC_E_STD_MSG[std_msg & 7]
    elif cust_msg and not std_msg:
        out['mice_status'] = MIC_E_CUST_MSG[cust_msg & 7]
    else:
        out['mice_status'] = '非法组合（标准集与自定义集混用）'
    return out


'''

old_a = "def parse_info(info):\n"
new_a = NEW_CODE + "def parse_info(info, dest=''):\n"
E.append((old_a, new_a))

# ---------------------------------------------------------------- B. mice 分支
old_b = """    if c in '`\\'':
        out['dtype'] = 'mice'
        out['comment'] = s[9:]
        # Mic-E 的经纬度编码在目的地址里，解析需要目的地址，交给上层补
        out['mice_raw'] = s[1:9]
        return out"""
new_b = """    if c in '`\\'':
        out['mice_raw'] = s
        mic = parse_mic_e(dest, s)
        for k, v in mic.items():
            if v is not None:
                out[k] = v
        out['dtype'] = 'mice'
        return out"""
E.append((old_b, new_b))

# ---------------------------------------------------------------- C. parse_packet 传 dest
old_c = "    info = parse_info(fr['info'])\n"
new_c = ("    # Mic-E 的纬度编码在目的地址里，必须把目的呼号一起传进去\n"
         "    info = parse_info(fr['info'], (fr['dst'] or {}).get('call', ''))\n")
E.append((old_c, new_c))

# ---------------------------------------------------------------- D. 字段白名单
old_d = """    for k in ('lat', 'lon', 'symbol_table', 'symbol_code', 'comment', 'wx',
              'analogs', 'digital', 'seq', 'msg_to', 'msg_text', 'msg_id',
              'obj_name', 'course', 'speed_kt', 'alt_m', 'ambiguity'):"""
new_d = """    for k in ('lat', 'lon', 'symbol_table', 'symbol_code', 'comment', 'wx',
              'analogs', 'digital', 'seq', 'msg_to', 'msg_text', 'msg_id',
              'obj_name', 'course', 'speed_kt', 'alt_m', 'ambiguity',
              'mice_dti', 'mice_dest', 'mice_lat_ns', 'mice_lon_ew',
              'mice_lon_offset', 'mice_status', 'mice_std_msg', 'mice_cust_msg',
              'mice_msg_capable', 'mice_raw'):"""
E.append((old_d, new_d))

# ---------------------------------------------------------------- E. 数据库列
old_e = """    wx_json TEXT, telemetry_json TEXT,"""
new_e = """    wx_json TEXT, telemetry_json TEXT, mice_json TEXT,"""
E.append((old_e, new_e))
E.append((
    "    wx_json TEXT, telemetry_json TEXT,",
    "    wx_json TEXT, telemetry_json TEXT, mice_json TEXT,"))

old_f = """                'course', 'speed_kt', 'alt_m', 'wx_json', 'telemetry_json',
                'msg_to', 'msg_text', 'msg_id', 'obj_name', 'source', 'created')"""
new_f = """                'course', 'speed_kt', 'alt_m', 'wx_json', 'telemetry_json',
                'mice_json',
                'msg_to', 'msg_text', 'msg_id', 'obj_name', 'source', 'created')"""
E.append((old_f, new_f))

old_g = """            elif c == 'telemetry_json':"""
new_g = """            elif c == 'mice_json':
                mice = {k: rec.get(k) for k in (
                    'mice_dti', 'mice_dest', 'mice_lat_ns', 'mice_lon_ew',
                    'mice_lon_offset', 'mice_status', 'mice_std_msg',
                    'mice_cust_msg', 'mice_msg_capable') if rec.get(k) is not None}
                v = json.dumps(mice, ensure_ascii=False) if mice else None
            elif c == 'telemetry_json':"""
E.append((old_g, new_g))

for i, (o, n) in enumerate(E):
    c = src.count(o)
    assert c == 1, 'anchor %d 命中 %d 次: %r' % (i + 1, c, o[:70])
    src = src.replace(o, n, 1)

with open(PATH, 'w', encoding='utf-8') as f:
    f.write(src)
print('Mic-E 已实现，%d 处改动，文件 %d 字节' % (len(E), len(src)))
