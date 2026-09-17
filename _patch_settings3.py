# -*- coding: utf-8 -*-
"""设置页优化（v3）：真正删除冗余说明段落 + 传感器布局重构 + 实时状态行。"""
from pathlib import Path

HTML = Path(r'C:\Users\Admin\Desktop\ELF2\智能中继架构\web_client\templates\dashboard.html')
JS = Path(r'C:\Users\Admin\Desktop\ELF2\智能中继架构\web_client\static\js\app.js')

h = HTML.read_bytes().decode('utf-8').replace('\r\n', '\n')


def drop_paragraph(text, marker, note=''):
    """删除包含 marker 的整个 <p>…</p> 段落。"""
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit('未找到标记：%s' % marker)
    p0 = text.rfind('<p', 0, idx)
    if p0 < 0:
        raise SystemExit('未找到 %s 的 <p> 起始' % marker)
    p1 = text.find('</p>', idx)
    if p1 < 0:
        raise SystemExit('未找到 %s 的 </p>' % marker)
    line_start = text.rfind('\n', 0, p0) + 1
    line_end = text.find('\n', p1)
    line_end = len(text) if line_end < 0 else line_end + 1
    print('  删除段落: %s%s' % (marker, note))
    return text[:line_start] + text[line_end:]


# 1) 校准卡：实时值紧凑化（模板里的占位块同步改）
old_live = '''      <div class="kv-list mt" id="cal-live"><span class="muted">--</span></div>'''
new_live = '''      <div class="muted small mt" id="cal-live">实时值：--</div>'''
assert h.count(old_live) == 1
h = h.replace(old_live, new_live)
# 删除「换算链路」说明段
h = drop_paragraph(h, '换算链路：')

# 2) PTT 自检：删除排查步骤段，补一句操作提示
h = drop_paragraph(h, '排查顺序：')
anchor = '''      <div class="mt" id="ptt-diag-events"><span class="muted small">暂无 PTT 事件</span></div>
'''
assert h.count(anchor) == 1
h = h.replace(anchor, anchor + '''      <p class="muted small">按住发射、松开即释放；3 秒无心跳或超过 30 秒自动松开。</p>
''')

# 3) 删除 TTS 外部 API 备注段
h = drop_paragraph(h, '外部 OpenAI 兼容 TTS 已下线')

# 4) 传感器设置重构
start_mark = '''    <div class="card">
      <div class="card-title">气象 Modbus / 串口设置</div>'''
end_mark = '''  <div class="card mt">
    <div class="card-title">修改当前用户密码</div>'''
i0 = h.find(start_mark)
i1 = h.find(end_mark)
if i0 < 0 or i1 <= i0:
    raise SystemExit('传感器卡片区间未找到')
NEW = '''    <div class="card">
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
      <div class="card-title">风力变送器（风速）</div>
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
      <div class="card-title">降水量传感器（翻斗式）</div>
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
h = h[:i0] + NEW + h[i1:]
while '\n\n\n' in h:
    h = h.replace('\n\n\n', '\n\n')
HTML.write_bytes(h.replace('\n', '\r\n').encode('utf-8'))

# ======================= app.js =======================
t = JS.read_bytes().decode('utf-8').replace('\r\n', '\n')
P = []

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

P.append(('''  async function loadWeatherSettings() {
''', '''  // 传感器卡片实时状态（设置页友好显示：是否采集 / 当前值 / 最后成功 / 错误）
  async function loadSensorStatus() {
    if (role !== 'admin') return;
    try {
      const w = await apiFetch('/api/weather/realtime');
      const r = w.realtime || {};
      const ok = r.last_ok ? new Date(r.last_ok * 1000).toLocaleTimeString('zh-CN') : '--';
      const el = $('#wind-sensor-status');
      if (el) {
        const spd = (r.last_speed == null || r.last_speed === '') ? '--' : (r.last_speed + ' m/s');
        el.textContent = r.running
          ? `状态：采集中　风速 ${spd}　最后成功 ${ok}　错误 ${r.error_count || 0}` +
            (r.last_error ? `（${r.last_error}）` : '')
          : '状态：未运行（保存设置后自动启动）';
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
      const rt = d.realtime || {};
      const el = $('#rain-sensor-status');
      if (el) {
        const today = (d.today && d.today.total_mm != null) ? d.today.total_mm : 0;
        const hour = (d.recent_hour_mm != null) ? d.recent_hour_mm : 0;
        const ok = rt.last_ok ? new Date(rt.last_ok * 1000).toLocaleTimeString('zh-CN') : '--';
        el.textContent = rt.enabled
          ? `状态：已启用　今日 ${today} mm　近 1 小时 ${hour} mm　最后成功 ${ok}　错误 ${rt.error_count || 0}` +
            (rt.last_error ? `（${rt.last_error}）` : '')
          : '状态：已停用';
      }
    } catch (e) { /* 忽略 */ }
  }

  async function loadWeatherSettings() {
'''))

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
print('OK: 设置页说明精简 + 传感器布局重构 + 状态行')
