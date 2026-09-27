# -*- coding: utf-8 -*-
"""数值口语化的自测（纯函数，不需要板子/Flask）。

盯三件事：
  1) 中文数字写对（含万/亿分组、组间补零、四舍五入到两位、不补零）；
  2) 只在**看得出是计量**的地方改写，呼号/日期/时刻/坐标/型号/编号一律不碰；
  3) 幂等 —— 播报、TTS 入口、网页对话三处都会调用它，重复调用不能越改越乱。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import announce_service as A                                        # noqa: E402
import speech_text as S                                             # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


print('\n=== 1. 中文整数 ===')
for n, want in ((0, '零'), (1, '一'), (9, '九'), (10, '十'), (11, '十一'), (12, '十二'),
                (19, '十九'), (20, '二十'), (21, '二十一'), (99, '九十九'),
                (100, '一百'), (102, '一百零二'), (110, '一百一十'), (120, '一百二十'),
                (1000, '一千'), (1002, '一千零二'), (1050, '一千零五十'),
                (10000, '一万'), (10005, '一万零五'), (12000, '一万二千'),
                (100000, '十万'), (100200, '十万零二百'), (2026, '二千零二十六'),
                (120000, '十二万'), (1234567, '一百二十三万四千五百六十七'),
                (100000000, '一亿'), (-15, '负十五')):
    check('%s → %s' % (n, want), S.cn_int(n) == want, S.cn_int(n))

print('\n=== 2. 小数与四舍五入（最多两位、不补零）===')
for t, want in (('12.2446', '十二点二四'), ('12.1957', '十二点二'), ('48.1', '四十八点一'),
                ('13.2', '十三点二'), ('0.5', '零点五'), ('12.20', '十二点二'),
                ('12.199', '十二点二'), ('9.999', '十'), ('-3.456', '负三点四六'),
                ('0.0', '零'), ('12', '十二'), ('2.005', '二点零一'),
                ('99.999', '一百'), ('09', '零九'), ('007', '零零七')):
    check('%s → %s' % (t, want), S.cn_number(t) == want, S.cn_number(t))
check('非数字返回 None', S.cn_number('abc') is None)
check('带单位返回 None', S.cn_number('12V') is None)

print('\n=== 3. 计量数值改写 ===')
for src, want in (
        ('电池电压12.1957伏特，机内温度52.7摄氏度。',
         '电池电压十二点二伏特，机内温度五十二点七摄氏度。'),
        ('中继台运行正常，电池电压12.369伏特，机内温度47.2摄氏度。',
         '中继台运行正常，电池电压十二点三七伏特，机内温度四十七点二摄氏度。'),
        ('内存占用92.1%，剩余15.6GB，负载1.74。',
         '内存占用百分之九十二点一，剩余十五点六吉字节，负载一点七四。'),
        ('当前风速2.7米每秒，今日累计降水0.0毫米。',
         '当前风速二点七米每秒，今日累计降水零毫米。'),
        ('温度范围25.5-35.0摄氏度。', '温度范围二十五点五到三十五摄氏度。'),
        ('电池电压12.10V、机内温度48.1°C。', '电池电压十二点一伏特、机内温度四十八点一摄氏度。'),
        ('CPU温度49.9摄氏度，磁盘剩余15.60吉字节。',
         'CPU温度四十九点九摄氏度，磁盘剩余十五点六吉字节。'),
        ('海拔 45 米，距离 2.5 公里。', '海拔 四十五米，距离 二点五公里。'),
        ('电压 12 伏特。', '电压 十二伏特。'),
):
    got = S.speakable(src)
    check('%s' % src[:22], got == want, '得到：%s' % got)

print('\n=== 4. 绝不碰的东西 ===')
for src in ('BG7LTG-7 在东南二点七零公里，BI7KHI-9 距离你 12.3 公里。',
            '2026年9月27日 19:09:22 星期六',
            '北纬23.0564，东经113.368',
            'RK3588 上跑 qwen2.5-1.5b',
            'GPIO 97，SSID 7，端口 8080',
            '频率 438.500 MHz 守听',
            '第 3 条记录，编号 1024',
            'APRS 信标：BI7KHI-9>APRS,WIDE1-1'):
    got = S.speakable(src)
    # 呼号/型号/编号部分必须原样（允许其中真正的计量被改写）
    keep = [w for w in ('BG7LTG-7', 'BI7KHI-9', '2026年9月27日', '19:09:22',
                        '23.0564', '113.368', 'RK3588', 'qwen2.5-1.5b', 'GPIO 97',
                        'SSID 7', '8080', '438.500', '第 3 条', '编号 1024',
                        'BI7KHI-9>APRS,WIDE1-1') if w in src]
    ok = all(w in got for w in keep)
    check('保留 %s' % ('/'.join(keep) or src[:12]), ok, '得到：%s' % got)

print('\n=== 5. 边界与幂等 ===')
check('空串不崩', S.speakable('') == '')
check('None 不崩', S.speakable(None) == '')
check('无数字文本不变', S.speakable('中继台运行正常。') == '中继台运行正常。')
check('纯中文数字不变', S.speakable('十二点二四伏特') == '十二点二四伏特')
samples = ['电池电压12.1957伏特，机内温度52.7摄氏度。',
           '内存占用92.1%，剩余15.6GB',
           '温度范围25.5-35.0摄氏度',
           'BG7LTG-7 距离 12.3 公里',
           '2026年9月27日 19:09:22']
for s in samples:
    once = S.speakable(s)
    check('幂等：%s' % s[:20], S.speakable(once) == once, S.speakable(once))

print('\n=== 6. 播报模板联动（默认模板 + 实时变量）===')
VALS = {'time_cn': '北京时间十四点整', 'battery': 12.2446, 'pv': 6.1445,
        'cpu_temp': 47.2, 'load1': 0.85, 'mem_percent': 92.1, 'uptime_h': 10.1,
        'wind': 2.7, 'rain_today': 0.0, 'wx_temp': 31.5, 'wx_temp_max': 35.0,
        'wx_temp_min': 25.5, 'wx_humidity': 56, 'wx_wind': 2.7, 'wx_condition': '晴',
        'weekday': '六'}


def expand(t, v=None):
    vals = dict(VALS)
    vals.update(v or {})

    def rep(m):
        x = vals.get(m.group(1))
        return m.group(0) if x is None else str(x)
    import re
    return re.sub(r'\{([a-z_][a-z0-9_]*)\}', rep, t)


text = A.compose({'time': True, 'status': True, 'weather': True}, A.DEFAULTS, VALS,
                 expand=expand)
print('     展开后：%s' % text)
spoken = S.speakable(text)
print('     口语化：%s' % spoken)
check('展开后确实带着原始阿拉伯数值（这就是问题现场）',
      '12.2446' in text or '47.2' in text, text)
check('口语化后不再有带小数点的阿拉伯数字',
      not any(c.isdigit() and '.' in spoken[i:i + 6]
              for i, c in enumerate(spoken)), spoken)
check('电压读成「十二点二四」', '十二点二四' in spoken, spoken)
check('温度读成「四十七点二摄氏度」', '四十七点二摄氏度' in spoken, spoken)
check('时间仍是中文时刻读法', '北京时间十四点整' in spoken, spoken)

print('\n=== 7. 助手回复出口（clamp_reply → clean_for_tts）也走同一套 ===')
try:
    import assistant_service as AS
    got, _trunc = AS.clamp_reply('电池电压12.4893伏特，机内温度54.5摄氏度。', 100)
    check('助手回复里的数值已口语化',
          '十二点四九伏特' in got and '五十四点五摄氏度' in got, got)
    check('长度上限仍生效', len(AS.clamp_reply('甲' * 300, 100)[0]) <= 100)
    check('空回复不崩', AS.clamp_reply('', 100)[0] == '')
except Exception as e:
    print('  SKIP 助手模块不可用（%s: %s）' % (type(e).__name__, e))

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  x %s' % f)
sys.exit(1 if FAIL else 0)
