#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-test: build a known AX.25 APRS packet, Bell202 modulate at any sr, decode back."""
import numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aprs_probe import decode_stream, ax25_parse, crc16_x25, fmt_call

def ax25_addr(call, ssid=0, last=False):
    c = (call + ' ' * 6)[:6]
    b = bytearray(ch << 1 for ch in c.encode('ascii'))
    v = 0x60 | ((ssid & 0x0F) << 1) | (1 if last else 0)
    b.append(v)
    return bytes(b)

def build_packet(src, dst, path, info, src_ssid=0, dst_ssid=0, pid=0xF0):
    pkt = ax25_addr(dst, dst_ssid, last=False)
    pkt += ax25_addr(src, src_ssid, last=(len(path) == 0))
    for i, (p, s) in enumerate(path):
        pkt += ax25_addr(p, s, last=(i == len(path) - 1))
    pkt += bytes([0x03, pid]) + info
    fcs = crc16_x25(pkt)
    return pkt + bytes([fcs & 0xFF, (fcs >> 8) & 0xFF])

def hdlc_bits(data):
    bits = []
    for b in data:
        for i in range(8):
            bits.append((b >> i) & 1)
    out = []
    ones = 0
    for b in bits:
        out.append(b)
        if b == 1:
            ones += 1
            if ones == 5:
                out.append(0)
                ones = 0
        else:
            ones = 0
    flag = [0, 1, 1, 1, 1, 1, 1, 0]
    return flag * 30 + out + flag * 4

def nrzi_encode(bits):
    out = []
    cur = 1
    for b in bits:
        if b == 0:
            cur ^= 1
        out.append(cur)
    return out

def modulate(bits, sr=16000, baud=1200.0, f0=1200.0, f1=2200.0, amp=0.5):
    spb = sr / baud
    n = int(round(len(bits) * spb))
    phase = np.zeros(n)
    # build instantaneous freq per sample
    ft = np.zeros(n)
    for i in range(n):
        k = int(i / spb)
        if k >= len(bits):
            k = len(bits) - 1
        ft[i] = f0 if bits[k] else f1   # Bell202: mark/level-1 = 1200Hz
    ph = 2 * np.pi * np.cumsum(ft) / sr
    return amp * np.sin(ph)

def test(sr, baud=1200.0, snr=None, amp=0.5, extra_silence=0.0):
    info = b'!2232.00N/11404.00E>VR-N76 relay test'
    pkt = build_packet('BI7KHI', 'APN100', [('WIDE1-1', 0)], info, dst_ssid=0)
    bits = hdlc_bits(pkt)
    levels = nrzi_encode(bits)          # NRZI BEFORE modulation (Bell202)
    wave = modulate(levels, sr=sr, baud=baud, amp=amp)
    if extra_silence:
        pad = np.zeros(int(extra_silence * sr))
        wave = np.concatenate([pad, wave, pad])
    if snr is not None:
        sig_p = np.mean(wave ** 2)
        noise = np.random.randn(len(wave))
        noise *= np.sqrt(sig_p / (10 ** (snr / 10.0)))
        wave = wave + noise
    pkts, d, W = decode_stream(wave, sr, baud=baud)
    uniq = []
    seen = set()
    for p in pkts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    ok = any(p == pkt for p in uniq)
    print('sr=%-6d snr=%-6s amp=%.2f  frames=%d uniq=%d  EXACT_MATCH=%s' % (
        sr, str(snr), amp, len(pkts), len(uniq), ok))
    for p in uniq[:2]:
        a = ax25_parse(p)
        if a:
            print('    %s > %s   %s' % (fmt_call(a['addrs'][1]), ','.join(fmt_call(z) for z in a['addrs']),
                                        a['info'].decode('utf-8', 'replace')))
    return ok

if __name__ == '__main__':
    print('--- CRC sanity: crc over packet+fcs should be 0xF0B8 ---')
    p = build_packet('BI7KHI', 'APN100', [], b'x')
    print('   residue = 0x%04X' % crc16_x25(p))
    print('--- CRC-16/X-25 test vector: "123456789" must be 0x906E ---')
    print('   got = 0x%04X' % crc16_x25(b'123456789'))
    print('--- clean synthetic at various sample rates ---')
    for sr in (16000, 48000, 8000, 44100):
        test(sr)
    print('--- noise sweep @16000 ---')
    for snr in (30, 20, 15, 10, 6, 3, 0):
        test(16000, snr=snr)
    print('--- low amplitude (weak signal) @16000 ---')
    for a in (0.5, 0.2, 0.05, 0.02, 0.005):
        test(16000, amp=a)
    print('--- with leading/trailing silence @16000 ---')
    test(16000, extra_silence=3.0)
