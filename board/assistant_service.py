# -*- coding: utf-8 -*-
"""中继语音助手：BUSY 语音唤醒 → ASR → 本地 LLM → TTS → 受控发射。

架构位置
--------
nau8822 采集设备**独占**，全板只有 app.py 的 `_mic_capture_loop` 一路 arecord。
本模块作为该采集中枢的第三个消费者挂上去（前两个是 voice_service 语音日志、
aprs_service TNC），与它们共用同一份原始立体声块：

    _mic_capture_loop →┬→ voice_service.feed()   语音日志
                       ├→ aprs_service.feed()    APRS TNC
                       └→ assistant_service.feed() ← 本模块

为什么不自带第二路 arecord：设备独占，第二路会直接 `Device or resource busy`。

为什么不直接复用语音日志的 ASR 结果
-----------------------------------
ASR 模型确实是同一份（`asr_service.ENGINE` 单例 + 解码锁，**没有**重复加载），
但唤醒对**时机**的要求和归档完全不同，直接挂 vlog 结果会踩两个坑：

  1. 归档 `vlog_post_roll=2.0s` 才收段，唤醒会白白多等 2 秒；
  2. 归档 `vlog_min_seconds=1.0`，短于 1 秒的「中继台」会被判成 jitter，且
     `transcribe_one` 里 `segs` 为空导致**根本不跑 ASR**——单独喊唤醒词永远唤不醒。

因此本模块自带一套轻量分段（能量迟滞 + 静音判尾 + 前置缓冲），共用
`voice_service.Vad` 与 `asr_service` 做边界校正与识别，既能 0.45s 收段，
也不受语音日志开关与门槛影响。

安全红线（全部对应可调设置项）
----------------------------
  * BUSY 有效时**绝不**发射，最多等 `assist_busy_wait_seconds` 秒后放弃本次回答；
  * 与上次发射间隔不足 `assist_min_gap_seconds` 时强制等待；
  * 单条回答硬上限 `assist_max_tx_seconds` 秒，超时由 app.py 侧 kill aplay；
  * 自己发射期间 `assist_tx_guard_ms` 内不收音，防止自激；
  * 可选禁发时段 `assist_quiet_hours`；
  * 网页可一键停止，`stop()` 会立刻打断播放并清空待处理队列。
"""
import difflib
import json
import math
import inspect
import queue
import re
import sqlite3
import threading
import time
import wave
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

import agent_service

LOG = '[ASSIST]'

# 唤醒方式：level = 电平分段后判唤醒词（原行为）；busy = BUSY 触发 + 唤醒词双条件
WAKE_MODES = ('level', 'busy')

SAMPLE_RATE = 16000
FRAME_BYTES = 2                       # 16bit 单声道
WORK_DIR = Path('/opt/ai/relay_assist')

# ---------------------------------------------------------------------------
# 默认设置（全部可在「中继语音助手」页面在线修改，即改即生效）
# ---------------------------------------------------------------------------
DEFAULT_SUFFIX = (
    '你是中继台的语音助手，回复会被合成语音后发射出去。\n'
    '只输出可直接朗读的纯口语，不要 Markdown、星号、井号、列表、emoji；\n'
    '不超过 {max_chars} 字，一句答完，不复述问题、不解释过程；\n'
    '没数据就说不知道，不要编造。'
)

