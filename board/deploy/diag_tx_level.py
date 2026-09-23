# -*- coding: utf-8 -*-
"""量化发射期间的真实电平：APRS 与 TTS 语音各有多高。

整段 dBFS 会被 3 s 前导 + 2 s 尾音稀释（APRS 整段 -13.4，实际发射时 -3~-4）。
这里只统计「发射中」的窗口，给出可比的 RMS / 峰值 / 峰均比，
用来回答「APRS 电平是否真的比语音高」。
"""
import sqlite3
import sys

import numpy as np

sys.path.insert(0, '/www')
import voice_service as vs

c = sqlite3.connect('/www/relay.db')
c.row_factory = sqlite3.Row


def active_window(x, sr, rel=0.25):
    """用短时 RMS 找出真正的发射窗口（超过整段峰值 -20 dB 的部分）。"""
    win = int(0.05 * sr)
    rms = np.array([np.sqrt((x[i:i + win] ** 2).mean())
                    for i in range(0, max(1, len(x) - win), win)])
    if rms.size == 0:
        return 0, len(x)
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    thr = db.max() - 20.0
    on = np.where(db >= thr)[0]
    if on.size == 0:
        return 0, len(x)
    return on[0] * win, min(len(x), (on[-1] + 1) * win)


print('=== 发射期间的真实电平（已剔除前导/尾音静音）===')
print('%-5s %-8s %8s %9s %9s %9s %8s' % (
    'id', '类别', '发射时长', 'RMS dBFS', '峰值 dBFS', '峰均比', '削顶数'))

rows = list(c.execute(
    "SELECT id,ts,kind,category,path FROM voice_logs "
    "WHERE kind='tx' AND path IS NOT NULL ORDER BY id DESC LIMIT 14"))
aps = []
for r in rows:
    x, sr = vs.read_wav_mono(r['path'])
    if x.size == 0:
        continue
    a, b = active_window(x, sr)
    seg = x[a:b]
    if seg.size < 100:
        continue
    rms = float(np.sqrt((seg ** 2).mean()))
    pk = float(np.abs(seg).max())
    crest = 20 * np.log10(max(pk, 1e-9) / max(rms, 1e-9))
    nclip = int((np.abs(seg) >= 0.995).sum())
    rms_db = 20 * np.log10(max(rms, 1e-9))
    pk_db = 20 * np.log10(max(pk, 1e-9))
    print('#%-4d %-8s %7.1fs %9.1f %9.1f %9.1f %8d' % (
        r['id'], r['category'], len(seg) / float(sr), rms_db, pk_db, crest, nclip))
    if r['category'] == 'tone':
        aps.append((rms_db, pk_db))

print()
# 对照：接收段同样口径
print('=== 对照：接收（rx）发射期间口径 ===')
rows = list(c.execute(
    "SELECT id,ts,kind,category,path FROM voice_logs "
    "WHERE kind='rx' AND path IS NOT NULL ORDER BY id DESC LIMIT 8"))
for r in rows:
    x, sr = vs.read_wav_mono(r['path'])
    a, b = active_window(x, sr)
    seg = x[a:b]
    if seg.size < 100:
        continue
    rms = float(np.sqrt((seg ** 2).mean()))
    pk = float(np.abs(seg).max())
    print('#%-4d %-8s %7.1fs %9.1f %9.1f %9.1f %8d' % (
        r['id'], r['category'], len(seg) / float(sr),
        20 * np.log10(max(rms, 1e-9)), 20 * np.log10(max(pk, 1e-9)),
        20 * np.log10(max(pk, 1e-9) / max(rms, 1e-9)),
        int((np.abs(seg) >= 0.995).sum())))

print()
print('=== 发射链数字域参数（用于反推串扰衰减）===')
print('  APRS: AFSK_AMP=0.55，单音幅度 0.55 → 峰值 -5.19 dBFS；')
print('        实测标称峰值 -2.9 dBFS（两音叠加后）')
print('  TTS : Piper 输出 WAV，需实测峰值')
import subprocess
try:
    out = subprocess.run(['bash', '-lc',
                          'ls -t /www/tts_cache/*.wav 2>/dev/null | head -1'],
                         capture_output=True, text=True, timeout=10).stdout.strip()
    if out:
        w, sr = vs.read_wav_mono(out)
        print('        最近合成文件 %s：峰值 %.1f dBFS，RMS %.1f dBFS'
              % (out.split('/')[-1],
                 20 * np.log10(max(float(np.abs(w).max()), 1e-9)),
                 20 * np.log10(max(float(np.sqrt((w ** 2).mean())), 1e-9))))
except Exception as e:
    print('        取 TTS 样例失败：%s' % e)
