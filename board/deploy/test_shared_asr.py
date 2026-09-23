# -*- coding: utf-8 -*-
"""回归验证：共用识别入口 + 前置缓冲加大后，#92 能否被正确识别。

三项验证：
  A. 语音日志重构后行为不变 —— transcribe_one 重跑 #90/#91/#92，
     结果应与库中原值一致（这是防止我改坏归档链路的护栏）。
  B. 助手新链路 —— 模拟助手取音窗口（前置缓冲 1200ms）走
     voice_service.transcribe_pcm，应得到完整的「中继台现在风速多少？」。
  C. 对照实验 —— 老的前置缓冲 400ms 在同一段音频上仍会丢字，
     证明修复确实起作用而不是碰巧。
"""
import sqlite3
import sys

import numpy as np

sys.path.insert(0, '/www')
import asr_service
import voice_service as vs

DB = '/www/relay.db'
asr_service.set_language_getter(lambda: 'auto')
asr_service.ENGINE.ensure()

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
orig = {r['id']: (r['asr_text'] or '') for r in
        c.execute('SELECT id,asr_text FROM voice_logs WHERE id IN (90,91,92)')}

print('=== A. 语音日志回归（重构 transcribe_one 后重跑）===')
svc = vs.VoiceService(DB)
for rid in (90, 91, 92):
    try:
        svc.transcribe_one(rid)
    except Exception as e:
        print('  #%d 重跑异常：%s: %s' % (rid, type(e).__name__, e))
        continue
    now = c.execute('SELECT asr_text,category,asr_json FROM voice_logs WHERE id=?', (rid,)).fetchone()
    old = orig.get(rid, '')
    new = now['asr_text'] or ''
    same = (old.strip() == new.strip())
    print('  #%-3d 原=%-22r 新=%-22r %s' % (rid, old, new, '一致 OK' if same else '**变化**'))
    if not same:
        print('       分类=%s  分段=%s' % (now['category'], (now['asr_json'] or '')[:120]))

print()
print('=== B. 助手新链路（前置缓冲 1200ms + 共用识别入口）===')
row = c.execute('SELECT id,path,asr_text FROM voice_logs WHERE id=92').fetchone()
x, sr = vs.read_wav_mono(row['path'])
span = vs.active_span(x, sr)
print('  #92 全 %.2fs，有声段 %.2f~%.2fs' % (len(x) / sr, span[0] / sr, span[1] / sr))

for preroll in (0.40, 1.20):
    a = max(0, span[0] - int(preroll * sr))
    b = min(len(x), span[1] + int(0.45 * sr))
    seg = x[a:b]
    text, ms = vs.transcribe_pcm_text(seg, sr, enhance=True, min_seconds=0.30)
    ok = '中继台' in text
    print('  前置缓冲 %.2fs（段长 %.2fs）-> %r  %s  [%dms]'
          % (preroll, len(seg) / sr, text, 'OK' if ok else '仍丢字', ms))

print()
print('=== C. 与库中原值对照 ===')
print('  语音日志 #92 = %r' % (orig.get(92, '')))

c.close()
