# -*- coding: utf-8 -*-
"""能量统计（电池 / 光伏电压时间序列）的纯计算层。

只做这几件事，**不依赖 Flask、不碰硬件**，便于离线自测：
  * points_from_rows —— 原始采样点按 N 分钟分桶成曲线点（可带滤波列）
  * smooth / median_filter / hampel —— 曲线与统计用的滤波（纯函数）
  * rested_voltage   —— 静息电压估计（剔除发射中的采样后取中位数）
  * day_stats        —— 当日统计：原始一套 + 滤波一套（含疑似负载跌落点数）
  * rows_to_csv      —— 整日序列导出

为什么要滤波（2026-09-29 板端实测，不是拍脑袋）：
  * 电池节点上有一个快纹波，**单个瞬时采样只是抓到了它的某个相位**。
    实测：以 100ms 采 10 秒，看起来像周期 3.4 秒的锯齿；改成 37ms 取样，
    锯齿周期随之变成 0.30 秒 —— 周期跟着采样率走，说明是**混叠**而不是真慢振荡。
  * **更狠的一条**：ADC 读得越密，读数越低 —— 读 3 次（间隔 0.2/0.5s）落差
    0.85~1.0V，间隔 3s 只剩 0.06V；先把节点读趴下再每 0.5s 读一次，读数会在
    7.1~11.2V 游走十几秒。第一版按「每 60ms 读一次、摊开 5 秒」改采样，新采样
    直接落到 7.8V，而每 60 秒只读一次的值是 12.7~12.8V —— 差 5V 全是**测量本身**
    造成的（测量改变被测对象）。所以最终方案是「少读、读得开、取中位数」。
  * 顺带纠正一个直觉：波动**不是发射造成的**。全天 1428 个采样里只有 0.8%
    落在发射窗口内，最深的几个谷都不在窗口里；把发射窗口±5s 全剔除，
    峰谷差一点没变。
"""
from datetime import datetime

UNIT = 'V'

# ---- 采样与滤波参数（都有板端实测依据，改之前先看上面那段）----
# **两次 ADC 读之间必须隔 1.5~3 秒**：读得密会把节点拉低。2026-09-29 实测的
# 恢复过程（先把节点读趴下，再每 0.5s 读一次）清楚显示：0.5s 间隔时读数在 7.1~11.2V
# 之间游走十几秒，而间隔 3s 连读三次只有 13 LSB（0.06V）的落差。
# 我第一版按「每 60ms 读一次、摊开 5 秒」做，结果新采样落到 7.8V，而每 60 秒只读
# 一次的值是 12.7~12.8V —— **差 5V 全是读取本身造成的**，是测量把被测对象改变了。
BURST_READS = 3            # 一轮采样读几次（间隔 BURST_GAP_MS）
BURST_GAP_MS = 3000        # 每读一次 ADC 之间的间隔（毫秒）——见上面的实测
REST_WINDOW_MIN = 30       # 静息电压回看窗口（分钟）
REST_MIN_SAMPLES = 5       # 静息估计至少要有几个采样
FILTER_MODES = ('hampel', 'median', 'none')
FILTER_WINDOW = 9          # Hampel / 中位数窗口（点数）
FILTER_K = 3.0             # Hampel 的 MAD 倍数
# 局部 MAD 为 0 时的兜底尺度（伏）。为什么需要：序列「一片相同值 + 一个尖峰」时
# 邻域偏差里位数正好是 0 → MAD=0 → 经典 Hampel 会**放跑**那个尖峰（实测：
# 12.8×7 里塞一个 8.4，k=3 判定不出来）。这正是电压序列最常见的形态，所以补兜底：
# 先用全序列 MAD，再用这个绝对下限（约 2 个 LSB，不会把 ±1LSB 的噪声当离群）。
HAMPEL_FLOOR_V = 0.01


def clamp_interval(minutes):
    """时间轴分桶间隔（分钟）钳到 1..120。"""
    try:
        v = int(float(minutes))
    except (TypeError, ValueError):
        v = 5
    return max(1, min(120, v))


def clamp_sample_sec(sec):
    """采样间隔（秒）钳到 10..600。"""
    try:
        v = int(float(sec))
    except (TypeError, ValueError):
        v = 60
    return max(10, min(600, v))


def clamp_retention_days(days):
    """保留天数钳到 1..3650。"""
    try:
        v = int(float(days))
    except (TypeError, ValueError):
        v = 365
    return max(1, min(3650, v))


