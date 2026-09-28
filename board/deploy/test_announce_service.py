# -*- coding: utf-8 -*-
"""定时播报纯计算层自测（不需板子、不需 Flask、不发声）。"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import announce_service as A

FAIL, OK = [], [0]


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


print('\n=== 1. 中文数字读法 ===')
check('0 → 零', A.cn_num(0) == '零')
check('9 → 九', A.cn_num(9) == '九')
check('10 → 十', A.cn_num(10) == '十')
check('14 → 十四', A.cn_num(14) == '十四')
check('20 → 二十', A.cn_num(20) == '二十')
check('21 → 二十一', A.cn_num(21) == '二十一')
check('59 → 五十九', A.cn_num(59) == '五十九')
check('垃圾输入不崩', A.cn_num('x') == 'x' and A.cn_num(None) == 'None')

print('\n=== 2. 时间变量 ===')
v = A.clock_vars(datetime(2026, 9, 27, 14, 0))
check('整点读作「北京时间十四点整」', v['time_cn'] == '北京时间十四点整', v['time_cn'])
check('整点给出 hour_cn', v['hour_cn'] == '十四')
v2 = A.clock_vars(datetime(2026, 9, 27, 8, 5))
check('非整点读作「八点零五分」', v2['time_cn'] == '北京时间八点零五分', v2['time_cn'])
check('非整点给出 minute_cn', v2['minute_cn'] == '零五', v2['minute_cn'])
check('0 点读作「零点整」', A.clock_vars(datetime(2026, 9, 27, 0, 0))['time_cn']
      == '北京时间零点整')

print('\n=== 3. 整点表解析 ===')
check('正常逗号串', A.parse_hours('8,10,12') == (8, 10, 12))
check('空格/顿号/分号混合', A.parse_hours('8 10、12;14') == (8, 10, 12, 14))
check('去重并升序', A.parse_hours('12,8,12,10') == (8, 10, 12))
check('越界值被丢弃', A.parse_hours('-1,24,25,8') == (8,))
check('垃圾输入得空元组', A.parse_hours('abc,xyz') == ())
check('空串得空元组（不替用户兜默认值）', A.parse_hours('') == ())
check('None 得空元组', A.parse_hours(None) == ())
check("'08' 这种补零也认", A.parse_hours('08,09') == (8, 9))
check('小数向下取整', A.parse_hours('8.9') == (8,))
check('回写串可往返', A.parse_hours(A.hours_to_str((8, 12, 20))) == (8, 12, 20))
check('回写串去重升序', A.hours_to_str((20, 8, 8)) == '8,20')

print('\n=== 4. 模块开关 ===')
check('全关 → 空列表', A.enabled_modules({}) == [])
check('只开时间', A.enabled_modules({'time': True}) == ['time'])
check('三类顺序固定（时间→状态→气象）',
      A.enabled_modules({'weather': True, 'time': True, 'status': True})
      == ['time', 'status', 'weather'])
check('显式 False 不算开', A.enabled_modules({'time': False, 'status': True}) == ['status'])

print('\n=== 5. 文案组装 ===')
EXP = lambda t, v=None: (t.replace('{time_cn}', (v or {}).get('time_cn', 'X'))
                         .replace('{battery}', '12.6'))
FLAGS3 = {'time': True, 'status': True, 'weather': True}
TPL = {'time': '现在是{time_cn}', 'status': '电压{battery}伏特',
       'weather': '风速2米每秒'}
out = A.compose(FLAGS3, TPL, {'time_cn': '北京时间十四点整'}, expand=EXP)
check('三段都拼进来', out.count('。') == 3, out)
check('顺序为 时间→状态→气象', out.index('现在是') < out.index('电压') < out.index('风速'), out)
check('模板末尾自动补句号', '现在是北京时间十四点整。' in out, out)
check('已带句号的不重复补', '电压12.6伏特。' in out and '。。' not in out, out)
check('变量被展开', '{battery}' not in out and '12.6' in out, out)

only_t = A.compose({'time': True}, TPL, {'time_cn': '北京时间十四点整'}, expand=EXP)
check('只开时间就只播时间', '电压' not in only_t and '风速' not in only_t, only_t)
check('全关得空串（调用方据此不发）', A.compose({}, TPL, {}, expand=EXP) == '')
check('模板为空时回落到默认模板',
      '北京时间' in A.compose({'time': True}, {'time': ''},
                              {'time_cn': '北京时间十四点整'}, expand=EXP))
check('展开器抛异常时用原文兜底（不丢播报）',
      '现在是{time_cn}。' == A.compose({'time': True}, {'time': '现在是{time_cn}'}, {},
                                      expand=lambda t, v=None: 1 / 0))
check('只收一个参数的展开器也兼容',
      'X' == A.compose({'time': True}, {'time': 'X'},
                       expand=lambda t: t).rstrip('。'))
long_tpl = {'time': '啊' * 500}
check('超长文案被截到上限', len(A.compose({'time': True}, long_tpl, expand=lambda t, v=None: t))
      <= A.TEXT_LIMIT)

print('\n=== 6. 整点该不该播 ===')
H = A.parse_hours('8,14,20')
fired = set()
check('所选整点、且刚过整点 30s → 该播',
      A.due_hour(datetime(2026, 9, 27, 14, 0, 30), H, fired) == '2026-09-27 14')
check('不在所选整点 → 不播',
      A.due_hour(datetime(2026, 9, 27, 15, 0, 30), H, fired) is None)
check('已播过（fired 里有）→ 不播',
      A.due_hour(datetime(2026, 9, 27, 14, 0, 30), H, {'2026-09-27 14'}) is None)
check('超出 grace（14:05）→ 不播（重启后不补播过期的）',
      A.due_hour(datetime(2026, 9, 27, 14, 5, 0), H, fired) is None)
check('整点前 1 秒 → 不播',
      A.due_hour(datetime(2026, 9, 27, 13, 59, 59), H, fired) is None)
check('0 点也在表里时 00:00:10 该播',
      A.due_hour(datetime(2026, 9, 27, 0, 0, 10), A.parse_hours('0'), set())
      == '2026-09-27 00')
check('空整点表 → 永不播',
      A.due_hour(datetime(2026, 9, 27, 14, 0, 1), (), set()) is None)
check('垃圾时间对象不崩', A.due_hour('不是时间', H, set()) is None)

print('\n=== 7. 禁发时段 ===')
check('空值不禁发', A.in_quiet_hours('', datetime(2026, 9, 27, 3, 0)) is False)
check('同日段内', A.in_quiet_hours('23:00-07:00', datetime(2026, 9, 27, 3, 0)) is True)
check('同日段外', A.in_quiet_hours('23:00-07:00', datetime(2026, 9, 27, 12, 0)) is False)
check('跨零点两侧都命中',
      A.in_quiet_hours('22:00-06:00', datetime(2026, 9, 27, 23, 30)) is True
      and A.in_quiet_hours('22:00-06:00', datetime(2026, 9, 27, 5, 30)) is True)
check('多段', A.in_quiet_hours('12:00-13:00,18:00-19:00',
                               datetime(2026, 9, 27, 18, 30)) is True)
check('边界含头不含尾', A.in_quiet_hours('12:00-13:00',
                                        datetime(2026, 9, 27, 13, 0)) is False)
check('垃圾输入不禁发', A.in_quiet_hours('abc', datetime(2026, 9, 27, 3, 0)) is False)

print('\n' + '=' * 62)
print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
for f in FAIL:
    print('  ✗ %s' % f)
sys.exit(1 if FAIL else 0)
