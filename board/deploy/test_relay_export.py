# -*- coding: utf-8 -*-
"""运行数据导出器自测（纯本地：造一个假的 relay.db 就能跑）。

覆盖：增量语义（只导上次之后的新行）、状态推进、gzip 包结构与 sha256、
outbox 体量上限、上传失败时**不推进状态**（这条最关键——推进了就等于丢数据）。
"""
import gzip
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


TMP = Path(tempfile.mkdtemp())
DB = TMP / 'relay.db'
STATE = TMP / 'state.json'
OUTBOX = TMP / 'outbox'
CONF = TMP / 'upload.conf'
OUTBOX.mkdir(parents=True, exist_ok=True)
CONF.write_text('UPLOAD_URL=https://example.invalid/ingest\nUPLOAD_TOKEN=t0ken\n',
                encoding='utf-8')

# 造一个只有 4 张目标表的最小库
c = sqlite3.connect(str(DB))
c.executescript('''
CREATE TABLE assist_turns(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, action TEXT,
                          decision TEXT, reason TEXT, think TEXT, heard TEXT);
CREATE TABLE voice_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT,
                        asr_text TEXT);
CREATE TABLE voltage_readings(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
                              battery REAL, n_reads INTEGER, load INTEGER);
CREATE TABLE aprs_packets(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, src TEXT);
CREATE TABLE something_else(id INTEGER PRIMARY KEY AUTOINCREMENT, x TEXT);
''')
c.execute("INSERT INTO assist_turns(ts,action,decision,reason,think) "
          "VALUES('2026-09-29T10:00:00','shadow','answer','shadow','对方在问电压')")
c.execute("INSERT INTO voice_logs(ts,kind,asr_text) VALUES('2026-09-29T10:00:01','rx','中继台')")
c.execute("INSERT INTO voltage_readings(ts,battery,n_reads,load) VALUES('2026-09-29T10:00:00',12.5,3,0)")
c.execute("INSERT INTO aprs_packets(ts,src) VALUES('2026-09-29T10:00:02','BI7KHI')")
c.execute("INSERT INTO something_else(x) VALUES('不该被导出')")
c.commit()
c.close()

os.environ.update({'ELF2_DB': str(DB), 'ELF2_UPLOAD_STATE': str(STATE),
                   'ELF2_UPLOAD_OUTBOX': str(OUTBOX), 'ELF2_UPLOAD_CONF': str(CONF)})
