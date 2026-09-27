# -*- coding: utf-8 -*-
"""本机发射（tx）段文字来源的自测：登记、时间窗匹配、策略判定。

背景：本机发射的声音是我们自己合成的，文本在合成前就有。让 ASR 回头识别自己的
回录音频既费资源又必然出错（实测「12.8 伏特」→「1156伏特」）。这份自测盯的就是
「什么时候用原文、什么时候才允许送 ASR」这条线，不需要板子、不需要 Flask。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import voice_service as V

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


# ---------------------------------------------------------------------------
print('\n=== 1. 时长估算 ===')
check('空文本 0 秒', V.est_speech_seconds('') == 0.0)
check('纯空白 0 秒', V.est_speech_seconds('   ') == 0.0)
check('None 不崩', V.est_speech_seconds(None) == 0.0)
d8 = V.est_speech_seconds('电池电压十二点八')          # 8 个汉字
check('8 个汉字约 2 秒（4 字/秒）', 1.9 <= d8 <= 2.1, d8)
check('极短文本仍有下限 0.8s', V.est_speech_seconds('好') >= 0.8)
check('中英混排比纯中文长', V.est_speech_seconds('你好 world hello') > 0.8)

# ---------------------------------------------------------------------------
print('\n=== 2. 发射文本登记 ===')
V.reset_tx_texts()
check('空文本不登记', V.note_tx_text('') is None and V.note_tx_text('  ') is None)
it = V.note_tx_text('现在是北京时间十九点整', seconds=3.0, ts=1000.0, source='announce')
check('登记项带起止时刻', it[0] == 1000.0 and it[1] == 1003.0, it)
check('登记项保留文本与来源', it[2] == '现在是北京时间十九点整' and it[3] == 'announce')
check('seconds<=0 时按时长估算',
      V.note_tx_text('测试一段话', seconds=0, ts=2000.0)[1] > 2000.0)
V.reset_tx_texts()
check('清空后没有登记', V.tx_matches(1000.0, 3.0) == [])

# ---------------------------------------------------------------------------
print('\n=== 3. 时间窗匹配 ===')
V.reset_tx_texts()
V.note_tx_text('电池电压十二点八伏特', seconds=5.0, ts=1000.0)
m = V.tx_matches(1000.0, 5.0)
check('同一时间窗命中', len(m) == 1 and m[0]['text'] == '电池电压十二点八伏特', m)
check('命中项不是 live', m[0]['live'] is False)
check('重叠时长被记录', m[0]['overlap'] == 5.0, m)
check('完全错开的段不命中', V.tx_matches(1100.0, 5.0) == [])
check('只压住尾巴一点点也能命中', len(V.tx_matches(1004.0, 5.0)) == 1)
check('极短重叠（0.1s）不算命中', V.tx_matches(1005.1, 5.0) == [], V.tx_matches(1005.1, 5.0))
# pre-roll：段的 start_ts 之后写进去的最前面几秒其实是更早录到的音频，
# 所以登记表要能靠「提前录进来」的那一段认领这个段
V.reset_tx_texts()
V.note_tx_text('播报开场', seconds=1.0, ts=998.0)
check('无 pre-roll 补偿时漏配', V.tx_matches(1000.0, 2.0) == [])
loaded = V.tx_matches(1000.0, 2.0, lead=3.0)
check('给 pre-roll 补偿后命中', len(loaded) == 1 and loaded[0]['text'] == '播报开场', loaded)

V.reset_tx_texts()
V.note_tx_text('短句', seconds=0.6, ts=3000.0)
check('短段小重叠能命中', len(V.tx_matches(3000.2, 0.6)) == 1)
check('短段几乎不重叠不命中', V.tx_matches(3000.9, 0.6) == [])

V.reset_tx_texts()
V.note_tx_text('先发的那条', seconds=2.0, ts=5000.0)
V.note_tx_text('后发的那条', seconds=2.0, ts=5001.0)
best = V.tx_matches(5001.0, 2.0)
check('多条命中时取重叠最大的', best[0]['text'] == '后发的那条', best)
check('两条都在候选里', len(best) == 2, best)

# TTL：过期登记不参与匹配（直接构造一条 added 很旧的记录）
V.reset_tx_texts()
with V._TX_TEXTS_LOCK:
    old_added = time.time() - (V.TX_TEXT_TTL + 60)
    V._TX_TEXTS.append((6000.0, 6005.0, '很久以前发的', 'tts', old_added))
check('超过 TTL 的登记不命中', V.tx_matches(6000.0, 5.0) == [])
V.reset_tx_texts()

# 文本登记优先于 live 标记（同一段同时压住两者时不能退化成送 ASR）
V.reset_tx_texts()
V.note_tx_text('有原文', seconds=4.0, ts=7000.0)
V.note_tx_live(ts=7000.0, hold=4.0)
top = V.tx_matches(7000.0, 4.0)
check('同重叠时文本登记排第一', top and top[0]['text'] == '有原文', top)

# ---------------------------------------------------------------------------
print('\n=== 4. 人工实时发射（网页对讲）标记 ===')
V.reset_tx_texts()
V.note_tx_live(ts=8000.0, hold=20.0, source='intercom')
live = V.tx_matches(8000.0, 3.0)
check('live 标记命中且 live=True', len(live) == 1 and live[0]['live'] is True, live)
check('live 标记没有文本', live[0]['text'] == '')
V.note_tx_live(ts=8000.1, hold=20.0, source='intercom')
check('心跳节流：0.1s 后不追加', len(V.tx_matches(8000.0, 3.0)) == 1)
V.reset_tx_texts()

# ---------------------------------------------------------------------------
print('\n=== 5. 策略判定 tx_decision ===')
note = V.TX_TEXT_NOTE
skip_note = V.TX_SKIP_NOTE
check('rx 段一律照旧送识别', V.tx_decision('auto', 'rx', '有字', True) == ('pending', '', ''))
check('both 段照旧送识别', V.tx_decision('auto', 'both', '', True) == ('pending', '', ''))
check('mode=on 是老行为（tx 也送）',
      V.tx_decision('on', 'tx', '有原文', False) == ('pending', '', ''))
check('auto + 有原文 → 用原文不送识别',
      V.tx_decision('auto', 'tx', '现在是北京时间十九点整', False)
      == ('tx', '现在是北京时间十九点整', note))
check('auto + 无原文 + 人工实时发射 → 仍送识别',
      V.tx_decision('auto', 'tx', '', True) == ('pending', '', ''))
check('auto + 无原文 + 非人声 → 跳过并说明',
      V.tx_decision('auto', 'tx', '', False) == ('skip', '', skip_note))
check('off + 人工实时发射 → 也不送识别',
      V.tx_decision('off', 'tx', '', True) == ('skip', '', skip_note))
check('off + 有原文 → 用原文',
      V.tx_decision('off', 'tx', '通告内容', False) == ('tx', '通告内容', note))
check('空白原文按「无原文」处理',
      V.tx_decision('auto', 'tx', '   ', False) == ('skip', '', skip_note))
check('原文两端空白被去掉',
      V.tx_decision('auto', 'tx', '  通告  ', False)[1] == '通告')

print('\n=== 6. 策略取值 ===')
check('缺省 auto', V.tx_asr_mode({}) == 'auto')
check('None 表 auto', V.tx_asr_mode(None) == 'auto')
check('off 原样', V.tx_asr_mode({'vlog_tx_asr': 'off'}) == 'off')
check('on 原样', V.tx_asr_mode({'vlog_tx_asr': 'ON'}) == 'on')
check('大小写/空白容忍', V.tx_asr_mode({'vlog_tx_asr': ' Auto '}) == 'auto')
check('非法值回落 auto', V.tx_asr_mode({'vlog_tx_asr': '随便写的'}) == 'auto')
check('默认设置里带这一项', V.DEFAULTS.get('vlog_tx_asr') == 'auto')
check('模式常量齐全', V.TX_ASR_MODES == ('off', 'auto', 'on'))

print('\n=== 7. 落段即定文字（真写库、真写 WAV）===')
if V.np is None:
    print('  SKIP numpy 不可用，跳过落段集成测试')
else:
    import shutil
    import struct
    import wave as _wave

    # 临时目录放当前目录下：板子/开发机都被各自的沙箱限制，别处不一定可写。
    # 不用 tempfile.mkdtemp —— 部分沙箱下它建出来的目录里 sqlite 打不开文件。
    tmp = os.path.join(os.getcwd(), '_txtext_tmp')
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    store = V.Store(os.path.join(tmp, 'v.db'))
    queued = []

    class _Stub:
        """只提供 Recorder 需要的那几样，其它一律不碰（不起线程、不发声）。"""

        override = {}

        def settings(self):
            return dict(V.DEFAULTS, vlog_dir=tmp, vlog_min_seconds='0.2',
                        vlog_pre_roll='3.0', **self.override)

        def get_rx(self):
            return False

        def get_tx(self):
            return True

        def _fill_aprs_pos(self, *_a):
            return (0, '', None, None)

        def _aprs_overlap(self, *_a):
            return False

        def tx_match(self, ts, seconds):
            hits = V.tx_matches(ts, seconds, lead=3.0)
            return hits[0] if hits else None

        def enqueue_asr(self, rid):
            queued.append(rid)

    svc = _Stub()
    svc.store = store
    svc.counters = {}
    rec = V.Recorder(svc)
    st = svc.settings()
    mono = struct.pack('<%dh' % 16000, *([1200] * 16000))       # 1s 单声道

    def _one_segment(kind, t0, st_use=None):
        rec.session_id = 'S1'
        rec._open_segment(t0, kind, st_use or st)
        rec._write(mono)                     # 正好 1 秒单声道
        rec._close_segment(t0 + 1.0)
        row = store.one('SELECT * FROM voice_logs ORDER BY id DESC LIMIT 1') or {}
        return row

    # 用接近「现在」的真实时间戳：Windows 的 fromtimestamp 在小值上会报 Errno 22
    T0 = time.time() - 120.0

    V.reset_tx_texts()
    V.note_tx_text('现在是北京时间十九点整，中继台运行正常', seconds=1.0, ts=T0)
    row = _one_segment('tx', T0)
    check('tx 段直接用发射原文', row.get('asr_text') == '现在是北京时间十九点整，中继台运行正常',
          row.get('asr_text'))
    check('tx 段状态标成 tx', row.get('asr_status') == 'tx', row.get('asr_status'))
    check('tx 段带说明', row.get('note') == V.TX_TEXT_NOTE, row.get('note'))
    check('tx 段归类为语音', row.get('category') == 'voice', row.get('category'))
    check('tx 段不排 ASR', queued == [], queued)
    check('落库字段完整（含 APRS 列不报错）', abs(float(row.get('end_epoch') or 0) - (T0 + 1.0)) < 0.01
          and abs(float(row.get('seconds') or 0) - 1.0) < 0.01 and row.get('path'), row)

    V.reset_tx_texts()
    row = _one_segment('tx', T0 + 400.0)
    check('无原文的 tx 段跳过识别', row.get('asr_status') == 'skip'
          and row.get('asr_text') == '', row)
    check('无原文的 tx 段写明原因', row.get('note') == V.TX_SKIP_NOTE, row.get('note'))
    check('跳过的 tx 段也不排 ASR', queued == [], queued)

    # 反例控制：rx 段即使旁边有同时间的发射登记，也必须照旧送识别
    V.reset_tx_texts()
    V.note_tx_text('这段是本机发的，不该贴到 rx 段上', seconds=1.0, ts=T0 + 800.0)
    row = _one_segment('rx', T0 + 800.0)
    check('rx 段仍走 ASR（待识别）', row.get('asr_status') == 'pending', row.get('asr_status'))
    check('rx 段不套用发射原文', (row.get('asr_text') or '') == '', row.get('asr_text'))
    check('rx 段进入 ASR 队列', len(queued) == 1, queued)

    # auto + 人工实时发射（网页对讲）：文本未知，仍应送识别
    V.reset_tx_texts()
    V.note_tx_live(ts=T0 + 1200.0, hold=10.0)
    row = _one_segment('tx', T0 + 1200.0)
    check('网页对讲的 tx 段仍送识别', row.get('asr_status') == 'pending', row.get('asr_status'))
    check('网页对讲的 tx 段进入队列', len(queued) == 2, queued)

    # tx_asr=off：连人工实时发射的 tx 段也不送识别
    V.reset_tx_texts()
    V.note_tx_live(ts=T0 + 1600.0, hold=10.0)
    svc.override = {'vlog_tx_asr': 'off'}    # _close_segment 自己读设置，得改 stub
    row = _one_segment('tx', T0 + 1600.0)
    svc.override = {}
    check('off 模式下 tx 段跳过识别', row.get('asr_status') == 'skip', row.get('asr_status'))
    check('off 模式下队列没有新增', len(queued) == 2, queued)

    V.reset_tx_texts()
    shutil.rmtree(tmp, ignore_errors=True)

print('\n=== 8. 接线防漏：每个合成站点都要登记发射文本 ===')
# 逻辑对了但漏登记，等于没修：那一段还是会被拿去 ASR。这条断言盯的是**接线数量** ——
# app.py 里每出现一次 synthesize_multilingual(，就应该有一次 _tx_note_wav(。
# 新增「合成但不上发射机」的路径时这条会误报，那时把新站点加进来或说明理由即可。
_app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.py')
if not os.path.exists(_app):
    print('  SKIP 找不到 app.py，跳过接线检查')
else:
    src = open(_app, encoding='utf-8').read()
    n_synth = src.count('synthesize_multilingual(')
    n_note = src.count('_tx_note_wav(')
    check('合成站点 %d 个 → 登记调用 %d 处（含定义 1 处）' % (n_synth, n_note - 1),
          n_note == n_synth + 1, 'synth=%d note=%d' % (n_synth, n_note))
    check('_tx_note_play 只在发射前被调一次（另有定义一处）',
          src.count('_tx_note_play(') == 2, src.count('_tx_note_play('))
    check('登记挂在 _play_file_locked 上（本地试听不算发射）',
          '_tx_note_play(path)' in src)
    check('登记以 PTT 已拉起为前提', 'if PTT_HOLD_COUNT > 0:' in src)
    check('网页对讲打了「人工实时发射」心跳',
          'note_tx_live(' in src and "source='intercom'" in src)
    check('重播/播报/助手三处都是 _tx_note_wav(path, text)',
          src.count('_tx_note_wav(path, text)') >= 5, src.count('_tx_note_wav(path, text)'))

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  ✗ %s' % f)
sys.exit(1 if FAIL else 0)
