#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解调灵敏度实验：在真实录音上比较不同解调变体，用「是否解出」说话。

变体维度：
  band  : 带通范围
  frac  : 是否用分数间隔匹配滤波（真实比特长度 sr/1200=13.333，取整 W=13 会截断）
  dfo   : 频偏搜索范围（Hz），真实电台 AFC/晶振偏差会有几十 Hz
"""
import glob
import os
import sys
import time
import wave

import numpy as np


def load(f):
    with wave.open(f, 'rb') as w:
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
        sr = w.getframerate()
    d = np.frombuffer(raw, dtype='<i2').astype(np.float64) / 32768.0
    if ch > 1:
        d = d.reshape(-1, ch).mean(axis=1)
    return d, sr


def bandpass(x, sr, lo, hi, order=4):
    from scipy.signal import butter, lfilter
    if lo <= 0:
        b, a = butter(order, hi / (sr / 2.0), btype='low')
    else:
        b, a = butter(order, [lo / (sr / 2.0), hi / (sr / 2.0)], btype='band')
    return lfilter(b, a, x)


def crc16_x25(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (crc & 1) else (crc >> 1)
    return crc ^ 0xFFFF


FLAG = [0, 1, 1, 1, 1, 1, 1, 0]


def nrzi_decode(levels):
    out = []
    prev = 1
    for b in levels:
        out.append(1 if b == prev else 0)
        prev = b
    return out


def bits_to_frames(bits):
    n = len(bits)
    res = []
    if n < 8:
        return res
    b = np.asarray(bits, dtype=np.uint8)

    def isf(p):
        return p + 8 <= n and b[p] == 0 and b[p + 7] == 0 and bool(b[p + 1:p + 7].all())

    j = 0
    while j + 8 <= n:
        if not isf(j):
            j += 1
            continue
        k = j + 8
        while isf(k):
            k += 8
        out = bytearray()
        ones = 0
        closed = False
        while k < n:
            if ones < 5 and isf(k):
                closed = True
                break
            bit = int(b[k])
            if ones == 5:
                if bit == 1:
                    break
                ones = 0
                k += 1
                continue
            ones = ones + 1 if bit else 0
            out.append(bit)
            k += 1
        if closed and len(out) >= 136:
            m = len(out) - (len(out) % 8)
            bs = bytes(sum((out[i + t] & 1) << t for t in range(8))
                       for i in range(0, m, 8))
            r = crc16_x25(bs)
            if r in (0xF0B8, 0x0F47):
                res.append(bs)
        j = k if k > j else j + 1
    return res


def corr(sig, f, W, sr):
    t = np.arange(W) / sr
    return np.correlate(sig, np.exp(-2j * np.pi * f * t), 'valid')


def decision(xf, sr, f0, f1, frac=True, dfo=0.0):
    spb = sr / 1200.0
    W = max(4, int(np.floor(spb)))
    alpha = spb - W
    f0 = f0 + dfo
    f1 = f1 + dfo
    if frac and alpha > 1e-6:
        a0 = corr(xf, f0, W, sr)
        b0 = corr(xf, f0, W + 1, sr)
        a1 = corr(xf, f1, W, sr)
        b1 = corr(xf, f1, W + 1, sr)
        # W 与 W+1 的 'valid' 相关长度差 1，必须对齐到公共长度再混合
        m = min(len(a0), len(b0), len(a1), len(b1))
        y0 = (1 - alpha) * a0[:m] + alpha * b0[:m]
        y1 = (1 - alpha) * a1[:m] + alpha * b1[:m]
    else:
        y0 = corr(xf, f0, W, sr)
        y1 = corr(xf, f1, W, sr)
    p0 = y0.real ** 2 + y0.imag ** 2
    p1 = y1.real ** 2 + y1.imag ** 2
    return p0 - p1


def try_decode(x, sr, band=(300.0, 3600.0), frac=True, nphase=64, dfos=(0.0,)):
    xf = bandpass(x, sr, band[0], band[1])
    hits = {}
    for dfo in dfos:
        d = decision(xf, sr, 1200.0, 2200.0, frac=frac, dfo=dfo)
        n = len(d)
        spb = sr / 1200.0
        for pol in (1.0, -1.0):
            dd = d * pol
            for p in range(nphase):
                off = p * spb / nphase
                pos = np.arange(off, n - 1.001, spb)
                if len(pos) < 40:
                    continue
                i0 = pos.astype(np.int64)
                fr_ = pos - i0
                v = dd[i0] * (1 - fr_) + dd[i0 + 1] * fr_
                bits = nrzi_decode((v > 0).astype(np.uint8))
                for bs in bits_to_frames(bits):
                    hits.setdefault(bs, 0)
                    hits[bs] += 1
    return hits


def main():
    files = sorted(glob.glob('/opt/ai/relay_voice/*/vlog_*.wav'))
    data = [(os.path.basename(f),) + load(f) for f in files]
    variants = [
        ('A 400-3400 W=int (old)',   dict(band=(400.0, 3400.0), frac=False)),
        ('B 300-3600 W=int',         dict(band=(300.0, 3600.0), frac=False)),
        ('C 300-3600 frac',          dict(band=(300.0, 3600.0), frac=True)),
        ('D 300-3600 frac +-30Hz',   dict(band=(300.0, 3600.0), frac=True,
                                          dfos=(-30, 0, 30))),
        ('E 250-3800 frac +-30Hz',   dict(band=(250.0, 3800.0), frac=True,
                                          dfos=(-30, 0, 30))),
    ]
    print('%-30s %6s %6s  %s' % ('variant', 'files', 'frames', 'per-file(唯一帧数)'))
    for name, kw in variants:
        t0 = time.time()
        nf = 0
        tot = 0
        det = []
        for (nm, x, sr) in data:
            hits = try_decode(x, sr, **kw)
            u = len(hits)
            tot += u
            if u:
                nf += 1
            det.append('%s:%d' % (nm.split('_')[1], u))
        print('%-30s %6d %6d  %s  [%.1fs]' % (name, nf, tot, ' '.join(det), time.time() - t0))
    print('\n应命中文件：222607(#51) 与 221421(#46)')


if __name__ == '__main__':
    main()
