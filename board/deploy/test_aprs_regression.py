#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对真实中继录音做流式 TNC 回归验证。

模拟 app.py 采集中枢的喂法：每块 1024 个单声道样本（arecord 一次读 4096 字节
S16_LE 立体声 = 1024 帧）。验证目标：
  #51 vlog_222607_rx_00.wav  APRS 在 t≈8.72s
  #46 vlog_221421_rx_00.wav  APRS 在 t≈7.82s
报文应为 BI7KHI>APN000,BI7KHI,WIDE1-1,WIDE2-1  INFO='>'
"""
import glob
import json
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aprs_service as A


def load(f):
    with wave.open(f, 'rb') as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    d = np.frombuffer(raw, dtype='<i2').astype(np.float64) / 32768.0
    if ch > 1:
        d = d.reshape(-1, ch).mean(axis=1)
    return d, sr, ch


def main(files):
    tot_frames = 0
    tot_hits = 0
    for f in files:
        x, sr, ch = load(f)
        tnc = A.Tnc(sr)
        t0 = time.time()
        frames = []
        # 采集中枢的真实块大小
        for i in range(0, len(x), 1024):
            frames += tnc.feed(x[i:i + 1024])
        frames += tnc.flush()
        el = time.time() - t0
        uniq = {}
        for (t, fr) in frames:
            uniq.setdefault(bytes(fr), t)
        real = tnc.d_len
        print('=== %-26s %6.2fs ch=%d  解出唯一帧=%d  用时 %.2fs (%.1f%% 实时)'
              % (os.path.basename(f), len(x) / sr, ch, len(uniq),
                 el, el / (len(x) / sr) * 100))
        if frames:
            tot_hits += 1
        tot_frames += len(uniq)
        for fr, t in sorted(uniq.items(), key=lambda kv: kv[1]):
            rec = A.parse_packet(fr)
            if not rec:
                print('    [解析失败] %s' % fr.hex().upper())
                continue
            print('    t=%.2fs  %s' % (t, rec['path']))
            print('      dtype=%s len=%d ctrl=%02X pid=%s' % (
                rec['dtype'], rec['frame_len'], rec['ctrl'],
                hex(rec['pid']) if rec['pid'] is not None else '-'))
            print('      INFO=%r' % rec['info'])
            if rec.get('lat') is not None:
                print('      POS=%.6f,%.6f  sym=%s%s' % (
                    rec['lat'], rec['lon'], rec.get('symbol_table', ''),
                    rec.get('symbol_code', '')))
        if not uniq:
            print('    (该段无 APRS)')
    print('\n汇总：%d/%d 个文件解出 APRS，共 %d 个唯一帧' % (tot_hits, len(files), tot_frames))
    return 0 if tot_hits >= 2 else 1


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        args = sorted(glob.glob('/opt/ai/relay_voice/*/vlog_*.wav'))
    sys.exit(main(args))
