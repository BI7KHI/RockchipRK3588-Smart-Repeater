# -*- coding: utf-8 -*-
"""板端验收：数值口语化之后，「念出来」到底对不对。

办法：合成一段文本 → 用板端自己的 ASR 把音频转写回来。这不是在给 ASR 找工作，
而是把它当耳朵用：合成出来的声音里实际说的是什么，转写回来就是什么。

要证两件事：
  1) **未口语化**的阿拉伯小数，听回来是错的（这就是修它的原因，作为反例控制）；
  2) 口语化后的文本，听回来的数值与真值一致。

跑法（板端，root）：
    PYTHONPATH=/home/elf/.local/lib/python3.10/site-packages python3 check_speech_asr.py
"""
import os
import re
import sys

sys.path.insert(0, '/www')
import speech_text as S            # noqa: E402
import tts_service                 # noqa: E402
import voice_service as V          # noqa: E402

VOICE = 'zh_CN-huayan-medium'

# (要念的真值, 原始文本, 期望在听回文本里出现的形式, 原始写法是否本来就念不对)
CASES = [
    ('12.1957V', '电池电压12.1957伏特。', '12.2', True),   # 工具原始值就是 4 位小数
    ('47.2°C', '机内温度47.2摄氏度。', '47.2', False),
    ('2.7m/s', '当前风速2.7米每秒。', '2.7', False),
    ('92.1%', '内存占用92.1%。', '92.1', False),
]

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


def say(text):
    """合成 → 用板端 ASR 听回。返回 (听回的文本, 时长秒)。"""
    path = tts_service.synthesize_multilingual(text, VOICE)
    x, sr = V.read_wav_mono(path)
    segs, _ms = V.transcribe_pcm(x, sr, enhance=True, min_seconds=0.30)
    heard = ' '.join((s.get('text') or '').strip() for s in segs).strip()
    return heard, len(x) / float(sr)


def norm(heard):
    """ASR 有时把小数点写成「点」（听到十二点三七却写成 12点37），归一化再比。"""
    return re.sub(r'(?<=\d)[点.](?=\d)', '.', heard or '')


def num_in(heard, want):
    """听回的文本里是否出现了这个数值（ASR 习惯写回阿拉伯数字）。"""
    h = norm(heard)
    return want in h or want.rstrip('0').rstrip('.') in h


print('=== 1. 原始写法 vs 口语化写法（ASR 只当旁证，它自己也有误差）===')
print('    同一个输入两次转写结果可能不同，所以「听回对不对」不作判据；判据是')
print('    「送去合成的文本已经不含阿拉伯小数」+ 人耳听到的现场。')
for label, raw, want, _bad in CASES:
    spoken = S.speakable(raw)
    h_raw, s_raw = say(raw)
    h_cn, s_cn = say(spoken)
    print('  %s' % label)
    print('     原始：%s → 听回 %s（%.1fs）' % (raw, h_raw or '（没听出）', s_raw))
    print('     口语：%s → 听回 %s（%.1fs）' % (spoken, h_cn or '（没听出）', s_cn))
    check('%s：口语化后听回含 %s' % (label, want), num_in(h_cn, want), h_cn)

print('\n=== 2. 确定性事实（不依赖 ASR）===')
check('口语化确实改掉了要合成的文本',
      all(S.speakable(raw) != raw for _l, raw, _w, _b in CASES))
check('口语化后的文本里没有带小数点的阿拉伯数字',
      all(not re.search(r'\d+\.\d', S.speakable(raw)) for _l, raw, _w, _b in CASES))

print('\n=== 3. 整句播报（默认模板 + 实时值）===')
try:
    import announce_service as A
    vals = {'time_cn': '北京时间十九点四十五分', 'battery': 12.369, 'pv': 6.1445,
            'cpu_temp': 47.2, 'load1': 0.85, 'mem_percent': 92.1, 'uptime_h': 10.1,
            'wind': 2.7, 'rain_today': 0.0, 'wx_temp': 31.5, 'wx_temp_max': 35.0,
            'wx_temp_min': 25.5, 'wx_humidity': 56, 'wx_wind': 2.7, 'wx_condition': '晴',
            'weekday': '六'}
    import re

    def expand(t, v=None):
        vv = dict(vals)
        vv.update(v or {})
        return re.sub(r'\{([a-z_][a-z0-9_]*)\}',
                      lambda m: str(vv.get(m.group(1), m.group(0))), t)

    text = A.compose({'time': True, 'status': True}, A.DEFAULTS, vals, expand=expand)
    spoken = S.speakable(text)
    print('  播报文本：%s' % spoken)
    heard, secs = say(spoken)
    print('  听回    ：%s（%.1fs）' % (heard, secs))
    check('听回含电压 12.37', num_in(heard, '12.37') or '十二点三七' in heard, heard)
    check('听回含温度 47.2', num_in(heard, '47.2') or '四十七点二' in heard, heard)
    # ASR 把时刻写成 19点45 / 19:45 都算对（它自己也习惯把「点」换成数字）
    check('听回含时刻「十九点四十五分」',
          ('19.45' in norm(heard) or '19:45' in heard or '十九点四十五' in heard), heard)
except Exception as e:
    check('整句播报验收', False, '%s: %s' % (type(e).__name__, e))

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  x %s' % f)
sys.exit(1 if FAIL else 0)
