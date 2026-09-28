# -*- coding: utf-8 -*-
"""LLM 提供方选择：auto（有网走外部 API，不可达/无网络回退本地）/ local / external。

为什么单独一个模块：选提供方的地方有**六个**（全局 provider_config、网页对话、
Agent 对话、语音助手、决策层、状态接口）。如果各写一遍，早晚出现「网页走外部、
助手走本地」这种两处各说各话 —— 本项目在提示词上已经踩过这个坑。

两条设计原则：
  * **纯逻辑与 IO 分开**：`pick()` / `resolve()`（probe 可注入）是纯函数，本地套件
    直接测决策表；真正的网络探测只有一个入口，带缓存。
  * **探测不花 token**：只做 DNS + TCP 连接外部 base_url，不发业务请求。
    整体还有硬超时 —— 没有网络时 `getaddrinfo` 实测能卡十几秒，绝不能挂在
    Flask 请求线程上。
  * 真实调用失败（连接级）可以 `mark_external_failed()`：缓存立刻改判不可达，
    下一个请求马上走本地，不用等 TTL 过期。
"""
import socket
import threading
import time
from urllib.parse import urlsplit

MODES = ('auto', 'local', 'external')
DEFAULT_MODE = 'auto'
# 探测结果缓存秒数。太短 = 每次请求都去连外网（没网时每个请求都要等超时），
# 太长 = 网络恢复了还在用本地。60 秒是「网络抖动一次最多影响一分钟」的折中。
PROBE_TTL = 60.0
# 单次 TCP 连接超时 / 整体硬超时
PROBE_TIMEOUT = 2.0
HARD_TIMEOUT = 3.0

MODE_LABEL = {
    'auto': '自动（网络正常用外部 API，不可达/无网络退回本地）',
    'local': '仅本地模型',
    'external': '仅外部 API',
}
# 结论码 → 人话（页面与日志共用，避免两处各翻一套）
REASON_LABEL = {
    'explicit': '按设置指定',
    'net-ok': '网络可达',
    'net-fail': '外部 API 不可达',
    'dns-fail': '域名解析失败（多半没网）',
    'tcp-fail': '连接外部 API 失败',
    'timeout': '探测超时（多半没网）',
    'call-failed': '外部 API 调用失败，已临时降级',
    'no-external-url': '外部 API 未配置地址',
    'no-external-key': '外部 API 未配置 Key',
    'no-local': '本地 LLM 未配置地址',
    'none': '两边都没配置',
    'cold': '尚未探测',
}

_lock = threading.Lock()
_cache = {}          # key(host:port) -> {'ts','ok','reason','ms','host','detail'}
_last_sel = {}       # 最近一次解析结果，供页面显示


def normalize_mode(v):
    v = str(v or '').strip().lower()
    return v if v in MODES else DEFAULT_MODE


def split_url(url):
    """从 base_url 取 (host, port)。没写协议按 http 处理。"""
    u = str(url or '').strip()
    if not u:
        return '', 0
    if '://' not in u:
        u = 'http://' + u
    try:
        p = urlsplit(u)
    except Exception:
        return '', 0
    host = p.hostname or ''
    try:
        port = int(p.port or (443 if p.scheme == 'https' else 80))
    except Exception:
        port = 0
    return host, port


def pick(mode, net_ok, ext_ok, ext_reason='', local_ok=True):
    """决策表（纯函数）：返回 (provider, reason)。

    ext_ok  = 外部 API 配置齐备**且**此刻可达
    ext_reason = 外部不可用的原因码（用于给页面显示为什么回退了）
    """
    mode = normalize_mode(mode)
    if mode == 'local':
        return 'local', 'explicit'
    if mode == 'external':
        return 'external', 'explicit'
    # auto：有网且外部配好了就用外部；否则本地；本地也没有才退回外部
    if ext_ok and net_ok:
        return 'external', 'net-ok'
    if local_ok:
        return 'local', (ext_reason or 'net-fail')
    if ext_ok:
        return 'external', 'no-local'
    return 'local', (ext_reason or 'none')


def _probe_raw(url, timeout=PROBE_TIMEOUT):
    """DNS + TCP 连接。返回 (ok, reason, ms, detail)。"""
    host, port = split_url(url)
    if not host or not port:
        return False, 'no-external-url', 0, ''
    t0 = time.time()
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except OSError as e:
        return False, 'dns-fail', int((time.time() - t0) * 1000), str(e)[:80]
    last = ''
    for fam, typ, proto, _cn, sa in (infos or [])[:4]:
        s = None
        try:
            s = socket.socket(fam, typ, proto)
            s.settimeout(timeout)
            s.connect(sa)
            return True, 'tcp-ok', int((time.time() - t0) * 1000), '%s:%s' % (host, port)
        except OSError as e:
            last = type(e).__name__
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
    return False, 'tcp-fail', int((time.time() - t0) * 1000), last


