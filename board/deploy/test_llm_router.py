# -*- coding: utf-8 -*-
"""LLM 提供方解析（auto / local / external）纯逻辑 + 真实探测自测。

不需要板子、不需要模型：网络探测用**本机真实 TCP 监听**验（起一个 socket 就算
「网络可达」），决策表全部用注入的假探测。

覆盖：
  1. 模式归一化
  2. 决策表 pick()（auto 的四条分支 + 显式模式绝不自动切换）
  3. resolve() 端到端（含「没配外部就不该去探测」这条省事又省时的规则）
  4. base_url 解析（协议/端口/缺省端口）
  5. 真实探测 + 60 秒缓存 + force 重探
  6. 调用失败降级 mark_external_failed
  7. 探测硬超时（没网时不能把请求线程挂住）
  8. 结论码字典齐全（页面要拿它翻人话）
"""
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
import llm_router as R          # noqa: E402

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
print('\n=== 1. 模式归一化 ===')
check('空值 → auto（默认）', R.normalize_mode('') == 'auto'
      and R.normalize_mode(None) == 'auto')
check('大小写/空格容错', R.normalize_mode(' AUTO ') == 'auto')
check('三种合法值原样返回',
      [R.normalize_mode(x) for x in ('auto', 'local', 'external')]
      == ['auto', 'local', 'external'])
check('乱写 → auto（不是 local）', R.normalize_mode('banana') == 'auto')
check('DEFAULT_MODE 是 auto', R.DEFAULT_MODE == 'auto')

# ---------------------------------------------------------------------------
print('\n=== 2. 决策表 pick() ===')
check('auto + 有网 + 外部配好 → 外部',
      R.pick('auto', True, True, '', True) == ('external', 'net-ok'))
check('auto + 没网 + 本地可用 → 本地',
      R.pick('auto', False, True, 'dns-fail', True) == ('local', 'dns-fail'))
check('auto + 外部没配 → 本地',
      R.pick('auto', False, False, 'no-external-url', True)
      == ('local', 'no-external-url'))
check('auto + 没网 + 本地也没配 → 退回外部（能试就试）',
      R.pick('auto', False, True, 'net-fail', False) == ('external', 'no-local'))
check('auto + 有网 + 外部配好 + 本地没配 → 外部',
      R.pick('auto', True, True, '', False) == ('external', 'net-ok'))
check('仅本地：有网也不换外部', R.pick('local', True, True, '', True)
      == ('local', 'explicit'))
check('仅外部：没网也不换本地', R.pick('external', False, True, 'net-fail', True)
      == ('external', 'explicit'))
check('仅外部：外部没配也照办（照办才会暴露配置错误）',
      R.pick('external', False, False, 'no-external-url', True)
      == ('external', 'explicit'))
check('两边都没配 → 本地（至少给出可诊断的结论）',
      R.pick('auto', False, False, 'no-external-url', False)
      == ('local', 'no-external-url'))

# ---------------------------------------------------------------------------
print('\n=== 3. resolve() 端到端（探测可注入） ===')
CALLS = []


def probe_ok(url):
    CALLS.append(url)
    return {'ok': True, 'reason': 'tcp-ok', 'ms': 12}


def probe_bad(url):
    CALLS.append(url)
    return {'ok': False, 'reason': 'dns-fail', 'ms': 8}


EXT = 'https://api.example.com/v1'
KEY = 'sk-test'
LOCAL = 'http://127.0.0.1:8001/v1'

CALLS.clear()
check('auto + 探测可达 → 外部',
      R.resolve('auto', external_url=EXT, external_key=KEY, local_url=LOCAL,
                probe_fn=probe_ok) == ('external', 'net-ok'))
check('确实探测了外部地址', CALLS == [EXT], CALLS)

CALLS.clear()
check('auto + 探测不可达 → 本地，且原因来自探测',
      R.resolve('auto', external_url=EXT, external_key=KEY, local_url=LOCAL,
                probe_fn=probe_bad) == ('local', 'dns-fail'))

CALLS.clear()
check('外部地址没配 → 本地，且**不去探测**（省掉每次请求的等待）',
      R.resolve('auto', external_url='', external_key=KEY, local_url=LOCAL,
                probe_fn=probe_ok) == ('local', 'no-external-url')
      and CALLS == [], CALLS)

CALLS.clear()
check('外部缺 Key → 本地，也不探测',
      R.resolve('auto', external_url=EXT, external_key='', local_url=LOCAL,
                probe_fn=probe_ok) == ('local', 'no-external-key')
      and CALLS == [], CALLS)

check('请求里点名 local → 一律照办（有网也不换）',
      R.resolve('auto', requested='local', external_url=EXT, external_key=KEY,
                local_url=LOCAL, probe_fn=probe_ok) == ('local', 'explicit'))
check('请求里点名 external → 一律照办（没网也不换）',
      R.resolve('auto', requested='external', external_url=EXT, external_key=KEY,
                local_url=LOCAL, probe_fn=probe_bad) == ('external', 'explicit'))
check('请求里点名 auto → 按 auto 判（盖过设置里的 local）',
      R.resolve('local', requested='auto', external_url=EXT, external_key=KEY,
                local_url=LOCAL, probe_fn=probe_ok) == ('external', 'net-ok'))
check('设置仅本地 → 不探测',
      R.resolve('local', external_url=EXT, external_key=KEY, local_url=LOCAL,
                probe_fn=probe_ok) == ('local', 'explicit'))
