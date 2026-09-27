# -*- coding: utf-8 -*-
"""「答非所据」检测的自测（纯函数，不需要板子/LLM）。

背景：板端 1.5B 有约 1/3 的概率把约束里的**范式例句**当答案照抄（问「电池电压是多少」
答「早上好，友台，呼叫信号为59，喵」），也有数据在手里却答「不确定。喵」的情况。
靠提示词治不好（同一份约束下时好时坏），所以做成「可判定 + 带数据重试一次」。
这份自测盯的就是判定本身：该判过关的别重试，该判不过关的别放过。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent_service as A                                          # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


DATA = [{'get_power': {'battery_v': 11.2138, 'battery_raw': 2524, 'pv_v': 5.0756,
                       'pv_raw': 679}},
        {'get_system': {'cpu_temp_c': 54.5, 'cpu_percent': 16.5, 'load1': 2.63,
                        'mem_percent': 69.3, 'disk_free_gb': 13.2, 'uptime_h': 11.2}}]
NESTED = [{'get_nearby_stations': {'count': 2, 'stations': [
    {'call': 'BG7LTG', 'km': 2.5}, {'call': 'BG7LTG-7', 'km': 2.7}]}}]

print('\n=== 1. 从工具数据里抽事实 ===')
facts = A.data_facts(DATA)
print('     %s' % facts)
check('数值给原样数字串', '11.2138' in facts and '54.5' in facts)
check('数值同时给中文口语（四舍五入两位）',
      '十一点二一' in facts and '五十四点五' in facts, facts)
check('单字值不参与判定（「零」几乎出现在任何句子里）', '0' not in facts and '零' not in facts,
      facts)
check('嵌套结构也能抽出来', 'BG7LTG' in A.data_facts(NESTED)
      and 'BG7LTG-7' in A.data_facts(NESTED), A.data_facts(NESTED))
check('空数据得到空列表', A.data_facts([]) == [] and A.data_facts(None) == [])

print('\n=== 2. 判定：过关的三种情况 ===')
cases = [
    ('复述了数字原样', '当前电池电压是11.2138伏。', True),
    ('复述了数值（中文，两位）', '电池电压是十一点二一伏特喵。', True),
    ('复述了温度（中文）', '机内温度五十四点五摄氏度。', True),
    ('复述了内存占用', '内存占用百分之六十九点三。', True),
    ('明确说不知道', '不知道喵。', True),
    ('明确说无法确定', '当前位置无法确定喵。', True),
    ('没有可核对的事实', '中继台运行正常。', True),
]
for name, reply, want in cases:
    got, why = A.answer_grounded(reply, DATA if '事实' not in name else [])
    check('%s → %s' % (name, '过关' if want else '不过关'), got == want, '%s / %s' % (got, why))

print('\n=== 3. 判定：该判不过关的 ===')
bad_cases = [
    ('照抄范式例句（真机实测的那种）', '早上好，友台，呼叫信号为59，喵。'),
    ('把约束规则念出来', '听到"CQ CQ CQ，这里是（呼号），呼叫智能中继"时，我以"早上好"回答。'),
    ('只说结论不带数', '电压偏低，光伏没在充电。'),
    ('空回复', ''),
]
for name, reply in bad_cases:
    got, why = A.answer_grounded(reply, DATA)
    check('%s → 判不过关' % name, got is False, '%s / %s' % (got, why))

print('\n=== 4. 要不要重试 ===')
check('数据问题 + 没用到数据 → 重试',
      A.needs_data_retry('早上好，友台，呼叫信号为59，喵。', DATA,
                         '当前电池电压是多少？')[0] is True)
check('数据问题 + 用上了 → 不重试',
      A.needs_data_retry('电池电压十一点二一伏特喵。', DATA, '当前电池电压是多少？')[0] is False)
check('非数据问题 → 不重试（哪怕回复很空）',
      A.needs_data_retry('晚上好呀。', DATA, '晚上好')[0] is False)
check('没有工具数据 → 不重试',
      A.needs_data_retry('不知道喵。', [], '电压多少')[0] is False)
check('空数据 + 空回复也不重试', A.needs_data_retry('', [], '')[0] is False)

print('\n=== 5. 重试消息本身（顺序是实测定的）===')
_msgs = A.retry_messages([{'get_power': {'battery_v': 11.2138}}], '当前电池电压是多少？')
_c = _msgs[0]['content']
print('     %s' % _c.replace('\n', ' / '))
check('只有一条 user 消息', len(_msgs) == 1 and _msgs[0]['role'] == 'user')
check('要求说出数值', '数值' in _c, _c)
check('保留「确实没有才说不知道」', '不知道' in _c, _c)
check('带上「喵」（与出口兜底一致）', '喵' in _c, _c)
check('把工具数据带上了', '11.2138' in _c, _c)
check('数据在格式要求之后', _c.index('设备实时数据') > _c.index('【重试】'), _c)
check('问题在最后一段（板端只理最后一段）',
      _c.rstrip().endswith('当前电池电压是多少？'), _c[-40:])
check('重试不带那份输出约束（人格/范式会把回答带偏）', '通联范式' not in _c, _c)
check('拒绝词表覆盖实测出现的说法',
      all(w in A.REFUSAL_WORDS for w in ('不知道', '不确定', '没数据', '暂无')))

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  x %s' % f)
sys.exit(1 if FAIL else 0)