def _probe_hard(url, timeout=PROBE_TIMEOUT, hard=HARD_TIMEOUT):
    """给探测套一层硬超时：没网时 getaddrinfo 可能卡很久（实测十几秒）。"""
    box = {}

    def run():
        try:
            box['r'] = _probe_raw(url, timeout)
        except Exception as e:                       # 兜底：探测自己不许抛
            box['r'] = (False, 'tcp-fail', 0, '%s: %s' % (type(e).__name__, e))

    t = threading.Thread(target=run, name='llm-probe', daemon=True)
    t.start()
    t.join(hard)
    if 'r' not in box:
        return False, 'timeout', int(hard * 1000), '探测线程未在 %.1fs 内返回' % hard
    return box['r']


def probe(url, force=False, ttl=PROBE_TTL):
    """带缓存的可达性探测。返回 {ok, reason, ms, host, age, cached, detail}。"""
    host, port = split_url(url)
    key = '%s:%s' % (host, port)
    now = time.time()
    with _lock:
        item = _cache.get(key)
        if (not force and item and (now - item['ts']) < ttl):
            out = dict(item)
            out['age'] = round(now - item['ts'], 1)
            out['cached'] = True
            return out
    ok, reason, ms, detail = _probe_hard(url)
    with _lock:
        _cache[key] = {'ts': now, 'ok': bool(ok), 'reason': reason, 'ms': int(ms),
                       'host': key, 'detail': detail}
        item = dict(_cache[key])
    item['age'] = 0.0
    item['cached'] = False
    return item


def mark_external_failed(url, reason='call-failed'):
    """真实调用出现连接级失败 → 马上把该外部地址标记为不可达（不用等 TTL）。"""
    host, port = split_url(url)
    key = '%s:%s' % (host, port)
    with _lock:
        old = _cache.get(key) or {}
        _cache[key] = {'ts': time.time(), 'ok': False, 'reason': reason,
                       'ms': int(old.get('ms') or 0), 'host': key,
                       'detail': '真实调用失败'}
    return True


def clear_cache():
    with _lock:
        _cache.clear()


def cache_state():
    """给状态接口/页面看：当前缓存了什么、多旧。"""
    now = time.time()
    with _lock:
        items = [dict(v, age=round(now - v['ts'], 1)) for v in _cache.values()]
    return {'ttl': PROBE_TTL, 'items': items}


def resolve(mode=DEFAULT_MODE, requested=None, external_url='', external_key='',
            local_url='', probe_fn=None, force=False):
    """把「想要谁」解析成**此刻真能用谁**。返回 (provider, reason)。

    requested 是调用方在请求里点名要的（网页对话可以指定）；'local'/'external'
    一律照办 —— 用户在页面上说死了就用哪个，不要偷偷换。
    auto 才看网络。
    """
    req = str(requested or '').strip().lower()
    if req in ('local', 'external'):
        sel = (req, 'explicit')
        _remember(sel, mode, external_url)
        return sel
    if req == 'auto':
        mode = 'auto'
    mode = normalize_mode(mode)

    ext_url = str(external_url or '').strip()
    ext_key = str(external_key or '').strip()
    local_ok = bool(str(local_url or '').strip())

    ext_reason = ''
    if not ext_url:
        ext_reason = 'no-external-url'
    elif not ext_key:
        ext_reason = 'no-external-key'
    net = False
    if mode == 'auto' and ext_url and not ext_reason:
        # 真实探测走带缓存的 probe()；套件里注入 probe_fn 换成假的（可注入才好测）
        res = probe(ext_url, force=force) if probe_fn is None else probe_fn(ext_url)
        net = bool((res or {}).get('ok'))
        if not net:
            ext_reason = (res or {}).get('reason') or 'net-fail'
    sel = pick(mode, net, bool(ext_url and not ext_reason), ext_reason, local_ok)
    _remember(sel, mode, ext_url)
    return sel


def _remember(sel, mode, ext_url):
    with _lock:
        _last_sel.clear()
        _last_sel.update({'provider': sel[0], 'reason': sel[1],
                          'mode': normalize_mode(mode), 'external_url': ext_url,
                          'ts': time.time()})


def last_selection():
    with _lock:
        out = dict(_last_sel)
    if out:
        out['reason_label'] = REASON_LABEL.get(out.get('reason'), out.get('reason'))
        out['mode_label'] = MODE_LABEL.get(out.get('mode'), out.get('mode'))
        out['age'] = round(time.time() - float(out.get('ts') or 0), 1)
    return out