check('设置仅外部 → 不探测',
      R.resolve('external', external_url=EXT, external_key=KEY, local_url=LOCAL,
                probe_fn=probe_ok) == ('external', 'explicit'))
check('设置值乱写 → 按 auto 处理',
      R.resolve('banana', external_url=EXT, external_key=KEY, local_url=LOCAL,
                probe_fn=probe_bad) == ('local', 'dns-fail'))
_last = R.last_selection()
check('记住最近一次解析结果（页面/日志用）',
      _last.get('provider') == 'local' and _last.get('reason') == 'dns-fail'
      and _last.get('mode') == 'auto', _last)
check('最近一次结果自带中文说明',
      bool(_last.get('reason_label')) and bool(_last.get('mode_label')), _last)

# ---------------------------------------------------------------------------
print('\n=== 4. base_url 解析 ===')
check('https 缺省 443', R.split_url('https://api.deepseek.com/v1') ==
      ('api.deepseek.com', 443))
check('http 缺省 80', R.split_url('http://127.0.0.1/v1') == ('127.0.0.1', 80))
check('显式端口', R.split_url('http://127.0.0.1:8001/v1') == ('127.0.0.1', 8001))
check('不写协议按 http', R.split_url('api.example.com:8443/v1') ==
      ('api.example.com', 8443))
check('空值', R.split_url('') == ('', 0) and R.split_url(None) == ('', 0))
check('带路径与查询也不受影响',
      R.split_url('https://h.example.com:9443/a/b?c=1')[0] == 'h.example.com')

# ---------------------------------------------------------------------------
print('\n=== 5. 真实探测 + 缓存 + force 重探 ===')
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('127.0.0.1', 0))
srv.listen(8)
PORT = srv.getsockname()[1]
STOP = {'v': False}


def acceptor():
    srv.settimeout(0.3)
    while not STOP['v']:
        try:
            c, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            c.close()
        except Exception:
            pass


th = threading.Thread(target=acceptor, daemon=True)
th.start()
URL = 'http://127.0.0.1:%d/v1' % PORT

R.clear_cache()
p1 = R.probe(URL)
check('起一个本地监听 → 探测可达（真实 DNS+TCP 路径）',
      p1['ok'] is True and p1['reason'] == 'tcp-ok', p1)
check('首次探测不是缓存命中', p1['cached'] is False)
p2 = R.probe(URL)
check('第二次走缓存（60 秒内不再连）', p2['cached'] is True and p2['ok'] is True, p2)

# 关掉监听，缓存里仍然是「可达」——这正是 TTL 的意义：不能每个请求都去连
STOP['v'] = True
try:
    srv.close()
except Exception:
    pass
time.sleep(0.4)
p3 = R.probe(URL)
check('监听关掉后仍读缓存（TTL 内不重复探测）',
      p3['ok'] is True and p3['cached'] is True, p3)
p4 = R.probe(URL, force=True)
check('force 重探 → 立刻变不可达', p4['ok'] is False and p4['cached'] is False, p4)

# ---------------------------------------------------------------------------
print('\n=== 6. 真实调用失败 → 立刻降级 ===')
R.clear_cache()
R.probe('http://127.0.0.1:%d/v1' % PORT, force=True)     # 先留一个可达的缓存
R.mark_external_failed('http://127.0.0.1:%d/v1' % PORT)
p5 = R.probe('http://127.0.0.1:%d/v1' % PORT)
check('标记失败后缓存立刻改判不可达（不等 TTL）',
      p5['ok'] is False and p5['reason'] == 'call-failed', p5)
sel = R.resolve('auto', external_url='http://127.0.0.1:%d/v1' % PORT,
                external_key='k', local_url=LOCAL)
check('于是 auto 立刻回退本地', sel == ('local', 'call-failed'), sel)
check('缓存快照可读（页面显示用）',
      isinstance(R.cache_state().get('items'), list)
      and R.cache_state()['ttl'] == R.PROBE_TTL)

# ---------------------------------------------------------------------------
print('\n=== 7. 探测硬超时（不能把请求线程挂住） ===')
R.clear_cache()
t0 = time.time()
p6 = R.probe('http://10.255.255.1:9/v1')      # 不可路由地址：连接会一直等
dt = time.time() - t0
check('不可达地址在硬超时内返回', p6['ok'] is False, p6)
check('耗时不超过硬超时 + 余量（实测 %.1fs）' % dt, dt <= R.HARD_TIMEOUT + 1.5,
      '%.2fs' % dt)

# ---------------------------------------------------------------------------
print('\n=== 8. 结论码字典齐全 ===')
codes = ['explicit', 'net-ok', 'net-fail', 'dns-fail', 'tcp-fail', 'timeout',
         'call-failed', 'no-external-url', 'no-external-key', 'no-local', 'none']
missing = [c for c in codes if c not in R.REASON_LABEL]
check('生产代码会产出的结论码都有中文说明', not missing, missing)
check('三种模式都有中文说明',
      all(m in R.MODE_LABEL for m in R.MODES), sorted(R.MODE_LABEL))
check('MODES 顺序是 auto/local/external', R.MODES == ('auto', 'local', 'external'))

print('\n%d 通过 / %d 失败' % (OK[0], len(FAIL)))
if FAIL:
    print('失败用例：')
    for f in FAIL:
        print('  - %s' % f)
    sys.exit(1)
