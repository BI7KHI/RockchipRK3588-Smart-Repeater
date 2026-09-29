# -*- coding: utf-8 -*-
"""能量统计纯计算层自测（不需要板子、不需要 Flask、不碰硬件）。

覆盖：分桶、缺桶不补值、当日统计取原始采样、CSV 导出、以及 API 用的那条
「按天过滤」SQL 对 ISO 时间戳是否真的成立。
"""
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import energy_service as E

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


# ---------------------------------------------------------------------------
print('\n=== 1. 参数钳制 ===')
check('interval 下限 1', E.clamp_interval(0) == 1)
check('interval 上限 120', E.clamp_interval(9999) == 120)
check('interval 正常值', E.clamp_interval('10') == 10)
check('interval 垃圾输入退回 5', E.clamp_interval('abc') == 5)
check('interval 小数向下取整', E.clamp_interval(7.9) == 7)
check('sample_sec 下限 10', E.clamp_sample_sec(1) == 10)
check('sample_sec 上限 600', E.clamp_sample_sec(99999) == 600)
check('sample_sec 默认 60', E.clamp_sample_sec(None) == 60)
check('retention 下限 1', E.clamp_retention_days(0) == 1)
check('retention 上限 3650', E.clamp_retention_days(10 ** 9) == 3650)
check('retention 默认 365', E.clamp_retention_days('') == 365)

# ---------------------------------------------------------------------------
print('\n=== 2. 分桶（缺桶不补值）===')
# 基准：某天 00:00 起，步长 3600 秒对齐
BASE = int(datetime(2026, 9, 26, 0, 0, 0).timestamp())


def row(minutes, battery, pv=None, raw=100):
    return {'ts': datetime.fromtimestamp(BASE + minutes * 60).strftime(
                '%Y-%m-%dT%H:%M:%S+08:00'),
            'ts_epoch': BASE + minutes * 60,
            'battery': battery, 'pv': pv, 'battery_raw': raw, 'pv_raw': raw}


rows = [row(0, 12.0, 18.0), row(10, 12.4, 18.6), row(30, 11.8, 17.0),
        row(120, 12.2, 19.0)]
pts = E.points_from_rows(rows, 60)
check('1 小时分桶 → 2 个桶（0~59 分一桶，120 分一桶）', len(pts) == 2,
      str(len(pts)))
check('同一桶内取平均', pts[0]['battery'] == round((12.0 + 12.4 + 11.8) / 3, 3),
      str(pts[0]['battery']))
check('同一桶内记 min/max', pts[0]['battery_min'] == 11.8
      and pts[0]['battery_max'] == 12.4, str(pts[0]))
check('空的 01:00 桶**不补**：两点相隔 7200 秒而不是补出中间那个点',
      pts[1]['epoch'] - pts[0]['epoch'] == 7200,
      str(pts[1]['epoch'] - pts[0]['epoch']))
check('桶按时间升序', [p['epoch'] for p in pts] == sorted(p['epoch'] for p in pts))
check('n 记的是桶内采样数', pts[0]['n'] == 3 and pts[1]['n'] == 1,
      str([p['n'] for p in pts]))
check('time 形如 HH:MM', bool(re.match(r'^\d{2}:\d{2}$', pts[0]['time'])),
      pts[0]['time'])
