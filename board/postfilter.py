# -*- coding: utf-8 -*-
"""后处理：动态去齿音(de-esser) + 低通 + 高架衰减，抑制 Piper 输出的气声/齿音/过亮。
用法: python postfilter.py in.wav out.wav [--shelf-db -2] [--shelf-f 3500] [--lp 8000]
        [--deess-max 5] [--deess-lo 4500] [--deess-hi 9000] [--deess-thr 4] [--deess-pct 75]
仅需 numpy（无 scipy 时用纯 Python biquad 兜底），可直接在板端运行。
"""
import argparse, wave
import numpy as np

def _lfilter(x, b, a):
    try:
        from scipy.signal import lfilter as _lf
        return _lf(b, a, x)
    except Exception:
        b0, b1, b2 = b[0]/a[0], b[1]/a[0], b[2]/a[0]
        a1, a2 = a[1]/a[0], a[2]/a[0]
        y = np.empty_like(x); z1 = z2 = 0.0
        for i in range(x.shape[0]):
            v = x[i]
            yv = b0*v + z1
            z1 = b1*v - a1*yv + z2
            z2 = b2*v - a2*yv
            y[i] = yv
        return y

def _norm(b, a):
    a0 = a[0]
    return [c/a0 for c in b], [c/a0 for c in a]

def lp_coeffs(fs, f0, q=0.707):
    w0 = 2*np.pi*f0/fs; al = np.sin(w0)/(2*q); c = np.cos(w0)
    return _norm([(1-c)/2, 1-c, (1-c)/2], [1+al, -2*c, 1-al])

def hp_coeffs(fs, f0, q=0.707):
    w0 = 2*np.pi*f0/fs; al = np.sin(w0)/(2*q); c = np.cos(w0)
    return _norm([(1+c)/2, -(1+c), (1+c)/2], [1+al, -2*c, 1-al])

def highshelf_coeffs(fs, f0, gain_db, q=0.7):
    A = 10**(gain_db/40); w0 = 2*np.pi*f0/fs; c = np.cos(w0)
    al = np.sin(w0)/(2*q); s = 2*np.sqrt(A)*al
    b = [A*((A+1)+(A-1)*c+s), -2*A*((A-1)+(A+1)*c), A*((A+1)+(A-1)*c-s)]
    a = [(A+1)-(A-1)*c+s, 2*((A-1)-(A+1)*c), (A+1)-(A-1)*c-s]
    return _norm(b, a)

def _smooth_env(x, fs, atk_ms=1.0, rel_ms=60.0):
    a_atk = np.exp(-1.0/(fs*atk_ms/1000.0)); a_rel = np.exp(-1.0/(fs*rel_ms/1000.0))
    out = np.empty_like(x); prev = 0.0
    for i in range(x.shape[0]):
        v = abs(x[i])
        a = a_atk if v > prev else a_rel
        prev = a*prev + (1-a)*v
        out[i] = prev
    return out

def deess(x, fs, lo=4500, hi=9000, max_red_db=5.0, thr_margin=4.0, knee_db=6.0, pct=75.0):
    band = _lfilter(x, *hp_coeffs(fs, lo, 0.707))
    band = _lfilter(band, *lp_coeffs(fs, hi, 0.707))
    env = _smooth_env(band, fs)
    env_db = 20*np.log10(env + 1e-9)
    thr = float(np.percentile(env_db, pct)) + thr_margin
    red = -max_red_db*np.clip((env_db - thr)/knee_db, 0.0, 1.0)
    g = 10**(red/20.0)
    return (x - band) + band*g, red

def _centroid(d, fs):
    D = np.abs(np.fft.rfft(d*np.hanning(len(d)))); f = np.fft.rfftfreq(len(d), 1/fs)
    return float((D*f).sum()/max(D.sum(), 1e-9))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--shelf-db', type=float, default=-2.0)
    ap.add_argument('--shelf-f', type=float, default=3500.0)
    ap.add_argument('--lp', type=float, default=8000.0)
    ap.add_argument('--deess-max', type=float, default=5.0)
    ap.add_argument('--deess-lo', type=float, default=4500.0)
    ap.add_argument('--deess-hi', type=float, default=9000.0)
    ap.add_argument('--deess-thr', type=float, default=4.0)
    ap.add_argument('--deess-pct', type=float, default=75.0)
    ap.add_argument('--no-normalize', action='store_true')
    args = ap.parse_args()

    w = wave.open(args.inp); fs = w.getframerate(); n = w.getnframes(); ch = w.getnchannels()
    x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)/32768.0
    if ch > 1: x = x.reshape(-1, ch).mean(axis=1)

    y, red = deess(x, fs, args.deess_lo, args.deess_hi, args.deess_max, args.deess_thr, 6.0, args.deess_pct)
    y = _lfilter(y, *lp_coeffs(fs, args.lp, 0.707))
    if args.shelf_db:
        y = _lfilter(y, *highshelf_coeffs(fs, args.shelf_f, args.shelf_db, 0.7))
    if not args.no_normalize:
        peak = float(np.abs(y).max())
        if peak > 0.97: y = y*(0.97/peak)
    out = (np.clip(y, -1, 1)*32767).astype(np.int16)
    with wave.open(args.out, 'wb') as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(fs); o.writeframes(out.tobytes())
    frac = float(np.mean(red < -1.0))*100.0
    print('%s -> %s centroid %.0f -> %.0f Hz | deess %.1f%% frames max %.1f dB' % (
        args.inp.split('/')[-1], args.out.split('/')[-1], _centroid(x, fs), _centroid(y, fs), frac, float(red.min())))

if __name__ == '__main__':
    main()
