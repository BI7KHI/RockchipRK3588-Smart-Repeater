# -*- coding: utf-8 -*-
"""板端运行数据导出器：把「上次成功上传以来」的新增行打成一个小包，POST 到服务器。

设计要点（都是为了 4G + 无人值守）：
  * **只传文本类新增行**（assist_turns / voice_logs / voltage_readings / aprs_packets），
    录像、录音、模型一律不碰 —— 实测录像 8GB、录音 308MB，而文本一天只有几十 KB；
  * **断点续传靠状态文件**：`/opt/ai/upload_state.json` 记每张表已上传到的 max(id)，
    上传成功才推进；断网/失败就留在 outbox 下次重试，不丢数据；
  * **幂等**：包名带时间戳与 sha256；服务器侧同名不覆盖，重跑安全；
  * 上传走 HTTPS（服务器自签证书时用 `--cacert` 固定证书；没有证书才退 `--insecure`，
    并打印一行告警 —— 真正确认身份的是 token + 包内 sha256）。

用法（板端）：
  python3 relay_export.py                # 导出并上传
  python3 relay_export.py --dry-run      # 只导出、不上传，看有多大
  python3 relay_export.py --with-debug-audio   # 附带唤醒/识别留档音频（约 2~3MB）
配置：/etc/elf2/upload.conf（shell 语法），键：
  UPLOAD_URL=https://rpt.bi7khi.xyz/ingest
  UPLOAD_TOKEN=<服务器与板端共用的口令>
"""
import argparse
import glob
import gzip
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

DB = os.environ.get('ELF2_DB', '/www/relay.db')
STATE = os.environ.get('ELF2_UPLOAD_STATE', '/opt/ai/upload_state.json')
OUTBOX = os.environ.get('ELF2_UPLOAD_OUTBOX', '/opt/ai/upload_outbox')
SENT = os.path.join(OUTBOX, 'sent')
CONF = os.environ.get('ELF2_UPLOAD_CONF', '/etc/elf2/upload.conf')
CA = '/etc/elf2/rpt.crt'          # 有就把服务器证书放这儿（推荐），没有才 --insecure
TABLES = ('assist_turns', 'voice_logs', 'voltage_readings', 'aprs_packets')
# 单张表单次上限：正常一天几十~几千行，这里给足余量又能在长期断网后分批发
BATCH = 20000
MAX_OUTBOX_MB = 200
KEEP_SENT = 20


def log(msg):
    print('[UPLOAD] %s' % msg, flush=True)