def clamp_burst_reads(sample_sec, want=BURST_READS):
    """一轮采样读几次：由采样间隔倒推，保证「读一轮 + 休眠」装得进一个间隔。

    每读一次之间隔 BURST_GAP_MS，所以 n 次要 (n-1)*gap 秒。留一半时间给休眠，
    免得采样线程一直占着 ADC（占着 ADC 本身就会把读数压低）。
    """
    try:
        s = float(sample_sec)
    except (TypeError, ValueError):
        s = 60.0
    try:
        n = int(want)
    except (TypeError, ValueError):
        n = BURST_READS
    n = max(1, min(5, n))
    budget = max(1.0, s * 0.5)
    gap_s = BURST_GAP_MS / 1000.0
    fit = int(budget / gap_s) + 1
    return max(1, min(n, fit))


def burst_seconds(sample_sec, want=BURST_READS):
    """一轮采样实际占用的秒数（给页面显示口径用）。"""
    n = clamp_burst_reads(sample_sec, want)
    return round((n - 1) * BURST_GAP_MS / 1000.0, 1)


def clamp_filter_window(w):
    try:
        v = int(float(w))
    except (TypeError, ValueError):
        v = FILTER_WINDOW
    if v % 2 == 0:                     # 中位数/Hampel 用奇数窗口才能取正中
        v += 1
    return max(3, min(31, v))


def normalize_filter(mode):
    m = str(mode or '').strip().lower()
    return m if m in FILTER_MODES else 'hampel'


def _f(v):
    try:
        return None if v is None or v == '' else float(v)
    except (TypeError, ValueError):
        return None


def _avg(nums):
    return round(sum(nums) / len(nums), 3) if nums else None