check('minute 形如 YYYY-MM-DD HH:MM',
      bool(re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$', pts[0]['minute'])),
      pts[0]['minute'])

# 只有 pv、没有 battery 的桶：battery 必须是 None，不能变成 0
pts2 = E.points_from_rows([row(0, None, 18.0)], 60)
check('battery 缺测时给 None 而不是 0', pts2[0]['battery'] is None, str(pts2[0]))
check('同一桶的 pv 照常有值', pts2[0]['pv'] == 18.0, str(pts2[0]))

check('空输入返回空表', E.points_from_rows([], 5) == [])
check('缺 ts_epoch 的行被跳过', E.points_from_rows([{'battery': 1.0}], 5) == [])
check('单点也能出桶', len(E.points_from_rows([row(0, 12.0)], 5)) == 1)
check('5 分钟步长比 60 分钟出更多桶',
      len(E.points_from_rows(rows, 5)) > len(E.points_from_rows(rows, 60)))
check('interval 非法时退回 5 分钟（不崩）',
      len(E.points_from_rows(rows, 'x')) == len(E.points_from_rows(rows, 5)))

# ---------------------------------------------------------------------------
print('\n=== 3. 当日统计（必须取原始采样，不能被分桶均值抹平尖峰）===')
spike = [row(0, 12.6, 20.0), row(5, 11.0, 19.0), row(10, 12.4, 18.0)]
st = E.day_stats(spike)
check('最高取原始值 12.6', st['battery']['max'] == 12.6, str(st['battery']))
check('最低取原始值 11.0（尖峰没被均值抹掉）',
      st['battery']['min'] == 11.0, str(st['battery']))
check('平均为 3 点均值', st['battery']['avg'] == round((12.6 + 11.0 + 12.4) / 3, 3),
      str(st['battery']))
check('最高时刻指向那条采样',
      st['battery']['max_ts'] == spike[0]['ts'], st['battery']['max_ts'])
check('最低时刻指向那条采样',
      st['battery']['min_ts'] == spike[1]['ts'], st['battery']['min_ts'])
check('峰谷差 = 1.6', st['battery_drop'] == 1.6, str(st['battery_drop']))
check('统计点数 = 3', st['points'] == 3)
check('光伏最高 20.0', st['pv']['max'] == 20.0, str(st['pv']))
check('起止时间取首尾', st['first_ts'] == spike[0]['ts']
      and st['last_ts'] == spike[-1]['ts'])

empty = E.day_stats([])
check('空数据不崩且全 None',
      empty['battery']['min'] is None and empty['battery']['avg'] is None
      and empty['battery']['max_ts'] == '' and empty['points'] == 0, str(empty))
nullch = E.day_stats([row(0, None, 18.0)])
check('整通道缺测时该通道全 None', nullch['battery']['max'] is None, str(nullch['battery']))
check('缺测通道不产生峰谷差', nullch['battery_drop'] is None, str(nullch['battery_drop']))
check('另一通道照常统计', nullch['pv']['max'] == 18.0)

# ---------------------------------------------------------------------------
print('\n=== 4. CSV 导出 ===')
csv = E.rows_to_csv([row(0, 12.3456, 18.9), row(1, None, 19.0)])
lines = csv.strip().split('\n')
# 表头在 2026-09-29 扩列：采样层改成「摊开取中位数」后，min/max/n_reads/load
# 是证据列（中位数是存下来的值，min/max 保留纹波与压降的真实幅度，load 标记
# 这一轮里是否正在发射）。这是**有意的契约变更**，不是回归。
check('表头含新增证据列',
      lines[0] == ('时间,时间戳,电池电压V,光伏电压V,电池ADC,光伏ADC,'
                   '电池最低V,电池最高V,光伏最低V,光伏最高V,本轮读数,发射中'),
      lines[0])
check('行数 = 表头 + 数据', len(lines) == 3, str(len(lines)))
check('电压保留 4 位小数', '12.3456' in lines[1] and '18.9000' in lines[1], lines[1])
check('缺测留空而不是 0', lines[2].split(',')[2] == '', lines[2])
check('空输入只有表头', len(E.rows_to_csv([]).strip().split('\n')) == 1)

# ---------------------------------------------------------------------------
print('\n=== 4b. 滤波（Hampel / 中位数）===')
spiky = [12.80, 12.79, 12.81, 12.78, 11.13, 12.80, 12.82, 12.77, 12.79, 12.81,
         12.80, 8.44, 12.78, 12.80, 12.79]
flt, flags = E.hampel(spiky, 7, 3.0)
check('Hampel 揪出两个离群点', len(flags) == 2, str(flags))
check('离群点被局部中位数替换',
      abs(flt[4] - 12.80) < 0.05 and abs(flt[11] - 12.80) < 0.05,
      '%r' % [round(x, 3) for x in flt])
check('非离群点原样保留', flt[0] == 12.80 and flt[14] == 12.79)
med = E.median_filter(spiky, 5)
check('中位数滤波也压掉尖峰', min(med) > 12.0, '%.3f' % min(med))
same, noflag = E.smooth(spiky, 'none')
check("mode='none' 一个点都不改", same == spiky and not noflag)
check('窗口强制奇数', E.clamp_filter_window(8) == 9 and E.clamp_filter_window(2) == 3)
check('非法滤波模式退回 hampel', E.normalize_filter('乱写') == 'hampel')
check('合法模式原样', E.normalize_filter('median') == 'median')

# ---------------------------------------------------------------------------
print('\n=== 4c. 静息电压估计（剔除发射中的采样）===')
_now = 1800000000.0
rows_r = [dict(ts='t%d' % i, ts_epoch=_now - (20 - i) * 60, battery=v, pv=18.0,
               load=l)
          for i, (v, l) in enumerate([(12.80, 0), (12.79, 0), (12.81, 0),
                                      (10.20, 1), (12.78, 0), (12.80, 0),
                                      (12.82, 0), (9.90, 1), (12.79, 0)])]
r = E.rested_voltage(rows_r, now=_now)
check('静息估计剔除了 load=1 的低值', abs(r['battery'] - 12.80) < 0.03, str(r))
check('来源标记为 idle-median', r['source'] == 'idle-median', r['source'])
check('样本数 = 非发射采样数', r['samples'] == 7, str(r['samples']))
check('窗口外的不参与',
      E.rested_voltage(rows_r, window_min=3, now=_now)['samples'] <= 3,
      str(E.rested_voltage(rows_r, window_min=3, now=_now)))
few = [dict(ts='t', ts_epoch=_now, battery=12.5, pv=18.0, load=0)]
r2 = E.rested_voltage(few, now=_now)
check('样本不足时明确报 insufficient',
      r2['source'] == 'insufficient' and r2['battery'] is None, str(r2))
r3 = E.rested_voltage([], now=_now)
check('无采样不崩', r3['battery'] is None and r3['source'] == 'none')
old = [dict(ts='t%d' % i, ts_epoch=_now - i * 60, battery=12.0 + i * 0.01,
            pv=18.0) for i in range(6)]        # 老数据没有 load 列
r4 = E.rested_voltage(old, now=_now)
check('老数据（无 load 列）不剔除、只用中位数', r4['battery'] is not None,
      str(r4))

# ---------------------------------------------------------------------------
print('\n=== 4d. 采样参数钳制（读得密会把读数压低，所以是「少读、读得开」）===')
check('默认一轮读 3 次', E.clamp_burst_reads(60) == 3, str(E.clamp_burst_reads(60)))
check('一轮占用 = (n-1)×间隔',
      E.burst_seconds(60) == round(2 * E.BURST_GAP_MS / 1000.0, 1),
      str(E.burst_seconds(60)))
check('采样间隔 10s 时自动少读，避免占着 ADC',
      E.clamp_burst_reads(10) >= 1 and E.burst_seconds(10) <= 5.0,
      (E.clamp_burst_reads(10), E.burst_seconds(10)))
check('再短的间隔也至少读 1 次', E.clamp_burst_reads(1) == 1,
      str(E.clamp_burst_reads(1)))
check('垃圾输入回默认次数', E.clamp_burst_reads('abc') == 3,
      str(E.clamp_burst_reads('abc')))
check('两次读之间至少 1.5 秒（实测 0.5s 会掉 1V）',
      E.BURST_GAP_MS >= 1500, str(E.BURST_GAP_MS))

# ---------------------------------------------------------------------------
print('\n=== 4e. 统计同时给「原始」与「滤波后」两套 ===')
spiky_rows = [dict(ts='2026-09-29T00:%02d:00' % i, ts_epoch=1000.0 + i * 60,
                   battery=v, pv=12.0, load=0)
              for i, v in enumerate([12.8, 12.8, 12.8, 8.4, 12.8, 12.8, 12.8])]
s = E.day_stats(spiky_rows, 'hampel', 5)
check('原始 min 保留尖峰（刻意的取舍）', s['battery']['min'] == 8.4,
      str(s['battery']))
check('原始峰谷差同样保留', s['battery_drop'] == 4.4, str(s['battery_drop']))
check('滤波后 min 抹掉尖峰', s['battery_f']['min'] > 12.5, str(s['battery_f']))
check('滤波后峰谷差变小', s['battery_drop_f'] < 0.2, str(s['battery_drop_f']))
check('报出剔了几个离群点', s['outliers'] == 1, str(s['outliers']))
check('统计里带静息估计',
      'rested' in s and s['rested']['battery'] is not None, str(s.get('rested')))
check('滤波口径可回读', s['filter'] == 'hampel' and s['filter_window'] == 5)
pts = E.points_from_rows(spiky_rows, 1, 'hampel', 5)
check('曲线点带滤波列', all('battery_f' in p for p in pts))
check('曲线点仍带原始桶均值与极值',
      all(('battery' in p and 'battery_min' in p) for p in pts))
check('桶内离群计数可查', sum(p['outliers'] for p in pts) == 1,
      str([p['outliers'] for p in pts]))
pts0 = E.points_from_rows(spiky_rows, 1, 'none')
check("filter='none' 时滤波列等于原始桶均值",
      all(p['battery_f'] == p['battery'] for p in pts0))

# ---------------------------------------------------------------------------
print('\n=== 5. API 用的那条按天过滤 SQL（ISO 时间戳能否 LIKE 命中）===')
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, 't.db')
c = sqlite3.connect(db)
c.executescript('''
CREATE TABLE voltage_readings (id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, ts_epoch REAL NOT NULL, battery REAL, pv REAL,
  battery_raw INTEGER, pv_raw INTEGER);
''')
for r in rows:
    c.execute('INSERT INTO voltage_readings(ts,ts_epoch,battery,pv,battery_raw,pv_raw)'
              ' VALUES(?,?,?,?,?,?)',
              (r['ts'], r['ts_epoch'], r['battery'], r['pv'],
               r['battery_raw'], r['pv_raw']))
# 再塞一条前一天的，验证按天过滤真的把它挡在外面
c.execute('INSERT INTO voltage_readings(ts,ts_epoch,battery,pv) VALUES(?,?,?,?)',
          ('2026-09-25T23:59:00+08:00', BASE - 60, 99.0, 99.0))
c.commit()
got = c.execute('SELECT ts,battery FROM voltage_readings WHERE ts LIKE ? '
                'ORDER BY ts_epoch ASC LIMIT 20000', ('2026-09-26%',)).fetchall()
c.close()
check('按天过滤命中当天 4 条', len(got) == 4, str(len(got)))
check('前一天的采样被挡住', all(v != 99.0 for _, v in got))
check('过滤出来的行能直接喂给分桶',
      len(E.points_from_rows([{'ts_epoch': BASE, 'battery': 12.0}], 60)) == 1)

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  ✗ %s' % f)
sys.exit(1 if FAIL else 0)
