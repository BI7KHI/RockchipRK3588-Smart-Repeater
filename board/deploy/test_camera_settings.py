# -*- coding: utf-8 -*-
"""摄像头码率设置的离线自测：写法校验、重启策略、与 camera_service 的接线。

三块要钉住的东西：
  1. `_norm_camera_bitrate`：'' 与 500k / 1.5M 这类写法接受并归一化成 `NNNNk`，
     乱七八糟的输入必须报错（页面上打错了要当场告诉用户，而不是悄悄写进库）；
  2. `_camera_restart_plan`：改码率只该重启录像/推流（保住采集与实时预览，
     并让正在写的那段正常收尾），改采集层参数才整条重开，什么都没变就别动；
  3. 接线：设置里的值要能真的走到 camera_service（回调注册 + 优先级），
     留空时必须回落到环境变量 —— 否则板端 unit 里设的码率会被空设置顶掉。

用临时库跑（把 app.DB_PATH 指到 temp 目录），不碰工作区里的 relay.db。
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import app            # noqa: E402
import camera_service  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


TMP = Path(tempfile.mkdtemp(prefix='cam_settings_'))
OLD_DB = app.DB_PATH
app.DB_PATH = TMP / 'relay.db'
app.init_db()


def getk(key, default=''):
    """读设置：set_setting/get_setting 走 Flask 的 g，必须自己在应用上下文里跑。"""
    with app.app.app_context():
        return app.get_setting(key, default)


def setk(key, value):
    with app.app.app_context():
        app.set_setting(key, value)

print('\n=== 1. 码率写法（归一化 + 拒绝垃圾输入）===')
ok_cases = [('', ''), ('1000k', '1000k'), (' 800K ', '800k'), ('1.5M', '1500k'),
            ('1.5m', '1500k'), ('2M', '2000k'), ('0.5M', '500k'), ('100k', '100k'),
            ('20000k', '20000k'), ('1500k', '1500k')]
for raw, want in ok_cases:
    try:
        got = app._norm_camera_bitrate(raw)
        check('接受 %r → %r' % (raw, want), got == want, got)
    except Exception as e:
        check('接受 %r → %r' % (raw, want), False, '%s: %s' % (type(e).__name__, e))
bad_cases = ['abc', '1000', 'k', '1G', '0k', '30M', '-500k', '1.2.3M', '100000k']
for raw in bad_cases:
    try:
        got = app._norm_camera_bitrate(raw)
        check('拒绝 %r' % raw, False, '竟然接受了，返回 %r' % got)
    except ValueError:
        check('拒绝 %r' % raw, True)
    except Exception as e:
        check('拒绝 %r（要 ValueError）' % raw, False, type(e).__name__)

print('\n=== 2. 重启策略（_camera_restart_plan）===')
plan_cases = [
    (set(), 'none', '什么都没变 → 不动（白重启会截断正在录的那段）'),
    ({'bitrate'}, 'recorder', '只改录像码率 → 只重启录像/推流'),
    ({'stream_bitrate'}, 'recorder', '只改推流码率 → 只重启录像/推流'),
    ({'bitrate', 'stream_bitrate'}, 'recorder', '两路码率都改 → 只重启录像/推流'),
    ({'loop_seconds'}, 'recorder', '改分段时长 → 只重启录像'),
    ({'loop_autostart'}, 'recorder', '改自动录像开关 → 只重启录像'),
    ({'fps'}, 'full', '改帧率 → 整条重开'),
    ({'resolution'}, 'full', '改分辨率 → 整条重开'),
    ({'device'}, 'full', '改设备 → 整条重开'),
    ({'osd'}, 'full', '改 OSD → 整条重开（滤镜烘在采集里）'),
    ({'bitrate', 'fps'}, 'full', '码率+帧率一起改 → 以采集层为准，整条重开'),
]
for changed, want, why in plan_cases:
    got = app._camera_restart_plan(changed)
    check('%s（%s）' % (want, why), got == want, got)

print('\n=== 3. 默认值：两路码率默认留空（= 跟随环境变量）===')
check('camera_bitrate 默认是空串', getk('camera_bitrate', None) == '',
      repr(getk('camera_bitrate', None)))
check('camera_stream_bitrate 默认是空串',
      getk('camera_stream_bitrate', None) == '',
      repr(getk('camera_stream_bitrate', None)))

print('\n=== 4. 接线：设置 → camera_service（含优先级与回落）===')
os.environ['RELAY_CAM_BITRATE'] = '1500k'
os.environ['RELAY_CAM_RECORD_BITRATE'] = '1000k'
setk('camera_bitrate', '800k')
setk('camera_stream_bitrate', '')
info = camera_service.bitrate_info()
print('  bitrate_info = %s' % info)
check('录像：页面设置 800k 生效且来源标为 setting',
      info['record']['value'] == '800k' and info['record']['source'] == 'setting', info)
check('推流：留空 → 回落环境变量 RELAY_CAM_BITRATE=1500k',
      info['stream']['value'] == '1500k' and info['stream']['source'] == 'env', info)
check('推流来源写明是哪个环境变量',
      info['stream']['env_key'] == 'RELAY_CAM_BITRATE', info)
check('_camera_cfg() 把两路码率带给前端',
      app._camera_cfg().get('bitrate') == '800k'
      and app._camera_cfg().get('stream_bitrate') == '', app._camera_cfg())

setk('camera_bitrate', '')
os.environ.pop('RELAY_CAM_RECORD_BITRATE', None)
info = camera_service.bitrate_info()
check('清空页面设置 + 去掉专用环境变量 → 录像也用公共值 1500k',
      info['record']['value'] == '1500k' and info['record']['source'] == 'env', info)

os.environ.pop('RELAY_CAM_BITRATE', None)
info = camera_service.bitrate_info()
check('连公共环境变量都没有 → 记作内置默认',
      info['record']['source'] == 'default' and info['record']['value'] == '1000k', info)

app.DB_PATH = OLD_DB
print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
for x in FAIL:
    print('  FAIL %s' % x)
sys.exit(1 if FAIL else 0)
