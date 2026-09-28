# -*- coding: utf-8 -*-
"""中继语音助手·自主回答（思维链/自主决策）纯逻辑自测。

不需要板子、不需要 ASR/LLM 模型：决策模型用**假通道**喂固定输出，
所以这里测的是「判定、解析、闸门、影子锁」这些真代码，不是模型。

覆盖：
   1. 决策提示词（结构、长度、指令在最后、想字数）
   2. 四行输出解析（容错、fail-closed、答+理由自相矛盾、置信度钳制）
   3. 闸门顺序与红线（忙/禁发/测试模式/频率/冷却/间隔/白名单/影子锁）
   4. 预筛与回声（太短、数据音、自己刚说的话）
   5. 点名判定（同音唤醒词、本台呼号）
   6. 端到端影子（判答但**一次都不发射**、落库成 dry、计数器对账）
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import assistant_service as A          # noqa: E402

# 录音目录改成临时目录：套件只该写自己的沙盒，绝不碰 /opt/ai/relay_assist。
# （本机也没这个目录，写它会被沙箱/权限拦下，把套件结果搅成环境噪音。）
A.WORK_DIR = Path(tempfile.mkdtemp())

FAIL = []
OK = [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


# ---------------------------------------------------------------------------
print('\n=== 0. 阶段一只开放影子模式（发射锁） ===')
check('AUTO_MODES_OPEN 只含 shadow', A.AUTO_MODES_OPEN == ('shadow',),
      repr(A.AUTO_MODES_OPEN))
check('三种模式都还有代码路径', A.AUTO_MODES == ('shadow', 'half', 'full'))

# ---------------------------------------------------------------------------
print('\n=== 1. 决策提示词 ===')
p = A.compose_decision_prompt('中继台，现在电池电压多少',
                              {'called': True, 'callsign': 'BI7KHI',
                               'since': 123, 'whitelist': 'BI7KHI', 'think_chars': 30,
                               'last': [('对方', '刚才那句'), ('我', '收到')]})
check('含听到的原文', '电池电压' in p)
check('含状态行', '点名：是' in p and 'BI7KHI' in p and '123' in p)
check('输出要求在最后一段', p.rstrip().splitlines()[-1].endswith('信：0~9'))
check('四行格式齐全', all(('第%s行只写' % n) in p for n in '一二三四'))
check('长度有上限', len(p) <= 600, 'len=%d' % len(p))
p2 = A.compose_decision_prompt('喂',
                               {'think_chars': 8, 'called': False, 'since': 0})
check('想字数可调', '不超过8个字' in p2)
check('空文本不炸', '（无）' in A.compose_decision_prompt('', {}))
check('超长输入被截断', len(A.compose_decision_prompt('啊' * 500, {})) <= 600)

# ---------------------------------------------------------------------------
print('\n=== 2. 四行解析（fail-closed） ===')
d = A.parse_decision('想：对方在问电压\n判：答\n由：直接提问\n信：7')
check('标准四行 → 答', d['decision'] == 'answer' and d['reason'] == 'question'
      and d['confidence'] == 7 and d['ok'])
check('想被记下', d['think'] == '对方在问电压')
d = A.parse_decision('想：与本台无关\n判：默\n由：与本站无关\n信：9')
check('明确判默', d['decision'] == 'silent' and d['reason'] == 'unrelated' and d['ok'])
d = A.parse_decision('想：喊的是别人\n判：默\n由：正在通联\n信：8')
check('通联中不插话', d['decision'] == 'silent' and d['reason'] == 'ongoing')
# 模型多话：判/由后面带解释，不能因此判成解析失败
d = A.parse_decision('想：被点名了\n判：答（对方在叫我）\n由：被点名 —— 呼叫本台\n信：6')
check('判/由带解释仍能解析', d['decision'] == 'answer' and d['reason'] == 'called'
      and d['ok'], repr(d))
# 四行糊成一行
d = A.parse_decision('想：问天气 判：答 由：直接提问 信：5')
check('糊成一行也能解析', d['decision'] == 'answer' and d['reason'] == 'question'
      and d['confidence'] == 5, repr(d))
# 正文里的「想」不能当字段
d = A.parse_decision('这段语音里有人说：我想问一下天气怎么样\n判：答\n由：直接提问\n信：5')
check('正文里的「想」不干扰判定', d['decision'] == 'answer' and d['reason'] == 'question')
# fail-closed 各态
d = A.parse_decision('')
check('空输出 → 默且未解析', d['decision'] == 'silent' and not d['ok'])
d = A.parse_decision('对方在问电池电压，应该回答一下。')
check('纯散文（无四行）→ 默', d['decision'] == 'silent' and not d['ok'])
d = A.parse_decision('判：答\n由：听不清\n信：3')
check('「答」却给不可接受的理由 → 降级为默',
      d['decision'] == 'silent' and d['reason'] == 'reason' and not d['ok'], repr(d))
d = A.parse_decision('判：答\n由：随便编的理由\n信：3')
check('理由不在闭集 → 默', d['decision'] == 'silent' and not d['ok'])
d = A.parse_decision('判：也许吧\n由：直接提问\n信：3')
check('判定词不认识 → 默', d['decision'] == 'silent' and not d['ok'])
d = A.parse_decision('判：答\n由：被点名\n信：99')
check('置信度钳到 9', d['confidence'] == 9)
d = A.parse_decision('判：答\n由：被点名\n信：')
check('置信度缺失 → 0 且仍判答', d['confidence'] == 0 and d['decision'] == 'answer')
d = A.parse_decision('想：' + '很' * 100 + '\n判：答\n由：闲聊\n信：4', max_think=12)
check('「想」被截断到上限', len(d['think']) == 12, 'len=%d' % len(d['think']))
d = A.parse_decision('判：默\n由：求助\n信：2')
check('判默但理由是求助 → 仍是默（以判为准）',
      d['decision'] == 'silent' and d['reason'] == 'help')

# ---------------------------------------------------------------------------
print('\n=== 3. 闸门与红线 ===')
NOW = 100000.0
# 闸门自身的逻辑要能被验证，所以临时把「已开放模式」扩到三种（=阶段二的开关），
# 验完立刻改回。这样做同时证明了一件事：**能不能发射只由 AUTO_MODES_OPEN 一处决定**。
_OPEN0 = A.AUTO_MODES_OPEN
A.AUTO_MODES_OPEN = ('shadow', 'half', 'full')


def gate(**kw):
    base = dict(mode='full', now=NOW)
    base.update(kw)
    return A.auto_gate(**base)


check('判默 → 静默', gate(decision='silent', reason='unrelated')[1] == 'silent')
check('判答+可接受理由 → 放行', gate(decision='answer', reason='called')[0] is True)
check('判答+不可接受理由 → reason',
      gate(decision='answer', reason='unclear')[1] == 'reason')
check('白名单不符 → whitelist',
      gate(decision='answer', reason='called', callsign='BI7ABC',
           whitelist='BI7KHI')[1] == 'whitelist')
check('白名单相符 → 继续走后面的闸门',
      gate(decision='answer', reason='called', callsign='bi7khi',
           whitelist='BI7KHI')[0] is True)
check('白名单为空 = 不限呼号',
      gate(decision='answer', reason='called', callsign='XX9XX', whitelist='')[0] is True)
check('同呼号冷却中 → cooldown',
      gate(decision='answer', reason='called', callsign='BI7KHI',
           call_ts=NOW - 100, cooldown=600)[1] == 'cooldown')
check('冷却已过 → 放行',
      gate(decision='answer', reason='called', callsign='BI7KHI',
           call_ts=NOW - 700, cooldown=600)[0] is True)
check('本小时已满 → rate',
      gate(decision='answer', reason='called', hits=[NOW - i * 10 for i in range(6)],
           max_per_hour=6)[1] == 'rate')
check('一小时以前的命中不算 → 放行',
      gate(decision='answer', reason='called', hits=[NOW - 3600 - i for i in range(9)],
           max_per_hour=6)[0] is True)
check('max_per_hour=0 → 立刻 rate',
      gate(decision='answer', reason='called', max_per_hour=0)[1] == 'rate')
check('距上次发射太近 → gap',
      gate(decision='answer', reason='called', last_tx=NOW - 10, min_gap=90)[1] == 'gap')
check('间隔够 → 放行',
      gate(decision='answer', reason='called', last_tx=NOW - 100, min_gap=90)[0] is True)
check('信道忙 → busy（红线，与模式无关）',
      gate(decision='answer', reason='called', busy=True)[1] == 'busy')
check('禁发时段 → quiet', gate(decision='answer', reason='called', quiet=True)[1] == 'quiet')
check('全局测试模式 → test_mode',
      gate(decision='answer', reason='called', test_mode=True)[1] == 'test_mode')
check('影子模式 → shadow（阶段一唯一结局）',
      gate(decision='answer', reason='called', mode='shadow')[1] == 'shadow')
check('影子模式下红线照样拦得住（忙）',
      gate(decision='answer', reason='called', mode='shadow', busy=True)[1] == 'busy')
# 顺序：quiet/test_mode 先于 busy；busy 先于 shadow
check('顺序：quiet 先于 busy',
      gate(decision='answer', reason='called', quiet=True, busy=True)[1] == 'quiet')
check('顺序：busy 先于 shadow',
      gate(decision='answer', reason='called', mode='shadow', busy=True)[1] == 'busy')
check('顺序：silent 先于一切',
      gate(decision='silent', reason='unrelated', busy=True, quiet=True)[1] == 'silent')

A.AUTO_MODES_OPEN = _OPEN0            # —— 关回阶段一 ——
check('关回后：full/half 一律 locked，绝不放行',
      gate(decision='answer', reason='called', mode='half')[1] == 'locked'
      and gate(decision='answer', reason='called', mode='full')[1] == 'locked'
      and gate(decision='answer', reason='called', mode='banana')[1] == 'locked')
check('locked 时 allowed 必为 False',
      gate(decision='answer', reason='called', mode='full')[0] is False)
check('关回后：影子仍是 shadow（不是 ok）',
      gate(decision='answer', reason='called', mode='shadow')[1] == 'shadow')
check('auto_mode 回落到 shadow', A.auto_mode({}) == 'shadow'
      and A.auto_mode({'assist_auto_mode': 'FULL'}) == 'full'
      and A.auto_mode({'assist_auto_mode': '乱写'}) == 'shadow')
check('结论码都有中文标签',
      all(k in A.AUTO_BLOCK_LABEL for k in
          ('silent', 'reason', 'whitelist', 'cooldown', 'rate', 'gap',
           'quiet', 'test_mode', 'busy', 'shadow')))

# ---------------------------------------------------------------------------
print('\n=== 4. 预筛与回声 ===')
check('太短 → 预筛掉', A.auto_prefilter('喂')[0] is False)
check('纯数字 → 预筛掉（数据音/报数残留）',
      A.auto_prefilter('599 599 12')[0] is False)
check('正常句子 → 送模型', A.auto_prefilter('中继台现在电压多少')[0] is True)
check('自己刚说的话 → 回声',
      A.auto_prefilter('现在电池电压是十二点二伏特', ['现在电池电压是十二点二伏特'])[1] == 'echo')
check('回声近似也算（ASR 误差）',
      A.auto_prefilter('现在电池电压十二点二伏特', ['现在电池电压是十二点二伏特'])[1] == 'echo')
check('别人的不同内容不算回声',
      A.auto_prefilter('请问中继台现在通联情况如何', ['现在电池电压是十二点二伏特'])[0] is True)
check('短回声不误判', A.auto_echo('好的', ['好的']) is False)
check('空自己内容不崩', A.auto_echo('随便说点什么吧', []) is False)

# ---------------------------------------------------------------------------
print('\n=== 5. 是不是在叫我们 ===')
W = ['智能中继', '中继台']
check('唤醒词在句中 → 被点名', A.auto_called('那个中继台，帮我查一下', W) is True)
check('同音字（太→台）→ 被点名', A.auto_called('中继太现在几点', W) is True)
check('提到本台呼号 → 被点名',
      A.auto_called('BI7KHI 在吗', W, ['BI7KHI']) is True)
check('别人的呼号 → 不算', A.auto_called('BI7ABC 你好', W, ['BI7KHI']) is False)
check('无关闲聊 → 不算', A.auto_called('今天天气不错啊', W, ['BI7KHI']) is False)
check('空文本不崩', A.auto_called('', W) is False)

# ---------------------------------------------------------------------------
print('\n=== 6. 端到端影子（关键：判答也一次都不发射） ===')

PLAY = {'n': 0}
TTS = {'n': 0}
ASK = {'n': 0, 'reply': '现在电池电压十二点二伏特。喵。'}
RAW = {'n': 0, 'text': '想：对方在问电压\n判：答\n由：直接提问\n信：7'}


def _tts(text, voice=''):
    TTS['n'] += 1
    d = Path(tempfile.mkdtemp())
    f = d / 'x.wav'
    f.write_bytes(b'RIFF0000WAVE')
    return str(f)


def _play(path, max_seconds=30.0):
    PLAY['n'] += 1
    return {'ok': True, 'seconds': 1.0}


def _ask(prompt, question='', max_tokens=256, temperature=0.3, use_tools=True,
         max_iters=2, sysprompt=''):
    ASK['n'] += 1
    return {'ok': True, 'reply': ASK['reply'], 'ms': 5, 'provider': 'fake',
            'model': 'fake', 'iters': 1, 'tools': ''}


def _ask_raw(messages, temperature=0.1, max_tokens=48, timeout=60):
    RAW['n'] += 1
    return {'ok': True, 'text': RAW['text'], 'ms': 7, 'provider': 'fake',
            'model': 'fake', 'error': ''}


SET = {'assist_auto_whitelist': '', 'assist_auto_dry_answer': '0',
       'assist_test_mode': '0', 'assist_wake_words': '智能中继,中继台'}


def new_svc():
    db = os.path.join(tempfile.mkdtemp(), 'a.db')
    s = A.AssistantService(db)
    s.configure(lambda: dict(SET), lambda: False, lambda: False,
                _ask, _tts, _play, lambda: '', None, None, _ask_raw)
    return s


svc = new_svc()
ITEM = {'data': b'\x00\x00' * 8000, 'dbfs': -30.0, 'seconds': 3.0, 'busy': True}
rec = {}
kept = []
ok_handled = svc._auto_try('现在电池电压多少', svc.settings(), ITEM, rec,
                            lambda a, w='': kept.append(a), 120, time.time())
check('自主层接管了这一段', ok_handled is True)
check('影子记录动作=shadow', rec.get('action') == 'shadow', repr(rec.get('action')))
check('影子记录带判定与理由', rec.get('auto', {}).get('decision') == 'answer'
      and rec['auto']['reason'] == 'shadow', repr(rec.get('auto')))
check('影子记录 would_reply=1', rec['auto']['would_reply'] is True)
check('**没有调用播放（一次都没发射）**', PLAY['n'] == 0, 'play=%d' % PLAY['n'])
check('也没生成语音（dry_answer 关）', TTS['n'] == 0, 'tts=%d' % TTS['n'])
rows = svc.store.query('SELECT * FROM assist_turns ORDER BY id')
check('落库一行', len(rows) == 1, repr(len(rows)))
r0 = rows[0]
check('库里 dry=1 / action=shadow / would_reply=1',
      r0['dry'] == 1 and r0['action'] == 'shadow' and r0['would_reply'] == 1)
check('库里存了判定/理由/置信度/想',
      r0['decision'] == 'answer' and r0['reason'] == 'shadow'
      and r0['confidence'] == 7 and '电压' in r0['think'])
check('kind=auto（影子判定行）', r0['kind'] == 'auto')
check('计数器：判答=1、影子拦下=1',
      svc.counters['auto_answered'] == 1 and svc.counters['auto_shadow_blocked'] == 1)
check('影子期 shadow_blocked == answered（不变式）',
      svc.counters['auto_shadow_blocked'] == svc.counters['auto_answered'])

# 判默
RAW['text'] = '想：说的是别人\n判：默\n由：与本站无关\n信：8'
svc.invalidate()
rec2 = {}
svc._auto_try('老李你那边天气怎么样', svc.settings(), ITEM, rec2, lambda a, w='': None,
              100, time.time())
check('判默 → action=silent', rec2.get('action') == 'silent', repr(rec2.get('action')))
check('判默不发射', PLAY['n'] == 0)
check('判默计数 +1', svc.counters['auto_silent'] == 1)

# 解析失败 → 默
RAW['text'] = '我觉得应该回答一下。'
svc.invalidate()
rec3 = {}
svc._auto_try('谁在那边说话', svc.settings(), ITEM, rec3, lambda a, w='': None,
              100, time.time())
check('解析失败 → 静默', rec3.get('action') == 'silent')
check('解析失败计数 +1', svc.counters['auto_parse_fail'] == 1)

# 信道忙（此刻）→ 连影子都不算「应发射」。
# 注意：用的是**当前** BUSY，不是这一段的 BUSY 标志 —— 听见对方正是因为有载波。
RAW['text'] = '想：问电压\n判：答\n由：直接提问\n信：7'
svc.invalidate()
svc.busy_getter = lambda: True
rec4 = {}
svc._auto_try('电池电压多少', svc.settings(), ITEM, rec4, lambda a, w='': None,
              100, time.time())
check('信道忙 → 判定被拦下', rec4.get('action') == 'silent', repr(rec4.get('action')))
check('信道忙 → gate=busy 且不计 would_reply',
      rec4['auto']['reason'] == 'busy' and rec4['auto']['would_reply'] is False,
      repr(rec4.get('auto')))
check('信道忙时一次都没发射', PLAY['n'] == 0)
svc.busy_getter = lambda: False
svc.invalidate()

# 注意：段标志 busy=True 不该拦住判定（否则「听见了就永远不许答」）
rec4b = {}
svc._auto_try('电池电压多少', svc.settings(), ITEM, rec4b, lambda a, w='': None,
              100, time.time())
check('收到时的载波标志不影响判定（只看此刻）',
      rec4b.get('action') == 'shadow', repr(rec4b.get('action')))

# 频率上限
svc.invalidate()
svc.auto_hits.extend([time.time() - i for i in range(6)])
rec5 = {}
svc._auto_try('电池电压多少', svc.settings(), ITEM, rec5, lambda a, w='': None,
              100, time.time())
check('本小时满额 → rate', rec5['auto']['reason'] == 'rate', repr(rec5['auto']))
check('rate 计数 +1', svc.counters['auto_rate_limited'] >= 1)
svc.auto_hits.clear()

# 白名单
svc.invalidate()
SET['assist_auto_whitelist'] = 'BI7KHI'
svc.invalidate()
rec6 = {}
svc._auto_try('电池电压多少', svc.settings(), ITEM, rec6, lambda a, w='': None,
              100, time.time())
check('白名单不匹配 → whitelist', rec6['auto']['reason'] == 'whitelist',
      repr(rec6['auto']))
check('whitelist 计数 +1', svc.counters['auto_whitelist_blocked'] == 1)
SET['assist_auto_whitelist'] = ''
svc.invalidate()

# 回声：先造一句「自己刚发射的」
svc.tx_texts.append('现在电池电压是十二点二伏特')
rec7 = {}
kept7 = svc._auto_try('现在电池电压是十二点二伏特', svc.settings(), ITEM, rec7,
                      lambda a, w='': None, 100, time.time())
check('自己的回声不进决策', kept7 is False)
check('回声计数 +1', svc.counters['auto_echo_skipped'] == 1)
check('回声不落库（shadow 行只有那两条「本来会答」的）',
      len(svc.store.query("SELECT id FROM assist_turns WHERE action='shadow'")) == 2,
      repr(len(svc.store.query("SELECT id FROM assist_turns WHERE action='shadow'"))))

# 影子试答：dry_answer 打开后仍然一次都不发射
PLAY['n'] = 0
TTS['n'] = 0
SET['assist_auto_dry_answer'] = '1'
svc.invalidate()
svc.tx_texts.clear()
rec8 = {}
svc._auto_try('中继台，电池电压多少', svc.settings(), ITEM, rec8,
              lambda a, w='': None, 90, time.time())
deadline = time.time() + 8
while svc.auto_dry_running and time.time() < deadline:
    time.sleep(0.05)
time.sleep(0.3)
check('影子试答生成了语音', TTS['n'] >= 1, 'tts=%d' % TTS['n'])
check('**影子试答仍然一次都没发射**', PLAY['n'] == 0, 'play=%d' % PLAY['n'])
dry = svc.store.query("SELECT * FROM assist_turns WHERE kind='auto-answer'")
check('试答单独落一行 kind=auto-answer', len(dry) == 1, repr(len(dry)))
if dry:
    check('试答行动作=shadow、dry=1、带判定',
          dry[0]['action'] == 'shadow' and dry[0]['dry'] == 1
          and dry[0]['decision'] == 'answer', repr(dict(dry[0]))[:200])
    check('试答文本被记下（人可回看答得对不对）',
          '电压' in (dry[0]['reply'] or ''), repr(dry[0]['reply']))
check('试答不计 aborted（不是「被拦下的发射」）', svc.counters['aborted'] == 0,
      'aborted=%d' % svc.counters['aborted'])

# 总关闭
SET['assist_auto_dry_answer'] = '0'
SET['assist_auto_enabled'] = '0'
svc.invalidate()
check('总开关关掉 → 自主层不介入',
      svc._auto_try('电池电压多少', svc.settings(), ITEM, {},
                    lambda a, w='': None, 90, time.time()) is False)
SET['assist_auto_enabled'] = '1'
# 未开放模式不跑决策
SET['assist_auto_mode'] = 'full'
svc.invalidate()
before = RAW['n']
check('未开放模式（full）连模型都不叫',
      svc._auto_try('电池电压多少', svc.settings(), ITEM, {},
                    lambda a, w='': None, 90, time.time()) is False
      and RAW['n'] == before)
SET['assist_auto_mode'] = 'shadow'
svc.invalidate()

# ---------------------------------------------------------------------------
print('\n=== 7. 页面自测接口（test_decide） ===')
svc.invalidate()
t = svc.test_decide('BI7KHI 帮我看看电压', busy=False)
check('自测回报判定与闸门', t.get('decision') == 'answer' and t.get('gate') == 'shadow',
      repr({k: t.get(k) for k in ('decision', 'gate')}))
check('自测回报预筛结果', t.get('prefilter') == 'pass')
check('自测回报上限设置', t['limits']['max_per_hour'] == 6)
check('自测能验「忙则不答」（不用接无线电）',
      svc.test_decide('BI7KHI 帮我看看电压', busy=True)['gate'] == 'busy')
check('自测默认不入库',
      len(svc.store.query("SELECT id FROM assist_turns WHERE kind='auto-test'")) == 0)
t2 = svc.test_decide('帮我看看电压', busy=False, store=True)
check('store=True 才留档',
      len(svc.store.query("SELECT id FROM assist_turns WHERE kind='auto-test'")) == 1)
check('自测空文本报错', svc.test_decide('')['ok'] is False)
st = svc.decide_status()
check('状态含阶段锁说明', st['mode'] == 'shadow' and st['open_modes'] == ['shadow'])
check('状态含剩余额度', st['max_per_hour'] == 6 and st['used_last_hour'] == 0
      or st['used_last_hour'] >= 0)
check('状态含结论码字典', 'shadow' in st['reason_labels'])

# 注入判定：闸门链必须能**不依赖模型**复现（红线与模型的判断无关）
svc.invalidate()
n_before = RAW['n']
ji = svc.test_decide('随便一句话', busy=False,
                     judge={'decision': 'answer', 'reason': 'question'})
check('注入判定生效且未调用模型',
      ji.get('forced') is True and ji.get('decision') == 'answer' and RAW['n'] == n_before,
      'forced=%s raw_n=%s' % (ji.get('forced'), RAW['n']))
check('注入判答 + 不忙 → 影子（本应发射）',
      ji.get('gate') == 'shadow' and ji.get('would_reply') is True)
ji2 = svc.test_decide('随便一句话', busy=True,
                      judge={'decision': 'answer', 'reason': 'question'})
check('注入判答 + 信道忙 → busy（红线压过模型判断）',
      ji2.get('gate') == 'busy' and ji2.get('would_reply') is False, ji2.get('gate'))
check('注入「答」但理由不可接受 → 拒绝注入（改走真模型）',
      svc.test_decide('随便一句话', busy=False,
                      judge={'decision': 'answer', 'reason': 'unclear'}).get('forced')
      is False)
check('注入非法判定词 → 拒绝注入',
      svc.test_decide('随便一句话', busy=False,
                      judge={'decision': '随便'}).get('forced') is False)
check('注入判默 → silent', svc.test_decide(
    '随便一句话', busy=False,
    judge={'decision': 'silent', 'reason': 'unrelated', 'think': '注入'}).get('gate')
    == 'silent')
check('_forced_judge 对非字典返回 None',
      svc._forced_judge(None) is None and svc._forced_judge('answer') is None)

# ---------------------------------------------------------------------------
print('\n=== 9. 回归：未命中唤醒词的普通忽略不能崩 ===')
# 板端日志实测到「处理失败：KeyError: 'note'」：note 只在「接近唤醒词」或自主预筛时
# 才被赋值，而 _set_stage 直接下标取 —— 最常走的那条路（普通忽略）整段处理中断。
# 这条用例把 ASR 换成假实现，真跑 _handle，确保这条路走通。
SET['assist_auto_enabled'] = '0'
svc.invalidate()
svc._asr_shared = lambda x, sr, st: ('今天天气不错啊', 12, '')
try:
    svc._handle({'data': b'\x00\x00' * 1600, 'seconds': 0.5, 'dbfs': -30.0})
    crashed = ''
except Exception as e:
    crashed = '%s: %s' % (type(e).__name__, e)
check('普通忽略不抛异常', not crashed, crashed)
recs = [r for r in list(svc.recent) if r.get('heard') == '今天天气不错啊']
check('该段被记进实况流并标为 ignored',
      recs and recs[-1].get('action') == 'ignored',
      repr(recs[-1] if recs else None))
check('忽略计数 +1', svc.counters['ignored'] >= 1)

# 空识别结果、重复句这些旁路也别崩
svc._asr_shared = lambda x, sr, st: ('', 5, '')
try:
    svc._handle({'data': b'\x00\x00' * 1600, 'seconds': 0.5, 'dbfs': -30.0})
    crashed2 = ''
except Exception as e:
    crashed2 = '%s: %s' % (type(e).__name__, e)
check('空识别结果不抛异常', not crashed2, crashed2)
svc._asr_shared = lambda x, sr, st: ('', 5, 'ASRError: 模型未加载')
try:
    svc._handle({'data': b'\x00\x00' * 1600, 'seconds': 0.5, 'dbfs': -30.0})
    crashed3 = ''
except Exception as e:
    crashed3 = '%s: %s' % (type(e).__name__, e)
check('ASR 报错不抛异常', not crashed3, crashed3)
SET['assist_auto_enabled'] = '1'

# ---------------------------------------------------------------------------
print('\n=== 10. 老库迁移（增量补列、数据不动） ===')
import sqlite3                                        # noqa: E402
old = sqlite3.connect(os.path.join(tempfile.mkdtemp(), 'old.db'))
old.executescript("""
CREATE TABLE assist_turns(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, kind TEXT, wake TEXT, heard TEXT, reply TEXT, action TEXT,
  tx_seconds REAL DEFAULT 0, truncated INTEGER DEFAULT 0, error TEXT DEFAULT '',
  asr_ms INTEGER DEFAULT 0, llm_ms INTEGER DEFAULT 0, tts_ms INTEGER DEFAULT 0,
  wait_s REAL DEFAULT 0, rx_wav TEXT DEFAULT '', tx_wav TEXT DEFAULT '',
  prompt_chars INTEGER DEFAULT 0, reply_chars INTEGER DEFAULT 0,
  provider TEXT DEFAULT '', model TEXT DEFAULT '', iters INTEGER DEFAULT 0,
  tools TEXT DEFAULT '', dbfs REAL DEFAULT 0);
