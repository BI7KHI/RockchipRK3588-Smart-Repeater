# -*- coding: utf-8 -*-
"""摄像头分片「能不能播」的标记（录制中 / 未完成）自测（纯本地）。

为什么要有这一条：面板把**正在写的那一段**也列进列表、还给播放按钮，点它必然拿到
MEDIA_ERR_SRC_NOT_SUPPORTED(4)，因为文件还没写 moov。这个现象看起来像"编码不支持"，
本会话就被它误导过一次（HEVC 明明能播）。服务端现在对每个分片给出 playable /
recording，前端据此禁用按钮并标注；这个测试钉住服务端的判定规则：

  1. 还在长（没有 moov + mtime 刚刚更新）→ playable=False, recording=True
  2. 录制中断留下的半截文件（没有 moov + mtime 很旧）→ playable=False, recording=False
  3. 写完的（有 moov）→ playable=True, recording=False

第 2 条是对照组：如果只按"没有 moov"就判 recording，它会把中断残留也标成"录制中"，
这个测试就会失败。顺带检查 _camera_list_recordings 把标记透传出去。
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import app  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


TMP = Path(tempfile.mkdtemp(prefix='cam_playable_'))
_OLD_REC_DIR = app._camera_record_dir
app._camera_record_dir = lambda: TMP          # 别碰 /www
NOW = time.time()


def make(name, age_s):
    p = TMP / name
    p.write_bytes(b'not a real mp4 - no moov here')   # 造"没有 moov"的文件
    ts = NOW - age_s
    os.utime(str(p), (ts, ts))
    return p


print('目录：%s' % TMP)
fresh = make('loop_20260929_210000.mp4', 2)        # 还在长
stale = make('loop_20260929_210100.mp4', 600)      # 中断残留
done = make('loop_20260929_210200.mp4', 600)       # 写完的（下面把 duration 伪装成 60s）

# 先自检前提：这两个文件确实"读不出 moov"，否则后面测的就不是我们想测的东西
check('前提：新鲜文件读不出时长（没有 moov）',
      app._camera_mp4_duration_ms(fresh) is None)
check('前提：陈旧文件读不出时长（没有 moov）',
      app._camera_mp4_duration_ms(stale) is None)

real_duration = app._camera_mp4_duration_ms
app._camera_mp4_duration_ms = lambda p: (60000 if Path(p).name == done.name
                                         else real_duration(p))
try:
    r_fresh = app._camera_recording_record(fresh, 60)
    r_stale = app._camera_recording_record(stale, 60)
    r_done = app._camera_recording_record(done, 60)

    print('  新鲜 %s' % {k: r_fresh.get(k) for k in ('playable', 'recording', 'duration_ms')})
    print('  陈旧 %s' % {k: r_stale.get(k) for k in ('playable', 'recording', 'duration_ms')})
    print('  写完 %s' % {k: r_done.get(k) for k in ('playable', 'recording', 'duration_ms')})

    check('录制中的分段：playable=False', r_fresh.get('playable') is False, r_fresh)
    check('录制中的分段：recording=True', r_fresh.get('recording') is True, r_fresh)
    check('对照：中断残留的分段 recording=False（不能按"没有 moov"一刀切）',
          r_stale.get('recording') is False, r_stale)
    check('对照：中断残留同样不可播 playable=False', r_stale.get('playable') is False, r_stale)
    check('写完的分段：playable=True', r_done.get('playable') is True, r_done)
    check('写完的分段：recording=False', r_done.get('recording') is False, r_done)
    check('写完的分段时长仍按 moov 走（60s）', r_done.get('duration_ms') == 60000, r_done)
    check('录制中的分段时长是估算值（>0 且 ≤60s）',
          0 < (r_fresh.get('duration_ms') or 0) <= 60000, r_fresh)

    listed = app._camera_list_recordings()
    by = {x['filename']: x for x in listed}
    check('列表接口透传 playable/recording',
          by.get(fresh.name, {}).get('recording') is True
          and by.get(fresh.name, {}).get('playable') is False
          and by.get(done.name, {}).get('playable') is True, sorted(by))
    check('列表仍带 index / is_latest（没被这次改动弄丢）',
          all(('index' in x and 'is_latest' in x) for x in listed), listed)
finally:
    app._camera_mp4_duration_ms = real_duration
    app._camera_record_dir = _OLD_REC_DIR      # 还原，别影响同一进程里的后续套件

print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
for x in FAIL:
    print('  FAIL %s' % x)
sys.exit(1 if FAIL else 0)