def median_filter(xs, w=FILTER_WINDOW):
    """滑动中位数：对孤立尖峰/跌落最稳，又不像均值那样把台阶抹成斜坡。"""
    w = clamp_filter_window(w)
    h = w // 2
    out = []
    for i in range(len(xs)):
        seg = sorted(xs[max(0, i - h):min(len(xs), i + h + 1)])
        out.append(seg[len(seg) // 2])
    return out


def _mad_scale(xs):
    """1.4826 × MAD（对正态等价于 σ）；全同值时返回 0。"""
    if not xs:
        return 0.0
    m = sorted(xs)[len(xs) // 2]
    mad = sorted(abs(x - m) for x in xs)[len(xs) // 2]
    return 1.4826 * mad


def hampel(xs, w=FILTER_WINDOW, k=FILTER_K):
    """Hampel 滤波：局部中位数 + MAD 判离群，离群点用局部中位数替换。

    返回 (滤波后序列, 离群下标列表)。比纯中位数多一个好处：**能报出剔了几个**，
    页面可以显示「疑似负载跌落 N 点」，而不是悄悄抹掉。

    局部 MAD 退化到 0（邻域几乎全同）时用全序列 MAD 兜底，再退到
    HAMPEL_FLOOR_V —— 否则「一片相同值 + 一个尖峰」这种最常见的形态会被放跑。
    """
    w = clamp_filter_window(w)
    h = w // 2
    k = float(k) if k else FILTER_K
    gscale = _mad_scale(list(xs)) or HAMPEL_FLOOR_V
    out, flags = [], []
    for i in range(len(xs)):
        seg = xs[max(0, i - h):min(len(xs), i + h + 1)]
        m = sorted(seg)[len(seg) // 2]
        sigma = _mad_scale(seg) or gscale
        if sigma > 1e-9 and abs(xs[i] - m) > k * sigma:
            out.append(m)
            flags.append(i)
        else:
            out.append(xs[i])
    return out, flags


def smooth(xs, mode='hampel', w=FILTER_WINDOW, k=FILTER_K):
    """按模式滤波。mode='none' 时原样返回（一条也不改）。"""
    mode = normalize_filter(mode)
    if mode == 'none' or not xs:
        return list(xs), []
    if mode == 'median':
        return median_filter(xs, w), []
    return hampel(xs, w, k)


def _series(rows, key):
    """取出某通道的 (下标, 值) 序列（跳过空值）。"""
    out = []
    for i, r in enumerate(rows or ()):
        v = _f(r.get(key))
        if v is not None:
            out.append((i, v))
    return out


def _filter_channel(rows, key, mode='hampel', w=FILTER_WINDOW, k=FILTER_K):
    """对某通道整段滤波，返回与 rows 等长的列表（空值处为 None）与离群下标。"""
    pairs = _series(rows, key)
    out = [None] * len(rows or ())
    if not pairs:
        return out, []
    filt, flags = smooth([v for _i, v in pairs], mode, w, k)
    for pos, (i, _v) in enumerate(pairs):
        out[i] = round(filt[pos], 4)
    return out, [pairs[p][0] for p in flags]


def points_from_rows(rows, interval_minutes=5, filt='hampel', w=FILTER_WINDOW,
                     k=FILTER_K):
    """原始采样 → 按 interval_minutes 分桶的曲线点（按时间升序）。

    **空桶不补值**：电压 0 是合法读数（电池断开 / 被负载拉死），补 0 会画出一条
    掉到零的假线。缺桶就让它缺，图上的空档老实表达「这段时间没采到」。

    `filt` 不为 'none' 时，额外给出 `battery_f`/`pv_f`（**滤波后的曲线**，
    前端默认画它）与 `*_min/ *_max`（桶内原始极值，保留尖峰作证据）。
    """
    step = clamp_interval(interval_minutes) * 60
    buckets = {}
    for i, r in enumerate(rows or ()):
        e = _f(r.get('ts_epoch'))
        if not e:
            continue
        b = int(e) // step * step
        buckets.setdefault(b, []).append((i, r))

    bat_f, bat_flags = _filter_channel(rows, 'battery', filt, w, k)
    pv_f, _pv_flags = _filter_channel(rows, 'pv', filt, w, k)
    flag_rows = set(bat_flags)

    out = []
    for b in sorted(buckets):
        grp = buckets[b]
        bs = [v for v in (_f(x.get('battery')) for _i, x in grp) if v is not None]
        ps = [v for v in (_f(x.get('pv')) for _i, x in grp) if v is not None]
        bfs = [bat_f[i] for i, _x in grp if bat_f[i] is not None]
        pfs = [pv_f[i] for i, _x in grp if pv_f[i] is not None]
        try:
            t = datetime.fromtimestamp(b)
            minute, hm = t.strftime('%Y-%m-%d %H:%M'), t.strftime('%H:%M')
        except (ValueError, OSError, OverflowError):
            minute, hm = '', ''
        out.append({
            'epoch': b, 'minute': minute, 'time': hm,
            'battery': _avg(bs), 'pv': _avg(ps),
            'battery_f': _avg(bfs), 'pv_f': _avg(pfs),
            'battery_min': round(min(bs), 3) if bs else None,
            'battery_max': round(max(bs), 3) if bs else None,
            'pv_min': round(min(ps), 3) if ps else None,
            'pv_max': round(max(ps), 3) if ps else None,
            'outliers': sum(1 for i, _x in grp if i in flag_rows),
            'n': len(grp),
        })
    return out


def _channel_stats(vals):
    """vals: [(ts, value)] → {min,max,avg,min_ts,max_ts}（无值全 None）。"""
    nums = [v for _, v in vals]
    if not nums:
        return {'min': None, 'max': None, 'avg': None, 'min_ts': '', 'max_ts': '',
                'n': 0}
    lo, hi = min(nums), max(nums)
    return {
        'min': round(lo, 3), 'max': round(hi, 3), 'avg': _avg(nums),
        'min_ts': next(t for t, v in vals if v == lo),
        'max_ts': next(t for t, v in vals if v == hi),
        'n': len(nums),
    }


def rested_voltage(rows, window_min=REST_WINDOW_MIN, now=None, only_idle=True):
    """静息电压估计：回看 window_min 分钟，剔除「发射中」的采样后取中位数。

    为什么取中位数而不是最低值：这是**电量估计**要用的量，得代表「轻载时的电压」；
    发射/大负载期间的低值是真实压降，但它说明不了电量。`load` 列缺省（老数据）时
    不剔除，只用中位数抗离群。

    返回 {battery, pv, samples, window_min, source}；样本不够时 source='insufficient'。
    """
    rows = list(rows or ())
    if not rows:
        return {'battery': None, 'pv': None, 'samples': 0,
                'window_min': int(window_min), 'source': 'none'}
    try:
        cut = float(now) - float(window_min) * 60.0 if now is not None else None
    except (TypeError, ValueError):
        cut = None
    win = []
    for r in rows:
        e = _f(r.get('ts_epoch'))
        if e is None:
            # 没有时间戳的行（理论上不该有）无法按窗口过滤，只能放进来
            win.append(r)
            continue
        if cut is not None and e < cut:
            continue
        win.append(r)

    def collect(key):
        idle, allv = [], []
        for r in win:
            v = _f(r.get(key))
            if v is None:
                continue
            allv.append(v)
            load = r.get('load')
            if only_idle and load in (1, '1', True):
                continue
            idle.append(v)
        return idle, allv

    b_idle, b_all = collect('battery')
    p_idle, p_all = collect('pv')
    src = 'idle-median'
    if len(b_idle) < REST_MIN_SAMPLES:
        b_idle, src = (b_all, 'all-median') if len(b_all) >= REST_MIN_SAMPLES \
            else ([], 'insufficient')
    if len(p_idle) < REST_MIN_SAMPLES:
        p_idle = p_all if len(p_all) >= REST_MIN_SAMPLES else []

    def med(xs):
        if not xs:
            return None
        s = sorted(xs)
        return round(s[len(s) // 2], 3)

    return {'battery': med(b_idle), 'pv': med(p_idle),
            'samples': len(b_idle), 'window_min': int(window_min), 'source': src}


def day_stats(rows, filt='hampel', w=FILTER_WINDOW, k=FILTER_K, now=None):
    """当日统计。

    **原始 min/max 仍然保留**（这是刻意的取舍：电压尖峰——发射瞬间的压降——恰恰
    是最该看到的，均值/中位数会把它抹平）。滤波后的那一套放在 `battery_f`/`pv_f`
    里，供「电量估计/趋势」使用；两套数并列给页面，不做取舍。
    """
    rows = list(rows or ())
    bat = [(r.get('ts') or '', _f(r.get('battery'))) for r in rows]
    pv = [(r.get('ts') or '', _f(r.get('pv'))) for r in rows]
    b = _channel_stats([(t, v) for t, v in bat if v is not None])
    p = _channel_stats([(t, v) for t, v in pv if v is not None])
    drop = None
    if b['max'] is not None and b['min'] is not None:
        drop = round(b['max'] - b['min'], 3)

    bf, bflags = _filter_channel(rows, 'battery', filt, w, k)
    pf, pflags = _filter_channel(rows, 'pv', filt, w, k)
    bf_pairs = [(r.get('ts') or '', bf[i]) for i, r in enumerate(rows)
                if bf[i] is not None]
    pf_pairs = [(r.get('ts') or '', pf[i]) for i, r in enumerate(rows)
                if pf[i] is not None]
    bfs = _channel_stats(bf_pairs)
    pfs = _channel_stats(pf_pairs)
    out = {'points': len(rows), 'battery': b, 'pv': p, 'battery_drop': drop,
           'first_ts': rows[0].get('ts', '') if rows else '',
           'last_ts': rows[-1].get('ts', '') if rows else '',
           'filter': normalize_filter(filt), 'filter_window': clamp_filter_window(w),
           'battery_f': bfs, 'pv_f': pfs,
           'battery_drop_f': (round(bfs['max'] - bfs['min'], 3)
                              if bfs['max'] is not None and bfs['min'] is not None
                              else None),
           'pv_drop_f': (round(pfs['max'] - pfs['min'], 3)
                         if pfs['max'] is not None and pfs['min'] is not None
                         else None),
           'outliers': len(bflags), 'outliers_pv': len(pflags),
           'rested': rested_voltage(rows, now=now)}
    return out



CSV_HEADER = ('时间,时间戳,电池电压V,光伏电压V,电池ADC,光伏ADC,'
              '电池最低V,电池最高V,光伏最低V,光伏最高V,本轮读数,发射中\n')


def rows_to_csv(rows):
    """整日序列导出。含 BOM 由调用方加——Excel 打开中文表头才不会乱码。

    新增的 min/max/n_reads/load 是采样层摊开取中位数之后的证据列：
    中位数是存下来的值，min/max 保留纹波/压降的真实幅度，load 标记这一轮里
    是否正在发射（静息电压估计用它）。
    """
    def g(r, k):
        v = r.get(k)
        return '' if v is None else v

    out = [CSV_HEADER]
    for r in rows or ():
        b = _f(r.get('battery'))
        p = _f(r.get('pv'))
        out.append('%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' % (
            r.get('ts') or '', r.get('ts_epoch') or '',
            '' if b is None else ('%.4f' % b),
            '' if p is None else ('%.4f' % p),
            g(r, 'battery_raw'), g(r, 'pv_raw'),
            g(r, 'battery_min'), g(r, 'battery_max'),
            g(r, 'pv_min'), g(r, 'pv_max'),
            g(r, 'n_reads'), g(r, 'load')))
    return ''.join(out)
