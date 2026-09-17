# -*- coding: utf-8 -*-
"""设置页优化：
1) 删除冗余调试/说明文字（校准换算链路、PTT 排查步骤、TTS 外部 API 备注），校准实时值改单行紧凑显示
2) 重构传感器设置：RS485 总线卡（串口/波特率/轮询）+ 风速卡 + 雨量卡（同款 2 列栅格 + 实时状态行）
"""
from pathlib import Path

HTML = Path(r'C:\Users\Admin\Desktop\ELF2\智能中继架构\web_client\templates\dashboard.html')
JS = Path(r'C:\Users\Admin\Desktop\ELF2\智能中继架构\web_client\static\js\app.js')

h = HTML.read_bytes().decode('utf-8').replace('\r\n', '\n')
E = []

# ---------- 1) 校准卡：实时值紧凑化 + 删除换算链路说明 ----------
E.append(('''      <div class="kv-list mt" id="cal-live"><span class="muted">--</span></div>
      <div class="row gap mt">
        <button class="btn primary" id="btn-save-cal">保存校准</button>
        <button class="btn ghost" id="btn-cal-design">填入设计值（电池 10.11 / 光伏 17.01）</button>
      </div>
      <p class="muted small">换算链路：<b>引脚电压</b> = (raw − 零点) × 0.43945 mV（1.8V/4096）；<b>实际电压</b> = 引脚电压 × 倍率。<br>
        倍率单位统一为 <b>V/引脚电压</b>，等于分压比倒数 = (R上 + R下) / R下：<br>
        电池 R14 100Ω + R15 91kΩ / R16 10kΩ → 10k/101.1k = 0.098912 → 倍率 <b>10.11</b>，满量程 <b>18.198 V</b>，分辨率 4.443 mV/LSB；<br>
        光伏 100Ω + 160kΩ / 10kΩ → 10k/170.1k = 0.058789 → 倍率 <b>17.01</b>，满量程 <b>30.618 V</b>，分辨率 7.475 mV/LSB。</p>
''', '''      <div class="muted small mt" id="cal-live">实时值：--</div>
      <div class="row gap mt">
        <button class="btn primary" id="btn-save-cal">保存校准</button>
        <button class="btn ghost" id="btn-cal-design">填入设计值（电池 10.11 / 光伏 17.01）</button>
      </div>
'''))

# ---------- 2) PTT 自检：删除排查步骤长文，保留一句操作提示 ----------
E.append(('''      <p class="muted small">
        按住期间 GPIO3_A1（<b>gpiochip3 line1 → Linux 全局 GPIO 97</b>）输出高电平，
        经隔离/驱动送控制板 PTT，用于<b>不带音频</b>地验证整条发射链路；
        松开、3 秒无心跳或超过 30 秒会自动松开（防止一直压着信道）。<br>
        排查顺序：① 本页「引脚实测」是否变 1 → ② 万用表量 RK3588 侧 P26 pin1 对 GND（0V ↔ 3.3V）
        → ③ 量隔离板输入/输出侧 → ④ 量控制板 PTT 端子（<b>注意有效极性：低有效需反相</b>）
        → ⑤ 用导线短接控制板 PTT 端子模拟发射，判断断点在控制板还是隔离板一侧。
      </p>
''', '''      <p class="muted small">按住发射、松开即释放；3 秒无心跳或超过 30 秒自动松开。</p>
'''))

# ---------- 3) 传感器设置重构 ----------
old_sensors_start = '''    <div class="card">
      <div class="card-title">气象 Modbus / 串口设置</div>'''
i0 = h.index(old_sensors_start)
i1 = h.index('''  <div class="card mt">
    <div class="card-title">修改当前用户密码</div>''')