spec = importlib.util.spec_from_file_location('relay_export', HERE / 'relay_export.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

print('\n=== 1. 增量收集 ===')
bundle, before = E.collect()
check('四张目标表都有数据', set(bundle) == {'assist_turns', 'voice_logs',
                                          'voltage_readings', 'aprs_packets'},
      sorted(bundle))
check('第一次上传时 from 是空的', before == {}, before)
check('无关表不导出', 'something_else' not in bundle)
check('max_id 记对了', bundle['assist_turns'][1] == 1 and bundle['aprs_packets'][1] == 1)

print('\n=== 2. 打包 ===')
path, name, counts, extra = E.build(bundle)
check('包名带主机名与时间戳', name.startswith('elf2_') and name.endswith('.jsonl.gz'), name)
check('包存在且是 gzip', os.path.exists(path) and gzip.open(path, 'rt', encoding='utf-8').read(1) is not None)
with gzip.open(path, 'rt', encoding='utf-8') as f:
    lines = [json.loads(x) for x in f if x.strip()]
check('每行都带 _table 标记', all('_table' in x for x in lines), lines[:1])
check('行数 = 各表之和', len(lines) == sum(counts.values()), (len(lines), counts))
check('中文与文本原样保留（ensure_ascii=False）',
      any('对方在问电压' == x.get('think') for x in lines))
sha = E.sha256_of(path)
check('sha256 是 64 位十六进制', len(sha) == 64, sha)

print('\n=== 3. 上传失败时绝不推进状态（否则等于丢数据） ===')
orig = E.upload
E.upload = lambda *a, **k: (False, '模拟断网')
try:
    rc = E.main.__wrapped__ if hasattr(E.main, '__wrapped__') else None
except Exception:
    rc = None
sys.argv = ['relay_export.py']
try:
    E.main()
except SystemExit:
    pass
check('失败后状态文件没有生成/没被推进',
      (not STATE.exists()) or json.loads(STATE.read_text(encoding='utf-8')) == {},
      STATE.read_text(encoding='utf-8') if STATE.exists() else '(无)')
check('失败后包留在 outbox 等重试', len(list(OUTBOX.glob('*.gz'))) >= 1,
      [p.name for p in OUTBOX.glob('*.gz')])

print('\n=== 4. 上传成功才推进状态 ===')
E.upload = lambda *a, **k: (True, '{"ok":true}')
try:
    E.main()
except SystemExit:
    pass
st = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
check('状态推进到各表 max_id',
      st.get('assist_turns') == 1 and st.get('aprs_packets') == 1, st)
check('成功的包被移到 sent/', len(list((OUTBOX / 'sent').glob('*.gz'))) >= 1,
      [p.name for p in (OUTBOX / 'sent').glob('*.gz')])

print('\n=== 5. 没有新数据时不动 ===')
E.upload = orig
bundle2, before2 = E.collect()
check('再收集是空的（增量语义）', bundle2 == {}, sorted(bundle2))
check('状态里记着上次位置', before2.get('assist_turns') == 1, before2)

print('\n=== 5b. 补传积压：先发旧包，绝不重复导出 ===')
# 造一个「上次失败留下的包」，状态停在 0（=没推进）
old = OUTBOX / 'elf2_host_20260101_000000.jsonl.gz'
old.write_bytes(gzip.compress(b'{"_table":"assist_turns","id":1}\n'))
E.write_meta(str(old), {'assist_turns': 1}, {'assist_turns': 1})
check('旧包带 sidecar（sha256 + 覆盖到哪）',
      E.read_meta(str(old)).get('sha256') and
      E.read_meta(str(old)).get('to') == {'assist_turns': 1}, E.read_meta(str(old)))
sent_calls = []
E.upload = lambda path, name, conf, sha, meta: (sent_calls.append((name, meta)),
                                               (True, '{"ok":true}'))[1]
ok_n, fail_n = E.pending({'UPLOAD_URL': 'https://x/ingest', 'UPLOAD_TOKEN': 't'})
check('积压被补传出去', ok_n >= 1 and fail_n == 0, (ok_n, fail_n))
st2 = json.loads(STATE.read_text(encoding='utf-8'))
check('补传成功后状态按包内记录推进（不是重新导出得来的）',
      st2.get('assist_turns') == 1, st2)
check('补传的包带 resend 标记', any(m.get('resend') for _n, m in sent_calls),
      sent_calls[:2])
check('补传后 outbox 不再留着它',
      not os.path.exists(str(old)), [p.name for p in OUTBOX.glob('*.gz')])

print('\n=== 5c. 没有水位信息的旧包：删掉而不是硬发（否则服务器上会重复） ===')
orphan = OUTBOX / 'elf2_host_20260101_010000.jsonl.gz'
orphan.write_bytes(gzip.compress(b'{"_table":"assist_turns","id":2}\n'))
n_before = len(sent_calls)
ok_n2, fail_n2 = E.pending({'UPLOAD_URL': 'https://x/ingest', 'UPLOAD_TOKEN': 't'})
check('没有 sidecar 的包没有被上传', len(sent_calls) == n_before, sent_calls[n_before:])
check('并且被删掉（避免重复数据）', not os.path.exists(str(orphan)))
check('这种包不计成功也不计失败', ok_n2 == 0 and fail_n2 == 0, (ok_n2, fail_n2))

print('\n=== 6. outbox 体量上限 ===')
E.MAX_OUTBOX_MB = 0.0001          # 约 100 字节，逼它清理
for i in range(3):
    (OUTBOX / ('filler%d.gz' % i)).write_bytes(b'x' * 4096)
E.prune()
check('超限时删掉最旧的，不撑爆磁盘',
      sum(os.path.getsize(p) for p in OUTBOX.glob('*.gz')) <= 4096 * 2,
      [p.name for p in OUTBOX.glob('*.gz')])

print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
if FAIL:
    print('失败用例：')
    for f in FAIL:
        print('  - %s' % f)
    sys.exit(1)
