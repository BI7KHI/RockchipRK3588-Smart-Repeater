#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 APRS 子系统接入 /www/app.py（锚点断言 + 幂等检测）。

改动点：
  1. import aprs_service + 建实例
  2. defaults 增加 aprs_* 键
  3. /api/settings GET 键列表
  4. /api/settings POST 白名单与校验器
  5. 设置变更后 invalidate
  6. 采集中枢 _mic_capture_loop 里增加 feed 钩子
  7. configure + 启动
  8. APRS 路由块（页面/接口/天地图瓦片代理）
"""
import re
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else '/www/app.py'
with open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if 'import aprs_service' in src or 'aprs_service_instance' in src:
    print('已集成过，跳过（幂等）')
    sys.exit(0)

E = []

# ---------------------------------------------------------------- 1. import + 实例
E.append((
    "import weather_service\nimport voice_service\n",
    "import weather_service\nimport voice_service\nimport aprs_service\n"))

E.append((
    "voice_service_instance = voice_service.VoiceService(DB_PATH)\n",
    "voice_service_instance = voice_service.VoiceService(DB_PATH)\n"
    "aprs_service_instance = aprs_service.AprsService(DB_PATH)\n"))

# ---------------------------------------------------------------- 2. defaults
E.append((
    "        'vlog_callsign_whitelist': 'BI7KHI',\n"
    "        'vlog_callsign_max_dist': '0',\n",
    "        'vlog_callsign_whitelist': 'BI7KHI',\n"
    "        'vlog_callsign_max_dist': '0',\n"
    "        # APRS 收发（自研 1200bps Bell202 软件 TNC）\n"
    "        'aprs_enabled': '1',\n"
    "        'aprs_mycall': 'BI7KHI',\n"
    "        'aprs_ssid': '10',\n"
    "        'aprs_dest': 'APRS',\n"
    "        'aprs_path': 'WIDE1-1,WIDE2-1',\n"
    "        'aprs_lat': '22.533300',\n"
    "        'aprs_lon': '114.050000',\n"
    "        'aprs_beacon_enabled': '1',\n"
    "        'aprs_weather_enabled': '1',\n"
    "        'aprs_telemetry_enabled': '1',\n"
    "        'aprs_map_provider': 'tianditu',\n"
    "        'aprs_map_tk': 'eaa1673e60065f76cbf3c970063ec475',\n"
    "        'aprs_map_layers': 'img,cva',\n"))

# ---------------------------------------------------------------- 3. GET 键
E.append((
    "        'vlog_callsign_whitelist', 'vlog_callsign_max_dist',\n    ]\n",
    "        'vlog_callsign_whitelist', 'vlog_callsign_max_dist',\n"
    "        'aprs_enabled', 'aprs_mycall', 'aprs_ssid', 'aprs_dest', 'aprs_path',\n"
    "        'aprs_lat', 'aprs_lon', 'aprs_alt_m', 'aprs_pos_source', 'aprs_gps_port',\n"
    "        'aprs_gps_baud', 'aprs_symbol_table', 'aprs_symbol_code', 'aprs_comment',\n"
    "        'aprs_pos_ambiguity', 'aprs_channel',\n"
    "        'aprs_beacon_enabled', 'aprs_beacon_interval',\n"
    "        'aprs_weather_enabled', 'aprs_weather_interval',\n"
    "        'aprs_telemetry_enabled', 'aprs_telemetry_interval',\n"
    "        'aprs_status_enabled', 'aprs_status_interval', 'aprs_status_text',\n"
    "        'aprs_jitter', 'aprs_carrier_sense', 'aprs_defer_max',\n"
    "        'aprs_defer_jitter', 'aprs_min_gap',\n"
    "        'aprs_burst_threshold', 'aprs_burst_min_ms', 'aprs_phase_trials',\n"
    "        'aprs_dedup_window', 'aprs_telemetry_map', 'aprs_retention_days',\n"
    "        'aprs_map_provider', 'aprs_map_tk', 'aprs_map_tk_browser',\n"
    "        'aprs_map_layers', 'aprs_map_cache_mb', 'aprs_track_points',\n"
    "    ]\n"))

# ---------------------------------------------------------------- 4. POST 白名单
E.append((
    "        'vlog_llm_on_demand': _bool_caster,\n    }\n",
    "        'vlog_llm_on_demand': _bool_caster,\n"
    "        # —— APRS ——\n"
    "        'aprs_mycall': lambda v: (''.join(ch for ch in str(v).upper()\n"
    "            if ch.isalnum()))[:6] or 'BI7KHI',\n"
    "        'aprs_ssid': lambda v: str(max(0, min(15, int(float(v))))),\n"
    "        'aprs_dest': lambda v: (str(v).upper().strip() or 'APRS')[:6],\n"
    "        'aprs_path': lambda v: ','.join(\n"
    "            [x.strip().upper() for x in str(v).split(',') if x.strip()][:8])[:80],\n"
    "        'aprs_lat': lambda v: str(round(max(-90.0, min(90.0, float(v))), 6)),\n"
    "        'aprs_lon': lambda v: str(round(max(-180.0, min(180.0, float(v))), 6)),\n"
    "        'aprs_alt_m': lambda v: ('' if str(v).strip() == ''\n"
    "            else str(round(max(-500.0, min(9000.0, float(v))), 1))),\n"
    "        'aprs_pos_source': lambda v: v if v in ('manual', 'nmea') else 'manual',\n"
    "        'aprs_gps_port': lambda v: str(v).strip()[:60],\n"
    "        'aprs_gps_baud': lambda v: str(max(1200, min(921600, int(float(v))))),\n"
    "        'aprs_symbol_table': lambda v: v if v in ('/', '\\\\') else '/',\n"
    "        'aprs_symbol_code': lambda v: (str(v)[:1] or '-'),\n"
    "        'aprs_comment': lambda v: str(v).strip()[:60],\n"
    "        'aprs_pos_ambiguity': lambda v: str(max(0, min(4, int(float(v))))),\n"
    "        'aprs_channel': lambda v: v if v in ('left', 'right', 'mix') else 'left',\n"
    "        'aprs_beacon_interval': lambda v: str(max(60, min(86400, int(float(v))))),\n"
    "        'aprs_weather_interval': lambda v: str(max(60, min(86400, int(float(v))))),\n"
    "        'aprs_telemetry_interval': lambda v: str(max(60, min(86400, int(float(v))))),\n"
    "        'aprs_status_interval': lambda v: str(max(60, min(86400, int(float(v))))),\n"
    "        'aprs_status_text': lambda v: str(v).strip()[:60],\n"
    "        'aprs_jitter': lambda v: str(max(0, min(600, int(float(v))))),\n"
    "        'aprs_defer_max': lambda v: str(max(0, min(3600, int(float(v))))),\n"
    "        'aprs_defer_jitter': lambda v: str(max(0, min(60, int(float(v))))),\n"
    "        'aprs_min_gap': lambda v: str(max(0, min(600, int(float(v))))),\n"
    "        'aprs_burst_threshold': lambda v: str(round(max(0.05, min(0.9, float(v))), 3)),\n"
    "        'aprs_burst_min_ms': lambda v: str(max(20, min(2000, int(float(v))))),\n"
    "        'aprs_phase_trials': lambda v: str(max(8, min(256, int(float(v))))),\n"
    "        'aprs_dedup_window': lambda v: str(max(0, min(600, int(float(v))))),\n"
    "        'aprs_retention_days': lambda v: str(max(0, min(3650, int(float(v))))),\n"
    "        'aprs_track_points': lambda v: str(max(10, min(5000, int(float(v))))),\n"
    "        'aprs_map_cache_mb': lambda v: str(max(0, min(20480, int(float(v))))),\n"
    "        'aprs_map_provider': lambda v: v if v in ('tianditu', 'none') else 'tianditu',\n"
    "        'aprs_map_tk': lambda v: str(v).strip()[:64],\n"
    "        'aprs_map_tk_browser': lambda v: str(v).strip()[:64],\n"
    "        'aprs_map_layers': lambda v: ','.join(\n"
    "            [x.strip() for x in str(v).split(',') if x.strip()\n"
    "             and x.strip() in ('img', 'vec', 'ter', 'cva', 'cia', 'cta')][:4]),\n"
    "        'aprs_telemetry_map': lambda v: (str(v)[:2000] if str(v).strip().startswith('{')\n"
    "            else aprs_service.DEFAULTS['aprs_telemetry_map']),\n"
    "        'aprs_enabled': _bool_caster,\n"
    "        'aprs_beacon_enabled': _bool_caster,\n"
    "        'aprs_weather_enabled': _bool_caster,\n"
    "        'aprs_telemetry_enabled': _bool_caster,\n"
    "        'aprs_status_enabled': _bool_caster,\n"
    "        'aprs_carrier_sense': _bool_caster,\n"
    "    }\n"))

# ---------------------------------------------------------------- 5. invalidate
E.append((
    "    try:\n        voice_service_instance.invalidate()\n    except Exception:\n        pass\n",
    "    try:\n        voice_service_instance.invalidate()\n    except Exception:\n        pass\n"
    "    try:\n        aprs_service_instance.invalidate()\n    except Exception:\n        pass\n"))

# ---------------------------------------------------------------- 6. feed 钩子
E.append((
    "            try:\n"
    "                voice_service_instance.feed(chunk, time.time())\n"
    "            except Exception:\n"
    "                pass\n",
    "            try:\n"
    "                voice_service_instance.feed(chunk, time.time())\n"
    "            except Exception:\n"
    "                pass\n"
    "            # APRS 常驻解码：挂在同一个采集中枢上（采集设备独占，\n"
    "            # 不能再开第二路 arecord）。不受 BUSY/分段影响，全程监听。\n"
    "            try:\n"
    "                aprs_service_instance.feed(chunk, time.time())\n"
    "            except Exception:\n"
    "                pass\n"))

# ---------------------------------------------------------------- 7. configure + start
E.append((
    "voice_service_instance.start()\n"
    "threading.Thread(target=_vlog_capture_guard, daemon=True, name='vlog-capture').start()\n",
    "voice_service_instance.start()\n"
    "threading.Thread(target=_vlog_capture_guard, daemon=True, name='vlog-capture').start()\n"
    "\n"
    "# APRS：注入信道仲裁 / 音频发射 / 数据源（lambda 延迟解析，\n"
    "# 因为被引用的函数定义在文件更后面）\n"
    "aprs_service_instance.configure(\n"
    "    setting_getter=lambda k, d='': _setting_direct(k, d),\n"
    "    carrier_busy=lambda: _aprs_carrier_busy(),\n"
    "    play_raw=lambda raw, rate, hold: _aprs_play_raw(raw, rate, hold),\n"
    "    wx_getter=lambda: _aprs_weather_source(),\n"
    "    power_getter=lambda: _aprs_power_source(),\n"
    "    temp_getter=lambda: _aprs_cpu_temp(),\n"
    ")\n"))

# ---------------------------------------------------------------- 8. 路由块
ROUTES = r'''

# ---------------------------------------------------------------------------
# APRS 收发：自研 1200bps Bell202 软件 TNC（接收）+ 天地图（地图）
# 合规说明：底图使用「天地图」（国家地理信息公共服务平台，地图内容已审核、
# 自带审图号，资质由平台承担）；不使用 OSM（其国界画法不符合我国《公开地图
# 内容表示规范》，且本网络内 tile.openstreetmap.org 不可达）。天地图为 CGCS2000
# 坐标系，与 WGS-84 实用精度一致，因此 APRS 坐标可直接绘制，无需 GCJ-02 偏移
# 转换（高德/百度若不转换会有 300~600 米偏移）。
# ---------------------------------------------------------------------------
APRS_TILE_DIR = Path(os.environ.get('RELAY_APRS_TILE_DIR', '/opt/ai/aprs_tiles'))
TIANDITU_HOSTS = ['t%d.tianditu.gov.cn' % i for i in range(8)]
APRS_LAYERS = {
    'img': '影像底图', 'vec': '矢量底图', 'ter': '地形晕渲',
    'cva': '影像注记', 'cia': '矢量注记', 'cta': '地形注记',
}
_APRS_TILE_N = {'n': 0}


def _aprs_carrier_busy():
    """信道忙：BUSY 有效（电台上收到信号）或本机 PTT 正在发射。"""
    try:
        if bool(BUSY_STATE.get('active')):
            return True
    except Exception:
        pass
    try:
        return bool(PTT_LEVEL)
    except Exception:
        return False


def _aprs_weather_source():
    """气象站数据 -> APRS 需要的物理量。缺项为 None（APRS 允许省略字段）。"""
    out = {'online': False}
    try:
        st = weather_service_instance.realtime() or {}
    except Exception:
        st = {}
    out['online'] = bool(st.get('running')) and not st.get('last_error')

    def num(*keys):
        for k in keys:
            v = st.get(k)
            if v is not None and v != '':
                try:
                    return float(v)
                except Exception:
                    pass
        return None

    out['wind_ms'] = num('last_speed', 'wind_speed')
    out['wind_dir'] = num('wind_dir', 'last_dir', 'direction', 'dir')
    out['gust_ms'] = num('gust_ms', 'last_gust')
    out['temp_c'] = num('th_temperature', 'temperature', 'temp_c')
    out['humidity'] = num('th_humidity', 'humidity')
    out['pressure_hpa'] = num('pressure_hpa', 'pressure')
    if out['wind_dir'] is None:
        try:
            out['wind_dir'] = float(_setting_direct('aprs_wx_dir_fixed', '') or 0) or None
        except Exception:
            pass
    try:
        out['rain_1h_mm'] = float(weather_service_instance.rain_recent_hour())
    except Exception:
        pass
    try:
        rs = weather_service_instance.rain_stats(datetime.now().strftime('%Y-%m-%d'))
        if rs and rs.get('total_mm') is not None:
            out['rain_today_mm'] = float(rs['total_mm'])
    except Exception:
        pass
    return out


def _aprs_power_source():
    try:
        pw = voltage_payload() or {}
        return {'battery_v': (pw.get('battery') or {}).get('voltage'),
                'pv_v': (pw.get('pv') or {}).get('voltage')}
    except Exception:
        return {}


def _aprs_cpu_temp():
    try:
        for item in (read_temperature() or []):
            nm = str(item.get('name') or '').lower()
            if 'soc' in nm or 'cpu' in nm:
                return item.get('celsius')
        temps = read_temperature() or []
        return temps[0].get('celsius') if temps else None
    except Exception:
        return None


def _aprs_play_raw(pcm_bytes, rate=16000, hold_ptt=True):
    """把原始 PCM 送上 AUX 发射（自带 PTT 保持与设备抢占）。

    PTT 必须在音频之前拉起、在音频之后放下；同时要抢占上一路 aplay
    （同一张声卡同一时刻只允许一路），否则会因设备忙直接失败。
    """
    global CURRENT_PLAY_PROC
    t0 = time.time()
    ptt_on = False
    try:
        _ensure_audio_unmuted()
        if hold_ptt:
            _ptt_retain()
            ptt_on = True
            time.sleep(0.12)          # 等功放/继电器稳定再送音频
        with PLAY_LOCK:
            _stop_proc(CURRENT_PLAY_PROC)
            cmd = ['aplay', '-D', AUDIO_DEVICE, '-q', '-t', 'raw',
                   '-f', 'S16_LE', '-r', str(int(rate)), '-c', '1']
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
            CURRENT_PLAY_PROC = proc
            try:
                proc.stdin.write(pcm_bytes)
                proc.stdin.close()
            except Exception as e:
                _stop_proc(proc)
                return {'ok': False, 'error': '写入音频失败：%s' % e}
            limit = max(10.0, len(pcm_bytes) / float(rate * 2) + 10.0)
            try:
                proc.wait(timeout=limit)
            except Exception:
                _stop_proc(proc)
                return {'ok': False, 'error': '播放超时'}
            if CURRENT_PLAY_PROC is proc:
                CURRENT_PLAY_PROC = None
        rc = proc.returncode
        return {'ok': rc == 0, 'error': '' if rc == 0 else 'aplay 退出码 %s' % rc,
                'ptt_ms': int((time.time() - t0) * 1000)}
    except Exception as e:
        return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
    finally:
        if ptt_on:
            try:
                _ptt_release()
            except Exception:
                pass


def _aprs_tile_path(layer, z, x, y):
    return APRS_TILE_DIR / layer / str(z) / str(x) / str(y)


def _aprs_tile_trim():
    """按总量上限清理瓦片缓存（最旧的先删）。"""
    try:
        cap = int(float(_setting_direct('aprs_map_cache_mb', '512') or 512)) * 1024 * 1024
    except Exception:
        cap = 512 * 1024 * 1024
    if cap <= 0 or not APRS_TILE_DIR.exists():
        return 0
    items = []
    total = 0
    for p in APRS_TILE_DIR.rglob('*'):
        if p.is_file() and not p.name.endswith('.type'):
            try:
                stt = p.stat()
            except Exception:
                continue
            items.append((stt.st_mtime, stt.st_size, p))
            total += stt.st_size
    if total <= cap:
        return 0
    items.sort()
    freed = 0
    for (_m, sz, p) in items:
        if total - freed <= cap * 0.9:
            break
        try:
            p.unlink()
            p.with_suffix('.type').unlink()
            freed += sz
        except Exception:
            pass
    return freed


def _aprs_tile_fetch(layer, z, x, y):
    """向天地图取瓦片。使用「服务端」类型 tk（不需要 Referer）。"""
    tk = (_setting_direct('aprs_map_tk', '') or '').strip()
    if not tk:
        return None, '未配置天地图服务端 key'
    host = TIANDITU_HOSTS[(int(z) + int(x) + int(y)) % len(TIANDITU_HOSTS)]
    url = ('https://%s/%s_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0'
           '&LAYER=%s&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles'
           '&TILEMATRIX=%d&TILEROW=%d&TILECOL=%d&tk=%s'
           % (host, layer, layer, int(z), int(y), int(x), tk))
    try:
        r = requests.get(url, timeout=12,
                         headers={'User-Agent': 'ELF2-Relay/1.0'})
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, e)
    if r.status_code != 200:
        body = ''
        try:
            body = r.text[:120]
        except Exception:
            pass
        return None, '天地图返回 %s %s' % (r.status_code, body)
    if len(r.content) < 200:
        return None, '天地图返回内容异常（%d 字节）' % len(r.content)
    ct = (r.headers.get('Content-Type') or 'image/jpeg').split(';')[0].strip()
    if not ct.startswith('image/'):
        ct = 'image/jpeg'
    return r.content, ct


@app.route('/aprs')
@login_required
def aprs_page():
    return render_template('aprs.html', user=session.get('username'),
                           role=session.get('role'))


@app.route('/api/aprs/status')
@login_required
def api_aprs_status():
    payload = aprs_service_instance.stats_payload()
    payload['busy'] = _aprs_carrier_busy()
    payload['ptt'] = bool(PTT_LEVEL)
    payload['tile_dir'] = str(APRS_TILE_DIR)
    payload['layers'] = APRS_LAYERS
    return api_ok(**payload)


@app.route('/api/aprs/list')
@login_required
def api_aprs_list():
    def _int(name, dflt, lo, hi):
        try:
            return max(lo, min(hi, int(request.args.get(name) or dflt)))
        except Exception:
            return dflt

    rows = aprs_service_instance.list_packets(
        day=(request.args.get('day') or '').strip() or None,
        src=(request.args.get('src') or '').strip() or None,
        dtype=(request.args.get('dtype') or '').strip() or None,
        limit=_int('limit', 100, 1, 500),
        offset=_int('offset', 0, 0, 1000000),
        pos_only=request.args.get('pos_only') in ('1', 'true'),
        since_id=_int('since_id', 0, 0, 10 ** 9))
    for r in rows:
        r.pop('raw_hex', None)       # 列表不返回完整帧，详情接口才给
    return api_ok(packets=rows, count=len(rows))


@app.route('/api/aprs/geo')
@login_required
def api_aprs_geo():
    """地图数据：时间窗内有位置的站点 + 轨迹。"""
    try:
        minutes = max(5, min(10080, int(request.args.get('minutes') or 180)))
    except Exception:
        minutes = 180
    data = aprs_service_instance.packets_geo(
        day=(request.args.get('day') or '').strip() or None, minutes=minutes)
    data['home'] = aprs_service_instance.position.get()
    return api_ok(**data)


@app.route('/api/aprs/stations')
@login_required
def api_aprs_stations():
    return api_ok(stations=aprs_service_instance.stations())


@app.route('/api/aprs/<int:rid>')
@login_required
def api_aprs_detail(rid):
    row = aprs_service_instance.store.one(
        'SELECT * FROM aprs_packets WHERE id=?', (int(rid),))
    if not row:
        return api_err('记录不存在', 404)
    return api_ok(packet=row)


@app.route('/api/aprs/<int:rid>/raw')
@login_required
def api_aprs_raw(rid):
    """下载原始 AX.25 帧（含 FCS），用于外部工具交叉校验。"""
    row = aprs_service_instance.store.one(
        'SELECT id,ts,src,raw_hex FROM aprs_packets WHERE id=?', (int(rid),))
    if not row:
        abort(404)
    try:
        blob = bytes.fromhex(row['raw_hex'] or '')
    except Exception:
        blob = b''
    fn = 'aprs_%d_%s.bin' % (rid, re.sub(r'[^A-Za-z0-9-]', '', row['src'] or 'unk'))
    return Response(blob, mimetype='application/octet-stream',
                    headers={'Content-Disposition': 'attachment; filename=%s' % fn})


@app.route('/api/aprs/tx/list')
@login_required
def api_aprs_tx_list():
    try:
        limit = max(1, min(500, int(request.args.get('limit') or 60)))
    except Exception:
        limit = 60
    rows = aprs_service_instance.store.query(
        'SELECT * FROM aprs_tx ORDER BY id DESC LIMIT ?', (limit,))
    return api_ok(items=rows, count=len(rows))


@app.route('/api/aprs/tx', methods=['POST'])
@login_required
@admin_required
def api_aprs_tx():
    """手动发射一份 APRS 报文。"""
    data = request.get_json(silent=True) or {}
    ptype = (data.get('type') or '').strip()
    if ptype not in ('position', 'weather', 'status', 'telemetry', 'message'):
        return api_err('不支持的报文类型：%s' % ptype)
    kw = {}
    if ptype == 'message':
        kw['to'] = (data.get('to') or '').strip().upper()[:9]
        kw['text'] = (data.get('text') or '')[:67]
        if not kw['to']:
            return api_err('消息必须填写收件呼号')
    if ptype == 'status':
        kw['text'] = (data.get('text') or '')[:60]
    if not aprs_service_instance.enabled():
        return api_err('APRS 未启用，请先在设置中打开')
    res = aprs_service_instance.send(ptype, trigger='manual', **kw)
    audit('aprs_tx', '%s %s' % (ptype, (kw.get('to') or kw.get('text') or '')[:40]))
    if not res.get('ok'):
        return api_err(res.get('error') or '发射失败')
    return api_ok(**res)


@app.route('/api/aprs/pos', methods=['POST'])
@login_required
@admin_required
def api_aprs_pos():
    """保存本机位置与站点标识（地图上的「本站」，也是信标/气象源）。"""
    data = request.get_json(silent=True) or {}
    saved = {}
    for k, cast in (
            ('aprs_lat', lambda v: str(round(max(-90.0, min(90.0, float(v))), 6))),
            ('aprs_lon', lambda v: str(round(max(-180.0, min(180.0, float(v))), 6))),
            ('aprs_alt_m', lambda v: ('' if str(v).strip() == ''
                                      else str(round(float(v), 1)))),
            ('aprs_mycall', lambda v: (''.join(c for c in str(v).upper()
                                               if c.isalnum()))[:6]),
            ('aprs_ssid', lambda v: str(max(0, min(15, int(float(v)))))),
            ('aprs_comment', lambda v: str(v).strip()[:60])):
        if k in data:
            try:
                set_setting(k, cast(data[k]))
                saved[k] = get_setting(k)
            except Exception as e:
                return api_err('%s 无效：%s' % (k, e))
    if saved:
        aprs_service_instance.invalidate()
        audit('aprs_pos', json.dumps(saved, ensure_ascii=False))
    return api_ok(saved=saved, position=aprs_service_instance.position.get())


@app.route('/api/aprs/export')
@login_required
def api_aprs_export():
    """导出收包记录：txt / csv / json。"""
    day = (request.args.get('day') or datetime.now().strftime('%Y-%m-%d')).strip()
    fmt = (request.args.get('format') or 'txt').lower()
    rows = aprs_service_instance.list_packets(day=day, limit=5000)
    if fmt == 'json':
        return Response(json.dumps(rows, ensure_ascii=False, indent=1),
                        mimetype='application/json',
                        headers={'Content-Disposition':
                                 'attachment; filename=aprs_%s.json' % day})
    if fmt == 'csv':
        import csv
        import io
        buf = io.StringIO()
        cols = ['ts', 'src', 'dst', 'path', 'dtype', 'info', 'lat', 'lon',
                'comment', 'raw_hex']
        wtr = csv.writer(buf)
        wtr.writerow(cols)
        for r in rows:
            wtr.writerow([r.get(c) for c in cols])
        return Response('\ufeff' + buf.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition':
                                 'attachment; filename=aprs_%s.csv' % day})
    lines = []
    for r in rows:
        pos = ''
        if r.get('lat') is not None:
            pos = ' [%.5f,%.5f]' % (r['lat'], r['lon'])
        lines.append('%s  %-12s %-9s %s%s' % (
            r.get('ts') or '', r.get('src') or '', r.get('dtype_label') or '',
            (r.get('info') or '').replace('\n', ' '), pos))
    return Response('\n'.join(lines), mimetype='text/plain; charset=utf-8',
                    headers={'Content-Disposition':
                             'attachment; filename=aprs_%s.txt' % day})


@app.route('/api/aprs/cleanup', methods=['POST'])
@login_required
@admin_required
def api_aprs_cleanup():
    data = request.get_json(silent=True) or {}
    days = int(float(data.get('days') or 0))
    n = m = 0
    if days > 0:
        cut = time.time() - days * 86400
        n = aprs_service_instance.store.exec(
            'DELETE FROM aprs_packets WHERE ts_epoch < ?', (cut,)) or 0
        m = aprs_service_instance.store.exec(
            'DELETE FROM aprs_tx WHERE ts_epoch < ?', (cut,)) or 0
    freed = _aprs_tile_trim()
    audit('aprs_cleanup', 'days=%s packets=%s tx=%s' % (days, n, m))
    return api_ok(packets=n, tx=m, tile_freed=freed)


@app.route('/api/aprs/tile/<layer>/<int:z>/<int:x>/<int:y>')
@login_required
def api_aprs_tile(layer, z, x, y):
    """天地图瓦片代理 + 磁盘缓存。

    走服务端代理而不是让浏览器直连，好处有三：
      1) 服务端类型 tk 不需要 Referer，且 key 不会出现在前端；
      2) 可落盘缓存 —— 断网时已浏览过的区域仍能显示；
      3) 受登录保护，避免 key 被公开滥用（合规上更稳妥）。
    """
    if layer not in APRS_LAYERS:
        abort(404)
    if not (0 <= z <= 18) or x < 0 or y < 0 or x >= (1 << z) or y >= (1 << z):
        abort(404)
    p = _aprs_tile_path(layer, z, x, y)
    if p.exists():
        ct = 'image/jpeg'
        try:
            ct = (p.with_suffix('.type')).read_text(encoding='utf-8').strip() or ct
        except Exception:
            pass
        try:
            return Response(p.read_bytes(), mimetype=ct,
                            headers={'Cache-Control': 'public, max-age=86400',
                                     'X-Tile-Source': 'cache'})
        except Exception:
            pass
    data, ct = _aprs_tile_fetch(layer, z, x, y)
    if data is None:
        return api_err('瓦片获取失败：%s' % ct, 502)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        p.with_suffix('.type').write_text(ct, encoding='utf-8')
        _APRS_TILE_N['n'] += 1
        if _APRS_TILE_N['n'] % 200 == 0:
            _aprs_tile_trim()
    except Exception:
        pass
    return Response(data, mimetype=ct,
                    headers={'Cache-Control': 'public, max-age=86400',
                             'X-Tile-Source': 'upstream'})

'''

E.append((
    "# ---------------------------------------------------------------------------\n"
    "# 端侧语音识别（ASR）：sherpa-onnx + SenseVoice（离线）\n"
    "# ---------------------------------------------------------------------------\n",
    ROUTES.lstrip('\n') +
    "\n# ---------------------------------------------------------------------------\n"
    "# 端侧语音识别（ASR）：sherpa-onnx + SenseVoice（离线）\n"
    "# ---------------------------------------------------------------------------\n"))

for idx, (old, new) in enumerate(E):
    n = src.count(old)
    if n != 1:
        print('锚点 %d 命中 %d 次，失败：%r' % (idx + 1, n, old[:80]))
        sys.exit(2)
    src = src.replace(old, new, 1)

with open(PATH, 'w', encoding='utf-8') as f:
    f.write(src)
print('app.py 已集成 APRS，新增 %d 处改动，文件 %d 字节' % (len(E), len(src)))
