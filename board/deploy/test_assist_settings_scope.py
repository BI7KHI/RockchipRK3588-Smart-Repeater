# -*- coding: utf-8 -*-
"""助手设置快照的作用域自测（纯本地：临时库 + 直接调取值函数）。

为什么单独立这一条：助手后台线程拿设置走的是 `app._assist_settings_direct()`，
它原来只查 `assist_%`。可助手判「是不是在叫我们」要用**本台呼号**，而本台呼号
存在 `vlog_callsign_whitelist`（语音日志那摊）里 —— 键进不来快照，
`auto_told_callsigns()` 就恒为空。后果有两层：
  * 轻的：「被点名」提示位失准（历史 #207 就是这样，模型只能靠抽出的呼号猜）；
  * 重的：2026-09-29 上线的「显式点名」发射前置把真正的点名判成"没点名"，
    板端验收当场抓到 —— 文本 `BI7KHI 帮我看看现在电池电压多少` 得到 gate=noaddr。
所以这条测试钉住「跨域键必须进快照」，并且钉住端到端效果。
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import app            # noqa: E402
import assistant_service as A  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


TMP = Path(tempfile.mkdtemp(prefix='assist_scope_'))
OLD_DB = app.DB_PATH
app.DB_PATH = TMP / 'relay.db'
try:
    app.init_db()
    with app.app.app_context():
        app.set_setting('assist_wake_words', '智能中继,中继台,香香')
        app.set_setting('vlog_callsign_whitelist', 'BI7KHI')
        app.set_setting('assist_auto_mode', 'shadow')

    st = app._assist_settings_direct()
    print('  快照键数：%d' % len(st))
    check('快照里有 assist_* 键', 'assist_wake_words' in st, sorted(st)[:6])
    check('跨域键 vlog_callsign_whitelist 也进来了（这是本台呼号的来源）',
          st.get('vlog_callsign_whitelist') == 'BI7KHI', st.get('vlog_callsign_whitelist'))

    own = A.AssistantService.auto_told_callsigns(None, st)
    check('auto_told_callsigns 能取到本台呼号', own == ['BI7KHI'], own)

    W = A.AssistantService.wake_words(None, st)
    ok, why = A.auto_addressed('BI7KHI 帮我看看现在电池电压多少', W, own)
    check('端到端：带本台呼号的提问算「点名本台」', ok is True, why)
    ok2, why2 = A.auto_addressed(
        'hello hello. This is Bravo Italy number 7 kilo Hotel India', W, own)
    check('端到端：ICAO 拼读也算点名', ok2 is True, why2)

    # 闸门层面：点名齐全时不该再被 noaddr 拦
    allowed, code, _ = A.auto_gate(decision='answer', reason='question', mode='shadow',
                                   addressed=ok)
    check('点名齐全时闸门走到影子锁（而不是 noaddr）', code == 'shadow', code)
finally:
    app.DB_PATH = OLD_DB

print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
for x in FAIL:
    print('  FAIL %s' % x)
sys.exit(1 if FAIL else 0)
