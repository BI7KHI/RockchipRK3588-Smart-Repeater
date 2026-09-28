# -*- coding: utf-8 -*-
"""板端设置快照/还原（含密钥）—— 给验收脚本用，密钥不出板子。

**为什么必须有这个**：验收脚本要临时改设置（比如把外部 API 地址指到黑洞、
把 Key 清掉来验「没配 Key 就回退本地」），改完必须还原。而
`/api/settings` 的 GET **不回传** `*_api_key` 的值（只给 `xxx_api_key_set` 标志），
所以「从接口读出来存一份、验完写回去」这条路会把真 Key 冲掉 —— 实测已经踩过一次
（把用户的 DeepSeek Key 顶成了 sk-verify-dummy，最后只能从 relay.db 的 WAL 残留里捞回来）。

正确做法：快照与还原都在板端直接用 sqlite 做，密钥只在板子的文件系统里流转。

用法（板端）：
  python3 settings_snapshot.py save /tmp/llm_snap.json     # 存
  python3 settings_snapshot.py restore /tmp/llm_snap.json  # 还原（原样写回，含密钥）
  python3 settings_snapshot.py show /tmp/llm_snap.json     # 看（密钥打掩码）
缺省键集合 = LLM 提供方相关的四个；可用 --keys a,b,c 覆盖。
"""
import argparse
import json
import os
import sqlite3
import sys

DB = '/www/relay.db'
DEFAULT_KEYS = ['llm_provider', 'external_base_url', 'external_model',
                'external_api_key', 'local_base_url', 'local_model',
                'local_api_key']


def mask(v):
    v = str(v or '')
    return ('%s…%s（%d 位）' % (v[:6], v[-4:], len(v))) if len(v) > 12 else ('（%d 位）' % len(v) if v else '（空）')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['save', 'restore', 'show'])
    ap.add_argument('path')
    ap.add_argument('--keys', default='')
    args = ap.parse_args()
    keys = [k.strip() for k in args.keys.split(',') if k.strip()] or DEFAULT_KEYS

    c = sqlite3.connect(DB, timeout=15)
    if args.action == 'save':
        snap = {}
        for k in keys:
            row = c.execute('SELECT value FROM settings WHERE key=?', (k,)).fetchone()
            snap[k] = None if row is None else row[0]      # None = 键不存在（还原时删掉）
        with open(args.path, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False)
        os.chmod(args.path, 0o600)
        print('已快照 %d 项 → %s' % (len(snap), args.path))
        for k, v in snap.items():
            print('  %-22s %s' % (k, mask(v) if k.endswith('_api_key') else repr(v)))
        return 0

    if not os.path.exists(args.path):
        print('快照不存在：%s' % args.path)
        return 2
    snap = json.load(open(args.path, encoding='utf-8'))
    if args.action == 'show':
        for k, v in snap.items():
            print('  %-22s %s' % (k, mask(v) if k.endswith('_api_key') else repr(v)))
        return 0

    done = []
    for k, v in snap.items():
        if v is None:
            c.execute('DELETE FROM settings WHERE key=?', (k,))
        else:
            c.execute('INSERT INTO settings(key, value) VALUES(?, ?) '
                      'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k, v))
        done.append(k)
    c.commit()
    bad = []
    for k in done:
        row = c.execute('SELECT value FROM settings WHERE key=?', (k,)).fetchone()
        want = snap[k]
        got = None if row is None else row[0]
        if got != want:
            bad.append(k)
    print('还原 %d 项：%s' % (len(done), '全部一致' if not bad else '不一致 %s' % bad))
    for k in done:
        r = c.execute('SELECT value FROM settings WHERE key=?', (k,)).fetchone()
        v = None if r is None else r[0]
        print('  %-22s %s' % (k, mask(v) if k.endswith('_api_key') else repr(v)))
    return 0 if not bad else 3


if __name__ == '__main__':
    sys.exit(main())