NEW_SENSORS = '''    <div class="card">
      <div class="card-title">RS485 总线（风速 / 雨量共用）</div>
      <div class="cal-row">
        <div><label>串口</label><input id="weather-port" value="/dev/ttyS9"></div>
        <div><label>波特率</label><input id="weather-baud" type="number" value="9600"></div>
      </div>
      <div class="cal-row">
        <div><label>轮询间隔 (秒)</label><input id="weather-interval" type="number" step="0.5" value="2"></div>
        <div><label>数据格式</label><input value="8N1 · Modbus RTU" disabled></div>
      </div>
      <button class="btn primary" id="btn-weather-settings-save">保存总线设置</button>
      <div class="muted small mt" id="bus-status">状态：--</div>
    </div>
  </div>

  <div class="grid grid-2 mt">
    <div class="card">
      <div class="card-title">风力变送器（风速传感器）</div>
      <div class="cal-row">
        <div><label>从站地址</label><input id="weather-slave" type="number" value="1"></div>
        <div><label>功能码</label><select id="weather-function"><option value="3">03 保持寄存器</option><option value="4">04 输入寄存器</option></select></div>
      </div>
      <div class="cal-row">
        <div><label>寄存器地址</label><input id="weather-register" type="number" value="0"></div>
        <div><label>读取数量</label><input id="weather-quantity" type="number" value="1"></div>
      </div>
      <div class="cal-row">
        <div><label>倍率 (m/s per raw)</label><input id="weather-scale" type="number" step="0.0001" value="0.1"></div>
        <div></div>
      </div>
      <button class="btn primary" id="btn-wind-settings-save">保存风速设置</button>
      <div class="muted small mt" id="wind-sensor-status">状态：--</div>
    </div>
    <div class="card">
      <div class="card-title">降水量传感器（翻斗式雨量计）</div>
      <div class="cal-row">
        <div><label>启用</label><select id="rain-enabled"><option value="1">启用</option><option value="0">停用</option></select></div>
        <div><label>从站地址</label><input id="rain-slave" type="number" value="23"></div>
      </div>
      <div class="cal-row">
        <div><label>功能码</label><select id="rain-function"><option value="3">03 保持寄存器</option><option value="4">04 输入寄存器</option></select></div>
        <div><label>寄存器地址</label><input id="rain-register" type="number" value="0"></div>
      </div>
      <div class="cal-row">
        <div><label>读取数量</label><input id="rain-quantity" type="number" value="1"></div>
        <div><label>倍率 (mm per raw)</label><input id="rain-scale" type="number" step="0.0001" value="0.1"></div>
      </div>
      <button class="btn primary" id="btn-rain-settings-save">保存雨量设置</button>
      <div class="muted small mt" id="rain-sensor-status">状态：--</div>
    </div>
  </div>
'''
h = h[:i0] + NEW_SENSORS + h[i1:]

# ---------- 4) 删除 TTS 外部 API 备注 ----------
E.append(('''      <p class="muted small">外部 OpenAI 兼容 TTS 已下线，板端只使用 /opt/ai/voices 下的本地 Piper ONNX 模型（完全离线）。<br>
        音色包上传后可在此切换，试听请在「语音对话」页…</p>
''', ''))

for i, (old, new) in enumerate(E, 1):
    n = h.count(old)
    if n != 1:
        raise SystemExit('[H%d] 匹配 %d 次' % (i, n))
    h = h.replace(old, new)
HTML.write_bytes(h.replace('\n', '\r\n').encode('utf-8'))

# ======================= app.js =======================
t = JS.read_bytes().decode('utf-8').replace('\r\n', '\n')
P = []

