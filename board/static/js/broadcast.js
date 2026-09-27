/* ELF2 定时播报前端（自包含：子页面不加载 app.js） */
(function () {
  'use strict';

  const CSRF = window.BC_CSRF || '';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  function toast(msg, type) {
    const el = $('#toast');
    if (!el) { console.log(msg); return; }
    el.textContent = msg;
    el.className = 'toast show ' + (type || '');
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.className = 'toast ' + (type || ''); }, 3200);
  }

  async function api(url, opts) {
    const o = Object.assign({}, opts || {});
    o.headers = Object.assign({}, o.headers || {});
    if (o.method && o.method !== 'GET') {
      o.headers['X-CSRF-Token'] = CSRF;
      if (o.body && typeof o.body === 'string') o.headers['Content-Type'] = 'application/json';
    }
    const resp = await fetch(url, o);
    if (resp.status === 401) { location.href = '/login'; throw new Error('未登录'); }
    const ct = resp.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      const t = await resp.text();
      throw new Error(t.slice(0, 120) || ('HTTP ' + resp.status));
    }
    const d = await resp.json();
    if (d && d.ok === false) throw new Error(d.error || '请求失败');
    return d;
  }

  const state = { hours: [], log: [], poll: null };

  // ---------------- 整点勾选 ----------------
  function renderHours() {
    const box = $('#bc-hours');
    if (!box) return;
    box.innerHTML = '';
    for (let h = 0; h < 24; h++) {
      const lab = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = String(h);
      cb.checked = state.hours.indexOf(h) >= 0;
      cb.addEventListener('change', () => {
        lab.classList.toggle('on', cb.checked);
        markDirty();
      });
      lab.appendChild(cb);
      lab.appendChild(document.createTextNode(String(h).padStart(2, '0')));
      lab.classList.toggle('on', cb.checked);
      box.appendChild(lab);
    }
  }

  function pickedHours() {
    return $$('#bc-hours input:checked').map(cb => parseInt(cb.value, 10))
      .sort((a, b) => a - b);
  }

  function markDirty() {
    const el = $('#bc-save-state');
    if (el) el.textContent = '● 有未保存的修改';
  }

  // ---------------- 状态刷新 ----------------
  async function loadStatus() {
    try {
      const d = await api('/api/announce/status');
      state.hours = d.hours || [];
      renderHours();
      $('#bc-enabled').checked = !!d.enabled;
      $('#bc-quiet').value = d.quiet_hours || '';
      $('#bc-busy-wait').value = d.busy_wait || '0';
      const f = d.flags || {};
      $('#bc-mod-time').checked = !!f.time;
      $('#bc-mod-status').checked = !!f.status;
      $('#bc-mod-weather').checked = !!f.weather;
      const t = d.templates || {};
      if (document.activeElement !== $('#bc-text-time')) $('#bc-text-time').value = t.time || '';
      if (document.activeElement !== $('#bc-text-status')) $('#bc-text-status').value = t.status || '';
      if (document.activeElement !== $('#bc-text-weather')) $('#bc-text-weather').value = t.weather || '';
      $('#bc-preview').textContent = d.preview || '（当前没有启用任何播报内容）';

      const badge = $('#bc-state-badge');
      badge.textContent = d.enabled
        ? ('已启用 · ' + (state.hours.length ? state.hours.length + ' 个整点' : '但未选整点'))
        : '未启用';
      badge.className = 'badge ' + (d.enabled ? (state.hours.length ? 'ok' : 'warn') : 'idle');

      const bz = $('#bc-busy-badge');
      bz.textContent = d.busy_now ? '信道被占用' : '信道空闲';
      bz.className = 'badge ' + (d.busy_now ? 'warn' : 'ok');

      const w = d.weather || {};
      $('#bc-wx-provider').value = w.provider || 'off';
      $('#bc-wx-host').value = w.host || '';
      $('#bc-wx-lat').value = w.lat || '';
      $('#bc-wx-lon').value = w.lon || '';
      $('#bc-wx-key').placeholder = w.key_set ? '已保存（留空表示不改动）' : '尚未配置';
      toggleQw();
      $('#bc-wx-state').textContent = w.provider === 'off'
        ? '天气 API 已关闭'
        : (w.provider === 'openmeteo'
           ? ('Open-Meteo · 位置 ' + (w.lat || '?') + ',' + (w.lon || '?')
              + (w.lat_from_aprs ? '（取自 APRS 本站坐标）' : ''))
           : ('和风天气 · ' + (w.host || '未填 Host') + (w.key_set ? ' · key 已配置' : ' · 未配 key')));

      $('#bc-save-state').textContent = '';
      renderLog(d.log || []);
    } catch (e) {
      toast('加载失败：' + e.message, 'error');
    }
  }

  function renderLog(rows) {
    state.log = rows;
    const tb = $('#bc-log-table tbody');
    if (!tb) return;
    if (!rows.length) {
      tb.innerHTML = '<tr><td colspan="5" class="muted">暂无记录</td></tr>';
      return;
    }
    tb.innerHTML = '';
    rows.forEach(r => {
      const tr = document.createElement('tr');
      const res = r.ok ? '<b class="ok">已播报</b>'
        : (r.skipped ? '<span class="warn">已取消</span>' : '<span class="err">失败</span>');
      tr.innerHTML = '<td>' + esc((r.ts || '').slice(11, 19)) + '</td>'
        + '<td>' + esc(r.hour || '') + '</td>'
        + '<td>' + res + (r.dry ? ' <span class="muted">(试听)</span>' : '') + '</td>'
        + '<td class="muted">' + esc(r.error || '') + '</td>'
        + '<td>' + esc(r.text || '') + '</td>';
      tb.appendChild(tr);
    });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function toggleQw() {
    const on = $('#bc-wx-provider').value === 'qweather';
    $('#bc-wx-qw').style.display = on ? '' : 'none';
  }

  // ---------------- 保存 ----------------
  async function savePlan() {
    try {
      await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify({
          announce_enabled: $('#bc-enabled').checked ? '1' : '0',
          announce_hours: pickedHours().join(','),
          announce_quiet_hours: $('#bc-quiet').value.trim(),
          announce_busy_wait: $('#bc-busy-wait').value || '0',
        }),
      });
      toast('播报计划已保存（调度线程下一轮生效）', 'success');
      loadStatus();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function saveText() {
    try {
      await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify({
          announce_mod_time: $('#bc-mod-time').checked ? '1' : '0',
          announce_mod_status: $('#bc-mod-status').checked ? '1' : '0',
          announce_mod_weather: $('#bc-mod-weather').checked ? '1' : '0',
          announce_text_time: $('#bc-text-time').value,
          announce_text_status: $('#bc-text-status').value,
          announce_text_weather: $('#bc-text-weather').value,
        }),
      });
      toast('播报内容已保存', 'success');
      loadStatus();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function saveWeather() {
    const body = {
      weather_api_provider: $('#bc-wx-provider').value,
      weather_api_host: $('#bc-wx-host').value.trim(),
      weather_lat: $('#bc-wx-lat').value.trim(),
      weather_lon: $('#bc-wx-lon').value.trim(),
    };
    // 留空表示「不改动已保存的 key」，避免把已存的 key 抹成空
    const k = $('#bc-wx-key').value.trim();
    if (k) body.weather_api_key = k;
    try {
      await api('/api/settings', { method: 'POST', body: JSON.stringify(body) });
      $('#bc-wx-key').value = '';
      toast('天气设置已保存', 'success');
      loadStatus();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function testWeather() {
    const el = $('#bc-wx-state');
    el.textContent = '正在实测（会真的访问一次网络）…';
    try {
      const d = await api('/api/weather/api/test');
      const w = d.weather || {};
      if (w.ok) {
        el.textContent = '✅ 通了：' + (w.condition || '') + ' '
          + (w.temp_c == null ? '' : w.temp_c + '°C')
          + ' · 源 ' + (w.source || '') + ' · ' + (w.fetched_at || '');
        toast('天气 API 可用', 'success');
      } else {
        el.textContent = '❌ 没通：' + (w.error || '未知原因');
        toast('天气 API 不可用：' + (w.error || ''), 'error');
      }
    } catch (e) {
      el.textContent = '❌ 请求失败：' + e.message;
      toast(e.message, 'error');
    }
  }

  async function runAnnounce(dry) {
    const el = $('#bc-runstate');
    el.textContent = dry ? '正在合成（试听，不发射）…' : '正在播报（会真实发射）…';
    try {
      const d = await api('/api/announce/run', {
        method: 'POST', body: JSON.stringify({ dry: !!dry }),
      });
      if (d.ok) {
        el.textContent = (dry ? '✅ 已本地试听：' : '✅ 已播报：') + (d.text || '');
      } else {
        el.textContent = '⚠️ ' + (d.error || '未能播报')
          + (d.skipped ? '（本次取消，等下个整点）' : '');
      }
      loadStatus();
    } catch (e) {
      el.textContent = '❌ ' + e.message;
      toast(e.message, 'error');
    }
  }

  async function preview() {
    try {
      const d = await api('/api/announce/preview');
      $('#bc-preview').textContent = d.text || '（当前没有启用任何播报内容）';
    } catch (e) { toast(e.message, 'error'); }
  }

  function fillDefaults() {
    const d = state.defaults || {};
    if (d.time) $('#bc-text-time').value = d.time;
    if (d.status) $('#bc-text-status').value = d.status;
    if (d.weather) $('#bc-text-weather').value = d.weather;
    toast('已填入默认模板，确认后点「保存内容」', 'success');
  }

  // ---------------- 启动 ----------------
  document.addEventListener('DOMContentLoaded', () => {
    ['bc-enabled', 'bc-quiet', 'bc-busy-wait'].forEach(id => {
      const el = $('#' + id);
      if (el) el.addEventListener('change', markDirty);
    });
    $('#btn-bc-save')?.addEventListener('click', savePlan);
    $('#btn-bc-save-text')?.addEventListener('click', saveText);
    $('#btn-bc-save-wx')?.addEventListener('click', saveWeather);
    $('#btn-bc-test-wx')?.addEventListener('click', testWeather);
    $('#btn-bc-preview')?.addEventListener('click', preview);
    $('#btn-bc-fill')?.addEventListener('click', fillDefaults);
    $('#btn-bc-dry')?.addEventListener('click', () => runAnnounce(true));
    $('#btn-bc-run')?.addEventListener('click', () => {
      if (!confirm('立即播报会真实发射（占用 PTT 与信道）。确定继续？')) return;
      runAnnounce(false);
    });
    $('#bc-wx-provider')?.addEventListener('change', toggleQw);
    $('#btn-bc-refresh')?.addEventListener('click', loadStatus);

    // 默认模板由后端带下来，这里先拿一次
    api('/api/announce/status').then(d => { state.defaults = d.defaults || {}; })
      .catch(() => {});
    loadStatus();
    // 状态与记录每 10 秒刷一次；本页只在可见时轮询
    state.poll = setInterval(() => {
      if (document.visibilityState === 'visible') loadStatus();
    }, 10000);
  });
})();
