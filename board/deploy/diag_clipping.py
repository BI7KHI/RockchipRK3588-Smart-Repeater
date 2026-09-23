# -*- coding: utf-8 -*-
"""削顶定位：区分「持续幅度削顶」与「偶发尖峰（键控咔哒）」。

判据：
  * 持续削顶  → 接近满量程的样本大量且分散在整段，峰均比被压到 ~3 dB
  * 偶发尖峰  → 满量程样本集中在极少数位置（如 PTT 拉起/落下瞬间），
                 去掉尖峰后峰均比正常
对每条 tx / rx 记录给出：削顶样本数、占比、时间分布、剔尖后的真实峰值。
"""
import sqlite3
import sys

import numpy as np

sys.path.insert(0, '/www')
import voice_service as vs

c = sqlite3.connect('/www/relay.db')
c.row_factory = sqlite3.Row

FULL = 32767.0


def probe(row):
    x, sr = vs.read_wav_mono(row['path'])
    if x.size == 0:
        return None
    a = np.abs(x)
    # 接近满量程（留 0.5% 余量，避免把 32675 这类漏掉）
    thr = 0.995
    clipped = a >= thr
    n = int(clipped.sum())
    idx = np.where(clipped)[0]
    # 峰值
    pk = float(a.max())
    rms = float(np.sqrt((x ** 2).mean()))
    crest = 20 * np.log10(max(pk, 1e-9) / max(rms, 1e-9))
    # 剔掉满量程样本后的峰值与峰均比
    if n:
        mask = ~clipped
        pk2 = float(a[mask].max()) if mask.any() else 0.0
        rms2 = float(np.sqrt((x[mask] ** 2).mean())) if mask.any() else 0.0
        crest2 = 20 * np.log10(max(pk2, 1e-9) / max(rms2, 1e-9)) if rms2 else 0
    else:
        pk2, crest2 = pk, crest
    # 削顶样本是否连续成片（持续削顶）还是孤点（尖峰）
    if n > 1:
        runs = np.split(idx, np.where(np.diff(idx) > 8)[0] + 1)
        longest = max(len(r) for r in runs)
        nrun = len(runs)
    else:
        longest, nrun = n, n
    return {
        'dur': len(x) / float(sr), 'pk': pk, 'rms': rms, 'crest': crest,
        'nclip': n, 'ratio': n / float(len(x)) * 100,
        'first': (idx[0] / float(sr)) if n else -1,
        'last': (idx[-1] / float(sr)) if n else -1,
        'longest': longest, 'nrun': nrun, 'pk2': pk2, 'crest2': crest2,
    }


for kind in ('tx', 'rx'):
    rows = list(c.execute(
        "SELECT id,ts,kind,category,path,seconds FROM voice_logs "
        "WHERE kind=? AND path IS NOT NULL ORDER BY id DESC LIMIT 8", (kind,)))
    print('=' * 78)
    print('%s 最近 %d 条' % (kind, len(rows)))
    print('%-5s %-8s %6s %6s %6s %7s %8s %9s %8s %7s' % (
        'id', 'cat', '时长', '峰值', '峰均比', '削顶数', '占比%', '首/末(s)', '最长片', '剔尖峰均'))
    for r in rows:
        try:
            d = probe(r)
        except Exception as e:
            print('  #%s 读取失败 %s' % (r['id'], e))
            continue
        if not d:
            continue
        print('#%-4d %-8s %6.1f %6.0f %6.1f %7d %7.2f%% %9s %8d %7.1f' % (
            r['id'], r['category'], d['dur'], d['pk'], d['crest'], d['nclip'],
            d['ratio'], '%.2f/%.2f' % (d['first'], d['last']) if d['nclip'] else '-',
            d['longest'], d['crest2']))
    print()

# 对一条 APRS 发射做细看：削顶样本的位置分布
row = c.execute("SELECT id,ts,category,path,seconds FROM voice_logs "
                "WHERE kind='tx' AND category='tone' AND path IS NOT NULL "
                "ORDER BY id DESC LIMIT 1").fetchone()
if row:
    x, sr = vs.read_wav_mono(row['path'])
    a = np.abs(x)
    idx = np.where(a >= 0.995)[0]
    print('=' * 78)
    print('细节 #%d（%s，APRS 发射，%.1fs）削顶样本时间分布：' % (
        row['id'], row['ts'][11:19], len(x) / float(sr)))
    if idx.size:
        runs = np.split(idx, np.where(np.diff(idx) > 8)[0] + 1)
        for r_ in runs[:12]:
            print('    第 %6.3f ~ %6.3f s   连续 %d 个样本（约 %.4f s）'
                  % (r_[0] / float(sr), r_[-1] / float(sr), len(r_),
                     len(r_) / float(sr)))
    # 分段 RMS 包络
    win = int(0.25 * sr)
    env = [20 * np.log10(max(float(np.sqrt((x[i:i + win] ** 2).mean())), 1e-9))
           for i in range(0, len(x) - win, win)]
    print('  0.25s 包络（dBFS）: %s' % ' '.join('%.0f' % v for v in env[:40]))
