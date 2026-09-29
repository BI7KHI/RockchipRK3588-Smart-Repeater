# -*- coding: utf-8 -*-
"""录像 / 推流码率分离自测（纯本地：把 ffmpeg -encoders 的输出换成假的）。

背景：录像切 H.265 之后要降到 1000k 省三分之一存储（实测同源：HEVC@1000k 体积是
H.264@1500k 的 66.7%，PSNR 还高 1.09dB）；但推流是给人实时看的 H.264，不该被
"录像省空间"顺手降质。所以码率分两个覆盖变量。这个测试钉住四条：

  1. 录像候选（allow_hevc=True）认 RELAY_CAM_RECORD_BITRATE
  2. 推流候选（allow_hevc=False）认 RELAY_CAM_STREAM_BITRATE
  3. 都不设时回落到 RELAY_CAM_BITRATE —— 对照组：证明覆盖变量确实起了作用，
     而不是"怎么设都同一个值"
  4. 推流候选里永远不出现 H.265（远端 RTMP 播放端不一定解得了）
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import camera_service  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


class FakeProc:
    def __init__(self, out):
        self.stdout = out.encode()
        self.returncode = 0


LISTING = (' V..... hevc_rkmpp  Rockchip MPP HEVC encoder\n'
           ' V..... hevc_v4l2m2m  V4L2 mem2mem HEVC decoder wrapper\n'
           ' V..... h264_rkmpp  Rockchip MPP H.264 encoder\n')

camera_service.subprocess.run = lambda *a, **kw: FakeProc(LISTING)

SAVED = {k: os.environ.get(k) for k in
         ('RELAY_CAM_BITRATE', 'RELAY_CAM_RECORD_BITRATE', 'RELAY_CAM_STREAM_BITRATE')}
# 保存/还原码率回调：本套件会把它改成假的再清掉，而 app 导入时注册的那个回调
# 是**进程级**的 —— 直接置 None 会把后面所有套件（如 test_camera_settings）看到的
# 回调一起清掉。同一进程跑全套件时踩过：那套件因此报"来源不是 setting"。
_SAVED_PROVIDER = camera_service._BITRATE_PROVIDER


def setenv(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def bitrate_of(cands, name):
    for n, args in cands:
        if n == name:
            return args[args.index('-b:v') + 1]
    return None


try:
    print('=== 1. 只给公共 RELAY_CAM_BITRATE，两边都跟随 ===')
    setenv(RELAY_CAM_BITRATE='1500k', RELAY_CAM_RECORD_BITRATE=None,
           RELAY_CAM_STREAM_BITRATE=None)
    rec = camera_service._encoder_candidates(True)
    st = camera_service._encoder_candidates(False)
    check('录像首选 hevc_rkmpp', rec[0][0] == 'hevc_rkmpp', rec[0])
    check('录像码率跟随公共值 1500k', bitrate_of(rec, 'hevc_rkmpp') == '1500k', rec)
    check('推流首选 h264_rkmpp', st[0][0] == 'h264_rkmpp', st[0])
    check('推流码率跟随公共值 1500k', bitrate_of(st, 'h264_rkmpp') == '1500k', st)

    print('\n=== 2. 录像单独降到 1000k，推流不受牵连 ===')
    setenv(RELAY_CAM_RECORD_BITRATE='1000k')
    rec = camera_service._encoder_candidates(True)
    st = camera_service._encoder_candidates(False)
    check('录像降到 1000k', bitrate_of(rec, 'hevc_rkmpp') == '1000k', rec)
    check('对照组：推流仍是 1500k（没有被录像带着降）',
          bitrate_of(st, 'h264_rkmpp') == '1500k', st)
    check('录像的 H.264 兜底候选也用 1000k（编码器回退不改码率语义）',
          bitrate_of(rec, 'h264_rkmpp') == '1000k', rec)

    print('\n=== 3. 推流单独抬高，录像不受牵连 ===')
    setenv(RELAY_CAM_STREAM_BITRATE='2500k')
    rec = camera_service._encoder_candidates(True)
    st = camera_service._encoder_candidates(False)
    check('推流按覆盖值 2500k', bitrate_of(st, 'h264_rkmpp') == '2500k', st)
    check('对照组：录像仍是 1000k', bitrate_of(rec, 'hevc_rkmpp') == '1000k', rec)

    print('\n=== 4. 撤掉录像覆盖，回落公共值 ===')
    setenv(RELAY_CAM_RECORD_BITRATE=None)
    rec = camera_service._encoder_candidates(True)
    check('录像回落到公共值 1500k', bitrate_of(rec, 'hevc_rkmpp') == '1500k', rec)
    check('对照组：推流覆盖值 2500k 仍在', 
          bitrate_of(camera_service._encoder_candidates(False), 'h264_rkmpp') == '2500k')

    print('\n=== 5. 推流绝不出现 H.265 ===')
    setenv(RELAY_CAM_BITRATE='1000k')
    st = camera_service._encoder_candidates(False)
    check('推流候选里没有 hevc_*', not any('hevc' in n for n, _ in st), st)
    check('推流兜底是软件 H.264', st[-1][0] == 'libx264', st)
    check('录像候选里 H.265 排在 H.264 前面',
          [n for n, _ in rec][:2] == ['hevc_rkmpp', 'h264_v4l2m2m'] or
          rec[0][0].startswith('hevc'), [n for n, _ in rec])

    print('\n=== 6. 页面设置优先于环境变量（回调注册） ===')
    camera_service._ENCODER_CACHE.clear()
    page = {'record': '800k', 'stream': '2500k'}
    camera_service.set_bitrate_provider(lambda kind: page.get(kind, ''))
    setenv(RELAY_CAM_BITRATE='1500k', RELAY_CAM_RECORD_BITRATE='1000k',
           RELAY_CAM_STREAM_BITRATE=None)
    rec = camera_service._encoder_candidates(True)
    st = camera_service._encoder_candidates(False)
    check('页面设了录像码率 → 覆盖环境变量（800k）',
          bitrate_of(rec, 'hevc_rkmpp') == '800k', rec)
    check('对照组：推流按页面设置 2500k（不是环境变量的 1500k）',
          bitrate_of(st, 'h264_rkmpp') == '2500k', st)

    print('\n=== 7. 页面留空 → 回落到环境变量 ===')
    page['record'] = ''
    page['stream'] = ''
    rec = camera_service._encoder_candidates(True)
    st = camera_service._encoder_candidates(False)
    check('录像回落 RELAY_CAM_RECORD_BITRATE=1000k',
          bitrate_of(rec, 'hevc_rkmpp') == '1000k', rec)
    check('推流回落公共 RELAY_CAM_BITRATE=1500k',
          bitrate_of(st, 'h264_rkmpp') == '1500k', st)

    print('\n=== 8. 编码器缓存里冻的是"选哪个"，码率必须每次刷新 ===')
    # 这是本特性的关键坑：pick_encoder 每种用途只探测一次并缓存参数，
    # 若把 -b:v 一起冻住，用户改了码率、录像也重启了，跑的还是旧码率。
    camera_service._ENCODER_CACHE.clear()
    page['record'] = '1000k'
    name1, args1 = camera_service.pick_encoder('record')
    page['record'] = '600k'
    name2, args2 = camera_service.pick_encoder('record')
    check('两次拿到同一个编码器（缓存确实命中）', name1 == name2, (name1, name2))
    check('第一次用 1000k', args1[args1.index('-b:v') + 1] == '1000k', args1)
    check('缓存命中时也换成新的 600k',
          args2[args2.index('-b:v') + 1] == '600k', args2)
    check('码率信息接口报的是页面设置', 
          camera_service.bitrate_info()['record']['source'] == 'setting',
          camera_service.bitrate_info())

    print('\n=== 9. 回调抛异常也不能把录像带崩（退回环境变量） ===')
    def _boom(kind):
        raise RuntimeError('模拟设置读取出错')
    camera_service.set_bitrate_provider(_boom)
    name3, args3 = camera_service.pick_encoder('record')
    check('回调异常时仍能拿到编码器', bool(name3), name3)
    check('回调异常时退回环境变量 1000k',
          args3[args3.index('-b:v') + 1] == '1000k', args3)
finally:
    camera_service.set_bitrate_provider(_SAVED_PROVIDER)
    setenv(**SAVED)

print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
for x in FAIL:
    print('  FAIL %s' % x)
sys.exit(1 if FAIL else 0)