# 1) 校准实时值改单行紧凑
P.append(('''    const line = (key) => {
      const c = calCache[key];
      if (!c) return '';
      const ratio = c.divider_ratio != null ? c.divider_ratio.toFixed(6) : '--';
      const design = c.design_multiplier != null ? c.design_multiplier : '--';
      const fs = c.full_scale != null ? c.full_scale.toFixed(3) : '--';
      const mv = c.mv_per_lsb != null ? c.mv_per_lsb.toFixed(3) : '--';
      return `<div>${escapeHtml(c.label || key)}（VIN${c.adc_channel} / ${escapeHtml(c.raw_file || '')}）：raw <b>${c.raw ?? '--'}</b> · 引脚 <b>${c.pin_voltage ?? '--'} V</b> · 实际 <b>${c.voltage ?? '--'} V</b>` +
             `<span class="muted small">（分压比 ${ratio} · 倍率 ${c.multiplier} V/V · 设计值 ${design} · 满量程 ${fs} V · ${mv} mV/LSB）</span></div>`;
    };
    box.innerHTML = line('battery') + line('pv') || '<span class="muted">--</span>';
''', '''    const item = (key) => {
      const c = calCache[key];
      if (!c) return '';
      return `${escapeHtml(c.label || key)} <b>${c.voltage ?? '--'} V</b>`;
    };
    const parts = [item('battery'), item('pv')].filter(Boolean);
    box.innerHTML = parts.length ? ('实时值：' + parts.join('　·　')) : '实时值：--';
'''))

# 2) 传感器实时状态
P.append(('''  async function loadWeatherSettings() {
''', '''  // 传感器卡片里的实时状态（设置页友好显示：是否有数据/最后成功时间/错误）
  async function loadSensorStatus() {
    if (role !== 'admin') return;
    try {
      const w = await apiFetch('/api/weather/realtime');
      const r = w.realtime || {};
      const el = $('#wind-sensor-status');
      if (el) {
        const spd = (r.last_speed == null) ? '--' : (r.last_speed + ' m/s');
        const ok = r.last_ok ? new Date(r.last_ok * 1000).toLocaleTimeString('zh-CN') : '--';
        el.textContent = r.running
          ? `状态：采集中　风速 ${spd}　最后成功 ${ok}　错误 ${r.error_count || 0}${r.last_error ? '（' + r.last_error + '）' : ''}`
          : '状态：未运行（保存后自动启动）';
      }
      const bus = $('#bus-status');
      if (bus) {
        bus.textContent = r.running
          ? `状态：采集中　轮询 ${r.poll_count || 0} 次　错误 ${r.error_count || 0}`
          : '状态：未运行';
      }
    } catch (e) { /* 忽略 */ }
    try {
      const d = await apiFetch('/api/rain/realtime');
      const el = $('#rain-sensor-status');
      if (el) {
        const rt = d.realtime || {};
        const today = (d.today && d.today.total_mm != null) ? d.today.total_mm : 0;
        const hour = (d.recent_hour_mm != null) ? d.recent_hour_mm : 0;
        el.textContent = rt.enabled
          ? `状态：已启用　今日 ${today} mm　近 1 小时 ${hour} mm　最后成功 ` +
            (rt.last_ok ? new Date(rt.last_ok * 1000).toLocaleTimeString('zh-CN') : '--') +
            `　错误 ${rt.error_count || 0}${rt.last_error ? '（' + rt.last_error + '）' : ''}`
          : '状态：已停用';
      }
    } catch (e) { /* 忽略 */ }
  }

  async function loadWeatherSettings() {
'''))

# 3) 绑定新增的两个保存按钮 + 载入状态
P.append(("""    $('#btn-weather-settings-save')?.addEventListener('click', saveWeatherSettings);
""", """    $('#btn-weather-settings-save')?.addEventListener('click', saveWeatherSettings);
    $('#btn-wind-settings-save')?.addEventListener('click', saveWeatherSettings);
    $('#btn-rain-settings-save')?.addEventListener('click', saveWeatherSettings);
"""))

P.append(("""      loadWeatherSettings();
""", """      loadWeatherSettings();
      loadSensorStatus();
"""))

for i, (old, new) in enumerate(P, 1):
    n = t.count(old)
    if n != 1:
        raise SystemExit('[J%d] 匹配 %d 次' % (i, n))
    t = t.replace(old, new)
JS.write_bytes(t.replace('\n', '\r\n').encode('utf-8'))
print('设置页优化完成（删除冗余说明 + 传感器布局重构 + 状态行）')
