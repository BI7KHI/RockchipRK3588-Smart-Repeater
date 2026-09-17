/* ELF2 智能中继控制中心前端逻辑 */
(function () {
  'use strict';

  const role = window.APP_ROLE || 'user';
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let ttsState = { current: 'local', voices: [] };   // 外部 TTS 已下线，仅本地 Piper

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function showToast(msg, type = '') {
    const el = $('#toast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'toast show ' + type;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.className = 'toast ' + type; }, 3200);
  }

  async function apiFetch(url, options = {}) {
    const opts = Object.assign({}, options);
    opts.headers = Object.assign({}, opts.headers || {});
    if (!(opts.body instanceof FormData)) {
      opts.headers['Content-Type'] = 'application/json';
    }
    if (opts.method && opts.method !== 'GET') {
      opts.headers['X-CSRF-Token'] = csrfToken;
    }
    const resp = await fetch(url, opts);
    if (resp.status === 401) {
      location.href = '/login';
      throw new Error('未登录');
    }
    const ct = resp.headers.get('content-type') || '';
    let data;
    if (ct.includes('application/json')) {
      data = await resp.json();
    } else {
      data = { ok: resp.ok, text: await resp.text() };
    }
    if (!resp.ok || (data && data.ok === false)) {
      throw new Error((data && data.error) || `HTTP ${resp.status}`);
    }
    return data;
  }

  function fmtUptime(sec) {
    sec = Math.floor(sec || 0);
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d) return `${d}天 ${h}小时`;
    if (h) return `${h}小时 ${m}分`;
    return `${m}分 ${sec % 60}秒`;
  }

  function startBeijingClock() {
    const el = $('#clock-beijing');
    if (!el) return;
    const fmt = new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    });
    const tick = () => {
      const parts = fmt.formatToParts(new Date());
      const get = (t) => parts.find(p => p.type === t)?.value || '';
      el.textContent = `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`;
    };
    tick();
    setInterval(tick, 1000);
  }

  function setBar(id, percent) {
    const el = $(id);
    if (el) el.style.width = Math.max(0, Math.min(100, percent)) + '%';
  }

  // ---------------- tabs ----------------
  function initTabs() {
    $$('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.tab-btn').forEach(b => b.classList.remove('active'));
        $$('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const p = $('#tab-' + btn.dataset.tab);
        if (p) p.classList.add('active');
      });
    });
    if (role !== 'admin') {
      $$('.admin-only').forEach(el => { el.style.display = 'none'; });
    }
  }

  // ---------------- overview ----------------
  async function loadStatus() {
    try {
      const data = await apiFetch('/api/status');
      const v = data.voltages || {};
      if (v.battery) {
        $('#battery-voltage').textContent = (v.battery.voltage ?? '--') + ' V';
        $('#battery-raw').textContent = `raw ${v.battery.raw ?? '--'} · 引脚 ${v.battery.pin_voltage ?? '--'} V · 倍率 ${v.battery.multiplier ?? '--'} V/V`;
        setBar('#battery-bar', Math.min(100, (v.battery.voltage || 0) / 15 * 100));
      }
      if (v.pv) {
        $('#pv-voltage').textContent = (v.pv.voltage ?? '--') + ' V';
        $('#pv-raw').textContent = `raw ${v.pv.raw ?? '--'} · 引脚 ${v.pv.pin_voltage ?? '--'} V · 倍率 ${v.pv.multiplier ?? '--'} V/V`;
        setBar('#pv-bar', Math.min(100, (v.pv.voltage || 0) / 30 * 100));
      }
      $('#cpu-percent').textContent = (data.cpu_percent ?? '--') + ' %';
      $('#loadavg').textContent = `Load ${(+data.loadavg['1m']).toFixed(2)} / ${(+data.loadavg['5m']).toFixed(2)} / ${(+data.loadavg['15m']).toFixed(2)}`;
      setBar('#cpu-bar', data.cpu_percent || 0);
      const mem = data.memory || {};
      $('#mem-percent').textContent = (mem.percent ?? '--') + ' %';
      $('#mem-detail').textContent = mem.total ? `${(mem.used / 1073741824).toFixed(1)} / ${(mem.total / 1073741824).toFixed(1)} GiB` : '--';
      setBar('#mem-bar', mem.percent || 0);
      const tEl = $('#temperatures');
      if (tEl) {
        if (data.temperatures && data.temperatures.length) {
          tEl.innerHTML = data.temperatures.map(t => `<div><span>${escapeHtml(t.name)}</span><b>${t.celsius} °C</b></div>`).join('');
        } else {
          tEl.innerHTML = '<span class="muted">无温度传感器</span>';
        }
      }
      $('#uptime').textContent = fmtUptime(data.uptime_seconds);
      $('#last-update').textContent = '更新于 ' + (data.time || '');
    } catch (e) {
      console.warn('status error', e);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // ---------------- voltage calibration ----------------
  let calCache = {};

  function renderCalLive(v) {
    calCache = v || {};
    const box = $('#cal-live');
    if (!box) return;
    const item = (key) => {
      const c = calCache[key];
      if (!c) return '';
      return `${escapeHtml(c.label || key)} <b>${c.voltage ?? '--'} V</b>`;
    };
    const parts = [item('battery'), item('pv')].filter(Boolean);
    box.innerHTML = parts.length ? ('实时值：' + parts.join('　·　')) : '实时值：--';
  }

  async function loadCalibration() {
    try {
      const data = await apiFetch('/api/status');
      const v = data.voltages || {};
      if (v.battery) {
        if ($('#battery-ch')) $('#battery-ch').value = v.battery.adc_channel;
        $('#battery-zero').value = v.battery.zero_raw;
        $('#battery-mult').value = v.battery.multiplier;
      }
      if (v.pv) {
        if ($('#pv-ch')) $('#pv-ch').value = v.pv.adc_channel;
        $('#pv-zero').value = v.pv.zero_raw;
        $('#pv-mult').value = v.pv.multiplier;
      }
      renderCalLive(v);
    } catch (e) { showToast(e.message, 'error'); }
  }

  // 填入设计值：倍率 = 1/分压比（电池 10.11、光伏 17.01）
  function fillDesignCal() {
    let n = 0;
    ['battery', 'pv'].forEach((key) => {
      const c = calCache[key];
      if (!c || c.design_multiplier == null) return;
      const el = $(key === 'battery' ? '#battery-mult' : '#pv-mult');
      if (el) { el.value = c.design_multiplier; n += 1; }
    });
    showToast(n ? `已填入设计倍率（${n} 个通道），保存后生效` : '设计值不可用', n ? 'success' : 'error');
  }

  async function saveCalibration() {
    try {
      await apiFetch('/api/voltage/calibrate', {
        method: 'POST',
        body: JSON.stringify({
          battery_adc_channel: parseInt($('#battery-ch')?.value ?? '4', 10),
          battery_zero_raw: parseFloat($('#battery-zero').value),
          battery_multiplier: parseFloat($('#battery-mult').value),
          pv_adc_channel: parseInt($('#pv-ch')?.value ?? '6', 10),
          pv_zero_raw: parseFloat($('#pv-zero').value),
          pv_multiplier: parseFloat($('#pv-mult').value),
        }),
      });
      showToast('电压校准已保存', 'success');
      loadStatus();
      loadCalibration();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ---------------- users ----------------
  async function loadUsers() {
    if (role !== 'admin') return;
    try {
      const data = await apiFetch('/api/users');
      const tbody = $('#users-table tbody');
      if (!data.users.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted">暂无用户</td></tr>';
        return;
      }
      tbody.innerHTML = data.users.map(u => `
        <tr>
          <td>${u.id}</td>
          <td>${escapeHtml(u.username)}</td>
          <td>${u.role === 'admin' ? '管理员' : '用户'}</td>
          <td>${escapeHtml(u.last_login || '--')}</td>
          <td>
            <button class="btn ghost" data-reset="${u.id}" data-name="${escapeHtml(u.username)}">重置密码</button>
            ${u.username.toLowerCase() === 'admin' ? '' : `<button class="btn ghost" data-del="${u.id}" data-name="${escapeHtml(u.username)}">删除</button>`}
          </td>
        </tr>`).join('');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function addUser() {
    try {
      await apiFetch('/api/users', {
        method: 'POST',
        body: JSON.stringify({
          username: $('#new-user-name').value,
          password: $('#new-user-pass').value,
          role: $('#new-user-role').value,
        }),
      });
      $('#new-user-name').value = '';
      $('#new-user-pass').value = '';
      showToast('用户已添加', 'success');
      loadUsers();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ---------------- settings ----------------
  async function loadSettings() {
    if (role !== 'admin') return;
    try {
      const data = await apiFetch('/api/settings');
      const s = data.settings;
      $('#set-llm-provider').value = s.llm_provider || 'local';
      $('#set-local-base').value = s.local_base_url || '';
      $('#set-local-model').value = s.local_model || '';
      $('#set-ext-base').value = s.external_base_url || '';
      $('#set-ext-model').value = s.external_model || '';
      $('#set-auto-play').checked = s.record_auto_play === '1';
      if (s.local_api_key_set) $('#set-local-key').placeholder = '已设置，留空保持不变';
      if (s.external_api_key_set) $('#set-ext-key').placeholder = '已设置，留空保持不变';
      if ($('#set-tts-voice')) $('#set-tts-voice').value = s.tts_local_voice || '';
      if ($('#set-tts-en-voice')) $('#set-tts-en-voice').value = s.tts_en_voice || '';
      if ($('#set-tts-icao')) $('#set-tts-icao').checked = s.tts_icao === '1';
      if ($('#set-tts-icao-voice')) $('#set-tts-icao-voice').dataset.saved = s.tts_icao_voice || '';
      if ($('#tts-icao')) $('#tts-icao').checked = s.tts_icao !== '0';
      if ($('#set-tts-auto-speak')) $('#set-tts-auto-speak').checked = s.tts_auto_speak === '1';
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function saveSettings() {
    const body = {
      llm_provider: $('#set-llm-provider').value,
      local_base_url: $('#set-local-base').value,
      local_model: $('#set-local-model').value,
      external_base_url: $('#set-ext-base').value,
      external_model: $('#set-ext-model').value,
      record_auto_play: $('#set-auto-play').checked ? '1' : '0',
      tts_local_voice: $('#set-tts-voice')?.value || '',
      tts_en_voice: $('#set-tts-en-voice')?.value || '',
      tts_icao: $('#set-tts-icao')?.checked ? '1' : '0',
      tts_icao_voice: $('#set-tts-icao-voice')?.value || '',
      tts_auto_speak: $('#set-tts-auto-speak')?.checked ? '1' : '0',
    };
    if ($('#set-local-key').value) body.local_api_key = $('#set-local-key').value;
    if ($('#set-ext-key').value) body.external_api_key = $('#set-ext-key').value;
    try {
      await apiFetch('/api/settings', { method: 'POST', body: JSON.stringify(body) });
      showToast('设置已保存', 'success');
      loadSettings();
      loadProviders();
      loadTtsProviders();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function changeOwnPassword() {
    try {
      await apiFetch('/api/me/password', {
        method: 'POST',
        body: JSON.stringify({ old_password: $('#my-old-pass').value, new_password: $('#my-new-pass').value }),
      });
      $('#my-old-pass').value = '';
      $('#my-new-pass').value = '';
      showToast('密码已修改', 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ---------------- global audio volume ----------------
  function renderMixerStatus(data) {
    const el = $('#audio-mixer-status');
    if (!el) return;
    const row = (name, v) => v ? `<div><span>${name}</span><b>${v.percent ?? '--'}% ${v.on === false ? '（静音）' : '（开启）'}</b></div>` : `<div><span>${name}</span><b class="muted">不可用</b></div>`;
    el.innerHTML = [
      row('Headphone', data.headphone),
      row('Speaker', data.speaker),
      row('PCM', data.pcm),
      `<div><span>播放设备</span><b>${escapeHtml(data.device || '--')}</b></div>`,
    ].join('');
  }

  async function loadAudioVolume() {
    if (role !== 'admin') return;
    try {
      const data = await apiFetch('/api/audio/volume');
      const slider = $('#volume-slider');
      if (slider) slider.value = data.percent ?? 80;
      if ($('#volume-value')) $('#volume-value').textContent = (data.percent ?? '--') + '%';
      if ($('#volume-mute')) $('#volume-mute').checked = !!data.muted;
      renderMixerStatus(data);
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function applyAudioVolume() {
    try {
      const data = await apiFetch('/api/audio/volume', {
        method: 'POST',
        body: JSON.stringify({
          percent: parseInt($('#volume-slider')?.value || '80', 10),
          muted: !!$('#volume-mute')?.checked,
        }),
      });
      if ($('#volume-value')) $('#volume-value').textContent = (data.percent ?? '--') + '%';
      showToast(`全局音量已设为 ${data.percent}%${data.muted ? '（静音）' : ''}`, 'success');
      loadAudioVolume();
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ---------------- LLM chat ----------------
  let chatMessages = [];
  let ttsStreamSession = null;
  let ttsStreamBuffer = '';
  let ttsStreamPending = Promise.resolve();

  async function loadProviders() {
    try {
      const data = await apiFetch('/api/chat/providers');
      const sel = $('#llm-provider');
      sel.value = data.current || 'local';
      const cfg = data.providers[sel.value];
      $('#llm-model').value = cfg ? cfg.model : '';
      $('#llm-config-hint').textContent = cfg ? `${cfg.base_url || '未配置'} · ${cfg.model}` : '';
    } catch (e) {
      showToast(e.message, 'error');
    }
  }

  function addChatBubble(roleName, content) {
    const el = document.createElement('div');
    el.className = 'msg ' + roleName;
    el.textContent = content;
    const history = $('#chat-history');
    history.appendChild(el);
    history.scrollTop = history.scrollHeight;
    return el;
  }

  // 每个浏览器标签页一个 client id：板端只停同一标签页的旧流式会话，
  // 别的标签页 / 其它设备开始朗读不会掐断当前这一路回复
  const TTS_CLIENT_ID = (() => {
    try {
      let v = sessionStorage.getItem('elf2-tts-client');
      if (!v) {
        v = (window.crypto && crypto.randomUUID)
          ? crypto.randomUUID()
          : 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
        sessionStorage.setItem('elf2-tts-client', v);
      }
      return v;
    } catch (e) {
      return '';
    }
  })();

  async function startTtsStream() {
    const data = await apiFetch('/api/tts/stream/start', {
      method: 'POST', body: JSON.stringify({ client_id: TTS_CLIENT_ID }),
    });
    ttsStreamSession = data.session_id;
    ttsStreamBuffer = '';
    ttsStreamPending = Promise.resolve();
    if ($('#tts-stream-status')) $('#tts-stream-status').textContent = '流式朗读：已启动（PTT 随音频使能）';
  }

  function enqueueTtsChunk(text) {
    if (!ttsStreamSession || !text || !text.trim()) return;
    const sid = ttsStreamSession;
    const provider = 'local';   // 仅本地 Piper
    const voice = $('#tts-voice')?.value || '';
    // 与 speakText 保持一致：英文音色 / ICAO 开关对流式朗读同样生效
    const body = {
      session_id: sid, client_id: TTS_CLIENT_ID, text, provider, voice,
      en_voice: ttsEnVoice(), icao: ttsIcao(),
      icao_voice: $('#set-tts-icao-voice')?.value || '',
    };
    ttsStreamPending = ttsStreamPending
      .then(() => postTtsChunk(body))
      .catch(e => {
        console.warn('TTS stream chunk failed', e);
        if ($('#tts-stream-status')) $('#tts-stream-status').textContent = '流式朗读：片段投递失败（网络）';
      });
  }

  // 片段投递：板端链路偶发抖动（eth0 重新协商等）时退避重试，
  // 会话已被回收/重启则重建会话后重投这一段，避免丢字（原来失败即静默丢弃）。
  async function postTtsChunk(body, tries = 4) {
    let lastErr = null;
    for (let i = 0; i < tries; i++) {
      try {
        return await apiFetch('/api/tts/stream/chunk', {
          method: 'POST', body: JSON.stringify(body),
        });
      } catch (e) {
        lastErr = e;
        const msg = String((e && e.message) || e);
        if (/不存在|已结束|不属于/.test(msg)) {
          try {
            const d = await apiFetch('/api/tts/stream/start', {
              method: 'POST', body: JSON.stringify({ client_id: TTS_CLIENT_ID }),
            });
            ttsStreamSession = d.session_id;
            body.session_id = d.session_id;
          } catch (_) { /* 下一轮继续重试 */ }
        }
        await new Promise(r => setTimeout(r, 250 * (i + 1)));
      }
    }
    throw lastErr || new Error('片段投递失败');
  }

  function pumpTtsChunks(force = false) {
    if (!ttsStreamSession || !ttsStreamBuffer) return;
    // 优先按句末标点切分
    let cut = -1;
    for (let i = ttsStreamBuffer.length - 1; i >= 0; i--) {
      if ('。！？!?；;\n'.includes(ttsStreamBuffer[i])) { cut = i + 1; break; }
    }
    if (cut > 0) {
      enqueueTtsChunk(ttsStreamBuffer.slice(0, cut));
      ttsStreamBuffer = ttsStreamBuffer.slice(cut);
    } else if (ttsStreamBuffer.length > 80) {
      // 没有标点时，按逗号/空格切分，保证实时性
      let p = Math.max(ttsStreamBuffer.lastIndexOf('，'), ttsStreamBuffer.lastIndexOf(','), ttsStreamBuffer.lastIndexOf(' '));
      if (p < 20) p = 60;
      enqueueTtsChunk(ttsStreamBuffer.slice(0, p + 1));
      ttsStreamBuffer = ttsStreamBuffer.slice(p + 1);
    }
    if (force && ttsStreamBuffer.trim()) {
      enqueueTtsChunk(ttsStreamBuffer);
      ttsStreamBuffer = '';
    }
  }

  async function finishTtsStream() {
    if (!ttsStreamSession) return;
    pumpTtsChunks(true);
    if ($('#tts-stream-status')) $('#tts-stream-status').textContent = '流式朗读：播放剩余片段';
    try {
      await ttsStreamPending;
      const sid = ttsStreamSession;      // 期间可能已重建会话，取最新的
      ttsStreamSession = null;
      const res = await apiFetch('/api/tts/stream/end', {
        method: 'POST', body: JSON.stringify({ session_id: sid, client_id: TTS_CLIENT_ID }),
      });
      const err = res && res.last_error;
      if (err) {
        showToast('流式朗读失败：' + err, 'error');
        if ($('#tts-stream-status')) $('#tts-stream-status').textContent = '流式朗读：失败（' + err + '）';
      } else if ($('#tts-stream-status')) {
        $('#tts-stream-status').textContent = '流式朗读：已完成';
      }
    } catch (e) {
      console.warn('TTS stream end failed', e);
      if ($('#tts-stream-status')) $('#tts-stream-status').textContent = '流式朗读：异常';
    }
  }

  async function stopTtsStream() {
    try {
      await apiFetch('/api/tts/stream/stop', {
        method: 'POST', body: JSON.stringify({ client_id: TTS_CLIENT_ID }),
      });
    } catch (e) { /* ignore */ }
    ttsStreamSession = null;
    ttsStreamBuffer = '';
    ttsStreamPending = Promise.resolve();
    if ($('#tts-stream-status')) $('#tts-stream-status').textContent = '流式朗读：已停止';
  }

  async function sendChat() {
    const text = $('#chat-text').value.trim();
    if (!text) return;
    if ($('#chat-agent')?.checked) return sendChatAgent(text);   // Agent 模式：先调技能再回答
    const provider = $('#llm-provider').value;
    const model = $('#llm-model').value.trim();
    chatMessages.push({ role: 'user', content: text });
    addChatBubble('user', text);
    $('#chat-text').value = '';
    const autoSpeak = !!$('#tts-auto-speak')?.checked;
    const streamBox = $('#chat-stream');
    if (autoSpeak && streamBox && !streamBox.checked) streamBox.checked = true;
    const stream = !!(streamBox && streamBox.checked);
    const assistantEl = addChatBubble('assistant', '思考中…');
    let assistantText = '';
    let streamTtsActive = false;
    llmRateReset();
    startLlmRateTimer();

    try {
      if (stream) {
        if (autoSpeak) {
          try { await startTtsStream(); streamTtsActive = true; }
          catch (e) { showToast('启动流式朗读失败，将在回复完成后朗读：' + e.message, 'error'); }
        }
        const resp = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
          body: JSON.stringify({ messages: chatMessages, provider, model, stream: true }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const parts = buf.split('\n');
          buf = parts.pop();
          for (const line of parts) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) continue;
            const payload = trimmed.slice(5).trim();
            if (payload === '[DONE]') continue;
            try {
              const obj = JSON.parse(payload);
              if (obj.error) throw new Error(obj.error);
              const delta = obj.choices?.[0]?.delta?.content;
              if (delta) {
                assistantText += delta;
                assistantEl.textContent = assistantText;
                llmRateAdd(delta);
                if (autoSpeak && ttsStreamSession) {
                  ttsStreamBuffer += delta;
                  pumpTtsChunks(false);
                }
              }
            } catch (err) {
              if (err.message && !err.message.startsWith('Unexpected')) throw err;
            }
          }
        }
        if (!assistantText) assistantEl.textContent = '（空回复）';
        chatMessages.push({ role: 'assistant', content: assistantText });
        if (autoSpeak) {
          if (streamTtsActive && ttsStreamSession) {
            await finishTtsStream();
          } else {
            await maybeAutoSpeak(assistantText);
          }
        } else {
          maybeAutoSpeak(assistantText);
        }
      } else {
        const data = await apiFetch('/api/chat', {
          method: 'POST',
          body: JSON.stringify({ messages: chatMessages, provider, model, stream: false }),
        });
        assistantText = data.content || '（空回复）';
        assistantEl.textContent = assistantText;
        chatMessages.push({ role: 'assistant', content: assistantText });
        maybeAutoSpeak(assistantText);
      }
    } catch (e) {
      assistantEl.textContent = '错误：' + e.message;
      showToast(e.message, 'error');
      if (ttsStreamSession) await stopTtsStream();
    }
  }

  async function maybeAutoSpeak(text) {
    if (!$('#tts-auto-speak')?.checked) return;
    try {
      await speakText(text, 'local', $('#tts-voice')?.value || '', true, false, ttsEnVoice(), ttsIcao());
    } catch (e) {
      showToast('TTS 朗读失败：' + e.message, 'error');
    }
  }

  // ---------------- TTS ----------------
  function ttsEnVoice() { return $('#tts-en-voice')?.value || $('#set-tts-en-voice')?.value || ''; }
  function ttsIcao() {
    const el = $('#tts-icao') || $('#set-tts-icao');
    return el ? !!el.checked : true;
  }

  function renderVoiceTable() {
    const tb = $('#voice-table tbody');
    if (!tb) return;
    const rows = ttsState.voices.map(v => {
      const sz = v.size ? (v.size / 1048576).toFixed(1) + ' MB' : '-';
      const protectedVoice = v.id === 'zh_CN-huayan-medium';
      const del = protectedVoice
        ? '<span class="muted small">内置保护</span>'
        : `<button class="btn ghost small" data-del-voice="${escapeHtml(v.id)}">删除</button>`;
      return `<tr><td>${escapeHtml(v.id)}</td><td>${escapeHtml(v.name)}</td><td>${escapeHtml(v.language || '')}</td>` +
             `<td>${sz}</td><td>${v.ready ? '可用' : '不完整'}</td><td>${del}</td></tr>`;
    }).join('');
    tb.innerHTML = rows || '<tr><td colspan="6" class="muted">暂无音色包</td></tr>';
    const info = $('#voice-manage-info');
    if (info) info.textContent = `共 ${ttsState.voices.length} 个音色包（Rosmontis_en 等英文音色可用于中英混读）`;
    tb.querySelectorAll('[data-del-voice]').forEach((btn) => {
      btn.addEventListener('click', () => deleteVoicePack(btn.dataset.delVoice));
    });
  }

  async function deleteVoicePack(voiceId) {
    if (!confirm(`确定删除音色包 ${voiceId} ？该目录 /opt/ai/voices/${voiceId} 会被移除。`)) return;
    try {
      await apiFetch('/api/tts/voice/' + encodeURIComponent(voiceId), { method: 'DELETE' });
      showToast('音色包已删除：' + voiceId, 'success');
      await loadTtsProviders();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function loadTtsProviders() {
    try {
      const data = await apiFetch('/api/tts/providers');
      ttsState.current = 'local';
      ttsState.voices = data.voices || [];
      const voiceOptions = ttsState.voices.map(v =>
        `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}${v.ready ? '' : '（不完整）'}</option>`).join('');
      const cur = $('#set-tts-voice')?.value || '';
      if ($('#tts-voice')) $('#tts-voice').innerHTML = voiceOptions || '<option value="">无可选音色</option>';
      if ($('#set-tts-voice')) $('#set-tts-voice').innerHTML = voiceOptions || '<option value="">无可选音色</option>';
      // 英文音色下拉：默认「自动」（按 language=en* 挑一个）
      const enVoices = ttsState.voices.filter(v => String(v.language || '').toLowerCase().startsWith('en'));
      const enOptions = '<option value="">自动（有英文音色就用）</option>' + enVoices.map(v =>
        `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}</option>`).join('');
      const savedEn = $('#set-tts-en-voice')?.dataset.saved || '';
      ['#tts-en-voice', '#set-tts-en-voice'].forEach((sel) => {
        const el = $(sel);
        if (!el) return;
        const prev = el.value || savedEn;
        el.innerHTML = enOptions;
        if (prev && Array.from(el.options).some(o => o.value === prev)) el.value = prev;
      });
      // ICAO 专用音色下拉：全部音色 + 自动
      const icaoOptions = '<option value="">自动（优先 lessac 等官方英文音色）</option>' + ttsState.voices.map(v =>
        `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name)}（${escapeHtml(v.language || '')}）</option>`).join('');
      const savedIcao = $('#set-tts-icao-voice')?.dataset.saved || '';
      const icaoSel = $('#set-tts-icao-voice');
      if (icaoSel) {
        const prev = icaoSel.value || savedIcao;
        icaoSel.innerHTML = icaoOptions;
        if (prev && Array.from(icaoSel.options).some(o => o.value === prev)) icaoSel.value = prev;
      }
      const want = data.local?.voice || '';
      ['#tts-voice', '#set-tts-voice'].forEach((sel) => {
        const el = $(sel);
        if (!el) return;
        const val = el.value || cur || want;
        if (val && Array.from(el.options).some(o => o.value === val)) el.value = val;
      });
      renderVoiceTable();
      if ($('#tts-auto-speak')) $('#tts-auto-speak').checked = !!data.auto_speak;
      if ($('#set-tts-auto-speak')) $('#set-tts-auto-speak').checked = !!data.auto_speak;
      if (data.auto_speak && $('#chat-stream')) $('#chat-stream').checked = true;
    } catch (e) {
      showToast(e.message, 'error');
    }
  }





  async function speakText(text, provider, voice, autoPlay = true, playInWeb = false, enVoice = '', icao = true) {
    if (!text || !text.trim()) return showToast('朗读文本为空', 'error');
    const data = await apiFetch('/api/tts/speak', {
      method: 'POST',
      body: JSON.stringify({ text, provider, voice, auto_play: autoPlay, en_voice: enVoice || '', icao: !!icao }),
    });
    showToast(`TTS 已合成：${data.voice}（${(data.size / 1024).toFixed(1)} KB）`, 'success');
    loadRecordings();
    if (playInWeb) playTtsInWeb(data.filename);
    return data;
  }

  // 在网页里播放刚合成的 TTS（需要浏览器允许自动播放：由点击触发即可）
  function playTtsInWeb(filename) {
    const el = $('#tts-audio');
    const tip = $('#tts-web-status');
    if (!el || !filename) return;
    el.src = '/recordings/' + encodeURIComponent(filename) + '?t=' + Date.now();
    el.style.display = 'block';
    if (tip) tip.textContent = '网页播放器：' + filename;
    el.play().then(() => {
      if (tip) tip.textContent = '网页播放器：播放中 ' + filename;
    }).catch((err) => {
      if (tip) tip.textContent = '网页播放器：已加载（浏览器拦截了自动播放，请点播放键）';
      showToast('浏览器拦截自动播放，请点播放器上的播放键', 'error');
    });
  }

  // 带进度的上传（fetch 无法上报上传进度，这里用 XHR）
  function uploadWithProgress(url, fd, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url, true);
      xhr.withCredentials = true;
      xhr.timeout = 15 * 60 * 1000;
      if (csrfToken) xhr.setRequestHeader('X-CSRF-Token', csrfToken);
      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress(e.loaded / e.total, e.loaded, e.total);
        };
      }
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
        if (xhr.status === 401) return reject(new Error('未登录或会话已过期，请重新登录后再上传'));
        if (xhr.status === 413) return reject(new Error((data && data.error) || '上传内容超过板端上限'));
        if (xhr.status >= 200 && xhr.status < 300 && (!data || data.ok !== false)) {
          return resolve(data || { ok: true });
        }
        reject(new Error((data && data.error) || ('上传失败 HTTP ' + xhr.status)));
      };
      xhr.onerror = () => reject(new Error('网络错误：上传中断（请确认板端在线，且文件未超过上限）'));
      xhr.ontimeout = () => reject(new Error('上传超时（15 分钟），请重试或改用有线网络'));
      xhr.onabort = () => reject(new Error('上传已取消'));
      xhr.send(fd);
    });
  }

  function setUploadBar(barSel, infoSel, ratio, text) {
    const bar = $(barSel);
    if (bar) bar.style.width = Math.max(0, Math.min(100, Math.round(ratio * 100))) + '%';
    const info = $(infoSel);
    if (info && text) info.textContent = text;
  }

  async function uploadVoicePack() {
    const file = $('#tts-voice-zip')?.files?.[0];
    if (!file) return showToast('请选择音色包 zip', 'error');
    const mb = file.size / 1024 / 1024;
    const fd = new FormData();
    fd.append('voice_pack', file, file.name);
    fd.append('voice_id', ($('#tts-voice-id')?.value || '').trim());
    const t0 = Date.now();
    setUploadBar('#voice-upload-bar', '#voice-upload-info', 0, `准备上传 ${file.name}（${mb.toFixed(1)} MB）…`);
    try {
      await uploadWithProgress('/api/tts/upload_voice', fd, (r, loaded, total) => {
        const sp = (loaded / 1024 / 1024) / Math.max(0.001, (Date.now() - t0) / 1000);
        setUploadBar('#voice-upload-bar', '#voice-upload-info', r,
          `上传中 ${(r * 100).toFixed(0)}%（${(loaded / 1048576).toFixed(1)}/${(total / 1048576).toFixed(1)} MB，${sp.toFixed(1)} MB/s）`);
      });
      setUploadBar('#voice-upload-bar', '#voice-upload-info', 1, `上传完成：${file.name}（${mb.toFixed(1)} MB）`);
      showToast('音色包上传成功，已部署到 /opt/ai/voices', 'success');
      await loadTtsProviders();
    } catch (e) {
      setUploadBar('#voice-upload-bar', '#voice-upload-info', 0, '上传失败：' + e.message);
      showToast(e.message, 'error');
    }
  }

  async function uploadTrainingData() {
    const file = $('#tts-train-zip')?.files?.[0];
    if (!file) return showToast('请选择训练数据 zip', 'error');
    const mb = file.size / 1024 / 1024;
    const fd = new FormData();
    fd.append('dataset', file, file.name);
    fd.append('dataset_id', ($('#tts-train-id')?.value || '').trim());
    const t0 = Date.now();
    setUploadBar('#train-upload-bar', '#train-upload-info', 0, `准备上传 ${file.name}（${mb.toFixed(1)} MB）…`);
    try {
      await uploadWithProgress('/api/tts/training/upload', fd, (r, loaded, total) => {
        const sp = (loaded / 1024 / 1024) / Math.max(0.001, (Date.now() - t0) / 1000);
        setUploadBar('#train-upload-bar', '#train-upload-info', r,
          `上传中 ${(r * 100).toFixed(0)}%（${(loaded / 1048576).toFixed(1)}/${(total / 1048576).toFixed(1)} MB，${sp.toFixed(1)} MB/s）`);
      });
      setUploadBar('#train-upload-bar', '#train-upload-info', 1, `上传完成：${file.name}`);
      showToast('训练数据已上传，板端等待 PC/服务器微调', 'success');
    } catch (e) {
      setUploadBar('#train-upload-bar', '#train-upload-info', 0, '上传失败：' + e.message);
      showToast(e.message, 'error');
    }
  }

  // ---------------- board microphone capture & stream ----------------
  let micPollTimer = null;
  let micListenAbort = null;
  let micListenCtx = null;
  let micListenNextTime = 0;
  let micListenLeftover = new Uint8Array(0);

  async function loadMicLevel() {
    try {
      const data = await apiFetch('/api/mic/level');
      const l = data.level || {};
      const running = !!l.running;
      const level = running ? (l.level ?? 0) : 0;
      if ($('#mic-level')) $('#mic-level').textContent = level + '%';
      if ($('#mic-rms')) $('#mic-rms').textContent = running ? (l.rms ?? '--') : '--';
      if ($('#mic-peak')) $('#mic-peak').textContent = running ? (l.peak ?? '--') : '--';
      if ($('#mic-dbfs')) $('#mic-dbfs').textContent = running ? (l.dbfs ?? '--') : '--';
      if ($('#mic-left-rms')) $('#mic-left-rms').textContent = running ? (l.left_rms ?? '--') : '--';
      if ($('#mic-right-rms')) $('#mic-right-rms').textContent = running ? (l.right_rms ?? '--') : '--';
      if ($('#mic-device')) $('#mic-device').textContent = l.device || '--';
      setBar('#mic-level-bar', level);
      if (!l.running && micPollTimer) {
        clearInterval(micPollTimer);
        micPollTimer = null;
      }
    } catch (e) { /* ignore polling errors */ }
  }

  async function loadMicSettings() {
    try {
      const data = await apiFetch('/api/mic/settings');
      const s = data.settings || {};
      if ($('#mic-source')) $('#mic-source').value = s.source || 'main';
      if ($('#mic-channel')) $('#mic-channel').value = s.channel || 'right';
      if ($('#mic-pga')) { $('#mic-pga').value = s.pga_percent ?? 25; $('#mic-pga-val').textContent = (s.pga_percent ?? 25) + '%'; }
      if ($('#mic-adc')) { $('#mic-adc').value = s.adc_percent ?? 100; $('#mic-adc-val').textContent = (s.adc_percent ?? 100) + '%'; }
      if ($('#mic-l2r2')) { $('#mic-l2r2').value = s.l2r2_percent ?? 0; $('#mic-l2r2-val').textContent = (s.l2r2_percent ?? 0) + '%'; }
      if ($('#mic-aux')) { $('#mic-aux').value = s.aux_boost_percent ?? 0; $('#mic-aux-val').textContent = (s.aux_boost_percent ?? 0) + '%'; }
      if ($('#mic-pga-boost')) $('#mic-pga-boost').checked = !!s.pga_boost;
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function applyMicSettings() {
    try {
      const body = {
        source: $('#mic-source')?.value || 'main',
        channel: $('#mic-channel')?.value || 'right',
        pga_percent: parseInt($('#mic-pga')?.value || '25', 10),
        adc_percent: parseInt($('#mic-adc')?.value || '100', 10),
        l2r2_percent: parseInt($('#mic-l2r2')?.value || '0', 10),
        aux_boost_percent: parseInt($('#mic-aux')?.value || '0', 10),
        pga_boost: !!$('#mic-pga-boost')?.checked,
      };
      const data = await apiFetch('/api/mic/settings', { method: 'POST', body: JSON.stringify(body) });
      showToast('麦克风设置已应用', 'success');
      loadMicSettings();
      loadMicLevel();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function startMicCapture() {
    try {
      await apiFetch('/api/mic/capture/start', { method: 'POST', body: '{}' });
      showToast('开发板麦克风采集已启动', 'success');
      if (!micPollTimer) micPollTimer = setInterval(loadMicLevel, 250);
      loadMicLevel();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function stopMicCapture() {
    try {
      stopMicListen();
      await apiFetch('/api/mic/capture/stop', { method: 'POST', body: '{}' });
      showToast('开发板麦克风采集已停止', 'success');
      if (micPollTimer) { clearInterval(micPollTimer); micPollTimer = null; }
      loadMicLevel();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function startMicListen() {
    if (micListenAbort) return;
    try {
      micListenAbort = new AbortController();
      const resp = await fetch('/api/mic/stream', { signal: micListenAbort.signal });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${text.slice(0, 120)}`);
      }
      micListenCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      await micListenCtx.resume();
      const gain = micListenCtx.createGain();
      gain.gain.value = 0.9;
      gain.connect(micListenCtx.destination);
      micListenNextTime = micListenCtx.currentTime + 0.08;
      const reader = resp.body.getReader();
      showToast('网页实时监听已开启', 'success');
      micListenLeftover = new Uint8Array(0);
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!value || !value.length) continue;
        let all;
        if (micListenLeftover.length) {
          all = new Uint8Array(micListenLeftover.length + value.length);
          all.set(micListenLeftover, 0);
          all.set(value, micListenLeftover.length);
        } else {
          all = value;
        }
        const sampleBytes = all.byteLength - (all.byteLength % 2);
        if (sampleBytes <= 0) {
          micListenLeftover = all;
          continue;
        }
        const samples = new Int16Array(all.buffer, all.byteOffset, sampleBytes / 2);
        const floats = new Float32Array(samples.length);
        for (let i = 0; i < samples.length; i++) floats[i] = samples[i] / 32768;
        const buf = micListenCtx.createBuffer(1, floats.length, 16000);
        buf.copyToChannel(floats, 0);
        const src = micListenCtx.createBufferSource();
        src.buffer = buf;
        src.connect(gain);
        const now = micListenCtx.currentTime;
        const startAt = Math.max(now + 0.03, micListenNextTime);
        src.start(startAt);
        micListenNextTime = startAt + buf.duration;
        micListenLeftover = sampleBytes === all.byteLength ? new Uint8Array(0) : all.slice(sampleBytes);
      }
    } catch (e) {
      if (e.name !== 'AbortError') showToast('网页监听失败：' + e.message, 'error');
    } finally {
      stopMicListen();
    }
  }

  function stopMicListen() {
    if (micListenAbort) {
      try { micListenAbort.abort(); } catch (e) {}
      micListenAbort = null;
    }
    if (micListenCtx) {
      try { micListenCtx.close(); } catch (e) {}
      micListenCtx = null;
    }
    micListenNextTime = 0;
    micListenLeftover = new Uint8Array(0);
  }

  // ---------------- intercom ----------------
  let audioCtx = null;
  let mediaStream = null;
  let scriptNode = null;
  let silentGain = null;
  let recordChunks = [];
  let recording = false;
  let recordSampleRate = 16000;

  function mergeFloat32(chunks) {
    let total = chunks.reduce((n, c) => n + c.length, 0);
    const out = new Float32Array(total);
    let off = 0;
    for (const c of chunks) { out.set(c, off); off += c.length; }
    return out;
  }

  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, samples.length * 2, true);
    let off = 44;
    for (let i = 0; i < samples.length; i++, off += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([view], { type: 'audio/wav' });
  }

  async function startRecording() {
    if (recording) return;
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('当前页面不是安全上下文，浏览器未提供麦克风接口；请使用 HTTPS、localhost，或改用 WAV 上传测试');
      }
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
      audioCtx = new AudioContext({ sampleRate: 16000 });
      await audioCtx.resume();
      recordSampleRate = audioCtx.sampleRate;
      const source = audioCtx.createMediaStreamSource(mediaStream);
      scriptNode = audioCtx.createScriptProcessor(4096, 1, 1);
      silentGain = audioCtx.createGain();
      silentGain.gain.value = 0;
      scriptNode.onaudioprocess = (e) => {
        if (!recording) return;
        const data = e.inputBuffer.getChannelData(0);
        const copy = new Float32Array(data.length);
        copy.set(data);
        recordChunks.push(copy);
        let peak = 0;
        for (let i = 0; i < data.length; i++) peak = Math.max(peak, Math.abs(data[i]));
        setBar('#record-meter', Math.min(100, peak * 140));
      };
      source.connect(scriptNode);
      scriptNode.connect(silentGain);
      silentGain.connect(audioCtx.destination);
      recordChunks = [];
      recording = true;
      $('#record-dot').classList.add('recording');
      $('#record-status').textContent = '录音中…';
      $('#btn-record').textContent = '停止并上传';
    } catch (e) {
      showToast('无法访问麦克风：' + e.message, 'error');
    }
  }

  async function stopRecording() {
    if (!recording) return;
    recording = false;
    $('#record-dot').classList.remove('recording');
    $('#record-status').textContent = '正在生成 WAV…';
    $('#btn-record').disabled = true;
    try {
      if (scriptNode) scriptNode.disconnect();
      if (silentGain) silentGain.disconnect();
      if (audioCtx) await audioCtx.close();
      if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
      const samples = mergeFloat32(recordChunks);
      const blob = encodeWav(samples, recordSampleRate);
      const fd = new FormData();
      fd.append('audio', blob, 'web_intercom.wav');
      const data = await apiFetch('/api/intercom/upload', { method: 'POST', body: fd });
      showToast(`录音已上传：${data.duration_ms} ms，${(data.size / 1024).toFixed(1)} KB`, 'success');
      $('#record-status').textContent = '录音已上传';
      loadRecordings();
    } catch (e) {
      showToast('录音上传失败：' + e.message, 'error');
      $('#record-status').textContent = '上传失败';
    } finally {
      $('#btn-record').disabled = false;
      $('#btn-record').textContent = '开始录音';
      setBar('#record-meter', 0);
      audioCtx = null; mediaStream = null; scriptNode = null; silentGain = null; recordChunks = [];
    }
  }

  // ---------------- 实时对讲：网页麦克风 → 板端 AUX（按住说话） ----------------
  let pushStream = null;          // MediaStream
  let pushCtx = null;             // AudioContext(16000)
  let pushNode = null;            // ScriptProcessor
  let pushMute = null;            // 静音 Gain（保持音频图运行）
  let pushLoopTimer = null;       // UI 刷新
  let pushActive = false;
  let pushToken = '';
  let pushBytes = 0;
  let pushStartedAt = 0;
  let pushQueue = [];
  let pushBusy = false;

  function pushSetStatus(text, kind) {
    const el = $('#push-status');
    if (el) el.textContent = text;
    const dot = $('#push-dot');
    if (dot) {
      dot.classList.toggle('recording', kind === 'on');
    }
  }

  async function pushSendQueue(end) {
    if (pushBusy) return;                      // 上一块还没发完，等下一轮
    if (!pushQueue.length && !end) return;
    pushBusy = true;
    let payload = new Uint8Array(0);
    if (pushQueue.length) {
      let total = 0;
      pushQueue.forEach((b) => { total += b.length; });
      payload = new Uint8Array(total);
      let off = 0;
      pushQueue.forEach((b) => { payload.set(b, off); off += b.length; });
      pushQueue = [];
    }
    const url = '/api/intercom/push?token=' + encodeURIComponent(pushToken) + (end ? '&end=1' : '');
    try {
      const resp = await fetch(url, {
        method: 'POST', body: payload,
        headers: { 'Content-Type': 'application/octet-stream', 'X-CSRF-Token': csrfToken },
        credentials: 'same-origin',
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok || (data && data.ok === false)) {
        throw new Error((data && data.error) || ('HTTP ' + resp.status));
      }
      if (data && typeof data.total === 'number') pushBytes = data.total;
    } catch (e) {
      pushBusy = false;
      await stopPushTalk('推送中断：' + e.message);
      return;
    }
    pushBusy = false;
  }

  async function startPushTalk() {
    if (pushActive) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast('当前不是安全上下文（HTTPS/localhost），浏览器未提供麦克风接口', 'error');
      pushSetStatus('需要 HTTPS');
      return;
    }
    try {
      pushStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      pushCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      await pushCtx.resume();
      const src = pushCtx.createMediaStreamSource(pushStream);
      pushNode = pushCtx.createScriptProcessor(4096, 1, 1);
      pushMute = pushCtx.createGain();
      pushMute.gain.value = $('#push-monitor')?.checked ? 0.35 : 0;   // 可选本机监听
      pushNode.onaudioprocess = (ev) => {
        if (!pushActive) return;
        const f = ev.inputBuffer.getChannelData(0);
        const pcm = new Int16Array(f.length);
        for (let i = 0; i < f.length; i++) {
          let s = f[i] * 2.2;                    // 适度增益，贴近电台 MIC 电平
          if (s > 1) s = 1; else if (s < -1) s = -1;
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          const a = Math.abs(f[i]);
          if (a > (startPushTalk._peak || 0)) startPushTalk._peak = a;
        }
        pushQueue.push(new Uint8Array(pcm.buffer));
        setBar('#push-meter', Math.min(100, (startPushTalk._peak || 0) * 140));
        startPushTalk._peak = 0;
      };
      src.connect(pushNode);
      pushNode.connect(pushMute);
      pushMute.connect(pushCtx.destination);
      pushActive = true;
      pushBytes = 0;
      pushQueue = [];
      pushToken = 't' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      pushStartedAt = Date.now();
      pushSetStatus('对讲中…（松开停止）', 'on');
      await pushSendQueue(false);              // 立刻建立 aplay + 拉 PTT
      pushLoopTimer = setInterval(() => {
        pushSendQueue(false);
        const sec = (Date.now() - pushStartedAt) / 1000;
        if (sec > 120) stopPushTalk('超过 120 秒自动停止');   // 安全上限
        const info = $('#push-info');
        if (info) info.textContent = `已推送 ${(pushBytes / 1024).toFixed(0)} KB / ${sec.toFixed(1)}s（16kHz 单声道，板端 AUX + PTT）`;
      }, 250);
    } catch (e) {
      showToast('无法访问麦克风：' + e.message, 'error');
      pushSetStatus('麦克风不可用');
      await stopPushTalk('麦克风不可用');
    }
  }

  async function stopPushTalk(reason) {
    if (!pushActive && !pushStream && !pushCtx) return;
    const wasActive = pushActive;
    pushActive = false;
    if (pushLoopTimer) { clearInterval(pushLoopTimer); pushLoopTimer = null; }
    try { if (pushNode) pushNode.disconnect(); } catch (e) {}
    try { if (pushMute) pushMute.disconnect(); } catch (e) {}
    if (pushStream) { pushStream.getTracks().forEach((t) => t.stop()); pushStream = null; }
    if (pushCtx) { try { await pushCtx.close(); } catch (e) {} pushCtx = null; }
    pushNode = null; pushMute = null;
    if (wasActive) {
      pushQueue = [];
      await pushSendQueue(true);               // 通知板端收尾并释放 PTT
    }
    pushSetStatus(reason ? ('已停止：' + reason) : '已停止');
    setBar('#push-meter', 0);
    const info = $('#push-info');
    if (info) info.textContent = `本次推送 ${(pushBytes / 1024).toFixed(0)} KB；松开按钮或 5 秒无数据，板端会自动释放 PTT。`;
  }

  async function loadRecordings() {
    try {
      const data = await apiFetch('/api/intercom/recordings');
      const tbody = $('#recordings-table tbody');
      if (!data.recordings.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted">暂无录音</td></tr>';
        return;
      }
      tbody.innerHTML = data.recordings.map(r => `
        <tr>
          <td>${escapeHtml(r.ts)}</td>
          <td>${escapeHtml(r.username || '--')}</td>
          <td>${r.duration_ms || 0} ms</td>
          <td>${((r.size_bytes || 0) / 1024).toFixed(1)} KB</td>
          <td><button class="btn ghost" data-play="${r.id}">重放</button></td>
        </tr>`).join('');
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function playTestTone() {
    try {
      const data = await apiFetch('/api/intercom/test-tone', { method: 'POST', body: '{}' });
      showToast('测试音已发送到 ' + data.device, 'success');
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ---------------- camera / weather ----------------
  // ---------------- camera / recording / RTMP ----------------
  let cameraSettings = {};
  let cameraOsd = {};
  let cameraServiceState = {};
  let cameraOsdTimer = null;

  function fmtBytes(n) {
    n = Number(n || 0);
    if (n > 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
    if (n > 1024) return (n / 1024).toFixed(1) + ' KB';
    return n + ' B';
  }

  function fillCameraForm(s, osd) {
    cameraSettings = s || {};
    cameraOsd = osd || {};
    if ($('#camera-device')) $('#camera-device').value = s.device || '';
    if ($('#camera-resolution')) $('#camera-resolution').value = s.resolution || '';
    if ($('#camera-fps')) $('#camera-fps').value = s.fps ?? 15;
    if ($('#camera-record-dir')) $('#camera-record-dir').value = s.record_dir || '';
    if ($('#camera-loop-seconds')) $('#camera-loop-seconds').value = s.loop_seconds ?? 60;
    if ($('#camera-loop-max-mb')) $('#camera-loop-max-mb').value = s.loop_max_mb ?? 2048;
    if ($('#camera-loop-max-files')) $('#camera-loop-max-files').value = s.loop_max_files ?? 100;
    if ($('#camera-storage-max-mb')) $('#camera-storage-max-mb').value = s.storage_max_mb ?? 8192;
    if ($('#camera-rtmp-url')) $('#camera-rtmp-url').value = s.rtmp_url || '';
    if ($('#camera-osd-enabled')) $('#camera-osd-enabled').checked = !!osd.enabled;
    if ($('#camera-osd-text')) $('#camera-osd-text').value = osd.text || '';
    if ($('#camera-osd-show-time')) $('#camera-osd-show-time').checked = !!osd.show_time;
    if ($('#camera-osd-position')) $('#camera-osd-position').value = osd.position || 'top-left';
    if ($('#camera-osd-fontsize')) $('#camera-osd-fontsize').value = osd.fontsize ?? 18;
    updateCameraOsd();
  }

  function updateCameraOsd() {
    const el = $('#camera-osd');
    if (!el) return;
    if (!cameraOsd.enabled) { el.textContent = ''; return; }
    const parts = [];
    if (cameraOsd.show_time) parts.push(new Date().toLocaleString());
    if (cameraOsd.text) parts.push(cameraOsd.text);
    el.textContent = parts.join('\n');
    el.className = 'camera-osd ' + (cameraOsd.position || 'top-left');
  }

  async function loadCameraStatus() {
    try {
      const data = await apiFetch('/api/camera/status');
      cameraServiceState = data.service || {};
      fillCameraForm(data.settings || {}, data.osd || {});
      const devs = data.devices || [];
      if ($('#camera-devices')) {
        $('#camera-devices').textContent = devs.length ? (devs.slice(0, 8).join(', ') + (devs.length > 8 ? ` 等 ${devs.length} 个` : '')) : '未发现';
      }
      if ($('#camera-device-info')) $('#camera-device-info').textContent = (data.settings && data.settings.device) || '--';
      const st = data.service || {};
      const badge = $('#camera-status-badge');
      if (badge) badge.textContent = st.running ? '预览运行中' : '未启动';
      const box = $('#camera-service-status');
      if (box) {
        box.innerHTML = `
          <div><span>采集</span><b>${st.running ? '运行' : '停止'}</b></div>
          <div><span>预览客户端</span><b>${st.clients ?? 0}</b></div>
          <div><span>录像</span><b>${st.recording ? (st.recording_label || '运行') : '停止'}</b></div>
          <div><span>RTMP</span><b>${st.rtmp ? '推流中' : '停止'}</b></div>
          ${st.last_error ? `<div><span>最近错误</span><b class="muted">${escapeHtml(String(st.last_error).slice(0,120))}</b></div>` : ''}`;
      }
      renderCameraRecordings(data.recordings || []);
      const wx = await apiFetch('/api/weather');
      if (wx.note && $('#weather-note')) $('#weather-note').textContent = wx.note;
    } catch (e) { /* 预留页静默 */ }
  }

  function renderCameraRecordings(list) {
    const tbody = $('#camera-recordings-table tbody');
    if (!tbody) return;
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted">暂无录像</td></tr>';
      return;
    }
    tbody.innerHTML = list.map(r => `
      <tr>
        <td>${escapeHtml(r.filename)}</td>
        <td>${r.type === 'loop' ? '循环' : (r.type === 'manual' ? '手动' : '其他')}</td>
        <td>${fmtBytes(r.size)}</td>
        <td>${new Date((r.mtime || 0) * 1000).toLocaleString()}</td>
        <td>
          <button class="btn ghost" data-cam-play="${escapeHtml(r.url)}">播放</button>
          <button class="btn ghost" data-cam-del="${escapeHtml(r.filename)}">删除</button>
        </td>
      </tr>`).join('');
  }

  async function cameraStart() {
    try {
      await apiFetch('/api/camera/start', { method: 'POST', body: '{}' });
      const img = $('#camera-preview');
      if (img) img.src = '/api/camera/stream?t=' + Date.now();
      showToast('摄像头预览已启动', 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraStop() {
    try {
      await apiFetch('/api/camera/stop', { method: 'POST', body: '{}' });
      const img = $('#camera-preview');
      if (img) img.src = '';
      showToast('摄像头已停止', 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraSnapshot() {
    try {
      const data = await apiFetch('/api/camera/snapshot', { method: 'POST', body: '{}' });
      showToast('抓拍已保存：' + data.filename, 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraLoopStart() {
    try {
      const data = await apiFetch('/api/camera/loop/start', {
        method: 'POST',
        body: JSON.stringify({ seconds: parseInt($('#camera-loop-seconds')?.value || '60', 10) }),
      });
      showToast(`循环录像已启动，分段 ${data.segment_seconds}s`, 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraLoopStop() {
    try {
      await apiFetch('/api/camera/loop/stop', { method: 'POST', body: '{}' });
      showToast('循环录像已停止', 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraManualStart() {
    try {
      const data = await apiFetch('/api/camera/record/manual/start', { method: 'POST', body: '{}' });
      showToast('单独录像已开始：' + data.filename, 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraManualStop() {
    try {
      await apiFetch('/api/camera/record/manual/stop', { method: 'POST', body: '{}' });
      showToast('单独录像已停止并保存', 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraRtmpStart() {
    try {
      const url = $('#camera-rtmp-url')?.value || '';
      await apiFetch('/api/camera/rtmp/start', { method: 'POST', body: JSON.stringify({ url }) });
      showToast('RTMP 推流已启动', 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function cameraRtmpStop() {
    try {
      await apiFetch('/api/camera/rtmp/stop', { method: 'POST', body: '{}' });
      showToast('RTMP 推流已停止', 'success');
      loadCameraStatus();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function saveCameraSettings() {
    const body = {
      device: $('#camera-device')?.value || '',
      resolution: $('#camera-resolution')?.value || '',
      fps: parseInt($('#camera-fps')?.value || '15', 10),
      quality: 5,
      record_dir: $('#camera-record-dir')?.value || '',
      loop_seconds: parseInt($('#camera-loop-seconds')?.value || '60', 10),
      loop_max_mb: parseInt($('#camera-loop-max-mb')?.value || '2048', 10),
      loop_max_files: parseInt($('#camera-loop-max-files')?.value || '100', 10),
      storage_max_mb: parseInt($('#camera-storage-max-mb')?.value || '8192', 10),
      rtmp_url: $('#camera-rtmp-url')?.value || '',
      osd: {
        enabled: !!$('#camera-osd-enabled')?.checked,
        text: $('#camera-osd-text')?.value || '',
        show_time: !!$('#camera-osd-show-time')?.checked,
        position: $('#camera-osd-position')?.value || 'top-left',
        fontsize: parseInt($('#camera-osd-fontsize')?.value || '18', 10),
      },
    };
    try {
      await apiFetch('/api/camera/settings', { method: 'POST', body: JSON.stringify(body) });
      showToast('摄像头设置已保存', 'success');
      loadCameraStatus();
      window.dispatchEvent(new CustomEvent('elf2:camera-settings-saved'));
    } catch (e) { showToast(e.message, 'error'); }
  }

  // ---------------- weather / wind speed ----------------
  let weatherSettings = {};

  function weatherDate() {
    const d = $('#weather-date')?.value;
    if (d) return d;
    const now = new Date();
    const s = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    if ($('#weather-date')) $('#weather-date').value = s;
    return s;
  }

  async function loadWeatherRealtime() {
    try {
      const rt = await apiFetch('/api/weather/realtime');
      weatherSettings = rt.settings || {};
      const r = rt.realtime || {};
      if ($('#weather-speed')) {
        $('#weather-speed').innerHTML = `${r.last_speed ?? '--'} <span style="font-size:16px">m/s</span>`;
      }
      if ($('#weather-raw')) $('#weather-raw').textContent = `raw ${r.last_raw ?? '--'} · 更新时间 ${r.last_ts || '--'}`;
      if ($('#weather-status')) {
        $('#weather-status').textContent = r.last_error ? `采集异常：${r.last_error}` : (r.last_ok ? '采集正常' : '等待数据');
        $('#weather-status').className = 'sub ' + (r.last_error ? 'text-error' : 'muted');
      }
      if ($('#weather-modbus-info')) $('#weather-modbus-info').textContent = `从站 ${weatherSettings.slave ?? '--'} / 寄存器 ${weatherSettings.register ?? '--'}`;
      if ($('#weather-interval-info')) $('#weather-interval-info').textContent = (weatherSettings.poll_interval ?? '--') + ' s';
    } catch (e) {
      if ($('#weather-status')) $('#weather-status').textContent = '采集服务异常：' + e.message;
    }
  }

  async function loadWeatherDaily() {
    const date = weatherDate();
    if ($('#weather-chart-date')) $('#weather-chart-date').textContent = date;
    try {
      const st = await apiFetch('/api/weather/stats?date=' + encodeURIComponent(date));
      const s = st.stats || {};
      if ($('#weather-max')) $('#weather-max').textContent = (s.max_speed ?? '--') + ' m/s';
      if ($('#weather-max-time')) $('#weather-max-time').textContent = s.max_time || '--';
      if ($('#weather-avg')) $('#weather-avg').textContent = (s.avg_speed ?? '--') + ' m/s';
      if ($('#weather-min')) $('#weather-min').textContent = (s.min_speed ?? '--') + ' m/s';
      if ($('#weather-count')) $('#weather-count').textContent = s.count ?? '--';
    } catch (e) { /* ignore */ }
    try {
      const interval = $('#weather-sample-interval')?.value || '5';
      const points = await apiFetch(`/api/weather/history?date=${encodeURIComponent(date)}&mode=minute&interval=${encodeURIComponent(interval)}`);
      drawWeatherChart(points.points || [], '#weather-chart', '当日暂无风力数据');
    } catch (e) { /* ignore */ }
  }

  async function loadWeather() {
    await Promise.all([loadWeatherRealtime(), loadWeatherDaily(), loadRainRealtime(), loadRainHourly()]);
  }

  async function queryWeatherHistory() {
    const days = $('#weather-export-days')?.value || '7';
    const interval = $('#weather-export-interval')?.value || '10';
    const hint = $('#weather-history-hint');
    if (hint) hint.textContent = '查询中…';
    try {
      const data = await apiFetch(`/api/weather/history_range?days=${encodeURIComponent(days)}&interval=${encodeURIComponent(interval)}`);
      drawWeatherChart(data.points || [], '#weather-history-chart', '所选时间段暂无数据');
      if (hint) hint.textContent = `已查询最近 ${days} 天，采样 ${interval} 分钟，共 ${(data.points || []).length} 个点`;
    } catch (e) {
      if (hint) hint.textContent = '查询失败：' + e.message;
    }
  }

  function exportWeatherCsv() {
    const days = $('#weather-export-days')?.value || '7';
    const interval = $('#weather-export-interval')?.value || '10';
    window.location.href = `/api/weather/export.csv?days=${encodeURIComponent(days)}&interval=${encodeURIComponent(interval)}`;
  }

  // ---------------- precipitation / rain gauge ----------------
  function rainDate() {
    const d = $('#rain-date')?.value;
    if (d) return d;
    const now = new Date();
    const s = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    if ($('#rain-date')) $('#rain-date').value = s;
    return s;
  }

  async function loadRainRealtime() {
    try {
      const rt = await apiFetch('/api/rain/realtime');
      const r = rt.realtime || {};
      const today = rt.today || {};
      if ($('#rain-total')) {
        $('#rain-total').innerHTML = `${r.last_total ?? '--'} <span style="font-size:16px">mm</span>`;
      }
      if ($('#rain-raw')) $('#rain-raw').textContent = `raw ${r.last_raw ?? '--'} · 更新时间 ${r.last_ts || '--'}`;
      if ($('#rain-status')) {
        $('#rain-status').textContent = r.last_error ? `采集异常：${r.last_error}` : (r.last_ok ? '采集正常' : '等待数据');
        $('#rain-status').className = 'sub ' + (r.last_error ? 'text-error' : 'muted');
      }
      if ($('#rain-today-total')) $('#rain-today-total').textContent = `${today.total_mm ?? '--'} mm`;
      if ($('#rain-recent-hour')) $('#rain-recent-hour').textContent = `${rt.recent_hour_mm ?? '--'} mm`;
      if ($('#rain-max-hour')) {
        $('#rain-max-hour').textContent = (Number(today.total_mm) > 0 && today.max_hour)
          ? `${today.max_hour} / ${today.max_hour_mm ?? 0} mm` : '--';
      }
      if ($('#rain-count')) {
        $('#rain-count').textContent = (today.points || []).reduce((a, p) => a + (p.samples || 0), 0);
      }
      const s = rt.settings || {};
      if ($('#rain-modbus-info')) $('#rain-modbus-info').textContent = `从站 ${s.rain_slave ?? '--'} / 寄存器 ${s.rain_register ?? '--'}`;
      if ($('#rain-scale-info')) $('#rain-scale-info').textContent = `${s.rain_scale ?? '--'} mm/raw`;
    } catch (e) {
      if ($('#rain-status')) $('#rain-status').textContent = '降水采集异常：' + e.message;
    }
  }

  async function loadRainHourly() {
    const date = rainDate();
    if ($('#rain-hourly-date-label')) $('#rain-hourly-date-label').textContent = date;
    const hint = $('#rain-hourly-hint');
    if (hint) hint.textContent = '查询中…';
    try {
      const data = await apiFetch(`/api/rain/hourly?date=${encodeURIComponent(date)}`);
      const stats = data.stats || {};
      const points = stats.points || [];
      drawRainChart(points);
      const tbody = $('#rain-hourly-table tbody');
      if (tbody) {
        tbody.innerHTML = points.map(p => {
          const v = Number(p.rain_mm || 0);
          return `<tr><td>${escapeHtml(p.hour || '--')}</td>` +
            `<td>${v.toFixed(2)}</td>` +
            `<td>${p.samples ?? 0}</td></tr>`;
        }).join('');
      }
      if (hint) {
        const n = points.reduce((a, p) => a + (p.samples || 0), 0);
        hint.textContent = `全天累计 ${stats.total_mm ?? 0} mm，共 ${n} 个采集点`;
      }
    } catch (e) {
      drawRainChart([]);
      if (hint) hint.textContent = '查询失败：' + e.message;
    }
  }

  function exportRainCsv() {
    const date = rainDate();
    window.location.href = `/api/rain/export.csv?date=${encodeURIComponent(date)}`;
  }

  function drawRainChart(points) {
    const canvas = $('#rain-hourly-chart');
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 800;
    const h = 220;
    canvas.width = Math.max(300, w) * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#0d1526';
    ctx.fillRect(0, 0, w, h);
    const pad = { l: 42, r: 12, t: 14, b: 28 };
    const cw = Math.max(10, w - pad.l - pad.r);
    const ch = h - pad.t - pad.b;
    ctx.strokeStyle = '#26334d';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + ch * i / 4;
      ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y);
    }
    ctx.stroke();
    if (!points.length) {
      ctx.fillStyle = '#8fa2c4';
      ctx.font = '13px Microsoft YaHei';
      ctx.fillText('当日暂无降水量数据', pad.l + 10, pad.t + 22);
      return;
    }
    const maxV = Math.max(1, ...points.map(p => Number(p.rain_mm) || 0));
    const n = points.length;
    const slot = cw / n;
    const barW = Math.max(4, slot * 0.55);
    ctx.fillStyle = '#38bdf8';
    points.forEach((p, i) => {
      const v = Number(p.rain_mm) || 0;
      const bh = ch * v / maxV;
      const x = pad.l + slot * i + (slot - barW) / 2;
      const y = pad.t + ch - bh;
      if (bh > 0) ctx.fillRect(x, y, barW, bh);
    });
    ctx.fillStyle = '#8fa2c4';
    ctx.font = '11px Microsoft YaHei';
    for (let i = 0; i <= 4; i++) {
      const v = maxV * (1 - i / 4);
      ctx.fillText(v.toFixed(1), 6, pad.t + ch * i / 4 + 4);
    }
    ctx.textAlign = 'center';
    points.forEach((p, i) => {
      if ((p.hour_index ?? i) % 3 === 0) {
        ctx.fillText((p.hour || '').slice(0, 2), pad.l + slot * i + slot / 2, h - 8);
      }
    });
    ctx.textAlign = 'left';
  }

  function drawWeatherChart(points, selector = '#weather-chart', emptyText = '暂无数据') {
    const canvas = $(selector);
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 800;
    const h = 220;
    canvas.width = Math.max(300, w) * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#0d1526';
    ctx.fillRect(0, 0, w, h);
    const pad = { l: 42, r: 12, t: 14, b: 26 };
    const cw = Math.max(10, w - pad.l - pad.r);
    const ch = h - pad.t - pad.b;
    ctx.strokeStyle = '#26334d';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + ch * i / 4;
      ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + cw, y);
    }
    ctx.stroke();
    if (!points.length) {
      ctx.fillStyle = '#8fa2c4';
      ctx.font = '13px Microsoft YaHei';
      ctx.fillText(emptyText, pad.l + 10, pad.t + 22);
      return;
    }
    const valid = points.filter(p => p.avg_speed !== null && p.avg_speed !== undefined);
    const maxV = Math.max(1, ...valid.map(p => (p.max_speed ?? p.avg_speed ?? 0)));
    const n = points.length;
    const xOf = i => points.length === 1 ? pad.l + cw / 2 : pad.l + cw * i / (n - 1);
    const yOf = v => pad.t + ch - ch * Math.min(1, (v || 0) / maxV);
    // 平均线
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    valid.forEach((p, i) => {
      const idx = points.indexOf(p);
      const x = xOf(idx), y = yOf(p.avg_speed);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    // 最大值线
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    valid.forEach((p, i) => {
      const idx = points.indexOf(p);
      const x = xOf(idx), y = yOf(p.max_speed ?? p.avg_speed);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    // Y 轴标注
    ctx.fillStyle = '#8fa2c4';
    ctx.font = '11px Microsoft YaHei';
    for (let i = 0; i <= 4; i++) {
      const v = maxV * (1 - i / 4);
      ctx.fillText(v.toFixed(1), 6, pad.t + ch * i / 4 + 4);
    }
    // X 轴首尾时间
    const label = (p) => (p.minute || p.ts || '').slice(-5);
    ctx.fillText(label(points[0]), pad.l, h - 8);
    ctx.fillText(label(points[n - 1]), pad.l + cw - 30, h - 8);
  }

  // 传感器卡片实时状态（设置页友好显示：是否采集 / 当前值 / 最后成功 / 错误）
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
    if (role !== 'admin') return;
    try {
      const data = await apiFetch('/api/weather/settings');
      const s = data.settings || {};
      if ($('#weather-port')) $('#weather-port').value = s.port || '';
      if ($('#weather-baud')) $('#weather-baud').value = s.baud ?? 9600;
      if ($('#weather-slave')) $('#weather-slave').value = s.slave ?? 1;
      if ($('#weather-function')) $('#weather-function').value = String(s.function ?? 3);
      if ($('#weather-register')) $('#weather-register').value = s.register ?? 0;
      if ($('#weather-quantity')) $('#weather-quantity').value = s.quantity ?? 1;
      if ($('#weather-scale')) $('#weather-scale').value = s.scale ?? 0.1;
      if ($('#weather-interval')) $('#weather-interval').value = s.poll_interval ?? 2;
      if ($('#rain-enabled')) $('#rain-enabled').value = s.rain_enabled ? '1' : '0';
      if ($('#rain-slave')) $('#rain-slave').value = s.rain_slave ?? 23;
      if ($('#rain-function')) $('#rain-function').value = String(s.rain_function ?? 3);
      if ($('#rain-register')) $('#rain-register').value = s.rain_register ?? 0;
      if ($('#rain-quantity')) $('#rain-quantity').value = s.rain_quantity ?? 1;
      if ($('#rain-scale')) $('#rain-scale').value = s.rain_scale ?? 0.1;
    } catch (e) { /* ignore */ }
  }

  async function saveWeatherSettings() {
    const body = {
      port: $('#weather-port')?.value || '/dev/ttyS9',
      baud: parseInt($('#weather-baud')?.value || '9600', 10),
      parity: 'N',
      stopbits: 1,
      timeout: 1.0,
      slave: parseInt($('#weather-slave')?.value || '1', 10),
      function: parseInt($('#weather-function')?.value || '3', 10),
      register: parseInt($('#weather-register')?.value || '0', 10),
      quantity: parseInt($('#weather-quantity')?.value || '1', 10),
      scale: parseFloat($('#weather-scale')?.value || '0.1'),
      poll_interval: parseFloat($('#weather-interval')?.value || '2'),
      rain_enabled: ($('#rain-enabled')?.value || '1') === '1',
      rain_slave: parseInt($('#rain-slave')?.value || '23', 10),
      rain_function: parseInt($('#rain-function')?.value || '3', 10),
      rain_register: parseInt($('#rain-register')?.value || '0', 10),
      rain_quantity: parseInt($('#rain-quantity')?.value || '1', 10),
      rain_scale: parseFloat($('#rain-scale')?.value || '0.1'),
      rain_cumulative: true,
    };
    try {
      await apiFetch('/api/weather/settings', { method: 'POST', body: JSON.stringify(body) });
      showToast('气象设置已保存', 'success');
      loadWeather();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function loadReservedPages() {
    await loadWeather();
  }

  // ---------------- PTT 发射自检（设置/校准「按住发射」，排查硬件） ----------------
  let pttHoldTimer = null;
  let pttPointerDown = false;      // 鼠标/手指是否仍按着
  let pttResumeTimer = null;

  async function pttManual(hold, reason) {
    try {
      const d = await apiFetch('/api/ptt/manual', {
        method: 'POST',
        body: JSON.stringify({ hold: !!hold, reason: reason || '', client_id: TTS_CLIENT_ID }),
      });
      renderPttDiag(d);
    } catch (e) {
      if (hold) showToast('PTT 自检失败：' + e.message, 'error');
    }
  }

  function startPttHold() {
    if (pttHoldTimer) return;
    pttManual(true, 'hold-start');
    pttHoldTimer = setInterval(() => pttManual(true, 'heartbeat'), 700);    // 心跳续期（0.7s，抗网络抖动）
    if ($('#ptt-diag-state')) $('#ptt-diag-state').textContent = '发射中（PTT 高）…';
  }

  // opts.resume：浏览器非用户主动地取消了指针（pointercancel / lostpointercapture）时，
  // 只要指针其实还按着，就自动恢复发射，避免出现「按住却间歇性发射」
  function stopPttHold(reason, opts) {
    const was = !!pttHoldTimer;
    if (pttHoldTimer) { clearInterval(pttHoldTimer); pttHoldTimer = null; }
    if (was) pttManual(false, reason || 'release');
    if ($('#ptt-diag-state')) $('#ptt-diag-state').textContent = reason || '已松开';
    if (opts && opts.resume && pttPointerDown) {
      clearTimeout(pttResumeTimer);
      pttResumeTimer = setTimeout(() => { if (pttPointerDown) startPttHold(); }, 200);
    }
  }

  function renderPttDiag(d) {
    const box = $('#ptt-diag-live');
    if (!box || !d) return;
    const p = d.ptt || {};
    const m = d.manual || {};
    const rows = [
      ['软件状态', (p.high ? '高（发射）' : '低（接收）') + '　引用计数 ' + (p.hold_count ?? 0) + (p.release_pending ? '（待释放）' : '')],
      ['引脚实测', 'value = ' + (p.sysfs_value || '--') + '　direction = ' + (p.direction || '--')],
      ['GPIO', (d.chip || 'gpiochip3') + ' line' + (d.line ?? 1) + ' → 全局 ' + (d.gpio_num ?? '?') + '　' + (d.active_high ? '高有效' : '低有效')],
      ['手动发射', m.held ? ('按住中（心跳 ' + m.heartbeat + 's / 上限 ' + m.max_hold + 's）') : (p.manual_hold ? '引用未释放' : '未按住')],
      ['sysfs 节点', p.sysfs || '--'],
      ['写入错误', p.error || '无'],
    ];
    box.innerHTML = rows.map(([k, v]) =>
      `<div><span>${escapeHtml(k)}</span><b>${escapeHtml(String(v))}</b></div>`).join('');
    const evBox = $('#ptt-diag-events');
    if (evBox) {
      const ev = (d.events || []).slice(-8).reverse();
      evBox.innerHTML = ev.length
        ? ev.map(e => `<div class="muted small">${escapeHtml(e.t)}.${String(e.ms || 0).padStart(3, '0')} ` +
            `${e.level ? '↑' : '↓'} <b>${escapeHtml(e.action)}</b> ${escapeHtml(e.reason || '')} ` +
            `<span class="muted">${escapeHtml(e.by || '')} hold=${e.hold}</span></div>`).join('')
        : '<span class="muted small">暂无 PTT 事件</span>';
    }
  }

  async function pollPttDiag() {
    const card = $('#ptt-diag-card');
    if (!card || card.offsetParent === null) return;      // 只在设置页可见时轮询
    try { renderPttDiag(await apiFetch('/api/ptt/diag')); } catch (e) { /* 忽略轮询错误 */ }
  }

  function bindPttSelfTest() {
    const btn = $('#btn-ptt-hold');
    if (btn) {
      btn.style.touchAction = 'none';
      btn.style.userSelect = 'none';
      btn.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        pttPointerDown = true;
        try { btn.setPointerCapture(e.pointerId); } catch (_) { /* 忽略 */ }
        startPttHold();
      });
      btn.addEventListener('pointerup', () => { pttPointerDown = false; stopPttHold('已松开(pointerup)'); });
      btn.addEventListener('pointercancel', () => stopPttHold('指针被取消(pointercancel)', { resume: true }));
      btn.addEventListener('lostpointercapture', () => stopPttHold('指针捕获丢失', { resume: true }));
      window.addEventListener('pointerup', () => {
        pttPointerDown = false;
        if (pttHoldTimer) stopPttHold('已松开(window-pointerup)');
      });
      window.addEventListener('mouseup', () => {
        pttPointerDown = false;
        if (pttHoldTimer) stopPttHold('已松开(window-mouseup)');
      });
      window.addEventListener('blur', () => {
        pttPointerDown = false;
        if (pttHoldTimer) stopPttHold('窗口失焦');
      });
      window.addEventListener('beforeunload', () => { if (pttHoldTimer) pttManual(false, 'unload'); });
    }
    $('#btn-ptt-release')?.addEventListener('click', () => {
      pttPointerDown = false;
      stopPttHold('已强制松开');
    });
  }

  // ---------------- LLM 生成速率监测 ----------------
  let llmRateTimer = null;
  let llmRateStart = 0;
  let llmRateTokens = 0;
  let llmRateFirst = 0;

  function estTokens(text) {
    let cjk = 0;
    let other = 0;
    for (const ch of String(text || '')) {
      const o = ch.codePointAt(0);
      if ((o >= 0x2e80 && o <= 0x9fff) || (o >= 0xff00 && o <= 0xffef)) cjk += 1;
      else other += 1;
    }
    return cjk + Math.ceil(other / 4);
  }

  function showLlmRate(tokens, ttftMs, tps) {
    const el = $('#llm-rate');
    if (!el) return;
    el.textContent = `生成速率：首字 ${Math.round(ttftMs || 0)} ms · ${(tps || 0).toFixed(1)} tok/s · ${tokens || 0} tok`;
  }

  function llmRateReset() {
    llmRateStart = performance.now();
    llmRateTokens = 0;
    llmRateFirst = 0;
    showLlmRate(0, 0, 0);
    const t = $('#llm-tools-live');
    if (t) t.textContent = '';
  }

  function llmRateAdd(text) {
    if (!text) return;
    if (!llmRateFirst) llmRateFirst = performance.now();
    llmRateTokens += estTokens(text);
  }

  function startLlmRateTimer() {
    if (llmRateTimer) return;
    llmRateTimer = setInterval(() => {
      const el = (performance.now() - llmRateStart) / 1000;
      const ttft = llmRateFirst ? (llmRateFirst - llmRateStart) : 0;
      const gen = Math.max(0.001, el - ttft / 1000);
      showLlmRate(llmRateTokens, ttft, llmRateTokens / gen);
    }, 350);
  }

  function stopLlmRateTimer() {
    if (llmRateTimer) { clearInterval(llmRateTimer); llmRateTimer = null; }
  }

  function addToolEvent(kind, name, detail) {
    const el = document.createElement('div');
    el.className = 'msg tool ' + kind;
    const icon = kind === 'start' ? '⚙ 调用技能' : (kind === 'error' ? '✖ 技能失败' : '✔ 技能返回');
    el.textContent = icon + ' ' + name + (detail ? ' — ' + detail : '');
    const hist = $('#chat-history');
    if (!hist) return el;
    hist.appendChild(el);
    hist.scrollTop = hist.scrollHeight;
    return el;
  }

  // ---------------- Agent 对话（技能/工具调用） ----------------
  async function sendChatAgent(text) {
    const provider = $('#llm-provider').value;
    const model = $('#llm-model').value.trim();
    chatMessages.push({ role: 'user', content: text });
    addChatBubble('user', text);
    $('#chat-text').value = '';
    const autoSpeak = !!$('#tts-auto-speak')?.checked;
    const el = addChatBubble('assistant', '思考中（可调用技能读取实时数据）…');
    let answer = '';
    llmRateReset();
    startLlmRateTimer();
    try {
      const resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body: JSON.stringify({ messages: chatMessages, provider, model }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n');
        buf = parts.pop();
        for (const line of parts) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload || payload === '[DONE]') continue;
          let ev = null;
          try { ev = JSON.parse(payload); } catch (e) { continue; }
          if (ev.type === 'delta') {
            answer += ev.content || '';
            el.textContent = answer;
            llmRateAdd(ev.content || '');
          } else if (ev.type === 'tool_start') {
            addToolEvent('start', ev.name, JSON.stringify(ev.arguments || {}));
            if ($('#llm-tools-live')) $('#llm-tools-live').textContent = '技能：' + ev.name;
          } else if (ev.type === 'tool_result') {
            addToolEvent(ev.ok ? 'result' : 'error', ev.name,
              (ev.ok ? '' : '失败 ') + JSON.stringify(ev.result || {}).slice(0, 150));
          } else if (ev.type === 'notice') {
            addToolEvent('result', '系统', ev.text || '');
          } else if (ev.type === 'error') {
            throw new Error(ev.error || 'Agent 出错');
          } else if (ev.type === 'usage' || ev.type === 'usage_total') {
            showLlmRate(ev.tokens, ev.ttft_ms, ev.tok_per_s);
          }
        }
      }
      if (!answer) el.textContent = '（没有回答）';
      chatMessages.push({ role: 'assistant', content: answer });
      if (autoSpeak && answer) await maybeAutoSpeak(answer);
    } catch (e) {
      el.textContent = '错误：' + e.message;
      showToast(e.message, 'error');
    } finally {
      stopLlmRateTimer();
      loadLlmStats();
    }
  }

  // ---------------- 提示词注入 / Agent 设置 / 速率统计 ----------------
  const DEFAULT_LLM_PROMPT =
    '你是 BG7XYZ/ELF2 中继台的值班助手"小中"，回答简短、口语化、适合电台语音播报；\n' +
    '涉及实时数据时必须先调用技能读取，不要凭记忆回答。\n' +
    '当前参考：电池 {battery} V、光伏 {pv} V、CPU {cpu_temp}℃、时间 {time}。';

  async function loadLlmAgentSettings() {
    try {
      const d = await apiFetch('/api/settings');
      const s = d.settings || {};
      if ($('#set-llm-prompt')) $('#set-llm-prompt').value = s.llm_system_prompt || '';
      if ($('#set-llm-prompt-on')) $('#set-llm-prompt-on').checked = s.llm_system_prompt_on === '1';
      if ($('#set-llm-prompt-vars')) $('#set-llm-prompt-vars').checked = s.llm_prompt_vars === '1';
      if ($('#set-agent-enabled')) $('#set-agent-enabled').checked = s.agent_enabled === '1';
      if ($('#set-agent-max-iters')) $('#set-agent-max-iters').value = s.agent_max_iters || 3;
      await loadAgentTools(s.agent_tools || '');
    } catch (e) { /* 非管理员或未登录 */ }
  }

  async function loadAgentTools(selectedCsv) {
    try {
      const d = await apiFetch('/api/agent/tools');
      const sel = new Set(String(selectedCsv || '').split(',').map(x => x.trim()).filter(Boolean));
      const box = $('#agent-tool-list');
      if (box) {
        box.innerHTML = (d.tools || []).map(t => {
          const on = sel.size ? sel.has(t.name) : true;
          return `<label class="checkline"><input type="checkbox" class="agent-tool" value="${escapeHtml(t.name)}"${on ? ' checked' : ''}>` +
            ` ${escapeHtml(t.title)} <span class="muted small">${escapeHtml(t.name)}${t.action ? '（会发射）' : ''}</span></label>`;
        }).join('') || '<span class="muted small">无</span>';
      }
      const v = $('#llm-prompt-vars-live');
      if (v && d.vars) {
        v.textContent = '实时变量：' + Object.keys(d.vars).map(k => `{${k}}=${d.vars[k]}`).join('　');
      }
    } catch (e) { showToast('技能列表加载失败：' + e.message, 'error'); }
  }

  async function saveLlmAgentSettings() {
    const boxes = [...document.querySelectorAll('.agent-tool')];
    const on = boxes.filter(c => c.checked).map(c => c.value);
    const body = {
      llm_system_prompt: $('#set-llm-prompt')?.value || '',
      llm_system_prompt_on: $('#set-llm-prompt-on')?.checked ? '1' : '0',
      llm_prompt_vars: $('#set-llm-prompt-vars')?.checked ? '1' : '0',
      agent_enabled: $('#set-agent-enabled')?.checked ? '1' : '0',
      agent_max_iters: $('#set-agent-max-iters')?.value || 3,
      agent_tools: (boxes.length && on.length !== boxes.length) ? on.join(',') : '',
    };
    try {
      await apiFetch('/api/settings', { method: 'POST', body: JSON.stringify(body) });
      showToast('已保存提示词 / Agent 设置', 'success');
      loadAgentTools(body.agent_tools);
    } catch (e) { showToast('保存失败：' + e.message, 'error'); }
  }

  async function loadLlmStats() {
    try {
      const d = await apiFetch('/api/llm/stats?limit=20');
      const tb = $('#llm-stats-table tbody');
      if (tb) {
        const rows = d.recent || [];
        tb.innerHTML = rows.length ? rows.map(r => `<tr><td>${escapeHtml(String(r.ts || '').slice(11, 19))}</td>` +
          `<td>${escapeHtml(r.mode || '')}</td><td>${r.ttft_ms || 0} ms</td>` +
          `<td>${(r.tok_per_s || 0).toFixed(1)}</td><td>${r.tokens || 0}</td>` +
          `<td class="muted small">${escapeHtml(r.tools || '-')}</td></tr>`).join('')
          : '<tr><td colspan="6" class="muted">暂无记录</td></tr>';
      }
      const t = d.today || {};
      const el = $('#llm-stats-today');
      if (el) {
        el.textContent = `今日 ${t.runs || 0} 次 · 平均 ${(t.avg_tps || 0).toFixed(1)} tok/s · ` +
          `最快 ${(t.max_tps || 0).toFixed(1)} tok/s · 平均首字 ${Math.round(t.avg_ttft || 0)} ms · 共 ${t.tokens || 0} tokens`;
      }
    } catch (e) { /* 忽略 */ }
  }

  // ---------------- 语音输入：BUSY 虚拟按键 → 录音 → 端侧 ASR → 文本 ----------------
  let voiceStream = null;
  let voiceCtx = null;
  let voiceNode = null;
  let voiceSink = null;
  let voiceChunks = [];
  let voiceActive = false;
  let voiceT0 = 0;
  let voicePeak = 0;
  let voiceTick = null;
  let voicePointerDown = false;

  function voiceSetState(text, cls) {
    const el = $('#voice-state');
    if (el) el.textContent = '语音输入：' + text;
    const b = $('#btn-voice-busy');
    if (b) b.classList.toggle('recording', cls === 'on');
  }

  // 16k 单声道 PCM → WAV Blob
  function encodeWav(chunks, sampleRate) {
    let len = 0;
    chunks.forEach((c) => { len += c.length; });
    const view = new DataView(new ArrayBuffer(44 + len * 2));
    const str = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
    str(0, 'RIFF'); view.setUint32(4, 36 + len * 2, true); str(8, 'WAVE');
    str(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true); str(36, 'data'); view.setUint32(40, len * 2, true);
    let off = 44;
    chunks.forEach((c) => {
      for (let i = 0; i < c.length; i++, off += 2) view.setInt16(off, c[i], true);
    });
    return new Blob([view], { type: 'audio/wav' });
  }

  async function startVoiceInput() {
    if (voiceActive) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast('需要 HTTPS 才能访问麦克风', 'error');
      voiceSetState('麦克风不可用');
      return;
    }
    try {
      voiceStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      voiceCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      await voiceCtx.resume();
      const src = voiceCtx.createMediaStreamSource(voiceStream);
      voiceNode = voiceCtx.createScriptProcessor(4096, 1, 1);
      voiceSink = voiceCtx.createGain();
      voiceSink.gain.value = 0;
      voiceChunks = [];
      voicePeak = 0;
      voiceActive = true;
      voiceT0 = Date.now();
      voiceNode.onaudioprocess = (ev) => {
        if (!voiceActive) return;
        const f = ev.inputBuffer.getChannelData(0);
        const pcm = new Int16Array(f.length);
        for (let i = 0; i < f.length; i++) {
          const a = Math.abs(f[i]);
          if (a > voicePeak) voicePeak = a;
          let s = f[i] * 2.0;
          if (s > 1) s = 1; else if (s < -1) s = -1;
          pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        voiceChunks.push(pcm);
      };
      src.connect(voiceNode);
      voiceNode.connect(voiceSink);
      voiceSink.connect(voiceCtx.destination);
      voiceSetState('录音中…（松开结束）', 'on');
      voiceTick = setInterval(() => {
        const sec = (Date.now() - voiceT0) / 1000;
        const info = $('#voice-info');
        if (info) info.textContent = `已录 ${sec.toFixed(1)}s · 峰值 ${(voicePeak * 100).toFixed(0)}%`;
      }, 200);
    } catch (e) {
      showToast('无法访问麦克风：' + e.message, 'error');
      stopVoiceInput(true);
    }
  }

  async function stopVoiceInput(cancel) {
    if (!voiceActive) return;
    voiceActive = false;
    if (voiceTick) { clearInterval(voiceTick); voiceTick = null; }
    try { if (voiceNode) voiceNode.disconnect(); } catch (e) {}
    try { if (voiceSink) voiceSink.disconnect(); } catch (e) {}
    if (voiceStream) { voiceStream.getTracks().forEach((x) => x.stop()); voiceStream = null; }
    try { if (voiceCtx) await voiceCtx.close(); } catch (e) {}
    voiceCtx = null; voiceNode = null; voiceSink = null;
    const secs = (Date.now() - voiceT0) / 1000;
    const chunks = voiceChunks;
    voiceChunks = [];
    if (cancel || !chunks.length || secs < 0.3) {
      voiceSetState(chunks.length ? '太短，已取消' : '已取消');
      return;
    }
    const blob = encodeWav(chunks, 16000);
    voiceSetState(`识别中…（${secs.toFixed(1)}s 音频）`);
    try {
      const fd = new FormData();
      fd.append('audio', blob, 'voice.wav');
      const resp = await fetch('/api/asr/transcribe', {
        method: 'POST', body: fd, credentials: 'same-origin',
        headers: { 'X-CSRF-Token': csrfToken },
      });
      const d = await resp.json().catch(() => null);
      if (!resp.ok || !d || d.ok === false) throw new Error((d && d.error) || ('HTTP ' + resp.status));
      const text = String(d.text || '').trim();
      if (!text) { voiceSetState('未识别到内容'); return; }
      voiceSetState(`识别完成：${d.ms} ms（RTF ${d.rtf}，${d.seconds}s 音频）`);
      const info = $('#voice-info');
      if (info) info.textContent = `已留档 ${d.filename || '--'}`;
      const ta = $('#chat-text');
      if (ta) ta.value = ta.value ? (ta.value.trim() + ' ' + text) : text;
      if ($('#voice-auto-send')?.checked) await sendChat();
    } catch (e) {
      voiceSetState('识别失败：' + e.message);
      showToast('语音识别失败：' + e.message, 'error');
    }
  }

  function bindVoiceInput() {
    const btn = $('#btn-voice-busy');
    if (!btn) return;
    btn.style.touchAction = 'none';
    btn.style.userSelect = 'none';
    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      voicePointerDown = true;
      try { btn.setPointerCapture(e.pointerId); } catch (_) {}
      startVoiceInput();
    });
    btn.addEventListener('pointerup', () => { voicePointerDown = false; stopVoiceInput(false); });
    btn.addEventListener('pointercancel', () => { voicePointerDown = false; stopVoiceInput(false); });
    btn.addEventListener('lostpointercapture', () => { if (voiceActive && !voicePointerDown) stopVoiceInput(false); });
    window.addEventListener('pointerup', () => {
      if (voiceActive && !voicePointerDown) stopVoiceInput(false);
    });
  }

  // ---------------- 总览：PTT / BUSY 实时状态（GPIO3_A1 拉高即 PTT 使能） ----------------
  async function updateRelayState() {
    if (role && document.getElementById('tab-overview')?.classList.contains('active') === false) return;
    try {
      const d = await apiFetch('/api/ptt/status');
      const p = d.ptt || {};
      const el = $('#relay-ptt');
      if (el) {
        el.classList.remove('on', 'rec');
        if (p.high) {
          el.textContent = 'PTT 使能（发射中）';
          el.classList.add('on');
          el.classList.remove('muted');
        } else {
          el.textContent = 'PTT 释放（接收）';
          el.classList.add('muted');
        }
      }
      const b = $('#relay-busy');
      if (b) {
        b.classList.remove('on', 'rec');
        if (voiceActive) {
          b.textContent = '本地录音中（语音输入）';
          b.classList.add('rec');
          b.classList.remove('muted');
        } else if (p.high) {
          b.textContent = '发射占用';
          b.classList.add('on');
          b.classList.remove('muted');
        } else {
          b.textContent = '空闲';
          b.classList.add('muted');
        }
      }
    } catch (e) { /* 忽略 */ }
  }

  // ---------------- event bindings ----------------
  function initEvents() {
    $('#volume-slider')?.addEventListener('input', (e) => {
      if ($('#volume-value')) $('#volume-value').textContent = e.target.value + '%';
    });
    $('#btn-volume-apply')?.addEventListener('click', applyAudioVolume);
    $('#btn-volume-refresh')?.addEventListener('click', loadAudioVolume);
    $('#btn-volume-test')?.addEventListener('click', playTestTone);
    $('#btn-save-cal')?.addEventListener('click', saveCalibration);
    bindPttSelfTest();
    $('#btn-cal-design')?.addEventListener('click', fillDesignCal);
    bindVoiceInput();
    $('#btn-save-prompt')?.addEventListener('click', saveLlmAgentSettings);
    $('#btn-save-agent')?.addEventListener('click', saveLlmAgentSettings);
    $('#btn-refresh-tools')?.addEventListener('click', () => loadAgentTools(''));
    $('#btn-refresh-stats')?.addEventListener('click', loadLlmStats);
    $('#btn-clear-stats')?.addEventListener('click', async () => {
      try { await apiFetch('/api/llm/stats', { method: 'DELETE' }); loadLlmStats(); }
      catch (e) { showToast(e.message, 'error'); }
    });
    $('#btn-insert-prompt')?.addEventListener('click', () => {
      const t = $('#set-llm-prompt');
      if (t) { t.value = DEFAULT_LLM_PROMPT; showToast('已填入推荐提示词，记得点保存', 'success'); }
    });
    $('#btn-add-user')?.addEventListener('click', addUser);
    $('#btn-save-settings')?.addEventListener('click', saveSettings);
    $('#btn-change-pass')?.addEventListener('click', changeOwnPassword);
    $('#btn-llm-refresh')?.addEventListener('click', loadProviders);
    $('#llm-provider')?.addEventListener('change', loadProviders);
    $('#btn-chat-send')?.addEventListener('click', sendChat);
    $('#btn-tts-stop')?.addEventListener('click', stopTtsStream);
    $('#tts-auto-speak')?.addEventListener('change', (e) => {
      if (e.target.checked && $('#chat-stream')) $('#chat-stream').checked = true;
    });
    $('#chat-text')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChat();
      }
    });
    $('#btn-tts-test')?.addEventListener('click', async () => {
      try {
        await speakText($('#tts-test-text')?.value || 'TTS 测试', 'local', $('#tts-voice')?.value || '', true,
                        false, ttsEnVoice(), ttsIcao());
      } catch (e) { showToast(e.message, 'error'); }
    });
    $('#btn-tts-test-web')?.addEventListener('click', async () => {
      try {
        // 只合成、不在板端播放，直接在网页播放器里播放
        await speakText($('#tts-test-text')?.value || 'TTS 测试', 'local', $('#tts-voice')?.value || '', false, true,
                        ttsEnVoice(), ttsIcao());
      } catch (e) { showToast(e.message, 'error'); }
    });
    $('#tts-audio')?.addEventListener('play', () => {
      const tip = $('#tts-web-status');
      if (tip) tip.textContent = '网页播放器：播放中';
    });
    $('#set-tts-icao-voice')?.addEventListener('change', (e) => {
      if (e.target) e.target.dataset.saved = e.target.value || '';
    });
    $('#set-tts-en-voice')?.addEventListener('change', (e) => {
      if (e.target) e.target.dataset.saved = e.target.value || '';
    });
    $('#tts-icao')?.addEventListener('change', () => { /* 仅前端开关，随朗读请求发送 */ });
    $('#btn-tts-voice-upload')?.addEventListener('click', uploadVoicePack);
    $('#btn-tts-train-upload')?.addEventListener('click', uploadTrainingData);
    const micSlider = (id, labelId) => {
      $(id)?.addEventListener('input', (e) => { if ($(labelId)) $(labelId).textContent = e.target.value + '%'; });
    };
    micSlider('#mic-pga', '#mic-pga-val');
    micSlider('#mic-adc', '#mic-adc-val');
    micSlider('#mic-l2r2', '#mic-l2r2-val');
    micSlider('#mic-aux', '#mic-aux-val');
    $('#btn-mic-settings-apply')?.addEventListener('click', applyMicSettings);
    $('#btn-weather-query')?.addEventListener('click', queryWeatherHistory);
    $('#btn-weather-export')?.addEventListener('click', exportWeatherCsv);
    $('#weather-sample-interval')?.addEventListener('change', loadWeatherDaily);
    $('#btn-weather-settings-save')?.addEventListener('click', saveWeatherSettings);
    $('#btn-wind-settings-save')?.addEventListener('click', saveWeatherSettings);
    $('#btn-rain-settings-save')?.addEventListener('click', saveWeatherSettings);
    $('#weather-date')?.addEventListener('change', loadWeatherDaily);
    $('#btn-rain-query')?.addEventListener('click', loadRainHourly);
    $('#btn-rain-export')?.addEventListener('click', exportRainCsv);
    $('#rain-date')?.addEventListener('change', loadRainHourly);
    $('#btn-camera-start')?.addEventListener('click', cameraStart);
    $('#btn-camera-stop')?.addEventListener('click', cameraStop);
    $('#btn-camera-snapshot')?.addEventListener('click', cameraSnapshot);
    $('#btn-camera-loop-start')?.addEventListener('click', cameraLoopStart);
    $('#btn-camera-loop-stop')?.addEventListener('click', cameraLoopStop);
    $('#btn-camera-manual-start')?.addEventListener('click', cameraManualStart);
    $('#btn-camera-manual-stop')?.addEventListener('click', cameraManualStop);
    $('#btn-camera-rtmp-start')?.addEventListener('click', cameraRtmpStart);
    $('#btn-camera-rtmp-stop')?.addEventListener('click', cameraRtmpStop);
    $('#btn-camera-settings-save')?.addEventListener('click', saveCameraSettings);
    $('#camera-recordings-table')?.addEventListener('click', async (e) => {
      const playUrl = e.target?.dataset?.camPlay;
      const delName = e.target?.dataset?.camDel;
      if (playUrl) {
        const v = $('#camera-playback');
        if (v) { v.src = playUrl; v.style.display = 'block'; v.play().catch(() => {}); }
      }
      if (delName) {
        if (!confirm('确定删除录像 ' + delName + ' ？')) return;
        try {
          await apiFetch('/api/camera/recordings/' + encodeURIComponent(delName), { method: 'DELETE' });
          showToast('录像已删除', 'success');
          loadCameraStatus();
        } catch (err) { showToast(err.message, 'error'); }
      }
    });
    $('#btn-mic-start')?.addEventListener('click', startMicCapture);
    $('#btn-mic-stop')?.addEventListener('click', stopMicCapture);
    $('#btn-mic-listen')?.addEventListener('click', startMicListen);
    $('#btn-mic-listen-stop')?.addEventListener('click', stopMicListen);
    $('#btn-record')?.addEventListener('click', () => recording ? stopRecording() : startRecording());
    // 实时对讲：按住说话（指针事件兼容鼠标/触摸）
    const pushBtn = $('#btn-push-talk');
    if (pushBtn) {
      // 按住说话：用 pointer capture 把指针锁在按钮上。
      // 原来还挂了 pointerleave —— 按住时鼠标只要抖一下/移出按钮一点点，
      // 就立刻停发并松开 PTT，用户再按又拉高，观感就是「PTT 反复触发、说不了话」。
      pushBtn.style.touchAction = 'none';
      pushBtn.style.userSelect = 'none';
      pushBtn.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        try { pushBtn.setPointerCapture(e.pointerId); } catch (_) { /* 忽略 */ }
        startPushTalk();
      });
      pushBtn.addEventListener('pointerup', () => { if (pushActive) stopPushTalk('松开按钮'); });
      pushBtn.addEventListener('lostpointercapture', () => { if (pushActive) stopPushTalk('松开按钮'); });
      pushBtn.addEventListener('pointercancel', () => { if (pushActive) stopPushTalk('取消'); });
      if (window.PointerEvent) {
        window.addEventListener('pointerup', () => { if (pushActive) stopPushTalk('松开按钮'); });
      } else {
        window.addEventListener('mouseup', () => { if (pushActive) stopPushTalk('松开按钮'); });
        window.addEventListener('touchend', () => { if (pushActive) stopPushTalk('松开按钮'); });
      }
    }
    $('#btn-push-stop')?.addEventListener('click', () => stopPushTalk('手动停止'));
    $('#push-monitor')?.addEventListener('change', () => {
      if (pushMute) pushMute.gain.value = $('#push-monitor')?.checked ? 0.35 : 0;
    });
    $('#btn-test-tone')?.addEventListener('click', playTestTone);
    $('#btn-upload-wav')?.addEventListener('click', async () => {
      const file = $('#wav-file')?.files?.[0];
      if (!file) return showToast('请先选择一个 WAV 文件', 'error');
      const fd = new FormData();
      fd.append('audio', file, file.name || 'upload.wav');
      try {
        const data = await apiFetch('/api/intercom/upload', { method: 'POST', body: fd });
        showToast(`WAV 已上传并发送到 AUX：${data.duration_ms} ms`, 'success');
        loadRecordings();
      } catch (e) { showToast(e.message, 'error'); }
    });
    $('#recordings-table')?.addEventListener('click', (e) => {
      const id = e.target?.dataset?.play;
      if (!id) return;
      apiFetch(`/api/intercom/play/${id}`, { method: 'POST', body: '{}' })
        .then(() => showToast('正在重放录音', 'success'))
        .catch(err => showToast(err.message, 'error'));
    });
    $('#users-table')?.addEventListener('click', async (e) => {
      const delId = e.target?.dataset?.del;
      const resetId = e.target?.dataset?.reset;
      if (delId) {
        if (!confirm(`确定删除用户 ${e.target.dataset.name}？`)) return;
        try { await apiFetch(`/api/users/${delId}`, { method: 'DELETE' }); showToast('用户已删除', 'success'); loadUsers(); }
        catch (err) { showToast(err.message, 'error'); }
      }
      if (resetId) {
        const pwd = prompt(`为 ${e.target.dataset.name} 设置新密码（至少 8 位）`);
        if (!pwd) return;
        try { await apiFetch(`/api/users/${resetId}/password`, { method: 'POST', body: JSON.stringify({ password: pwd }) }); showToast('密码已重置', 'success'); }
        catch (err) { showToast(err.message, 'error'); }
      }
    });
  }

  // ---------------- boot ----------------
  document.addEventListener('DOMContentLoaded', () => {
    startBeijingClock();
    initTabs();
    initEvents();
    loadStatus();
    loadProviders();
    loadTtsProviders();
    loadRecordings();
    loadReservedPages();
    loadCameraStatus();
    loadMicLevel();
    loadMicSettings();
    cameraOsdTimer = setInterval(updateCameraOsd, 1000);
    if (role === 'admin') {
      loadUsers();
      loadSettings();
      loadAudioVolume();
      loadWeatherSettings();
      loadSensorStatus();
      loadLlmAgentSettings();
      loadLlmStats();
    }
    loadCalibration();
    setInterval(loadStatus, 3000);
    updateRelayState();
    setInterval(updateRelayState, 1500);
    setInterval(pollPttDiag, 1200);
    setInterval(loadRecordings, 10000);
    setInterval(loadWeatherRealtime, 2000);
    setInterval(loadWeatherDaily, 10000);
    setInterval(loadRainRealtime, 2000);
    setInterval(loadRainHourly, 10000);
  });
})();