INSERT INTO assist_turns(ts,kind,heard,action,reply) VALUES('2026-09-01T10:00:00','wake','老数据','sent','旧回复');
""")
old.commit()
oldpath = old.execute('PRAGMA database_list').fetchone()[2]
old.close()
svc2 = A.AssistantService(oldpath)
cols = {r['name'] for r in svc2.store.query('PRAGMA table_info(assist_turns)')}
check('老库补齐全部新列',
      all(c in cols for c in ('decision', 'reason', 'confidence', 'think',
                              'callsigns', 'would_reply', 'dry')), repr(sorted(cols)))
keeprows = svc2.store.query('SELECT * FROM assist_turns')
check('老数据一行没动', len(keeprows) == 1 and keeprows[0]['reply'] == '旧回复')
svc2.store.exec("INSERT INTO assist_turns(ts,kind,heard,action,decision,think,dry) "
                "VALUES('2026-09-30T10:00:00','auto','x','silent','silent','想','1')")
check('补列后可写新字段',
      svc2.store.one("SELECT think FROM assist_turns WHERE kind='auto'")['think'] == '想')
svc2.store.init()
check('重复 init 幂等（再跑一次不报错、列不翻倍）',
      len([1 for r in svc2.store.query('PRAGMA table_info(assist_turns)')
           if r['name'] == 'decision']) == 1)

# ---------------------------------------------------------------------------
print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
if FAIL:
    print('失败用例：')
    for f in FAIL:
        print('  - %s' % f)
    sys.exit(1)
