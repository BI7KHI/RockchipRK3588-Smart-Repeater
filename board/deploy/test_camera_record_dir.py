# -*- coding: utf-8 -*-
"""录像/抓拍目录「能不能写」的判定自测（纯本地）。

现场故障：用户把录像目录改成 TF 卡挂载点 `/mnt/tfcard/video_rec/` 后
  * 抓拍 → HTTP 500（未捕获的 PermissionError，写在 app.py 的 snapshot 里）
  * 循环录像 → 日志说「已启动」，实际一个文件都不落（ffmpeg 写不进去）
根因不是"路径填错了"，而是**代码从没检查过目录能不能写**：`mkdir(exist_ok=True)`
对"已存在但不可写"的目录不报错，于是错误被推迟到真正落盘那一刻。

这条测试钉住三层：
  1. `_camera_dir_problem()` 对可写目录返回空串；
  2. 写不进去时返回**人话原因**（不能只是抛异常）；
  3. `_camera_record_dir_problem()` 会附上可直接照抄的修复命令。
权限类错误在 Windows 上没法用 chmod 真实复现，所以用 monkeypatch 造出
PermissionError —— 测的是"错误被翻译成人话"这条逻辑，不是 chmod 语义。
"""
import os
import sys
import tempfile
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


TMP = Path(tempfile.mkdtemp(prefix='cam_dir_'))
print('临时目录：%s' % TMP)

print('\n=== 1. 可写目录：不该报问题 ===')
check('可写目录 → 空串', app._camera_dir_problem(TMP) == '', app._camera_dir_problem(TMP))
sub = TMP / 'a' / 'b' / 'video_rec'
check('不存在的子目录 → 能创建就不算问题', app._camera_dir_problem(sub) == '',
      app._camera_dir_problem(sub))
check('创建后目录真的在', sub.is_dir())
check('探针文件没有留下垃圾',
      not [p.name for p in TMP.rglob('.elf2_write_probe_*')], list(TMP.rglob('*'))[:5])

print('\n=== 2. 写不进去：必须给出人话原因（现场故障的形态）===')
real_write = Path.write_bytes


def boom(self, data):
    raise PermissionError(13, 'Permission denied')


try:
    Path.write_bytes = boom
    reason = app._camera_dir_problem(TMP)
finally:
    Path.write_bytes = real_write
print('  写失败时的原因：%s' % reason)
check('识别为「没有写权限」而不是抛异常', '没有写权限' in reason, reason)
check('原因里带上了路径', str(TMP) in reason, reason)
check('原因里带上了错误类型（便于区分 EACCES/EROFS）',
      'PermissionError' in reason or 'Errno' in reason, reason)

real_mkdir = Path.mkdir


def boom_mkdir(self, *a, **kw):
    raise PermissionError(13, 'Permission denied')


try:
    Path.mkdir = boom_mkdir
    reason2 = app._camera_dir_problem(TMP / 'nope')
finally:
    Path.mkdir = real_mkdir
print('  建不了时的原因：%s' % reason2)
check('识别为「无法创建」', '无法创建' in reason2, reason2)

print('\n=== 3. 给用户的修复命令（能照抄）===')
hint = app._camera_dir_hint('/mnt/tfcard/video_rec')
print('  %s' % hint)
check('包含 mkdir -p 与目标路径', 'mkdir -p /mnt/tfcard/video_rec' in hint, hint)
check('包含 chown', 'chown' in hint, hint)
check('提到 FAT/exFAT 下 chown 无效的例外', 'exFAT' in hint or 'FAT' in hint, hint)
# 组合逻辑要单独测：/mnt/tfcard 只在板子上不可写，本机（Windows）会把它当成
# C:\mnt\tfcard 并成功创建 —— 直接拿板端路径断言会得到"没问题"的假结论。
real_problem = app._camera_dir_problem
try:
    app._camera_dir_problem = lambda d: ('目录存在但没有写权限：%s'
                                         '（PermissionError: [Errno 13] Permission denied）' % d)
    full = app._camera_record_dir_problem('/mnt/tfcard/video_rec')
finally:
    app._camera_dir_problem = real_problem
print('  给页面/接口的完整文案：%s' % full[:160])
check('完整文案 = 原因 + 命令', ('sudo mkdir -p' in full) and ('没有写权限' in full), full[:120])
check('默认录像目录常量存在且是站内路径',
      app.CAMERA_DEFAULT_RECORD_DIR == '/www/camera_recordings',
      app.CAMERA_DEFAULT_RECORD_DIR)

print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
for x in FAIL:
    print('  FAIL %s' % x)
sys.exit(1 if FAIL else 0)