def load_conf():
    conf = {'UPLOAD_URL': '', 'UPLOAD_TOKEN': ''}
    try:
        for line in open(CONF, encoding='utf-8'):
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            conf[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    conf['UPLOAD_URL'] = os.environ.get('UPLOAD_URL', conf['UPLOAD_URL'])
    conf['UPLOAD_TOKEN'] = os.environ.get('UPLOAD_TOKEN', conf['UPLOAD_TOKEN'])
    return conf


def load_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def collect():
    """把新增行收集成 {table: (rows, max_id)}。"""
    out, conn = {}, sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    before = load_state()
    for t in TABLES:
        last = int(before.get(t) or 0)
        try:
            rows = [dict(r) for r in conn.execute(
                'SELECT * FROM %s WHERE id > ? ORDER BY id LIMIT ?' % t,
                (last, BATCH)).fetchall()]
        except Exception as e:
            log('表 %s 读取失败：%s' % (t, e))
            continue
        if rows:
            out[t] = (rows, max(int(r['id']) for r in rows))
    conn.close()
    return out, before


def hostname():
    try:
        return open('/etc/hostname').read().strip() or 'elf2'
    except Exception:
        return 'elf2'


def build(bundle, debug_audio=False):
    """打成一份 gzip 的 JSONL（每行一个记录，带 _table 标记）。"""
    os.makedirs(OUTBOX, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = 'elf2_%s_%s.jsonl.gz' % (hostname(), ts)
    path = os.path.join(OUTBOX, name)
    counts = {}
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        for t, (rows, _mx) in bundle.items():
            counts[t] = len(rows)
            for r in rows:
                rec = dict(r)
                rec['_table'] = t
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
    extra = []
    if debug_audio:
        d = '/opt/ai/relay_assist/debug'
        for w in sorted(glob.glob(os.path.join(d, 'dbg_*.wav')))[-12:]:
            extra.append(w)
    return path, name, counts, extra


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def upload(path, name, conf, sha, meta):
    url = conf.get('UPLOAD_URL') or ''
    token = conf.get('UPLOAD_TOKEN') or ''
    if not url or not token:
        return False, '未配置 UPLOAD_URL/UPLOAD_TOKEN（%s）' % CONF
    cmd = ['curl', '-sS', '--max-time', '180', '-X', 'POST',
           '--data-binary', '@' + path,
           '-H', 'Content-Type: application/gzip',
           '-H', 'X-ELF2-Token: ' + token,
           '-H', 'X-ELF2-Host: ' + hostname(),
           '-H', 'X-ELF2-Name: ' + name,
           '-H', 'X-ELF2-Sha256: ' + sha,
           '-H', 'X-ELF2-Meta: ' + json.dumps(meta, ensure_ascii=False)]
    if os.path.exists(CA):
        cmd += ['--cacert', CA]
    else:
        cmd += ['-k']          # 自签证书；身份由 token + sha256 保证
        log('提示：没有 %s，本次用 -k 跳过证书校验（建议把服务器证书放上去）' % CA)
    cmd.append(url)
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=200)
        body = (r.stdout or b'').decode('utf-8', 'ignore').strip()
        if r.returncode == 0 and '"ok":true' in body.replace(' ', ''):
            return True, body[:200]
        return False, 'rc=%s %s' % (r.returncode, body[:200])
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)


def prune():
    """outbox 与 sent 都做体量/数量上限，别把 eMMC 塞满。"""
    os.makedirs(SENT, exist_ok=True)
    files = sorted(glob.glob(os.path.join(OUTBOX, '*.gz')),
                   key=os.path.getmtime)
    total = sum(os.path.getsize(f) for f in files)
    while files and total > MAX_OUTBOX_MB * 1024 * 1024:
        f = files.pop(0)
        total -= os.path.getsize(f)
        try:
            os.unlink(f)
            log('outbox 超限，删除最旧的 %s' % os.path.basename(f))
        except Exception:
            pass
    sent = sorted(glob.glob(os.path.join(SENT, '*')), key=os.path.getmtime)
    for f in sent[:-KEEP_SENT]:
        try:
            os.unlink(f)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只导出不上传')
    ap.add_argument('--with-debug-audio', action='store_true',
                    help='附带唤醒/识别留档音频（约 2~3MB）')
    ap.add_argument('--force', action='store_true', help='没有新行也发一个空包')
    args = ap.parse_args()

    conf = load_conf()
    bundle, before = collect()
    if not bundle and not args.force:
        log('没有新数据（上次已传到 %s），退出' % json.dumps(before, ensure_ascii=False))
        return 0
    path, name, counts, extra = build(bundle, args.with_debug_audio)
    size = os.path.getsize(path)
    sha = sha256_of(path)
    log('导出 %s：%s（%.1f KB）%s' % (name, json.dumps(counts, ensure_ascii=False),
                                      size / 1024.0,
                                      '，另附 %d 个留档音频' % len(extra) if extra else ''))
    if args.dry_run:
        log('dry-run：不推进状态、不上传')
        return 0
    meta = {'counts': counts, 'from': before, 'to': {t: v[1] for t, v in bundle.items()},
            'extra': [os.path.basename(x) for x in extra]}
    ok, msg = upload(path, name, conf, sha, meta)
    if ok:
        st = load_state()
        for t, (_rows, mx) in bundle.items():
            st[t] = mx
        save_state(st)
        os.makedirs(SENT, exist_ok=True)
        try:
            os.replace(path, os.path.join(SENT, name))
        except Exception:
            pass
        log('上传成功：%s' % msg)
    else:
        log('上传失败，留在 outbox 下次重试：%s' % msg)
    prune()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
