/* ELF2 中继语音日志前端 */
(function () {
  'use strict';

  const CSRF = window.VLOG_CSRF || '';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const state = {
    day: '',
    category: '',
    kind: '',
    q: '',
    limit: 100,
    offset: 0,
    items: [],
    total: 0,
    selected: null,
    segs: [],
    peaks: [],
    playTimer: null,
    refreshing: false,
  };

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

  const pad = (n) => String(n).padStart(2, '0');
  function hms(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? (h + ':' + pad(m) + ':' + pad(s)) : (m + ':' + pad(s));
  }
  function today() {
    const d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  // ---------------- 状态条 ----------------
  async function loadStatus() {
    try {
      const d = await api('/api/voice/status');
      const rec = d.recording;
      const badge = $('#vlog-live-badge');
      badge.className = 'badge ' + (rec ? 'busy' : 'idle');
      badge.textContent = rec
        ? ('录音中 ' + (d.kind === 'tx' ? '发射' : d.kind === 'both' ? '收发' : '接收'))
        : (d.active ? '收尾中' : '空闲');

      const rx = $('#vlog-rx-badge');
      rx.className = 'badge ' + (d.rx ? 'on' : 'idle');
      rx.textContent = 'BUSY ' + (d.rx ? '有信号' : '空闲');
      const tx = $('#vlog-tx-badge');
      tx.className = 'badge ' + (d.tx ? 'busy' : 'idle');
      tx.textContent = 'PTT ' + (d.tx ? '发射中' : '释放');

      const t = d.today || {};
      $('#vlog-m-total').textContent = t.total || 0;
      $('#vlog-m-voice').textContent = (t.categories && t.categories.voice) ? t.categories.voice.n : 0;
      $('#vlog-m-sec').textContent = hms(t.seconds || 0);
      $('#vlog-m-mb').textContent = (d.size_mb || 0).toFixed(1);

      $('#vlog-st-rec').textContent = rec
        ? ('正在写入 · ' + (d.stats && d.stats.error ? ('异常: ' + d.stats.error) : '正常'))
        : ('待触发 · 已记录 ' + ((d.stats && d.stats.sessions) || 0) + ' 次会话 / '
           + ((d.stats && d.stats.segments) || 0) + ' 段');
      $('#vlog-st-asr').textContent = d.asr_running
        ? ('处理中 ' + ((d.asr_current && d.asr_current.file) || ''))
        : (d.queue ? (d.queue + ' 条待处理') : '空闲')
          + (d.counters ? (' · 完成 ' + (d.counters.asr_done || 0)
            + ' 失败 ' + (d.counters.asr_error || 0)) : '');
      $('#vlog-st-vad').textContent = (d.vad && d.vad.available)
        ? ('silero 已加载 · ' + (d.vad.model || '').split('/').pop())
        : ('silero ' + ((d.vad && d.vad.state) || '不可用')
           + (d.vad && d.vad.error ? ('（' + d.vad.error + '）') : ''));
      $('#vlog-st-llm').textContent = (d.llm && d.llm.ready)
        ? '就绪（常驻中）'
        : ((d.llm && d.llm.running) ? '启动中…' : '未加载（按需启动）');
      const cats = (t.categories || {});
      $('#vlog-st-cats').textContent = Object.keys(cats).length
        ? Object.keys(cats).map(k => k + ' ' + cats[k].n).join(' / ')
        : '--';
      const lv = d.level || {};
      const lvEl = $('#vlog-st-level');
      if (lvEl) {
        lvEl.textContent = '最近峰值 ' + (lv.recent_peak || 0) + ' / rms '
          + (lv.recent_dbfs === undefined ? '--' : lv.recent_dbfs) + ' dBFS'
          + (lv.clipped ? ('　⚠ ' + lv.clipped + ' 条削顶，请降低 PGA') : '');
        lvEl.className = lv.clipped ? 'vlog-warn' : '';
        lvEl.title = lv.hint || '';
      }
      const status = d.status || {};
      $('#vlog-st-ret').textContent = '保留 ' + ((d.retention && d.retention.days) || 30) + ' 天 / '
        + ((d.retention && d.retention.mb) || 20480) + ' MB · 当前 '
        + (d.files || 0) + ' 文件';
      if (d.summary) {
        const s = d.summary;
        $('#vlog-sum-state').textContent = s.running
          ? ('生成中：' + (s.stage || '') + '（' + (s.chunks || 0) + ' 块）')
          : ('日报时间 ' + (d.summary_time || '23:30') + ' · 引擎 '
             + ({ auto: '自动', local: '本地 LLM', external: '外部 API' }[d.summary_provider] || d.summary_provider)
             + (s.error ? (' · 上次失败: ' + s.error) : ''));
      }
    } catch (e) { /* 静默，避免刷屏 */ }
  }

  // ---------------- 日期列表 ----------------
  async function loadDays() {
    try {
      const d = await api('/api/voice/days');
      const sel = $('#vlog-day');
      const cur = state.day || today();
      const days = (d.days || []).map(x => x.day);
      if (!days.includes(cur)) days.unshift(cur);
      sel.innerHTML = '';
      days.forEach(day => {
        const o = document.createElement('option');
        o.value = day; o.textContent = day;
        sel.appendChild(o);
      });
      sel.value = cur;
      state.day = cur;
    } catch (e) { toast(e.message, 'error'); }
  }

  // ---------------- 列表 ----------------
  async function loadList() {
    if (state.refreshing) return;
    state.refreshing = true;
    try {
      const qs = new URLSearchParams({
        day: state.day, limit: state.limit, offset: state.offset,
      });
      if (state.category) qs.set('category', state.category);
      if (state.kind) qs.set('kind', state.kind);
      if (state.q) qs.set('q', state.q);
      const d = await api('/api/voice/list?' + qs.toString());
      state.items = d.items || [];
      renderList();
      const total = (d.stats && d.stats.total) || 0;
      $('#vlog-page-info').textContent = '第 ' + (Math.floor(state.offset / state.limit) + 1)
        + ' 页 · 共 ' + total + ' 条';
      $('#btn-vlog-prev').disabled = state.offset <= 0;
      $('#btn-vlog-next').disabled = state.offset + state.limit >= total;
      const st = d.stats || {};
      $('#vlog-m-total-sub').textContent = '段 · 当前筛选 ' + state.items.length;
      loadTimeline();
    } catch (e) {
      toast('加载失败：' + e.message, 'error');
    } finally {
      state.refreshing = false;
    }
  }

  function tag(cls, text) {
    const s = document.createElement('span');
    s.className = 'tag ' + cls;
    s.textContent = text;
    return s;
  }

  function renderList() {
    const box = $('#vlog-list');
    box.innerHTML = '';
    if (!state.items.length) {
      const d = document.createElement('div');
      d.className = 'muted small vlog-empty';
      d.textContent = '该日期（或筛选条件下）没有记录。中继一旦收到信号或本机发射就会自动生成。';
      box.appendChild(d);
      return;
    }
    state.items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'vlog-item' + (state.selected === it.id ? ' sel' : '');
      row.dataset.id = it.id;

      const tm = document.createElement('div');
      tm.className = 'vlog-item-time';
      tm.textContent = (it.ts || '').slice(11, 19);

      const main = document.createElement('div');
      main.className = 'vlog-item-main';
      const tags = document.createElement('div');
      tags.className = 'vlog-item-tags';
      tags.appendChild(tag('k-' + it.kind, it.kind_label));
      tags.appendChild(tag('c-' + (it.category || 'pending'), it.category_label));
      (it.callsigns || []).forEach(cs => {
        const raw = (it.callsigns_raw || []).filter(x => x && x !== cs);
        const t = tag('cs', '呼号 ' + cs);
        if (raw.length) t.title = '识别原文为 ' + raw.join('/') + '，已按白名单纠错';
        tags.appendChild(t);
      });
      if (it.asr_status === 'pending' || it.asr_status === 'running') {
        tags.appendChild(tag('asr-' + it.asr_status, it.asr_status === 'running' ? '识别中' : '待识别'));
      } else if (it.asr_status === 'error') {
        tags.appendChild(tag('asr-error', '识别失败'));
      }
      main.appendChild(tags);
      const txt = document.createElement('div');
      const hasText = (it.text || '').trim().length > 0;
      txt.className = 'vlog-item-text' + (hasText ? '' : ' no-text');
      txt.textContent = hasText ? it.text : ('（' + it.category_label + '，无识别文字）');
      main.appendChild(txt);

      const right = document.createElement('div');
      right.className = 'vlog-item-right';
      right.textContent = it.seconds.toFixed(1) + 's';

      row.appendChild(tm); row.appendChild(main); row.appendChild(right);
      row.addEventListener('click', () => selectItem(it.id));
      box.appendChild(row);
    });
  }

  // ---------------- 全天时间轴 ----------------
  async function loadTimeline() {
    try {
      const d = await api('/api/voice/timeline?day=' + encodeURIComponent(state.day));
      const track = $('#vlog-tl-track');
      track.innerHTML = '';
      const dayStart = new Date(state.day + 'T00:00:00').getTime() / 1000;
      const span = 86400;
      (d.items || []).forEach(it => {
        const left = Math.max(0, Math.min(100, ((it.epoch - dayStart) / span) * 100));
        const w = Math.max(0.25, ((it.seconds || 1) / span) * 100);
        const b = document.createElement('div');
        b.className = 'vlog-tl-block cat-' + (it.category || it.kind || 'empty')
          + (it.kind === 'tx' ? ' kind-tx' : '') + (it.kind === 'both' ? ' kind-both' : '');
        b.style.left = left + '%';
        b.style.width = w + '%';
        b.title = (it.ts || '') + ' · ' + (it.seconds || 0).toFixed(1) + 's';
        b.dataset.id = it.id;
        b.addEventListener('click', () => selectItem(it.id));
        track.appendChild(b);
      });
      const now = Date.now() / 1000;
      if (state.day === today() && now >= dayStart && now < dayStart + span) {
        const n = document.createElement('div');
        n.className = 'vlog-tl-now';
        n.style.left = (((now - dayStart) / span) * 100) + '%';
        track.appendChild(n);
      }
      markTimelineCursor();
    } catch (e) { /* 忽略 */ }
  }

  function markTimelineCursor() {
    const track = $('#vlog-tl-track');
    if (!track) return;
    const old = track.querySelector('.vlog-tl-cursor');
    if (old) old.remove();
    if (!state.selected) return;
    const it = state.items.find(x => x.id === state.selected);
    if (!it) return;
    const dayStart = new Date(state.day + 'T00:00:00').getTime() / 1000;
    const c = document.createElement('div');
    c.className = 'vlog-tl-cursor';
    c.style.left = (((it.epoch - dayStart) / 86400) * 100) + '%';
    track.appendChild(c);
  }

  // ---------------- 详情 ----------------
  async function selectItem(id) {
    state.selected = id;
    $$('.vlog-item').forEach(el => el.classList.toggle('sel', Number(el.dataset.id) === id));
    const it = state.items.find(x => x.id === id);
    if (!it) return;
    $('#vlog-detail').classList.remove('hidden');
    $('#vlog-detail-title').textContent = (it.ts || '').replace('T', ' ');
    $('#vlog-d-kind').textContent = it.kind_label;
    $('#vlog-d-cat').textContent = it.category_label;
    $('#vlog-d-info').textContent = it.seconds.toFixed(1) + 's · rms '
      + (it.rms || 0).toFixed(0) + ' · 峰值 ' + (it.peak || 0) + ' · '
      + ((it.bytes || 0) / 1024).toFixed(0) + ' KB'
      + (it.rtf ? (' · RTF ' + it.rtf) : '')
      + ((it.callsigns || []).length ? (' · 呼号 ' + it.callsigns.join('/')) : '');
    $('#vlog-d-download').href = '/api/voice/' + id + '/download';

    const audio = $('#vlog-audio');
    audio.src = '/api/voice/' + id + '/audio';
    if ($('#vlog-autoplay').checked) {
      audio.play().catch(() => {});
    }
    renderSegs(it);
    markTimelineCursor();

    try {
      const d = await api('/api/voice/' + id + '/peaks?n=700');
      state.peaks = d.peaks || [];
      drawWave();
    } catch (e) { state.peaks = []; drawWave(); }
  }

  function renderSegs(it) {
    const box = $('#vlog-segs');
    box.innerHTML = '';
    const segs = it.segments || [];
    state.segs = segs;
    if (!segs.length) {
      const d = document.createElement('div');
      d.className = 'muted small';
      d.textContent = (it.text || '').trim()
        ? it.text
        : ('本条为「' + it.category_label + '」，未生成文字（非语音不送 ASR，避免幻觉）。');
      if ((it.text || '').trim() && it.asr_status === 'done') {
        d.className = 'vlog-seg vlog-seg-full';
      }
      box.appendChild(d);
      return;
    }
    segs.forEach(sg => {
      const row = document.createElement('div');
      row.className = 'vlog-seg';
      row.dataset.start = sg.start;
      row.dataset.end = sg.end;
      const t = document.createElement('div');
      t.className = 'vlog-seg-time';
      t.textContent = sg.start.toFixed(1) + 's';
      const x = document.createElement('div');
      x.textContent = sg.text;
      row.appendChild(t); row.appendChild(x);
      row.addEventListener('click', () => {
        const a = $('#vlog-audio');
        a.currentTime = Math.max(0, Number(sg.start) - 0.1);
        a.play().catch(() => {});
      });
      box.appendChild(row);
    });
  }

  function drawWave() {
    const cv = $('#vlog-canvas');
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth || 480, h = 120;
    cv.width = w * dpr; cv.height = h * dpr;
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.fillStyle = '#0d1526';
    g.fillRect(0, 0, w, h);
    const p = state.peaks || [];
    if (!p.length) {
      g.fillStyle = '#64748b'; g.font = '12px sans-serif';
      g.fillText('无波形数据', 10, h / 2);
      return;
    }
    const max = Math.max.apply(null, p) || 1;
    const step = w / p.length;
    g.fillStyle = '#3b82f6';
    for (let i = 0; i < p.length; i++) {
      const bh = Math.max(1, (p[i] / max) * (h - 8));
      g.fillRect(i * step, (h - bh) / 2, Math.max(1, step - 0.4), bh);
    }
    if (state.segs && state.segs.length) {
      g.fillStyle = 'rgba(34,197,94,.18)';
      const dur = $('#vlog-audio').duration || 0;
      if (dur > 0) {
        state.segs.forEach(sg => {
          g.fillRect((sg.start / dur) * w, 0, Math.max(1, ((sg.end - sg.start) / dur) * w), h);
        });
      }
    }
  }

  function onTimeUpdate() {
    const a = $('#vlog-audio');
    const t = a.currentTime;
    $$('#vlog-segs .vlog-seg').forEach(el => {
      const s = Number(el.dataset.start || -1), e = Number(el.dataset.end || -1);
      el.classList.toggle('act', s >= 0 && t >= s && t <= e);
    });
    const cv = $('#vlog-canvas');
    if (cv && a.duration > 0) {
      drawWave();
      const g = cv.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const w = cv.clientWidth || 480;
      g.fillStyle = '#f87171';
      g.fillRect((t / a.duration) * w, 0, 1.5, 120);
    }
  }

  // ---------------- 日报 ----------------
  async function loadSummary() {
    try {
      const d = await api('/api/voice/summary?day=' + encodeURIComponent(state.day));
      const s = d.summary || {};
      $('#vlog-summary').textContent = s.summary
        || ((d.transcript || '').trim()
          ? '该日期还没有生成日报。点击「立即生成日报」即可基于当日 ' +
            ((d.transcript || '').split('\n').length) + ' 条语音转写生成。'
          : '该日期没有可总结的语音通联内容。');
      $('#vlog-transcript').textContent = d.transcript || '（无）';
      if (s.status && s.status !== 'done' && s.error) {
        $('#vlog-summary').textContent = '上次生成失败：' + s.error;
      }
      const st = d.state || {};
      if (st.running) {
        $('#vlog-sum-state').textContent = '生成中：' + (st.stage || '') + '（' + (st.chunks || 0) + ' 块）';
      }
    } catch (e) { /* 忽略 */ }
  }

  async function runSummary() {
    const btn = $('#btn-vlog-summary-run');
    btn.disabled = true;
    try {
      const prov = $('#vlog-sum-provider').value;
      await api('/api/voice/summary/run', {
        method: 'POST',
        body: JSON.stringify({ day: state.day, provider: prov }),
      });
      toast('已开始生成日报，请稍候…', 'success');
      pollSummary();
    } catch (e) {
      toast('生成失败：' + e.message, 'error');
      btn.disabled = false;
    }
  }

  function pollSummary() {
    const btn = $('#btn-vlog-summary-run');
    let n = 0;
    clearInterval(state.playTimer);
    state.playTimer = setInterval(async () => {
      n++;
      await loadStatus();
      await loadSummary();
      const running = /生成中/.test($('#vlog-sum-state').textContent || '');
      if (!running || n > 120) {
        clearInterval(state.playTimer);
        btn.disabled = false;
        if (!running) toast('日报已更新', 'success');
      }
    }, 4000);
  }

  async function loadCsWhitelist() {
    try {
      const d = await api('/api/settings');
      const s = d.settings || {};
      const el = $('#vlog-cs-whitelist');
      if (el) el.value = s.vlog_callsign_whitelist || '';
    } catch (e) { /* 非管理员读取失败可忽略 */ }
  }

  async function saveCsWhitelist() {
    const el = $('#vlog-cs-whitelist');
    if (!el) return;
    try {
      await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify({ vlog_callsign_whitelist: el.value }),
      });
      toast('呼号白名单已保存（对之后的新录音生效）', 'success');
      el.value = (el.value || '').toUpperCase();
    } catch (e) { toast('保存失败：' + e.message, 'error'); }
  }

  // ---------------- 事件 ----------------
  function bind() {
    $('#btn-vlog-refresh').addEventListener('click', () => { loadDays(); loadList(); loadSummary(); loadStatus(); });
    $('#vlog-day').addEventListener('change', (e) => {
      state.day = e.target.value; state.offset = 0; state.selected = null;
      $('#vlog-detail').classList.add('hidden');
      loadList(); loadSummary();
    });
    $('#vlog-cat').addEventListener('change', (e) => { state.category = e.target.value; state.offset = 0; loadList(); });
    $('#vlog-kind').addEventListener('change', (e) => { state.kind = e.target.value; state.offset = 0; loadList(); });
    $('#btn-vlog-search').addEventListener('click', () => { state.q = $('#vlog-q').value.trim(); state.offset = 0; loadList(); });
    $('#vlog-q').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { state.q = e.target.value.trim(); state.offset = 0; loadList(); }
    });
    $('#btn-vlog-prev').addEventListener('click', () => {
      state.offset = Math.max(0, state.offset - state.limit); loadList();
    });
    $('#btn-vlog-next').addEventListener('click', () => {
      state.offset += state.limit; loadList();
    });
    $$('[data-export]').forEach(b => b.addEventListener('click', () => {
      window.location.href = '/api/voice/export?day=' + encodeURIComponent(state.day)
        + '&fmt=' + b.dataset.export;
    }));
    $('#vlog-audio').addEventListener('timeupdate', onTimeUpdate);
    $('#vlog-audio').addEventListener('loadedmetadata', drawWave);
    window.addEventListener('resize', drawWave);

    $('#vlog-canvas').addEventListener('click', (e) => {
      const cv = $('#vlog-canvas');
      const a = $('#vlog-audio');
      if (!a.duration) return;
      const rect = cv.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      a.currentTime = Math.max(0, Math.min(a.duration, pct * a.duration));
    });

    $('#btn-vlog-retranscribe').addEventListener('click', async () => {
      if (!state.selected) return;
      try {
        await api('/api/voice/' + state.selected + '/retranscribe', { method: 'POST', body: '{}' });
        toast('已加入识别队列', 'success');
        setTimeout(loadList, 2500);
      } catch (e) { toast(e.message, 'error'); }
    });

    $('#btn-vlog-delete').addEventListener('click', async () => {
      if (!state.selected) return;
      if (!confirm('确定删除这条录音及记录？此操作不可恢复。')) return;
      try {
        await api('/api/voice/' + state.selected + '/delete', { method: 'POST', body: '{}' });
        toast('已删除', 'success');
        state.selected = null;
        $('#vlog-detail').classList.add('hidden');
        loadDays(); loadList(); loadStatus();
      } catch (e) { toast(e.message, 'error'); }
    });

    $('#btn-vlog-summary-run').addEventListener('click', runSummary);
    $('#btn-vlog-cs-save').addEventListener('click', saveCsWhitelist);
  }

  // ---------------- 启动 ----------------
  document.addEventListener('DOMContentLoaded', async () => {
    await loadDays();
    bind();
    await loadStatus();
    await loadList();
    await loadSummary();
    await loadCsWhitelist();
    loadStatus();
    setInterval(loadStatus, 3000);
    setInterval(() => {
      const a = $('#vlog-audio');
      if (a && !a.paused) return;
      loadList();
    }, 15000);
  });
})();