DEFAULTS = {
    'assist_enabled': '0',
    'assist_wake_words': '智能中继,中继台',
    'assist_wake_fuzzy': '1',
    # level = 电平分段后判唤醒词（原行为）；busy = BUSY 触发 + 唤醒词双条件
    'assist_wake_mode': 'level',
    # 宽松匹配：允许唤醒词**漏一个字**（「智能中继」→「智能继」）。默认关闭 ——
    # 漏字变体会让短词更容易误触发，实测这是误唤醒的主要来源。
    'assist_wake_loose': '0',
    'assist_channel': 'left',
    # 分段
    'assist_dbfs_open': '-50',
    'assist_dbfs_close': '-56',
    'assist_preroll_ms': '1200',
    'assist_silence_ms': '450',
    'assist_min_speech_ms': '350',
    'assist_max_utterance': '15',
    # 交互
    'assist_followup_seconds': '30',
    'assist_ack_reply': '请讲',
    'assist_use_vad': '1',
    'assist_enhance': '1',
    # 发射安全
    'assist_max_tx_seconds': '30',
    'assist_min_gap_seconds': '15',
    'assist_busy_wait_seconds': '8',
    'assist_tx_guard_ms': '600',
    'assist_quiet_hours': '',
    'assist_test_mode': '0',
    # LLM 预算
    'assist_max_reply_chars': '80',
    'assist_max_tokens': '256',
    'assist_history_turns': '6',
    'assist_max_input_chars': '3000',
    'assist_temperature': '0.3',
    'assist_provider': 'local',
    'assist_use_tools': '1',
    'assist_agent_iters': '2',
    'assist_keep_llm_warm': '1',
    'assist_llm_wait': '25',
    # 语音
    'assist_prompt_suffix': DEFAULT_SUFFIX,
    'assist_voice': '',
    # 归档
    'assist_retention_days': '30',
    'assist_debug_keep': '12',   # 识别音频留档条数（0=不留）
    # ---- 自主回答（听到一段话自己判断该不该答；阶段一=影子模式）----
    # shadow 只做决策与记录、绝不发射；half/full 的代码路径已就位，但**尚未开放**
    # （见 AUTO_MODES_OPEN），设置里也先不提供，避免一个手滑就放开发射。
    'assist_auto_enabled': '1',
    'assist_auto_mode': 'shadow',
    'assist_auto_max_per_hour': '6',
    'assist_auto_min_gap': '90',
    'assist_auto_call_cooldown': '600',
    'assist_auto_whitelist': '',      # 呼号白名单；留空=不限呼号
    'assist_auto_think': '1',         # 让模型写「想」；关掉省几秒
    'assist_auto_think_chars': '30',
    # 影子期把「本来会说的话」也生成出来（只合成试听，绝不发射）——只看判定
    # 无法验收答得对不对，所以默认打开；嫌费时可以关。
    'assist_auto_dry_answer': '1',
    # 「显式点名」内容前置：听文里必须出现本台名（含实测变形）或本台呼号，才允许
    # 判答放行。默认开 —— 影子期 26 条拟发射里约一半是旁人互相通联，模型分不清
    # "在问旁边的朋友"和"在问本台"，而发射出去收不回来。
    'assist_auto_require_address': '1',
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS assist_turns(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, kind TEXT, wake TEXT, heard TEXT, reply TEXT, action TEXT,
  tx_seconds REAL DEFAULT 0, truncated INTEGER DEFAULT 0, error TEXT DEFAULT '',
  asr_ms INTEGER DEFAULT 0, llm_ms INTEGER DEFAULT 0, tts_ms INTEGER DEFAULT 0,
  wait_s REAL DEFAULT 0, rx_wav TEXT DEFAULT '', tx_wav TEXT DEFAULT '',
  prompt_chars INTEGER DEFAULT 0, reply_chars INTEGER DEFAULT 0,
  provider TEXT DEFAULT '', model TEXT DEFAULT '', iters INTEGER DEFAULT 0,
  tools TEXT DEFAULT '', dbfs REAL DEFAULT 0,
  decision TEXT DEFAULT '', reason TEXT DEFAULT '', confidence INTEGER DEFAULT 0,
  think TEXT DEFAULT '', callsigns TEXT DEFAULT '', would_reply INTEGER DEFAULT 0,
  dry INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_assist_ts ON assist_turns(ts);
"""

# 自主回答新增列：老库（板上已有几百条记录）靠 ALTER TABLE 增量补，
# 不重建表 —— 重建一次就等于把现场记录赌在一条 SQL 上。
AUTO_COLUMNS = (
    ('decision', "TEXT DEFAULT ''"),      # answer / silent
    ('reason', "TEXT DEFAULT ''"),        # 结论码：silent/reason/whitelist/cooldown/rate/gap/quiet/busy/shadow/ok
    ('confidence', 'INTEGER DEFAULT 0'),  # 模型自评 0~9
    ('think', "TEXT DEFAULT ''"),         # 「想」：只进库里给页面看，**绝不朗读**
    ('callsigns', "TEXT DEFAULT ''"),     # 本段抽到的呼号（逗号分隔）
    ('would_reply', 'INTEGER DEFAULT 0'), # 若放行会不会发射（影子期的核心指标）
    ('dry', 'INTEGER DEFAULT 0'),         # 1 = 影子记录，本身没有发射动作
)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _f(v, d=0.0):
    try:
        if v is None or v == '':
            return d
        return float(v)
    except Exception:
        return d


def _flag(v, d=False):
    if v is None:
        return d
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on', 'y', 't')


def _now_iso():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _takes_kw(fn, name):
    """fn 是否接受名为 name 的关键字参数（旧签名/测试替身返回 False）。"""
    if fn is None:
        return False
    try:
        return name in inspect.signature(fn).parameters
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 唤醒词匹配
# ---------------------------------------------------------------------------
# ASR 对同音字经常选错（实测「中继台」会出「中继太」）。这里只给**唤醒词用字**
# 开放同音集合，不做通用纠错——通用纠错会显著抬高误触发率。
# 只给**唤醒词用字**开放同音集合，不做通用纠错——通用纠错会显著抬高误触发率。
# 「机」是实测命中的：真实空口录音里「中继台」被识别成「中机台」，
# 而原来的集合里没有 jī 的常用字，唤醒直接落空。
_HOMOPHONE = {
    '台': '台太抬臺苔态泰胎',
    '太': '台太抬臺苔态泰胎',
    '智': '智志治至知制直只纸质置',
    '志': '智志治至知制直只纸',
    '继': '继记纪计技济机基击急即集几己寂寄系',
    '记': '继记纪计技济机基击急即集几己寂寄',
    '计': '继记纪计技济机基击急即集几己寂寄',
    '中': '中钟忠终肿种仲',
    '钟': '中钟忠终肿种仲',
    '能': '能嫩恁',
    '香': '香想相乡箱翔响享湘向像',
    '想': '香想相乡箱翔响享湘向像',
}

# 「本台名」的容错表：在唤醒词同音表的基础上，补上真实空口里**观测到**的那些变形。
# 与 _HOMOPHONE 分开维护是刻意的 —— 唤醒表一动，唤醒的误触发率就跟着变（唤醒成功
# 就会发射），而这张表只用于「有没有点名本台」的前置判断，两者风险量级不同。
# 数据来源：2026-09-28~29 影子期真实听文（中季台/中器台/中戏台/空气台/器台/中气台…）。
_ADDR_EXTRA = {'继': '季器戏气汽齐其', '记': '季器戏气汽齐其', '计': '季器戏气汽齐其',
               '中': '空冲充', '钟': '空冲充'}
_ADDR_HOMOPHONE = dict(_HOMOPHONE)
for _k, _v in _ADDR_EXTRA.items():
    _ADDR_HOMOPHONE[_k] = _HOMOPHONE.get(_k, _k) + _v

# 匹配前丢弃的标点/空白：ASR 可能给出任意断句，不能因此漏唤醒
_SKIP_CHARS = set(' \t\n\r，。！？、；：,.!?;:""\'\'“”‘’《》()（）[]【】{}<>·—－-…')


def _compact(text):
    """去掉标点空白并返回 (紧凑串, 每个字符在原文中的下标)。"""
    chars, idx = [], []
    for i, ch in enumerate(text or ''):
        if ch.isspace() or ch in _SKIP_CHARS:
            continue
        chars.append(ch)
        idx.append(i)
    return ''.join(chars), idx


# 唤醒词前后的标点拼接后会留下「，，」这类重复，统一折叠
_DUP_PUNC_RE = re.compile(r'([，。！？、；：,.!?;:])\1+')


def _wake_regex(word, fuzzy=True):
    if not word:
        return None
    parts = []
    for ch in str(word):
        if fuzzy and ch in _HOMOPHONE:
            parts.append('[' + re.escape(_HOMOPHONE[ch]) + ']')
        else:
            parts.append(re.escape(ch))
    try:
        return re.compile(''.join(parts))
    except Exception:
        return None


def _wake_variants(word, loose=False):
    """唤醒词的候选写法：原词（+ 宽松模式下各去掉一个字）。

    ASR **漏字**是实测最常见的失败（「智能中继」→「智能继」、「中继台」→「继台」）。
    但漏字变体会让短词变得极易误触发，所以只对 ≥3 字的词开放，且默认关闭
    （`assist_wake_loose`）。
    """
    out = [word]
    if loose and len(word) >= 3:
        for i in range(len(word)):
            v = word[:i] + word[i + 1:]
            if len(v) >= 2 and v not in out:
                out.append(v)
    return out


def match_wake(text, words, fuzzy=True, loose=False):
    """在识别文本里找唤醒词。

    返回 (配置里的唤醒词, 实际命中的原文片段, 剥掉唤醒词后剩余的问题文本)。
    未命中返回 ('', '', '')。
    """
    text = text or ''
    if not text.strip():
        return '', '', ''
    comp, idx = _compact(text)
    if not comp:
        return '', '', ''
    for w in words:
        for cand in _wake_variants(w, loose):
            rx = _wake_regex(cand, fuzzy)
            if rx is None:
                continue
            m = rx.search(comp)
            if not m:
                continue
            a, b = m.start(), m.end() - 1
            if a >= len(idx) or b >= len(idx):
                continue
            oa, ob = idx[a], idx[b]
            rest = (text[:oa] + text[ob + 1:]).strip(' \t，。！？、；：,.!?;:""\'\'（）()')
            rest = _DUP_PUNC_RE.sub(r'\1', rest)
            # 命中：返回**配置里的词**（不是变体），便于日志里对照
            return w, text[oa:ob + 1], rest
    return '', '', ''


def wake_near_miss(text, words, fuzzy=True, threshold=0.6):
    """没命中时给出「最像哪个唤醒词、相似度多少」——只做诊断，不参与判定。

    唤醒不上时最需要回答的问题是「到底差在哪」：是 ASR 完全没听出来，还是听成了
    近音字。这里用序列相似度给个数量级，帮助判断该加同音字还是该调电平。
    """
    comp, _idx = _compact(text or '')
    if not comp:
        return '', 0.0
    best, best_r = '', 0.0
    for w in (words or []):
        if not w:
            continue
        n = len(w)
        for size in {n, n + 1, n - 1, n + 2}:
            if size <= 0:
                continue
            for i in range(0, max(1, len(comp) - size + 1)):
                seg = comp[i:i + size]
                if not seg:
                    continue
                r = difflib.SequenceMatcher(None, seg, w).ratio()
                if r > best_r:
                    best_r, best = r, w
    return (best, round(best_r, 2)) if best_r >= threshold else ('', round(best_r, 2))


# ---------------------------------------------------------------------------
# 自主回答：决策层（阶段一 = 影子模式）
#
# 目标：助手听到一段话后**自己判断**该不该答，而不是只认唤醒词。
#
# 两条设计原则（都是板端实测逼出来的）：
#   1. **红线在代码里，模型无权突破**。信道忙、禁发时段、频率上限、呼号冷却这些
#      一律在 auto_gate() 里判定；模型只回答「这段话值不值得答」。
#   2. **模型输出必须结构化且 fail-closed**。1.5B 会照抄示例、会答非所据（实测约
#      1/3），所以让它在**最末**输出四行固定格式，解析不出来就一律判「默」。
#      「想」只进日志与页面，**由代码剥离、绝不进 TTS**（不靠模型自觉）。
# ---------------------------------------------------------------------------
AUTO_MODES = ('shadow', 'half', 'full')
# **阶段一只开放影子模式**：half/full 的判定与门闸代码都写好了，但这里不放行。
# 要开放必须同时改这里与前端选项 —— 不允许「设置里改一个字符串就放开发射」。
AUTO_MODES_OPEN = ('shadow',)

AUTO_REASONS = ('被点名', '直接提问', '呼叫本台', '闲聊', '与本站无关',
                '正在通联', '听不清', '重复', '数据音', '求助', '其它')
AUTO_REASON_CODE = {'被点名': 'called', '直接提问': 'question', '呼叫本台': 'cq',
                    '闲聊': 'chat', '与本站无关': 'unrelated', '正在通联': 'ongoing',
                    '听不清': 'unclear', '重复': 'duplicate', '数据音': 'data',
                    '求助': 'help', '其它': 'other'}
# 判「答」可接受的理由码：其余（与本台无关/正在通联/听不清/数据音…）都判「默」
AUTO_ANSWER_REASONS = ('called', 'question', 'cq', 'chat', 'help')
AUTO_REASON_LABEL = {v: k for k, v in AUTO_REASON_CODE.items()}

# 决策轮的系统提示：**只有角色，没有任何人设/格式装饰**。输出格式留给用户消息的
# 最后一段（板端 1.5B 只认最后一条指令），系统提示里再写一遍反而会被它当成范例照抄。
AUTO_DECISION_SYS = (
    '你在守听业余无线电中继台，负责判断刚听到的一段话要不要本台回答。\n'
    '严格按用户消息要求的四行格式输出，不要解释、不要多余内容、不要复述示例。'
)

# 闸门结论码：ok=放行；其余都是「被谁拦下」，会写进记录与计数器
AUTO_BLOCK_LABEL = {
    'silent': '判定为默',
    'reason': '答的理由码不可接受',
    'noaddr': '听文里没有点名本台',
    'whitelist': '呼号不在白名单',
    'cooldown': '同呼号冷却中',
    'rate': '本小时已达上限',
    'gap': '距上次发射太近',
    'quiet': '禁发时段',
    'test_mode': '全局测试模式',
    'busy': '信道忙',
    'shadow': '影子模式（阶段一：只记录不发射）',
    'locked': '该模式尚未开放',
}


def auto_mode(st):
    v = str((st or {}).get('assist_auto_mode') or 'shadow').strip().lower()
    return v if v in AUTO_MODES else 'shadow'


def compose_decision_prompt(text, ctx=None):
    """拼决策轮的提示词：短、结构固定、**指令放最末**（板端只理最后一条）。

    ctx: {'last': [('对方', '…'), ('我', '…')], 'called': bool, 'callsign': str,
          'since': 秒, 'whitelist': str, 'think_chars': int}
    """
    ctx = ctx or {}
    body = re.sub(r'\s+', ' ', str(text or '')).strip()[:200]
    lines = ['【这段听到的】' + (body or '（无）')]
    last = ctx.get('last') or []
    if last:
        lines.append('【最近】' + ' / '.join(
            '%s：%s' % (who, re.sub(r'\s+', ' ', str(what or ''))[:60])
            for who, what in last[:4]))
    lines.append('【状态】点名：%s　呼号：%s　距上次回答：%d 秒　白名单：%s'
                 % ('是' if ctx.get('called') else '否',
                    ctx.get('callsign') or '无',
                    int(ctx.get('since') or 0),
                    (ctx.get('whitelist') or '').strip() or '不限'))
    n = max(8, min(60, int(ctx.get('think_chars') or 30)))
    # 判答规则单独一段、并且紧挨着输出格式：板端 1.5B 实测**只理最后几条**。
    # 初版把「点名：是」只写在状态行里，结果它对着一句明确点名的提问答
    # 「由：与本站无关」—— 状态行的信息它基本没用上，必须写成规则。
    # 「含 CQ」是实测补的：写「呼叫本台」时，模型把 CQ 判成「通用呼叫、未点名本台」
    # 而答默 —— 对一台守着中继的助手来说，CQ 就是「有人想通联」，应当接。
    lines.append('【判答规则】被点名、直接向本台提问、呼叫本台（含 CQ 呼叫与直接报本台'
                 '呼号）→ 判答；与本站或中继台有关的求助与闲聊也判答；'
                 '明确是其他友台之间与本站无关的内容、听不清、纯数据音或报数 → 判默。')
    lines.append('【输出要求（必须遵守）】')
    lines.append('第一行只写 想：不超过%d个字的判断依据' % n)
    lines.append('第二行只写 判：答 或 默')
    lines.append('第三行只写 由：' + '|'.join(AUTO_REASONS))
    lines.append('第四行只写 信：0~9')
    return '\n'.join(lines)[:600]


def parse_decision(raw, max_think=30):
    """解析模型的四行输出 → dict。**解析不出来一律判「默」**（fail-closed）。

    返回 {'decision','reason','confidence','think','ok','raw_reason'}
      decision: 'answer' / 'silent'
      reason:   闸门/记录用的结论码（silent/reason 之外还有模型给的理由码）
    """
    text = str(raw or '')
    out = {'decision': 'silent', 'reason': 'other', 'confidence': 0,
           'think': '', 'ok': False, 'raw_reason': ''}

    def grab(names):
        """按 `字段：值` 取值。**先按行首锚定取，取不到再全串找**。

        两级是必要的：1.5B 有时规规矩矩一行一个字段，有时把四行糊成一行。
        只锚行首 → 糊成一行的解析不出来；只全串找 → 正文里的「想」会被当成字段名。
        """
        for nm in names:
            for pat in (r'(?:^|\n)\s*%s\s*[:：]\s*([^\n]*)' % nm,
                        r'%s\s*[:：]\s*([^\n]*)' % nm,
                        r'(?:^|\n)\s*%s\s+([^\n]*)' % nm):
                m = re.search(pat, text)
                if m:
                    return m.group(1).strip()
        return ''

    think = grab(['想'])
    judge = grab(['判'])
    reason_cn = grab(['由', '理由'])
    conf = grab(['信', '置信'])

    if think:
        out['think'] = think[:max(1, int(max_think or 30))]
    m = re.search(r'(\d{1,2})', conf or '')
    if m:
        out['confidence'] = max(0, min(9, int(m.group(1))))
    out['raw_reason'] = reason_cn

    # 判定：认「答/answer/yes/是」，认「默/silent/no」；其它一律默。
    # 用**前缀**而不是全等：实测 1.5B 很容易写成「答：因为对方在提问」，
    # 全等匹配会把这种本来正确的输出判成解析失败 → 全部判默，影子期就白跑了。
    v = re.sub(r'[^\w\u4e00-\u9fff]', '', judge or '').lower()
    if v.startswith('答') or v in ('answer', 'yes', '是'):
        out['decision'] = 'answer'
    elif v.startswith('默') or v in ('silent', 'no', '否', '沉默'):
        out['decision'] = 'silent'
    else:
        out['reason'] = 'other'
        return out

    # 理由同样容错：只要行里**出现**闭集里的词就算（模型爱在后面补解释）
    code = AUTO_REASON_CODE.get(reason_cn.strip(), '')
    if not code:
        for label in AUTO_REASONS:
            if label in (reason_cn or ''):
                code = AUTO_REASON_CODE[label]
                break
    if not code:
        # 理由写了但不在闭集里：判「默」——理由都不按格式给，行为更不可信
        out['decision'] = 'silent'
        out['reason'] = 'other'
        return out
    out['reason'] = code
    if out['decision'] == 'answer' and code not in AUTO_ANSWER_REASONS:
        # 「答」却给了「与本站无关/听不清」这类理由：自相矛盾，降级为默
        out['decision'] = 'silent'
        out['reason'] = 'reason'
        out['ok'] = False
        return out
    out['ok'] = True
    return out


def auto_gate(decision, reason, mode='shadow', callsign='', whitelist='',
              min_gap=90, max_per_hour=6, cooldown=600,
              hits=(), call_ts=0.0, last_tx=0.0, now=0.0,
              quiet=False, test_mode=False, busy=False, addressed=True):
    """闸门：返回 (allowed, code, 说明)。**纯函数**，红线全在这里，模型无权绕过。

    顺序是刻意的：先判「要不要答」，再判内容/频率红线，**影子锁最后** ——
    这样影子期还能看出「除了影子这一条，其它闸门会不会放行」（would_reply）。
    `addressed` 由调用方用 auto_addressed() 算好传进来（保持本函数是纯函数）。
    """
    if decision != 'answer':
        return (False, 'silent', AUTO_BLOCK_LABEL['silent'])
    if reason not in AUTO_ANSWER_REASONS:
        return (False, 'reason', AUTO_BLOCK_LABEL['reason'])
    if not addressed:
        # 内容前置：听文里没出现本台名/本台呼号 → 不认为在跟我们说话。
        # 影子期 26 条拟发射里约一半是旁人互相通联（"还有谁会上台呀"、"Breaking breaking"），
        # 模型分不清"在问旁边的朋友"还是"在问本台"，而发射出去就收不回来。
        return (False, 'noaddr', AUTO_BLOCK_LABEL['noaddr'])
    wl = [x.strip().upper() for x in re.split(r'[,;、\s]+', whitelist or '') if x.strip()]
    cs = (callsign or '').strip().upper()
    if wl and cs not in wl:
        return (False, 'whitelist', '%s，本次呼号 %s'
                % (AUTO_BLOCK_LABEL['whitelist'], cs or '（未识别）'))
    if cs and call_ts and (now - call_ts) < cooldown:
        return (False, 'cooldown', '%s（%s，还需 %.0f 秒）'
                % (AUTO_BLOCK_LABEL['cooldown'], cs, cooldown - (now - call_ts)))
    hour_hits = [t for t in hits if t and (now - t) < 3600]
    if len(hour_hits) >= max_per_hour:
        return (False, 'rate', '%s（%d 次/小时）'
                % (AUTO_BLOCK_LABEL['rate'], max_per_hour))
    if last_tx and (now - last_tx) < max(min_gap, 0):
        return (False, 'gap', '%s（还需 %.0f 秒）'
                % (AUTO_BLOCK_LABEL['gap'], min_gap - (now - last_tx)))
    if quiet:
        return (False, 'quiet', AUTO_BLOCK_LABEL['quiet'])
    if test_mode:
        return (False, 'test_mode', AUTO_BLOCK_LABEL['test_mode'])
    if busy:
        return (False, 'busy', AUTO_BLOCK_LABEL['busy'])
    if mode == 'shadow':
        return (False, 'shadow', AUTO_BLOCK_LABEL['shadow'])
    if mode not in AUTO_MODES_OPEN:
        # 阶段未开放的模式：挡死。_auto_try 那一层已经提前返回、根本走不到这里，
        # 这一条是给「有人直接改库把 mode 写成 full」留的兜底。
        return (False, 'locked', AUTO_BLOCK_LABEL['locked'])
    return (True, 'ok', '')


def _norm_text(s):
    """归一化：只留汉字/字母/数字，用于回声比对与长度判断。"""
    return re.sub(r'[^\w\u4e00-\u9fff]+', '', str(s or ''), flags=re.UNICODE)


def auto_echo(text, own):
    """自己刚发射的内容又被收进来（自激/回声）→ 不能再答一遍。

    这是「不重复自己」那道红线的实现：板端发射余波保护只有几百毫秒，而实际上
    自发自收在同一台设备上很容易被电平门限重新切开，一旦回声进决策层，助手就会
    自问自答无限循环。宁可漏判一次「对方正好说了同样的话」。
    """
    a = _norm_text(text)
    if len(a) < 4:
        return False
    for o in (own or ()):
        b = _norm_text(o)
        if len(b) < 4:
            continue
        if a == b or a in b or b in a:
            return True
        if difflib.SequenceMatcher(None, a, b).ratio() >= 0.75:
            return True
    return False


def auto_prefilter(text, own=()):
    """廉价预筛：返回 (是否值得叫模型, 原因码)。纯函数，不起 LLM。

    板端 LLM 一轮决策要好几秒，而工作线程是**串行**的：每段都叫一次模型，
    助手就会在思考期间听不见信道。所以先用零成本的规则滤掉明显不值得判的段。
    """
    t = str(text or '').strip()
    core = _norm_text(t)
    if len(core) < 3:
        return False, 'short'
    if not re.search(r'[\u4e00-\u9fffA-Za-z]', core):
        return False, 'nonspeech'
    if own and auto_echo(t, own):
        return False, 'echo'
    return True, ''


def auto_called(text, wake_words=(), told=(), fuzzy=True):
    """这段是不是在叫我们（点名 / 呼叫本台）。

    只看两类证据，不看模型：
      * 唤醒词（用宽松变体再扫一遍 —— 主匹配已经把标准写法过了一遍）；
      * 「自己人呼号」出现在文本里（白名单 + 语音日志那份本台呼号）。
    """
    t = str(text or '')
    if not t.strip():
        return False
    for w in (wake_words or ()):
        if not w:
            continue
        for cand in _wake_variants(w, True):
            rx = _wake_regex(cand, fuzzy)
            if rx is not None and rx.search(t if fuzzy else _compact(t)[0]):
                return True
    up = _norm_text(t).upper()
    for c in (told or ()):
        c = _norm_text(c).upper()
        if len(c) >= 4 and c in up:
            return True
    return False


def _addr_regex(word):
    """按「本台名容错表」给一个词生成正则（与 _wake_regex 同构，但同音表更宽）。"""
    parts = []
    for ch in str(word):
        if ch in _ADDR_HOMOPHONE:
            parts.append('[' + re.escape(_ADDR_HOMOPHONE[ch]) + ']')
        else:
            parts.append(re.escape(ch))
    try:
        return re.compile(''.join(parts))
    except Exception:
        return None


def auto_addressed(text, wake_words=(), own=()):
    """这段听文里是否**明确点名本台**（本台名，含实测变形；或本台呼号）。

    为什么单独立一条：自主层的判答规则写的是「直接提问 / 闲聊 / 求助」，模型分不清
    「在问旁边的朋友」和「在问本台」。影子期 26 条拟发射里约一半属于前者
    （"除了我跟你还有谁会上台呀"、"Breaking, breaking"、"你念我的呼号他能识别"），
    而发射出去就收不回来 —— 所以给发射加一道与模型无关的内容前置。
    与 auto_called 的区别：这里只认**本台名/本台呼号**，把"自己人呼号"也算作证据
    （别人报本台呼号时，我们在不在被叫之列由呼号白名单那道闸门再决定）。
    返回 (bool, 证据说明)。
    """
    t = str(text or '')
    if not t.strip():
        return False, '空文本'
    for w in (wake_words or ()):
        if not w:
            continue
        for cand in _wake_variants(w, True):
            rx = _addr_regex(cand)
            if rx is not None and rx.search(t):
                return True, '本台名「%s」' % cand
    up = _norm_text(t).upper()
    for c in (own or ()):
        c = _norm_text(c).upper()
        if len(c) >= 4 and c in up:
            return True, '本台呼号 %s' % c
    return False, '没听到本台名或本台呼号'


def auto_callsigns(text, whitelist=''):
    """抽取文本里的呼号（含 ICAO 字母解释法），并用白名单纠错。

    复用语音日志那套实现（`voice_service.extract_callsigns` / `correct_callsigns`），
    两边标准一致；懒加载避免服务启动时就拖入 ASR 侧的重依赖。
    """
    t = str(text or '')
    if not t.strip():
        return []
    try:
        from voice_service import extract_callsigns, correct_callsigns
        raw = extract_callsigns(t)
        if not raw:
            return []
        wl = [x for x in re.split(r'[,;\s]+', whitelist or '') if x]
        calls, _fixes = correct_callsigns(raw, wl, 0)
        return calls
    except Exception:
        return []


def clamp_reply(text, limit):
    """把回复裁到 limit 字以内，尽量在句末/逗号处断开。返回 (文本, 是否被截断)。"""
    from tts_service import clean_for_tts
    s = clean_for_tts(text)
    if not s:
        return '', False
    limit = int(limit or 0)
    if limit <= 0 or len(s) <= limit:
        return s, False
    cut = s[:limit]
    best = max((i for i, c in enumerate(cut) if c in '。！？；.!?;'), default=-1)
    if best >= int(limit * 0.4):
        return cut[:best + 1], True
    best = max((i for i, c in enumerate(cut) if c in '，,、'), default=-1)
    if best >= int(limit * 0.6):
        return cut[:best + 1], True
    return cut, True


def in_quiet_hours(spec, now=None):
    """spec 形如 '23:00-07:00'（支持逗号分隔多段）。跨零点自动处理。"""
    spec = (spec or '').strip()
    if not spec:
        return False
    t = now or datetime.now()
    cur = t.hour * 60 + t.minute
    for piece in re.split(r'[,;、]', spec):
        piece = piece.strip()
        m = re.match(r'^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$', piece)
        if not m:
            continue
        a = int(m.group(1)) * 60 + int(m.group(2))
        b = int(m.group(3)) * 60 + int(m.group(4))
        if a == b:
            continue
        if a < b:
            if a <= cur < b:
                return True
        else:                       # 跨零点
            if cur >= a or cur < b:
                return True
    return False


# ---------------------------------------------------------------------------
# silero VAD：全局单例（复用 voice_service 的封装与模型缓存）
# ---------------------------------------------------------------------------
_VAD_LOCK = threading.Lock()
_VAD = None


def _get_vad():
    """懒加载 VAD；加载失败返回 None（调用方退回能量边界，不报错）。"""
    global _VAD
    with _VAD_LOCK:
        if _VAD is None:
            try:
                import voice_service
                _VAD = voice_service.Vad()
                print('%s VAD 已挂载（复用 voice_service 封装）' % LOG, flush=True)
            except Exception as e:
                print('%s VAD 不可用，退回能量边界：%s' % (LOG, e), flush=True)
                _VAD = False
        return _VAD or None


# ---------------------------------------------------------------------------
# 存储（只存「真实答过的轮次」；未命中的实况文本只留在内存里供页面观察）
# ---------------------------------------------------------------------------
class Store:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self.init()

    def _conn(self):
        c = getattr(self._local, 'conn', None)
        if c is None:
            c = sqlite3.connect(self.db_path, timeout=20.0)
            c.row_factory = sqlite3.Row
            try:
                c.execute('PRAGMA journal_mode=WAL')
            except Exception:
                pass
            self._local.conn = c
        return c

    def init(self):
        c = self._conn()
        c.executescript(SCHEMA)
        self._migrate(c)
        c.commit()

    @staticmethod
    def _migrate(c):
        """增量补列（幂等）。老库缺哪列补哪列，已有数据一行不动。"""
        try:
            have = {str(r[1]) for r in c.execute(
                'PRAGMA table_info(assist_turns)').fetchall()}
        except Exception as e:
            print('%s 读取表结构失败：%s' % (LOG, e), flush=True)
            return
        for name, decl in AUTO_COLUMNS:
            if name in have:
                continue
            try:
                c.execute('ALTER TABLE assist_turns ADD COLUMN %s %s' % (name, decl))
                print('%s 迁移：assist_turns 增加列 %s' % (LOG, name), flush=True)
            except Exception as e:
                print('%s 迁移列 %s 失败：%s' % (LOG, name, e), flush=True)

    def exec(self, sql, args=()):
        c = self._conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur

    def query(self, sql, args=()):
        return [dict(r) for r in self._conn().execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self._conn().execute(sql, args).fetchone()
        return dict(r) if r else None


# ---------------------------------------------------------------------------
# 服务主体
# ---------------------------------------------------------------------------
class AssistantService:
    def __init__(self, db_path):
        self.store = Store(db_path)
        self.lock = threading.RLock()
        self.q = queue.Queue(maxsize=8)
        self.recent = deque(maxlen=80)          # 实况识别流（含未命中唤醒词）
        self.levels = deque(maxlen=260)         # 电平曲线（约 20 秒）
        self.history = deque(maxlen=20)         # 多轮上下文
        self.events = deque(maxlen=200)
        self.counters = {
            'segments': 0, 'asr_empty': 0, 'wakes': 0, 'ignored': 0,
            'turns': 0, 'tx': 0, 'tx_seconds': 0.0, 'busy_defers': 0,
            'gap_waits': 0, 'truncated': 0, 'errors': 0, 'aborted': 0,
            'quiet_blocked': 0, 'test_turns': 0,
            # 自主回答（阶段一影子模式）——这几个计数是验收影子期的依据
            'auto_decided': 0,      # 真的叫了决策模型的段数
            'auto_skipped': 0,      # 预筛掉、没叫模型的段数
            'auto_answered': 0,     # 模型判「答」
            'auto_silent': 0,       # 模型判「默」/解析失败
            'auto_parse_fail': 0,   # 四行格式没解析出来（fail-closed → 默）
            'auto_shadow_blocked': 0,   # 判答但被影子锁拦下（阶段一恒等于判答数）
            'auto_rate_limited': 0,
            'auto_cooldown': 0,
            'auto_gap_blocked': 0,
            'auto_whitelist_blocked': 0,
            'auto_echo_skipped': 0,
            # 事后审计用：决策调用失败（fail-closed 判默）与「没点名本台」各数各的。
            # 前者此前只留在 assist_turns.reason='error' 里，页面看不见（问题 6）。
            'auto_error': 0,
            'auto_noaddr': 0,
        }
        # 自主回答的频率状态：发射时刻环 + 呼号冷却表 + 自己刚说过的话
        self.auto_hits = deque(maxlen=200)
        self.auto_call_ts = {}
        self.auto_last_ts = 0.0
        self.auto_last = {}
        self.tx_texts = deque(maxlen=8)
        self.auto_dry_running = False
        self.stage = 'off'
        self.stage_since = time.time()
        self.stage_detail = ''
        self.follow_until = 0.0
        self.last_tx = 0.0
        self.tx_until = 0.0
        # 最后一次观测到 PTT 有效的时刻：余波保护从这里起算，
        # 绝不能从「当前时刻」起算（那会导致保护期无限续期）。
        self.tx_last_ts = 0.0
        self.stop_flag = False
        self.last_error = ''
        self.asr_last = {}
        self.llm_warm = {'ok': None, 'ts': 0.0, 'msg': '未探测'}
        self.started_at = time.time()
        self._threads_started = False
        self.settings_cache = {}
        self.settings_ts = 0.0
        # 依赖注入
        self._setting_getter = None
        self.busy_getter = lambda: False
        self.tx_getter = lambda: False
        self.ask_fn = None
        # 决策层专用的「一次纯文本调用」：不吃工具、不吃人设规范、不做总结轮。
        # 决策必须短平快且可复现，走 Agent 那条路会被工具协议和总结轮改写（实测
        # 总结轮会把「判：答」这种结构化输出重写成一段人话，解析必然失败）。
        self.ask_raw_fn = None
        self.tts_fn = None
        self.play_fn = None
        self.stop_play_fn = lambda: None
        self.base_prompt_fn = lambda: ''
        self.expand_fn = lambda t: t
        # 分段状态
        self.seg = None
        self.pre = deque()
        self.pre_bytes = 0
        self.last_dbfs = -120.0
        self._level_ts = 0.0
        self._last_heard = ''
        self._last_heard_ts = 0.0
        self._warned = ''

    # -- 配置 / 依赖注入 ---------------------------------------------------
    def configure(self, setting_getter, busy_getter, tx_getter, ask_fn, tts_fn,
                  play_fn, base_prompt_fn, stop_play_fn=None, expand_fn=None,
                  ask_raw_fn=None):
        self._setting_getter = setting_getter
        self.busy_getter = busy_getter or (lambda: False)
        self.tx_getter = tx_getter or (lambda: False)
        self.ask_fn = ask_fn
        self.ask_raw_fn = ask_raw_fn
        self.tts_fn = tts_fn
        self.play_fn = play_fn
        self.stop_play_fn = stop_play_fn or (lambda: None)
        self.base_prompt_fn = base_prompt_fn or (lambda: '')
        self.expand_fn = expand_fn or (lambda t: t)
        # ask_fn 要不要收 sysprompt=：测试替身用的是旧签名，硬传会 TypeError
        self._ask_takes_sysprompt = _takes_kw(ask_fn, 'sysprompt')

    def settings(self, force=False):
        now = time.time()
        with self.lock:
            if not force and self.settings_cache and (now - self.settings_ts) < 4.0:
                return self.settings_cache
        st = dict(DEFAULTS)
        try:
            if self._setting_getter:
                rows = self._setting_getter()
                if isinstance(rows, dict):
                    st.update({k: v for k, v in rows.items() if v is not None})
        except Exception:
            pass
        with self.lock:
            self.settings_cache = st
            self.settings_ts = now
        return st

    def invalidate(self):
        with self.lock:
            self.settings_cache = {}
            self.settings_ts = 0.0

    def enabled(self):
        return _flag(self.settings().get('assist_enabled'), False)

    def wake_words(self, st=None):
        st = st or self.settings()
        raw = st.get('assist_wake_words') or ''
        out = [w.strip() for w in re.split(r'[,;、\s]+', raw) if w.strip()]
        return out[:8]

    def wake_mode(self, st=None):
        """唤醒方式：level（电平分段，现状）/ busy（BUSY 触发 + 唤醒词）。

        busy 模式下**电平触发完全关闭**：只有载波有效时才算「检测到语音」，也才会
        开段送 ASR；唤醒与否再由唤醒词决定（两个条件都要满足）。
        """
        st = st or self.settings()
        v = str(st.get('assist_wake_mode') or 'level').strip().lower()
        return v if v in WAKE_MODES else 'level'

    @staticmethod
    def busy_gate(mode, busy_seg):
        """busy 模式下「这一段该不该处理」的判定；返回空串表示放行。

        抽成独立函数是为了**不用 ASR 也能自测**（处理链路本身依赖识别模型，
        板端才有）。判定规则：busy 模式下没有载波 → 整段丢弃，不唤醒、不追问。
        """
        if mode == 'busy' and not busy_seg:
            return 'BUSY 未触发，整段丢弃（BUSY 唤醒模式）'
        return ''

    def max_chars(self, st=None):
        st = st or self.settings()
        return max(10, int(_f(st.get('assist_max_reply_chars'), 80)))

    def hist_turns(self, st=None):
        st = st or self.settings()
        return max(0, min(12, int(_f(st.get('assist_history_turns'), 6))))

    # -- 生命周期 ----------------------------------------------------------
    def start(self):
        if self._threads_started:
            return
        self._threads_started = True
        for fn, name in ((self._worker, 'assist-worker'),
                         (self._maintenance, 'assist-maint')):
            t = threading.Thread(target=fn, name=name, daemon=True)
            t.start()
        print('%s 服务已启动（工作目录 %s）' % (LOG, WORK_DIR), flush=True)

    def _maintenance(self):
        time.sleep(12)
        while True:
            try:
                st = self.settings()
                if self.enabled() and _flag(st.get('assist_keep_llm_warm'), True):
                    # 语音助手不能等 20~40 秒冷启动：启用期间保持 LLM 常驻
                    if time.time() - float(self.llm_warm.get('ts') or 0) > 60:
                        self._warm_llm()
                self._cleanup()
            except Exception as e:
                print('%s 维护线程异常：%s: %s' % (LOG, type(e).__name__, e), flush=True)
            time.sleep(30)

    def _warm_llm(self):
        ok, msg = None, ''
        try:
            import voice_service
            # 注意：voice_service.llm_start() 返回 **bool**；
            # 返回 (ok, msg) 元组的是 VoiceService.ensure_llm_ready()，别搞混。
            wait = float(_f(self.settings().get('assist_llm_wait'), 25))
            ok = bool(voice_service.llm_start(wait=wait))
            msg = '' if ok else '本地 LLM 启动/等待就绪超时（%.0fs）' % wait
        except Exception as e:
            ok, msg = False, '%s: %s' % (type(e).__name__, e)
        self.llm_warm = {'ok': bool(ok), 'ts': time.time(), 'msg': str(msg or '')[:200]}
        if not ok:
            self.last_error = '本地 LLM 未就绪：%s' % self.llm_warm['msg']
        return bool(ok)

    def _cleanup(self):
        st = self.settings()
        days = max(1, int(_f(st.get('assist_retention_days'), 30)))
        cutoff = time.time() - days * 86400
        if not WORK_DIR.exists():
            return 0
        removed = 0
        for day in sorted(WORK_DIR.iterdir()):
            if not day.is_dir():
                continue
            try:
                if datetime.strptime(day.name, '%Y-%m-%d').timestamp() < cutoff:
                    for f in day.iterdir():
                        try:
                            f.unlink()
                        except Exception:
                            pass
                    day.rmdir()
                    removed += 1
            except Exception:
                continue
        if removed:
            print('%s 清理 %d 天前的助手录音' % (LOG, removed), flush=True)
        return removed

    # -- 采集入口（由 app.py 的 _mic_capture_loop 调用）--------------------
    def feed(self, raw_stereo, ts=None):
        if not self.enabled():
            if self.stage != 'off':
                self._set_stage('off')
            return
        ts = ts or time.time()
        st = self.settings()
        try:
            mono = self._pick(raw_stereo, st.get('assist_channel', 'left'))
        except Exception:
            return
        if not mono:
            return
        x = np.frombuffer(mono, dtype=np.int16).astype(np.float32) / 32768.0
        if x.size == 0:
            return
        rms = float(np.sqrt((x * x).mean()))
        dbfs = 20.0 * math.log10(max(rms, 1e-6))
        self.last_dbfs = dbfs
        now = time.time()
        if now - self._level_ts >= 0.08:
            self._level_ts = now
            self.levels.append([round(now, 2), round(dbfs, 1)])
        try:
            with self.lock:
                self._segment(x, mono, ts, dbfs, st)
        except Exception as e:
            self.last_error = '%s: %s' % (type(e).__name__, e)

    @staticmethod
    def _pick(raw, channel):
        """从 16k/立体声 S16_LE 里取指定声道，返回单声道 bytes。"""
        usable = len(raw) - (len(raw) % 4)
        if usable <= 0:
            return b''
        raw = raw[:usable]
        if channel == 'mix':
            a = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).astype(np.int32)
            return ((a[:, 0] + a[:, 1]) // 2).astype(np.int16).tobytes()
        idx = 0 if channel != 'right' else 1
        a = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)[:, idx]
        return np.ascontiguousarray(a).tobytes()

    def _segment(self, x, mono, ts, dbfs, st):
        """能量迟滞分段：够响就开段，静音够久就收段。"""
        # 自己发射期间及其余波：不收音（否则自己的声音会被当成对方说话 → 自激）。
        # 余波保护从**最后一次观测到 PTT 有效**起算。曾经写成
        #   self.tx_until = max(self.tx_until, ts + guard)
        # 它是「当前时刻 + 0.6s」，而保护期内每个采集块都会执行一次，
        # 于是截止时间被无限往后推、保护期永不结束 —— 实测表现为助手首发
        # 成功之后再也没收到任何呼叫（连丢三次，语音日志却全部收到）。
        guard = max(0.0, _f(st.get('assist_tx_guard_ms'), 600.0)) / 1000.0
        tx_now = bool(self.tx_getter())
        if tx_now:
            self.tx_last_ts = ts
        if tx_now or (self.tx_last_ts and (ts - self.tx_last_ts) < guard):
            if self.seg is not None:
                self.seg = None
            self.pre.clear()
            self.pre_bytes = 0
            self._set_stage('tx-guard', '发射中/余波保护')
            return

        open_db = _f(st.get('assist_dbfs_open'), -40.0)
        close_db = _f(st.get('assist_dbfs_close'), -46.0)
        if close_db > open_db:                      # 容错：关闭门限必须低于打开门限
            close_db = open_db - 6.0
        preroll_ms = max(0.0, _f(st.get('assist_preroll_ms'), 400.0))
        silence = max(0.15, _f(st.get('assist_silence_ms'), 450.0)) / 1000.0
        min_speech = max(0.1, _f(st.get('assist_min_speech_ms'), 350.0)) / 1000.0
        max_utt = max(2.0, _f(st.get('assist_max_utterance'), 15.0))
        busy_wake = self.wake_mode(st) == 'busy'
        busy_now = bool(self.busy_getter())

        # ------------------------------------------------------------------
        # BUSY 唤醒模式：**电平触发完全关闭**，只有载波才算「检测到语音」。
        #
        # 为什么必须这么硬（用户实测反馈 + 现场原因）：上一版把「电平过门限」也留着
        # 当开段条件（本意是照顾本地调试），结果**没有 BUSY 时说的话照样开段、照样
        # 送 ASR、照样被追问窗口当成一轮对话**。用户的要求很明确：检测到语音的逻辑
        # 就是「BUSY 触发」。所以这里整段逻辑与电平模式分开，两个门限（open/close）
        # 在 busy 模式下**完全不参与**开段与收段。
        # ------------------------------------------------------------------
        if busy_wake:
            if self.seg is None:
                if not busy_now:
                    # 载波没来：只维持 pre-roll 缓冲（开段时补进去，避免吃掉第一个字）
                    self._push_pre(ts, mono, preroll_ms)
                    self._set_stage('idle', '监听中（等 BUSY）')
                    return
                seg = {'start': ts, 'last_voice': ts, 'buf': [], 'n': 0,
                       'pre': list(self.pre), 'busy': True,
                       'peak': dbfs, 'voice_n': 0}
                seg['buf'].append(mono)
                seg['n'] += len(mono)
                seg['voice_n'] += len(mono)     # 载波就是「有声」
                self.seg = seg
                self._set_stage('speech', 'BUSY 触发')
                return

            seg = self.seg
            seg['buf'].append(mono)
            seg['n'] += len(mono)
            if dbfs > seg['peak']:
                seg['peak'] = dbfs
            if busy_now:
                seg['busy'] = True
                seg['last_voice'] = ts
                seg['voice_n'] += len(mono)

            too_long = (ts - seg['start']) >= max_utt
            silent = (ts - seg['last_voice']) >= silence
            if not (too_long or silent):
                return
            self.seg = None
            data = b''.join([m for (_t, m) in seg['pre']] + seg['buf'])
            seconds = len(data) / float(SAMPLE_RATE * FRAME_BYTES)
            voice_seconds = seg['voice_n'] / float(SAMPLE_RATE * FRAME_BYTES)
            if voice_seconds < min_speech or len(data) < int(0.15 * SAMPLE_RATE) * FRAME_BYTES:
                self._set_stage('idle', '载波过短丢弃（%.2fs）' % voice_seconds)
                return
            self.counters['segments'] += 1
            self.counters['busy_segments'] = int(self.counters.get('busy_segments', 0)) + 1
            try:
                self.q.put_nowait({'data': data, 'ts': seg['start'],
                                   'seconds': seconds, 'voice_seconds': voice_seconds,
                                   'dbfs': seg['peak'], 'busy': True})
            except queue.Full:
                self.counters['ignored'] += 1
                try:
                    self.q.get_nowait()
                    self.q.put_nowait({'data': data, 'ts': seg['start'],
                                       'seconds': seconds, 'voice_seconds': voice_seconds,
                                       'dbfs': seg['peak'], 'busy': True})
                except Exception:
                    pass
            return

        # ------------------------- 电平模式（原行为，一字未改）-------------------------
        if self.seg is None:
            if dbfs >= open_db:
                seg = {'start': ts, 'last_voice': ts, 'buf': [], 'n': 0,
                       'pre': list(self.pre), 'busy': busy_now,
                       'peak': dbfs, 'voice_n': 0}
                seg['buf'].append(mono)
                seg['n'] += len(mono)
                if busy_now or dbfs >= close_db:
                    seg['voice_n'] += len(mono)
                self.seg = seg
                self._set_stage('speech', '检测到语音' if not busy_now else 'BUSY 触发')
            else:
                self._push_pre(ts, mono, preroll_ms)
                # 启用后一直没人讲话时，必须把状态机从初始的 'off' 推进到 'idle'，
                # 否则页面一直显示「未启用」，与事实不符（实测踩到）。
                self._set_stage('idle', '监听中')
            return

        seg = self.seg
        seg['buf'].append(mono)
        seg['n'] += len(mono)
        if dbfs > seg['peak']:
            seg['peak'] = dbfs
        if busy_now:
            seg['busy'] = True
        if dbfs >= close_db or busy_now:
            seg['last_voice'] = ts
            seg['voice_n'] += len(mono)

        too_long = (ts - seg['start']) >= max_utt
        silent = (ts - seg['last_voice']) >= silence
        if not (too_long or silent):
            return

        # 收段
        self.seg = None
        self._push_pre(ts, mono, preroll_ms)
        data = b''.join([m for (_t, m) in seg['pre']] + seg['buf'])
        seconds = len(data) / float(SAMPLE_RATE * FRAME_BYTES)
        # 必须用**实际有声时长**判定，不能用缓冲区长度：缓冲区里还含着
        # 0.4s 前置缓冲与 0.45s 收段尾静音，用总长度判会让一个 0.2 秒的
        # 咔哒声凑成 1.05 秒蒙混过关（自测就是这么抓出来的）。
        voice_seconds = seg['voice_n'] / float(SAMPLE_RATE * FRAME_BYTES)
        if voice_seconds < min_speech or len(data) < int(0.15 * SAMPLE_RATE) * FRAME_BYTES:
            self._set_stage('idle', '过短丢弃（有声 %.2fs）' % voice_seconds)
            return
        self.counters['segments'] += 1
        try:
            self.q.put_nowait({'data': data, 'ts': seg['start'],
                               'seconds': seconds, 'voice_seconds': voice_seconds,
                               'dbfs': seg['peak'], 'busy': seg.get('busy', False)})
        except queue.Full:
            self.counters['ignored'] += 1
            self._set_stage('idle', '队列已满，丢弃最旧')
            try:
                self.q.get_nowait()
                self.q.put_nowait({'data': data, 'ts': seg['start'],
                                   'seconds': seconds, 'voice_seconds': voice_seconds,
                                   'dbfs': seg['peak'], 'busy': seg.get('busy', False)})
            except Exception:
                pass

    def _push_pre(self, ts, mono, preroll_ms):
        if preroll_ms <= 0:
            return
        self.pre.append((ts, mono))
        self.pre_bytes += len(mono)
        cap = int(preroll_ms / 1000.0 * SAMPLE_RATE) * FRAME_BYTES
        while self.pre_bytes > cap and self.pre:
            _t, old = self.pre.popleft()
            self.pre_bytes -= len(old)

    # -- 工作线程 ----------------------------------------------------------
    def _worker(self):
        try:
            import os
            os.nice(5)
        except Exception:
            pass
        while True:
            item = self.q.get()
            try:
                if self.enabled():
                    self._handle(item)
            except Exception as e:
                self.counters['errors'] += 1
                self.last_error = '%s: %s' % (type(e).__name__, e)
                print('%s 处理失败：%s' % (LOG, self.last_error), flush=True)
            finally:
                self.q.task_done()

    def _set_stage(self, stage, detail=''):
        with self.lock:
            if stage != self.stage:
                self.stage = stage
                self.stage_since = time.time()
            self.stage_detail = detail or ''

    def _stage_label(self):
        return {
            'off': '未启用', 'idle': '监听中', 'speech': '检测到语音',
            'asr': '识别中', 'think': '思考中', 'synth': '语音合成中',
            'wait': '等待信道', 'tx': '发射中', 'tx-guard': '发射余波保护',
            'followup': '追问窗口', 'error': '异常',
            'auto': '自主判定',
        }.get(self.stage, self.stage)

    # -- 单轮处理 ----------------------------------------------------------
    def _handle(self, item):
        st = self.settings()
        x, sr = self._decode(item['data'])
        if x is None or x.size < int(0.1 * SAMPLE_RATE):
            return
        # 直接调用语音日志的共用识别入口：预处理 → silero VAD 切分 →
        # merge_segments 合并 → SenseVoice。两边同一份实现，不会再漂移。
        # 这里刻意不再自己做 VAD 边界裁剪——实测 silero 报出的首段起点比真实
        # 语音起点晚约 320ms，自己裁会把「中继台」的开头两个字剪掉。
        self._set_stage('asr', '识别中')
        text, asr_ms, err = self._asr_shared(x, sr, st)
        self.asr_last = {'text': text, 'ms': asr_ms, 'ts': time.strftime('%H:%M:%S'),
                         'seconds': item['seconds'], 'error': err}
        rec = {'ts': time.strftime('%H:%M:%S'), 'heard': text, 'wake': '',
               'action': 'ignored', 'error': err, 'asr_ms': asr_ms,
               'seconds': round(item['seconds'], 2), 'dbfs': round(item['dbfs'], 1),
               'reply': '', 'id': 0}

        def keep(action, wake=''):
            if rec.get('_kept'):
                return
            rec['_kept'] = True
            rec['dbg'] = self._dbg_keep(item['data'], text, action, wake,
                                        item.get('dbfs') or 0)
        if err:
            rec['action'] = 'error'
            self.counters['errors'] += 1
            keep('error')
            self._push_recent(rec)
            self._set_stage('idle', '识别失败')
            return
        if not text:
            rec['action'] = 'empty'
            self.counters['asr_empty'] += 1
            keep('empty')
            self._push_recent(rec)
            self._set_stage('idle', '无有效语音')
            return
        # 去重：同一句话在 3 秒内重复出现（B 段/尾音重录）只处理一次
        now = time.time()
        if text == self._last_heard and (now - self._last_heard_ts) < 3.0:
            rec['action'] = 'duplicate'
            keep('duplicate')
            self._push_recent(rec)
            return
        self._last_heard, self._last_heard_ts = text, now

        fuzzy = _flag(st.get('assist_wake_fuzzy'), True)
        loose = _flag(st.get('assist_wake_loose'), False)
        words = self.wake_words(st)
        mode = self.wake_mode(st)
        busy_seg = bool(item.get('busy'))
        # BUSY 唤醒模式：**一切**都要先有载波才算数 —— 唤醒词、追问窗口、
        # 纯唤醒词应答都不例外。这一条是硬的：用户反馈「未有 BUSY 高电平也会被
        # 识别到语音触发」，根因就是只有命中唤醒词那条路被拦了，追问窗口那条没拦。
        gate = self.busy_gate(mode, busy_seg)
        if gate:
            rec['action'] = 'ignored'
            rec['note'] = gate
            self.counters['busy_skipped'] = int(self.counters.get('busy_skipped', 0)) + 1
            keep('ignored')
            self._push_recent(rec)
            self._set_stage('idle', gate)
            return
        wake, hit, rest = match_wake(text, words, fuzzy, loose)
        in_window = now <= self.follow_until
        if wake:
            rec['wake'] = hit
            self.counters['wakes'] += 1
            kind = 'wake'
        elif in_window:
            rec['wake'] = '(追问窗口)'
            kind = 'followup'
            rest = text
        else:
            # 没命中唤醒词、也不在追问窗口 —— 交给自主决策层判一次（阶段一影子：
            # 判归判、记归记，**绝不发射**）。返回 True 表示这一段已被自主层记下。
            if self._auto_try(text, st, item, rec, keep, asr_ms, now):
                return
            rec['action'] = 'ignored'
            self.counters['ignored'] += 1
            near, ratio = wake_near_miss(text, words, fuzzy)
            if near:
                # 差一点就命中：把「像哪个词、相似度」写进记录，调词时一眼看到差在哪
                rec['note'] = '接近唤醒词 %s（相似度 %.2f）' % (near, ratio)
            keep('ignored')
            self._push_recent(rec)
            # 必须用 .get：note 只在「接近唤醒词」或自主预筛时才写，
            # 直接下标取会在**普通忽略**这条最常走的路上 KeyError
            # （板端日志实测：处理失败：KeyError: 'note'，整段处理中断）。
            self._set_stage('idle', rec.get('note') or '未命中唤醒词')
            return

        if not rest:
            # 只喊了唤醒词：回一句「请讲」，并打开追问窗口
            ack = (st.get('assist_ack_reply') or '').strip() or '请讲'
            rec['action'] = 'ack'
            rec['reply'] = ack
            keep('ack', rec['wake'])
            self._push_recent(rec)
            self._answer(ack, st, kind='ack', heard=text, asr_ms=asr_ms,
                         rx_bytes=item['data'], dbfs=item['dbfs'], wake=hit)
            return

        rec['action'] = 'answer'
        keep('answer', rec['wake'])
        self._push_recent(rec)
        self._answer(rest, st, kind=kind, heard=text, asr_ms=asr_ms,
                     rx_bytes=item['data'], dbfs=item['dbfs'], wake=hit)

    # -- 自主回答（阶段一：影子模式）---------------------------------------
    def auto_told_callsigns(self, st):
        """「自己人」呼号：自主白名单 + 语音日志里那份本台呼号。

        只用来判 `被点名` 这个**提示位**，不参与发射与否的判定。
        """
        raw = ' '.join([str(st.get('assist_auto_whitelist') or ''),
                        str(st.get('vlog_callsign_whitelist') or '')])
        return [x.strip() for x in re.split(r'[,;、\s]+', raw) if len(x.strip()) >= 4]

    def auto_ctx(self, st, text, now=None, busy=False):
        """决策模型的输入上下文（纯读取，无副作用）。"""
        now = now if now is not None else time.time()
        wl = (st.get('assist_auto_whitelist') or '').strip()
        calls = auto_callsigns(text, wl)
        cs = calls[0] if calls else ''
        called = auto_called(text, self.wake_words(st),
                             self.auto_told_callsigns(st),
                             _flag(st.get('assist_wake_fuzzy'), True))
        last = []
        with self.lock:
            for h in list(self.history)[-2:]:
                last.append(('对方', h.get('q') or ''))
                last.append(('我', h.get('a') or ''))
        since = int(now - self.auto_last_ts) if self.auto_last_ts else 9999
        return {'wl': wl, 'callsigns': calls, 'callsign': cs, 'called': called,
                'last': last[-4:], 'since': since, 'busy': bool(busy)}

    def auto_decide(self, text, st=None, busy=None, now=None, judge=None):
        """跑一次决策层：**不发射、不入库**，只返回结构化结果。

        实况路径与页面「决策自测」共用这一份实现 —— 自测若走另一条路，测的就不是
        线上那条路了（这个坑在 PTT 自检上已经踩过一次）。

        `judge` 是**注入判定**（自测专用，为的是不依赖模型也能验闸门链），
        实况路径永远不传。
        """
        st = st or self.settings()
        now = now if now is not None else time.time()
        busy = bool(self.busy_getter()) if busy is None else bool(busy)
        ctx = self.auto_ctx(st, text, now, busy)
        out = {'text': text, 'mode': auto_mode(st), 'decision': 'silent',
               'reason': 'silent', 'confidence': 0, 'think': '', 'raw': '',
               'parse_ok': False, 'called': ctx['called'], 'callsign': ctx['callsign'],
               'callsigns': ctx['callsigns'], 'prompt': '', 'prompt_chars': 0,
               'ms': 0, 'provider': '', 'model': '', 'error': '',
               'gate': 'silent', 'gate_note': '', 'would_reply': False,
               'allowed': False, 'gate_label': AUTO_BLOCK_LABEL['silent']}
        think_on = _flag(st.get('assist_auto_think'), True)
        think_chars = max(8, min(60, int(_f(st.get('assist_auto_think_chars'), 30))))
        prompt = compose_decision_prompt(
            text, dict(ctx, think_chars=think_chars if think_on else 8))
        if not think_on:
            # 关掉「想」就明确告诉模型别写第一行，而不是让它写完了再丢
            prompt = prompt.replace('第一行只写 想：不超过%d个字的判断依据' % think_chars,
                                    '第一行只写 想：无')
        out['prompt'] = prompt
        out['prompt_chars'] = len(prompt)
        if judge:
            # 注入判定：跳过一次模型调用（自测专用，为了让闸门链可稳定复现）
            dec = dict(judge)
            out['raw'] = '（注入判定，未调用模型）'
            out['parse_ok'] = True
            out['provider'], out['model'] = 'inject', 'inject'
        else:
            if self.ask_raw_fn is None:
                out['error'] = '决策用 LLM 通道未注入'
                return out
            msgs = [{'role': 'system', 'content': AUTO_DECISION_SYS},
                    {'role': 'user', 'content': prompt}]
            t0 = time.time()
            try:
                r = self.ask_raw_fn(msgs, 0.1, 48) or {}
            except Exception as e:
                r = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
            out['ms'] = int(r.get('ms') or (time.time() - t0) * 1000)
            out['provider'] = str(r.get('provider') or '')
            out['model'] = str(r.get('model') or '')
            if not r.get('ok') or not str(r.get('text') or '').strip():
                out['error'] = str(r.get('error') or '决策调用无输出')
                out['decision'], out['reason'], out['gate'] = 'silent', 'error', 'error'
                return out
            out['raw'] = str(r.get('text') or '')
            dec = parse_decision(out['raw'], max_think=think_chars)
            out['parse_ok'] = bool(dec['ok'])
        out['decision'] = dec['decision']
        out['reason'] = dec['reason']
        out['confidence'] = dec['confidence']
        out['think'] = dec['think'] if think_on else ''
        # 「显式点名」前置：与模型无关的内容闸门（可用设置关掉，默认开）
        require_addr = _flag(st.get('assist_auto_require_address'), True)
        addr_ok, addr_why = auto_addressed(text, self.wake_words(st),
                                           self.auto_told_callsigns(st))
        out['addressed'], out['addr_why'] = addr_ok, addr_why
        out['require_address'] = require_addr
        allowed, code, note = auto_gate(
            dec['decision'], dec['reason'], mode=out['mode'],
            callsign=ctx['callsign'], whitelist=ctx['wl'],
            min_gap=_f(st.get('assist_auto_min_gap'), 90.0),
            max_per_hour=int(_f(st.get('assist_auto_max_per_hour'), 6)),
            cooldown=_f(st.get('assist_auto_call_cooldown'), 600.0),
            hits=list(self.auto_hits),
            call_ts=self.auto_call_ts.get((ctx['callsign'] or '').upper(), 0.0),
            last_tx=self.auto_last_ts, now=now,
            quiet=in_quiet_hours((st.get('assist_quiet_hours') or '').strip())
            if (st.get('assist_quiet_hours') or '').strip() else False,
            test_mode=_flag(st.get('assist_test_mode'), False),
            busy=busy, addressed=(addr_ok or not require_addr))
        out['allowed'], out['gate'], out['gate_note'] = allowed, code, note
        out['gate_label'] = AUTO_BLOCK_LABEL.get(code, code)
        # 影子期：除了「影子」那一道锁，其余闸门全放行 = 本来会发射
        out['would_reply'] = code in ('shadow', 'ok')
        return out

    def _auto_try(self, text, st, item, rec, keep, asr_ms, now):
        """实况路径的自主判定入口。返回 True = 这一段已由自主层记档。

        BUSY 用的是**此刻**的信道状态，不是这一段的 BUSY 标志：段标志说的是
        「刚才那段有载波」（那正是我们听见对方的原因），拿它当发射红线会导致
        「只要听见了就永远不许答」。真正的发射前检查在 _transmit 里还会再做一遍。
        """
        if not _flag(st.get('assist_auto_enabled'), True):
            return False
        mode = auto_mode(st)
        if mode not in AUTO_MODES_OPEN:
            # 未开放的模式（half/full）：连决策模型都不叫，避免白烧十几秒
            return False
        ok_pre, why = auto_prefilter(text, list(self.tx_texts))
        if not ok_pre:
            self.counters['auto_skipped'] = int(self.counters.get('auto_skipped', 0)) + 1
            if why == 'echo':
                self.counters['auto_echo_skipped'] = int(
                    self.counters.get('auto_echo_skipped', 0)) + 1
                rec['note'] = '自主：与自己刚发射的内容雷同，跳过'
            elif why == 'short':
                rec['note'] = '自主：内容太短，跳过'
            else:
                rec['note'] = '自主：不像有效语音，跳过'
            return False
        self.counters['auto_decided'] = int(self.counters.get('auto_decided', 0)) + 1
        res = self.auto_decide(text, st, busy=bool(self.busy_getter()), now=now)
        code = str(res.get('gate') or 'silent')
        if res.get('raw') and not res.get('parse_ok'):
            self.counters['auto_parse_fail'] = int(
                self.counters.get('auto_parse_fail', 0)) + 1
        if res['decision'] == 'answer':
            self.counters['auto_answered'] = int(
                self.counters.get('auto_answered', 0)) + 1
        else:
            self.counters['auto_silent'] = int(self.counters.get('auto_silent', 0)) + 1
        for name, key in (('whitelist', 'auto_whitelist_blocked'),
                          ('cooldown', 'auto_cooldown'), ('rate', 'auto_rate_limited'),
                          ('gap', 'auto_gap_blocked'), ('shadow', 'auto_shadow_blocked'),
                          ('noaddr', 'auto_noaddr'), ('error', 'auto_error')):
            if code == name:
                self.counters[key] = int(self.counters.get(key, 0)) + 1
        if res.get('error') and code != 'error':
            # 模型没输出但被判默之外的路径兜住时也要计数（否则 error 会漏账）
            self.counters['auto_error'] = int(self.counters.get('auto_error', 0)) + 1
        would = bool(res.get('would_reply'))
        label = AUTO_BLOCK_LABEL.get(code, code)
        rec['auto'] = {
            'decision': res['decision'], 'reason': code, 'gate_label': label,
            'model_reason': res['reason'], 'confidence': res['confidence'],
            'think': res['think'], 'callsign': res['callsign'],
            'would_reply': would, 'ms': res['ms'], 'error': res['error'],
            'parse_ok': res['parse_ok'], 'addressed': res.get('addressed'),
            'addr_why': res.get('addr_why', ''), 'provider': res.get('provider', ''),
            'model': res.get('model', '')}
        rec['action'] = 'shadow' if would else 'silent'
        rec['note'] = '自主：%s（%s）' % (
            '应答' if res['decision'] == 'answer' else '保持静默', label)
        # 影子行一定 dry=1 —— 它**没有**发射动作，查询时不能按 sent 统计
        rec['id'] = self._save_turn(
            'auto', text, '', rec['action'], error=str(res.get('error') or ''),
            asr_ms=asr_ms, llm_ms=int(res.get('ms') or 0),
            rx_bytes=(item.get('data') if would else None),
            dbfs=item.get('dbfs') or 0.0, decision=res['decision'], reason=code,
            confidence=res['confidence'], think=res['think'],
            # 归因：这一条判定到底是外部 API 还是本地 1.5B 拍的。
            # 此前这两列一直空着，事后无法把外部模型与本地模型的表现分开看（问题 4）。
            provider=str(res.get('provider') or ''), model=str(res.get('model') or ''),
            callsigns=','.join(res['callsigns']), would_reply=1 if would else 0, dry=1)
        keep(rec['action'])
        self._push_recent(rec)
        self.auto_last = dict(res, prompt='', ts=time.strftime('%H:%M:%S'))
        if would:
            self._set_stage('auto', '影子模式：本应发射（未发射）')
            print('%s [影子] 本应回答「%s」→ 想：%s（%s，信 %d，%dms）'
                  % (LOG, text[:40], res['think'][:30] or '-', code,
                     res['confidence'], res['ms']), flush=True)
            if _flag(st.get('assist_auto_dry_answer'), True):
                self._auto_dry_answer(text, st, res, asr_ms, item)
        else:
            self._set_stage('auto', '自主判定：保持静默（%s）' % label)
        return True

    def _auto_dry_answer(self, text, st, res, asr_ms, item):
        """影子期把「本来会说的话」生成出来，但**只合成不发射**（no_tx=True 硬保证）。

        只看「判答/判默」无法验收答得对不对，所以影子期连答案一起生成、写进记录，
        人再回头看。放独立线程：一轮要十几秒，压在工作线程上会让助手在这期间听不见
        唤醒词；同一时刻只跑一轮，来不及就跳过并在返回值里说明。
        """
        with self.lock:
            if self.auto_dry_running:
                print('%s [影子] 上一轮试答还没跑完，本段只留判定', LOG, flush=True)
                return False
            self.auto_dry_running = True

        def _run():
            try:
                self._answer(text, st, kind='auto-answer', heard=text, asr_ms=asr_ms,
                             rx_bytes=None, dbfs=item.get('dbfs') or 0.0, no_tx=True,
                             auto=res)
            except Exception as e:
                print('%s [影子] 试答失败：%s: %s' % (LOG, type(e).__name__, e), flush=True)
            finally:
                with self.lock:
                    self.auto_dry_running = False

        threading.Thread(target=_run, daemon=True, name='assist-auto-dry').start()
        return True

    def test_decide(self, text, busy=None, store=False, judge=None):
        """页面「决策自测」：给定一句话，回报决策层全链路结果（默认不入库）。

        `judge` 可以**注入**判定结果（{'decision':'answer','reason':'question'}），
        用来在不依赖 1.5B 模型心情的前提下验闸门链：红线必须与模型无关，
        「模型说答但信道忙」这类组合只有注入才能稳定复现。
        注入只存在于这条自测路径，**实况路径（_auto_try）永远不传它**。
        """
        text = (text or '').strip()
        if not text:
            return {'ok': False, 'error': '测试文本为空'}
        st = self.settings()
        forced = self._forced_judge(judge)
        res = self.auto_decide(text, st, busy=busy, judge=forced) if forced \
            else self.auto_decide(text, st, busy=busy)
        res.pop('prompt', None)
        res['ok'] = not res.get('error')
        res['forced'] = bool(forced)
        res['own'] = [x[:40] for x in self.tx_texts]
        res['prefilter'] = auto_prefilter(text, list(self.tx_texts))[1] or 'pass'
        res['busy'] = bool(self.busy_getter()) if busy is None else bool(busy)
        res['whitelist'] = (st.get('assist_auto_whitelist') or '').strip()
        res['limits'] = {'max_per_hour': int(_f(st.get('assist_auto_max_per_hour'), 6)),
                         'min_gap': _f(st.get('assist_auto_min_gap'), 90.0),
                         'cooldown': _f(st.get('assist_auto_call_cooldown'), 600.0)}
        if store:
            self._save_turn('auto-test', text, '', 'shadow' if res['would_reply'] else 'silent',
                            decision=res['decision'], reason=res['gate'],
                            confidence=res['confidence'], think=res['think'],
                            callsigns=','.join(res['callsigns']),
                            would_reply=1 if res['would_reply'] else 0, dry=1)
        return res

    @staticmethod
    def _forced_judge(judge):
        """校验注入的判定：只认闭集里的写法，写错就当没注入（宁可走真模型）。"""
        if not isinstance(judge, dict):
            return None
        d = str(judge.get('decision') or '').strip().lower()
        if d in ('answer', '答', '1', 'true'):
            d = 'answer'
        elif d in ('silent', '默', '0', 'false'):
            d = 'silent'
        else:
            return None
        r = str(judge.get('reason') or '').strip()
        # 理由两种写法都收：中文闭集标签（'直接提问'）或结论码（'question'）
        if r and r not in AUTO_REASON_CODE and r not in AUTO_REASON_LABEL:
            return None
        code = AUTO_REASON_CODE.get(r, r)
        if d == 'answer' and code not in AUTO_ANSWER_REASONS:
            # 注入「答」时必须给一个可接受的理由码，否则验的是自相矛盾那条分支
            return None
        return {'decision': d, 'reason': code or ('question' if d == 'answer' else 'unrelated'),
                'confidence': max(0, min(9, int(judge.get('confidence') or 5))),
                'think': str(judge.get('think') or '（注入判定）')[:60]}

    def decide_status(self, st=None):
        """页面/接口用的自主回答概览。"""
        st = st or self.settings()
        now = time.time()
        hits = [t for t in self.auto_hits if t and (now - t) < 3600]
        return {
            'enabled': _flag(st.get('assist_auto_enabled'), True),
            'mode': auto_mode(st),
            'mode_label': {'shadow': '影子模式（只记录不发射）',
                           'half': '半自动（阶段二开放）',
                           'full': '全自动（阶段二开放）'}.get(auto_mode(st), ''),
            'open_modes': list(AUTO_MODES_OPEN),
            'whitelist': (st.get('assist_auto_whitelist') or '').strip(),
            'max_per_hour': int(_f(st.get('assist_auto_max_per_hour'), 6)),
            'min_gap': _f(st.get('assist_auto_min_gap'), 90.0),
            'cooldown': _f(st.get('assist_auto_call_cooldown'), 600.0),
            'think': _flag(st.get('assist_auto_think'), True),
            'think_chars': int(_f(st.get('assist_auto_think_chars'), 30)),
            'dry_answer': _flag(st.get('assist_auto_dry_answer'), True),
            'used_last_hour': len(hits),
            'last_auto_ago': round(now - self.auto_last_ts, 1) if self.auto_last_ts else -1,
            'dry_running': bool(self.auto_dry_running),
            'own': [x[:60] for x in self.tx_texts],
            'last': {k: v for k, v in (self.auto_last or {}).items() if k != 'prompt'},
            'reason_labels': dict(AUTO_BLOCK_LABEL),
            'counters': {k: self.counters.get(k, 0) for k in (
                'auto_decided', 'auto_skipped', 'auto_answered', 'auto_silent',
                'auto_parse_fail', 'auto_shadow_blocked', 'auto_rate_limited',
                'auto_cooldown', 'auto_gap_blocked', 'auto_whitelist_blocked',
                'auto_echo_skipped', 'auto_error', 'auto_noaddr')},
            'require_address': _flag(st.get('assist_auto_require_address'), True),
        }

    def _decode(self, data):
        try:
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            return x, SAMPLE_RATE
        except Exception:
            return None, SAMPLE_RATE

    def _vad_trim(self, x, sr, seconds):
        """用 silero VAD 裁掉首尾静音。

        只做**边界收紧**，不做语音/非语音判决：判空时原样返回。
        这一点很重要——silero 偶尔会把只有 0.5~0.8 秒的「中继台」判成非语音，
        若据此丢弃整段，唤醒就再也唤不醒了。宁可多跑一次 ASR。
        """
        if seconds < 0.4:
            return x
        vad = _get_vad()
        if vad is None:
            return x
        try:
            segs = vad.split(x, sr)
        except Exception:
            return x
        if not segs:
            return x
        a = int(max(0.0, segs[0][0] - 0.05) * sr)
        b = int(min(len(x) / float(sr), segs[-1][1] + 0.10) * sr)
        if b - a < int(0.15 * sr):
            return x
        return x[a:b]

    def _asr_shared(self, x, sr, st):
        """调用 voice_service.transcribe_pcm（语音日志的同一套识别流程）。"""
        t0 = time.time()
        try:
            import voice_service
            text, ms = voice_service.transcribe_pcm_text(
                x, sr, enhance=_flag(st.get('assist_enhance'), True),
                min_seconds=0.30, vad_empty_fallback=True)
            return text, int(ms or (time.time() - t0) * 1000), ''
        except Exception as e:
            return '', int((time.time() - t0) * 1000), '%s: %s' % (type(e).__name__, e)

    def _push_recent(self, rec):
        with self.lock:
            self.recent.append(dict(rec))

    # -- 回答（LLM → TTS → 发射）------------------------------------------
    def _answer(self, question, st, kind='wake', heard='', asr_ms=0,
                rx_bytes=None, dbfs=0.0, wake='', no_tx=False, auto=None):
        """完整跑一轮回答。kind: wake / followup / ack / test / auto-answer。

        `auto` 给定时表示这是自主决策层触发的一轮（阶段一影子）：照常生成答案，
        但 `no_tx` 强制为真，且这一行记成 dry —— 它没有发射动作。
        """
        self.stop_flag = False
        auto = dict(auto or {})
        auto_kw = {}
        if auto:
            no_tx = True
            auto_kw = {'decision': auto.get('decision', ''),
                       'reason': auto.get('gate') or auto.get('reason', ''),
                       'confidence': int(auto.get('confidence') or 0),
                       'think': auto.get('think', ''),
                       'callsigns': ','.join(auto.get('callsigns') or []),
                       'would_reply': 1 if auto.get('would_reply') else 0,
                       'dry': 1}
        if kind != 'ack':
            self._set_stage('think', '思考中')
        base = ''
        try:
            base = (self.base_prompt_fn() or '').strip()
        except Exception:
            base = ''
        prompt, prompt_chars = self._build_prompt(question, st, base)
        # 总结轮要**重新**拿到「基础设定 + 语音播报规范」：真正被朗读的文本是
        # 总结轮产出的，而第一轮在 force_first 下被要求「只输出读取指令、不要
        # 回答用户」。约束只留在第一轮 = 对最终答案零生效（现场 bug）。
        sysprompt = '\n'.join([x for x in (base, self._spec_text(st)) if x])
        # 只有 ack 是固定短语，不必过 LLM；其余一律走 LLM
        reply, llm_ms, provider, model, iters, tools, lerr = '', 0, '', '', 0, '', ''
        if kind == 'ack':
            reply = (st.get('assist_ack_reply') or '').strip() or '请讲'
        else:
            if self.ask_fn is None:
                lerr = 'LLM 调用未注入'
            else:
                try:
                    kw = ({'sysprompt': sysprompt}
                          if self._ask_takes_sysprompt else {})
                    r = self.ask_fn(prompt, question,
                                    int(_f(st.get('assist_max_tokens'), 256)),
                                    _f(st.get('assist_temperature'), 0.3),
                                    _flag(st.get('assist_use_tools'), True),
                                    int(_f(st.get('assist_agent_iters'), 2)),
                                    **kw) or {}
                except Exception as e:
                    r = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
                llm_ms = int(r.get('ms') or 0)
                provider = str(r.get('provider') or '')
                model = str(r.get('model') or '')
                iters = int(r.get('iters') or 0)
                tools = str(r.get('tools') or '')
                if r.get('ok'):
                    reply = (r.get('reply') or '').strip()
                else:
                    lerr = str(r.get('error') or 'LLM 失败')[:200]
        if lerr or not reply:
            self.counters['errors'] += 1
            self.last_error = lerr or 'LLM 返回空内容'
            self._set_stage('idle', '回答失败')
            self._save_turn(kind, heard, '', 'error', error=self.last_error, wake=wake,
                            asr_ms=asr_ms, llm_ms=llm_ms, prompt_chars=prompt_chars,
                            provider=provider, model=model, iters=iters, tools=tools,
                            rx_bytes=rx_bytes, dbfs=dbfs, **auto_kw)
            return
        limit = self.max_chars(st)
        speak, truncated = clamp_reply(reply, limit)
        # 「句末加喵」这类关键标记不能赌模型（实测同一份约束下 2 次里丢 1 次），而它是
        # 本项目验证工具注入是否生效的探针，所以出口确定性补上；约束里没写喵就不补。
        if speak:
            try:
                speak = agent_service.ensure_meow(speak, self._spec_text(st))
            except Exception:
                pass
        if not speak:
            self.last_error = '回复清洗后为空'
            self._save_turn(kind, heard, reply, 'error', error=self.last_error, wake=wake,
                            asr_ms=asr_ms, llm_ms=llm_ms, prompt_chars=prompt_chars,
                            provider=provider, model=model, iters=iters, tools=tools,
                            rx_bytes=rx_bytes, dbfs=dbfs, **auto_kw)
            return
        if truncated:
            self.counters['truncated'] += 1
        # 记入多轮上下文（用完的原文，便于追问指代）
        if kind != 'ack':
            with self.lock:
                self.history.append({'q': question[:160], 'a': speak[:160]})
        # 合成
        self._set_stage('synth', '语音合成中')
        t0 = time.time()
        wav_path, terr = '', ''
        try:
            wav_path = self.tts_fn(speak, (st.get('assist_voice') or '').strip())
        except Exception as e:
            terr = '%s: %s' % (type(e).__name__, e)
        tts_ms = int((time.time() - t0) * 1000)
        if terr or not wav_path:
            self.counters['errors'] += 1
            self.last_error = '语音合成失败：%s' % (terr or '无输出')
            self._set_stage('idle', '合成失败')
            self._save_turn(kind, heard, speak, 'error', error=self.last_error, wake=wake,
                            asr_ms=asr_ms, llm_ms=llm_ms, tts_ms=tts_ms,
                            prompt_chars=prompt_chars, provider=provider, model=model,
                            iters=iters, tools=tools, rx_bytes=rx_bytes, dbfs=dbfs,
                            **auto_kw)
            return
        # 发射
        t_tx = time.time()
        res = self._transmit(wav_path, st, no_tx=no_tx)
        tx_seconds = float(res.get('seconds') or 0.0)
        ok = bool(res.get('ok'))
        skipped = bool(res.get('skipped'))
        action = 'sent' if ok else ('skipped' if skipped else 'failed')
        if auto and not ok:
            # 影子轮：no_tx 必然 skipped，但这不是「被拦下的发射」，是它本来就不发。
            # action 记 shadow，免得 day_stats 的 skipped/aborted 被影子刷成噪声。
            action = 'shadow'
        if ok:
            self.counters['tx'] += 1
            self.counters['tx_seconds'] += tx_seconds
            self.last_tx = time.time()
            self.tx_last_ts = self.last_tx
            self.tx_until = self.last_tx + max(
                0.0, _f(st.get('assist_tx_guard_ms'), 600.0)) / 1000.0
            self.follow_until = time.time() + max(0.0, _f(st.get('assist_followup_seconds'), 30.0))
            self._set_stage('followup', '追问窗口')
        elif skipped:
            self.counters['aborted'] += 1
            if auto:
                self.counters['aborted'] -= 1
            if '禁发时段' in str(res.get('error') or ''):
                self.counters['quiet_blocked'] += 1
            self._set_stage('idle', str(res.get('error') or '已跳过'))
        else:
            self.counters['errors'] += 1
            self.last_error = str(res.get('error') or '发射失败')
            self._set_stage('error', self.last_error)
        self.counters['turns'] += 1
        if ok:
            self.tx_texts.append(speak)     # 供「不重复自己」的回声闸门比对
        self._save_turn(kind, heard, speak, action, wake=wake,
                        error=str(res.get('error') or ''),
                        tx_seconds=tx_seconds, truncated=truncated,
                        asr_ms=asr_ms, llm_ms=llm_ms, tts_ms=tts_ms,
                        wait_s=float(res.get('waited') or 0.0),
                        prompt_chars=prompt_chars, reply_chars=len(speak),
                        provider=provider, model=model, iters=iters, tools=tools,
                        rx_bytes=rx_bytes, tx_wav=wav_path, dbfs=dbfs, **auto_kw)
        if auto:
            self._set_stage('auto', '影子试答完成（未发射）')
        print('%s [%s] %s → %s（发射 %.1fs%s）' % (
            LOG, kind, heard[:40], speak[:60], tx_seconds,
            '，已截断' if truncated else ''), flush=True)

    def _spec_text(self, st):
        """展开后的「语音播报约束」原文（{max_chars} 已代入）。

        _build_prompt 与 _answer 必须用**同一份**文本，否则总结轮回灌的约束
        会和第一轮说明的不一致。
        """
        suffix = (st.get('assist_prompt_suffix') or '').strip()
        if not suffix:
            return ''
        try:
            suffix = self.expand_fn(suffix)
        except Exception:
            pass
        return suffix.replace('{max_chars}', str(self.max_chars(st)))

    def _build_prompt(self, question, st, base=''):
        """拼提示词：基础设定在前，**行为约束在问题之后**。

        顺序不是随手排的，是板端实测出来的：同一份播报规范、同一个问题，长提示词
        下把规范放在**开头**模型直接无视——答「哈喽！中继台的电池电压是 12.6 伏。」，
        规范要求的句尾标记一个字都没出现；放到**结尾**就遵守——「好的，电池电压是
        12.6 伏，喵。」。短提示词两种都行，但一旦有基础设定/对话历史/工具数据，
        放前面的约束就守不住了。

        逐级降配：先砍历史 → 再砍基础设定；**规范与问题永远活到最后**，因为规范
        决定这句话能不能播出去。
        """
        suffix = self._spec_text(st)
        max_in = max(400, int(_f(st.get('assist_max_input_chars'), 3000)))
        n = self.hist_turns(st)
        q = (question or '').strip()[:400]
        variants = []
        for hist_n in (n, min(n, 3), min(n, 1), 0):
            for head in (base, base[:600], ''):
                parts = []
                if head:
                    parts.append('【系统设定】\n' + head)
                h = self._history_text(st, hist_n)
                if h:
                    parts.append('【对话历史】\n' + h)
                parts.append('【当前问题】\n' + q)
                if suffix:
                    parts.append('【播报要求（必须遵守）】\n' + suffix)
                variants.append('\n\n'.join(parts))
        for p in variants:
            if len(p) <= max_in:
                return p, len(p)
        # 兜底：只留问题与规范。截断只许砍问题，绝不能把规范切掉。
        room = max(0, max_in - len(suffix) - 40)
        tail = ('【当前问题】\n' + q[:room]) if room else '【当前问题】\n'
        if suffix:
            tail += '\n\n【播报要求（必须遵守）】\n' + suffix
        return tail, len(tail)

    def _history_text(self, st, turns):
        if turns <= 0 or not self.history:
            return ''
        lines = []
        for h in list(self.history)[-turns:]:
            lines.append('对方：' + (h.get('q') or '')[:120])
            lines.append('我：' + (h.get('a') or '')[:120])
        return '\n'.join(lines)

    def _transmit(self, wav_path, st, no_tx=False):
        """受控发射：禁发时段 → 等信道空闲+间隔 → 硬超时播放。

        no_tx=True 时**无条件**不发射（手动回环测试用），优先级高于一切设置项：
        页面上写着「不发射」就必须真的不发射，不能靠设置项巧合成立。
        """
        if no_tx:
            return {'ok': False, 'skipped': True,
                    'error': '本地回环测试：只合成试听，不发射'}
        qh = (st.get('assist_quiet_hours') or '').strip()
        if qh and in_quiet_hours(qh):
            return {'ok': False, 'skipped': True,
                    'error': '当前处于禁发时段（%s）' % qh}
        if _flag(st.get('assist_test_mode'), False):
            return {'ok': False, 'skipped': True, 'error': '测试模式：仅网页试听，不发射'}
        want_gap = max(0.0, _f(st.get('assist_min_gap_seconds'), 15.0))
        budget = max(3.0, _f(st.get('assist_busy_wait_seconds'), 8.0))
        budget = max(budget, want_gap + 3.0)
        max_tx = max(3.0, _f(st.get('assist_max_tx_seconds'), 30.0))
        tw = time.time()
        busy_seen = False
        while True:
            if self.stop_flag:
                return {'ok': False, 'skipped': True, 'error': '已被手动停止'}
            now = time.time()
            left = want_gap - (now - self.last_tx) if self.last_tx else 0.0
            busy = bool(self.busy_getter())
            if busy:
                busy_seen = True
            if not busy and left <= 0:
                break
            if now - tw >= budget:
                if busy:
                    self.counters['busy_defers'] += 1
                    return {'ok': False, 'skipped': True,
                            'error': '信道忙（BUSY 有效），已放弃本次回答'}
                self.counters['gap_waits'] += 1
                return {'ok': False, 'skipped': True,
                        'error': '距上次发射不足 %.0fs，已放弃本次回答' % want_gap}
            self._set_stage('wait', '信道忙' if busy else '等待最小间隔')
            time.sleep(0.15)
        waited = round(time.time() - tw, 2)
        self._set_stage('tx', '发射中')
        try:
            res = self.play_fn(wav_path, max_tx) or {}
        except Exception as e:
            res = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
        res = dict(res)
        res['waited'] = waited
        if busy_seen:
            res['busy_seen'] = True
        return res

    def _save_turn(self, kind, heard, reply, action, error='', tx_seconds=0.0,
                   wake='',
                   truncated=False, asr_ms=0, llm_ms=0, tts_ms=0, wait_s=0.0,
                   prompt_chars=0, reply_chars=0, provider='', model='', iters=0,
                   tools='', rx_bytes=None, tx_wav='', dbfs=0.0,
                   decision='', reason='', confidence=0, think='', callsigns='',
                   would_reply=0, dry=0):
        rx_name = ''
        try:
            rx_name = self._store_wav(rx_bytes, 'rx')
        except Exception:
            rx_name = ''
        tx_name = ''
        try:
            if tx_wav:
                tx_name = self._store_wav_file(tx_wav, 'tx')
        except Exception:
            tx_name = ''
        try:
            cur = self.store.exec(
                'INSERT INTO assist_turns(ts,kind,wake,heard,reply,action,tx_seconds,'
                'truncated,error,asr_ms,llm_ms,tts_ms,wait_s,rx_wav,tx_wav,'
                'prompt_chars,reply_chars,provider,model,iters,tools,dbfs,'
                'decision,reason,confidence,think,callsigns,would_reply,dry) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (_now_iso(), kind, wake, heard, reply, action, float(tx_seconds),
                 1 if truncated else 0, error[:300], int(asr_ms), int(llm_ms),
                 int(tts_ms), float(wait_s), rx_name, tx_name, int(prompt_chars),
                 int(reply_chars), provider, model, int(iters), tools, float(dbfs),
                 str(decision or ''), str(reason or ''), int(confidence or 0),
                 str(think or '')[:400], str(callsigns or '')[:120],
                 1 if would_reply else 0, 1 if dry else 0))
            return int(getattr(cur, 'lastrowid', 0) or 0)
        except Exception as e:
            print('%s 保存轮次失败：%s' % (LOG, e), flush=True)
            return 0

    def _dbg_keep(self, data, text, action, wake, dbfs):
        """环形保留最近 N 条识别音频，便于事后核对助手到底听到了什么。

        未命中的语音段原本既不落库也不落盘，排查「唤醒词丢字」只能靠反推，
        实测绕了四轮，因此加这个留档环。每条约 200KB，默认只留 12 条。
        """
        try:
            n = int(_f(self.settings().get('assist_debug_keep'), 12))
        except Exception:
            n = 12
        if n <= 0 or not data:
            return ''
        try:
            d = WORK_DIR / 'debug'
            d.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime('%m%d_%H%M%S')
            name = 'dbg_%s_%s.wav' % (stamp, action)
            with wave.open(str(d / name), 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(data)
            # 留档元信息写同名 .txt，含识别原文与判定，便于直接对比
            (d / (name[:-4] + '.txt')).write_text(
                '时间: %s\naction: %s\n唤醒: %s\n电平: %.1f dBFS\n识别: %s\n'
                % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), action, wake or '-',
                   dbfs, text or '(空)'), encoding='utf-8')
            for old in sorted(d.glob('dbg_*.wav'))[:-max(1, n)]:
                try:
                    old.unlink()
                    t = old.with_suffix('.txt')
                    if t.exists():
                        t.unlink()
                except Exception:
                    pass
            return name
        except Exception as e:
            print('%s 留档失败：%s' % (LOG, e), flush=True)
            return ''

    def debug_list(self):
        """列出留档（新的在前）。"""
        d = WORK_DIR / 'debug'
        out = []
        if not d.exists():
            return out
        for f in sorted(d.glob('dbg_*.wav'), reverse=True):
            info = {}
            t = f.with_suffix('.txt')
            if t.exists():
                try:
                    for ln in t.read_text(encoding='utf-8').splitlines():
                        if ':' in ln:
                            k, v = ln.split(':', 1)
                            info[k.strip()] = v.strip()
                except Exception:
                    pass
            out.append({'name': f.name, 'size': f.stat().st_size,
                        'ts': info.get('时间', ''), 'action': info.get('action', ''),
                        'wake': info.get('唤醒', ''), 'text': info.get('识别', ''),
                        'dbfs': info.get('电平', '')})
        return out

    def debug_path(self, name):
        name = str(name or '')
        if not name.startswith('dbg_') or not name.endswith('.wav') or '/' in name or '..' in name:
            return None
        f = WORK_DIR / 'debug' / name
        return f if f.exists() else None

    def _day_dir(self):
        d = WORK_DIR / datetime.now().strftime('%Y-%m-%d')
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _store_wav(self, data, tag):
        if not data:
            return ''
        try:
            d = self._day_dir()
            name = 'aturn_%s_%d_%s.wav' % (datetime.now().strftime('%H%M%S'), int(time.time() * 1000) % 100000, tag)
            with wave.open(str(d / name), 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLE_RATE)
                w.writeframes(data)
            return name
        except Exception:
            return ''

    def _store_wav_file(self, src, tag):
        try:
            src = Path(src)
            if not src.exists():
                return ''
            d = self._day_dir()
            name = 'aturn_%s_%s.wav' % (datetime.now().strftime('%H%M%S'), tag)
            dst = d / name
            dst.write_bytes(src.read_bytes())
            return name
        except Exception:
            return ''

    def wav_path(self, name):
        """把库里存的文件名解析成绝对路径（供 /api/assist/<id>/audio 使用）。"""
        name = str(name or '').strip()
        if not name or '/' in name or '\\' in name or '..' in name:
            return None
        if not name.endswith('.wav') or not name.startswith('aturn_'):
            return None
        for d in sorted(WORK_DIR.glob('*'), reverse=True):
            if d.is_dir() and (d / name).exists():
                return d / name
        return None

    # -- 对外接口 ----------------------------------------------------------
    def stop(self):
        """一键停止：打断当前播放、清空队列、关闭追问窗口。"""
        self.stop_flag = True
        self.follow_until = 0.0
        n = 0
        while True:
            try:
                self.q.get_nowait()
                self.q.task_done()
                n += 1
            except queue.Empty:
                break
        try:
            self.stop_play_fn()
        except Exception:
            pass
        self._set_stage('idle', '已手动停止')
        print('%s 手动停止：清空 %d 条待处理语音' % (LOG, n), flush=True)
        return {'stopped': True, 'cleared': n}

    def test_turn(self, text, tx=False):
        """本地回环测试：走完整链路（ASR 可跳过）。

        默认不发射（no_tx=True 是硬保证）；`tx=True` 时走**受控发射**那条路
        （禁发时段 → 等信道空闲与最小间隔 → 硬超时），全局「测试模式（只试听不发射）」
        仍然有效 —— 它开着就照旧拒绝发射并在返回值里说明原因。
        """
        text = (text or '').strip()
        if not text:
            return {'ok': False, 'error': '测试文本为空'}
        st = self.settings()

        def _run():
            try:
                self.counters['test_turns'] += 1
                self._last_heard, self._last_heard_ts = text, time.time()
                self._answer(text, st, kind='test', heard=text, asr_ms=0,
                             rx_bytes=None, dbfs=0.0, no_tx=not tx)
            except Exception as e:
                self.last_error = '%s: %s' % (type(e).__name__, e)
                print('%s 测试轮失败：%s' % (LOG, self.last_error), flush=True)

        threading.Thread(target=_run, daemon=True, name='assist-test').start()
        return {'ok': True, 'queued': True, 'tx': bool(tx),
                'test_mode': _flag(st.get('assist_test_mode'), False)}

    def say_text(self, text, tx=True, voice=''):
        """把**给定文本**合成后按受控发射（或只试听）。

        用途：手动测试 / 文本对话里点「发射这句」——文本已经生成好了，不需要再过 LLM。
        `tx=False` 时只合成，网页试听；两条路都记进对话记录，便于回看。
        """
        text = (text or '').strip()
        if not text:
            return {'ok': False, 'error': '文本为空'}
        if self.tts_fn is None or self.play_fn is None:
            return {'ok': False, 'error': 'TTS/播放未注入'}
        st = self.settings()
        fname = text[:60]

        def _run():
            try:
                self.counters['test_turns'] += 1
                wav = self.tts_fn(text, (voice or st.get('assist_voice') or '').strip())
                res = self._transmit(wav, st, no_tx=not tx) or {}
                ok = bool(res.get('ok'))
                action = 'sent' if ok else ('skipped' if res.get('skipped') else 'failed')
                err = '' if ok else str(res.get('error') or '')
                self._save_turn('say', '', text, action, error=err,
                                tx_seconds=float(res.get('seconds') or 0.0))
                if ok:
                    self.counters['tx'] += 1
                    self.last_tx = time.time()
                    self.tx_last_ts = self.last_tx
                    print('%s 手动发射完成：%s' % (LOG, fname), flush=True)
                else:
                    self.last_error = err or '发射失败'
                    print('%s 手动发射未执行：%s' % (LOG, self.last_error), flush=True)
            except Exception as e:
                self.last_error = '%s: %s' % (type(e).__name__, e)
                print('%s 手动发射失败：%s' % (LOG, self.last_error), flush=True)

        threading.Thread(target=_run, daemon=True, name='assist-say').start()
        return {'ok': True, 'queued': True, 'tx': bool(tx),
                'test_mode': _flag(st.get('assist_test_mode'), False)}

    def test_wake(self, text, busy=None):
        """只做唤醒词匹配测试，不调用 LLM、不发射。

        `busy` 给定时按 BUSY 唤醒模式判定「会不会真的唤醒」——不开无线电也能验双条件。
        """
        st = self.settings()
        fuzzy = _flag(st.get('assist_wake_fuzzy'), True)
        loose = _flag(st.get('assist_wake_loose'), False)
        words = self.wake_words(st)
        mode = self.wake_mode(st)
        wake, hit, rest = match_wake(text, words, fuzzy, loose)
        near, ratio = ('', 0.0)
        if not wake:
            near, ratio = wake_near_miss(text, words, fuzzy)
        would, reason = bool(wake), ''
        if wake and mode == 'busy' and busy is not None and not busy:
            would, reason = False, 'BUSY 未触发，按 BUSY 唤醒模式跳过'
        return {'words': words, 'matched': wake, 'hit': hit, 'question': rest,
                'fuzzy': fuzzy, 'loose': loose, 'mode': mode,
                'busy': busy, 'would_wake': would, 'reason': reason,
                'near': near, 'near_ratio': ratio}

    def list_turns(self, day=None, limit=100, offset=0):
        day = day or datetime.now().strftime('%Y-%m-%d')
        rows = self.store.query(
            'SELECT * FROM assist_turns WHERE ts LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?',
            (day + '%', int(limit), int(offset)))
        return rows

    def day_stats(self, day=None):
        day = day or datetime.now().strftime('%Y-%m-%d')
        r = self.store.one(
            "SELECT COUNT(*) AS turns, SUM(tx_seconds) AS tx_seconds,"
            " SUM(CASE WHEN action='sent' THEN 1 ELSE 0 END) AS sent,"
            " SUM(CASE WHEN action='skipped' THEN 1 ELSE 0 END) AS skipped,"
            " SUM(CASE WHEN truncated=1 THEN 1 ELSE 0 END) AS truncated,"
            " AVG(llm_ms) AS avg_llm, AVG(asr_ms) AS avg_asr"
            " FROM assist_turns WHERE ts LIKE ?", (day + '%',))
        return {k: (round(v, 1) if isinstance(v, float) else (v or 0))
                for k, v in (r or {}).items()}

    def status(self):
        st = self.settings()
        now = time.time()
        with self.lock:
            qsize = self.q.qsize()
            recent = list(self.recent)[-30:]
            levels = list(self.levels)[-120:]
            hist = len(self.history)
        return {
            'enabled': self.enabled(),
            'stage': self.stage,
            'stage_label': self._stage_label(),
            'stage_detail': self.stage_detail,
            'stage_seconds': round(now - self.stage_since, 1),
            'wake_words': self.wake_words(st),
            'fuzzy': _flag(st.get('assist_wake_fuzzy'), True),
            'wake_mode': self.wake_mode(st),
            'wake_loose': _flag(st.get('assist_wake_loose'), False),
            'busy_now': bool(self.busy_getter()),
            'follow_up_left': round(max(0.0, self.follow_until - now), 1),
            'history_turns': hist,
            'last_tx_ago': round(now - self.last_tx, 1) if self.last_tx else -1,
            'dbfs': round(self.last_dbfs, 1),
            'levels': levels,
            'recent': recent,
            'queue': qsize,
            'asr_last': self.asr_last,
            'llm_warm': dict(self.llm_warm,
                             age=round(now - float(self.llm_warm.get('ts') or now), 1)),
            'counters': dict(self.counters),
            'auto': self.decide_status(st),
            'today': self.day_stats(),
            'last_error': self.last_error,
            'uptime': round(now - self.started_at, 1),
            'settings': {k: st.get(k) for k in DEFAULTS},
        }
