/* 中继语音测试：文本对话 + 板端离线语音输入 + 网页试听
 *
 * 这块原先是「总览 → LLM 对话」页的全部内容。它跟语音助手用的是同一份提示词
 * （共用基础设定 + 语音播报约束）、同一条 agent 工具链路、同一套数值口语化出口，
 * 所以它本来就只是**语音助手的本地非接收测试**，不该在总览页再占一份设置。
 * 2026-09-27 并入本页（用户要求：并入语音助手，仅作为语音测试的组成，删冗余输入）。
 *
 * 与语音助手真机路径的差别只有一个：**不发射**（不拉 PTT、不上中继）。
 * 自包含：不依赖 app.js（子页面本来也不加载它）。
 */
(function () {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function csrf() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  }

  function toast(msg, kind) {
    if (window.asToast) { window.asToast(msg, kind); return; }
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  async function api(url, opts = {}) {
    const headers = Object.assign({ 'X-CSRF-Token': csrf() }, opts.headers || {});
    if (opts.body) headers['Content-Type'] = 'application/json';
    const r = await fetch(url, Object.assign({ credentials: 'same-origin' }, opts, { headers }));
    const txt = await r.text();
    let data = null;
    try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
    if (!r.ok || (data && data.ok === false)) {
      throw new Error((data && data.error) || ('HTTP ' + r.status));
    }
    return data;
  }

  // ---------------------------------------------------------------- 文本对话
  const chatMsgs = [];
  let rateTimer = null, rateChars = 0, rateStart = 0;

  function addBubble(role, content) {
    const box = $('#at-chat-history');
    if (!box) return null;
    const el = document.createElement('div');
    el.className = 'msg ' + role;
    el.textContent = content;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }

  function addToolEvent(kind, name, detail) {
    const box = $('#at-chat-history');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'msg tool ' + kind;
    const icon = kind === 'start' ? '⚙ 调用技能'
      : (kind === 'error' ? '✖ 技能失败' : '✔ 技能返回');
    el.textContent = icon + ' ' + name + (detail ? ' — ' + detail : '');
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
  }

  function rateReset() {
    rateChars = 0;
    rateStart = performance.now();
    if ($('#at-rate')) $('#at-rate').textContent = '生成速率：--';
  }

  function rateAdd(text) { rateChars += (text || '').length; }

  function startRateTimer() {
    stopRateTimer();
    rateTimer = setInterval(() => {
      const secs = Math.max(0.001, (performance.now() - rateStart) / 1000);
      const tps = rateChars / secs;
      if ($('#at-rate')) {
        $('#at-rate').textContent = '生成速率：' + tps.toFixed(1) + ' 字/秒（约 '
          + (rateChars) + ' 字）';
      }
    }, 250);
  }

  function stopRateTimer() {
    if (rateTimer) { clearInterval(rateTimer); rateTimer = null; }
  }

  // ---------------------------------------------- 发射（受控）：生成后发上无线电
  // 走 /api/assist/say（不过 LLM）：助手的受控发射链路全都在（禁发时段、信道占用、
  // 最小间隔、单次上限、全局测试模式），这里只负责发起与回显。
  let lastReply = '';

  function setTxState(msg) {
    const el = $('#at-tx-state');
    if (el) el.textContent = msg || '';
  }

  async function sayToAir(text, ask) {
    const t = (text || '').trim();
    if (!t) { toast('没有可发射的文本', 'error'); return; }
    if (ask && !confirm('会真的发射到无线电（占用信道，其他台能听到）。确定继续？')) return;
    setTxState('提交发射…');
    try {
      const d = await api('/api/assist/say', {
        method: 'POST', body: JSON.stringify({ text: t, tx: true }),
      });
      if (!d.ok) throw new Error(d.error || '提交失败');
      if (d.test_mode) {
        setTxState('全局「测试模式」开着：本次只合成不发射');
        toast('全局「测试模式（只试听不发射）」开着，本次只合成', 'error');
      } else {
        setTxState('已提交发射（受控：占用/间隔/上限生效）');
        toast('已提交发射到无线电', 'success');
      }
    } catch (e) {
      setTxState('发射提交失败：' + e.message);
      toast('发射失败：' + e.message, 'error');
    }
  }

  async function sendChat() {
    const ta = $('#at-chat-text');
    const text = (ta && ta.value || '').trim();
    if (!text) return;
    chatMsgs.push({ role: 'user', content: text });
    addBubble('user', text);
    ta.value = '';
    const el = addBubble('assistant', '思考中（可调用技能读取实时数据）…');
    let answer = '';
    rateReset();
    startRateTimer();
    try {
      const resp = await fetch('/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
        body: JSON.stringify({ messages: chatMsgs }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n');
        buf = parts.pop();
        for (const line of parts) {
          const s = line.trim();
          if (!s.startsWith('data:')) continue;
          const payload = s.slice(5).trim();
          if (!payload || payload === '[DONE]') continue;
          let ev = null;
          try { ev = JSON.parse(payload); } catch (e) { continue; }
          if (ev.type === 'delta') {
            answer += ev.content || '';
            el.textContent = answer;
            rateAdd(ev.content || '');
          } else if (ev.type === 'tool_start') {
            addToolEvent('start', ev.name, JSON.stringify(ev.arguments || {}));
            if ($('#at-tools-live')) $('#at-tools-live').textContent = '技能：' + ev.name;
          } else if (ev.type === 'tool_result') {
            addToolEvent(ev.ok ? 'result' : 'error', ev.name,
              (ev.ok ? '' : '失败 ') + JSON.stringify(ev.result || {}).slice(0, 150));
          } else if (ev.type === 'notice') {
            addToolEvent('result', '系统', ev.text || '');
          } else if (ev.type === 'error') {
            throw new Error(ev.error || 'Agent 出错');
          } else if (ev.type === 'final') {
            // 服务端把模型原文换成「将要念出来的那句」（数值口语化 + 补喵），
            // 网页对话是语音测试，屏幕上看到的就是会发射的那句话。
            answer = ev.text || answer;
            el.textContent = answer;
            lastReply = answer;
            if (ev.raw && ev.raw !== answer) {
              const d = document.createElement('details');
              d.className = 'chat-raw';
              const sm = document.createElement('summary');
              sm.textContent = '模型原文' + (ev.retried ? '（首答没用到数据，已带数据重试）' : '');
              const tx = document.createElement('div');
              tx.className = 'chat-raw-text';
              tx.textContent = ev.raw;
              d.appendChild(sm);
              d.appendChild(tx);
              el.appendChild(d);
            }
          }
        }
      }
      if (!answer) el.textContent = '（没有回答）';
      chatMsgs.push({ role: 'assistant', content: answer });
      // 用户勾了「生成后自动发射」：文本一生成就发上无线电（受控发射那条路）
      if (answer && $('#at-tx-auto') && $('#at-tx-auto').checked) {
        await sayToAir(answer, true);
      }
    } catch (e) {
      el.textContent = '错误：' + e.message;
      toast(e.message, 'error');
    } finally {
      stopRateTimer();
    }
  }

  // ------------------------------------------------- 板端离线语音输入（按住说话）
  let voiceActive = false, voiceStream = null, voiceCtx = null, voiceNode = null;
  let voiceChunks = [], voicePointerDown = false;

  function voiceSetState(text, cls) {
    const el = $('#at-voice-state');
    if (el) el.textContent = '语音输入：' + text;
    const b = $('#btn-at-voice');
    if (b) b.classList.toggle('recording', cls === 'on');
  }

  // Float32 单声道 → 16k WAV Blob
  function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeStr = (off, s) => {
      for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
    };
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
      const v = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(off, v < 0 ? v * 0x8000 : v * 0x7fff, true);
    }
    return new Blob([view], { type: 'audio/wav' });
  }

  function mergeFloat32(chunks) {
    let len = 0;
    chunks.forEach(c => { len += c.length; });
    const out = new Float32Array(len);
    let off = 0;
    chunks.forEach(c => { out.set(c, off); off += c.length; });
    return out;
  }

  async function startVoiceInput() {
    if (voiceActive) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      toast('需要 HTTPS 才能访问麦克风（当前页面不是安全上下文）', 'error');
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
      voiceChunks = [];
      voiceNode.onaudioprocess = (e) => {
        if (!voiceActive) return;
        voiceChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      src.connect(voiceNode);
      voiceNode.connect(voiceCtx.destination);
      voiceActive = true;
      voiceSetState('录音中…（松开发送）', 'on');
    } catch (e) {
      voiceSetState('麦克风打开失败：' + e.message);
      toast('麦克风打开失败：' + e.message, 'error');
    }
  }

  async function stopVoiceInput(cancel) {
    if (!voiceActive) return;
    voiceActive = false;
    try { if (voiceNode) voiceNode.disconnect(); } catch (e) { /* ignore */ }
    try { if (voiceCtx) await voiceCtx.close(); } catch (e) { /* ignore */ }
    try { if (voiceStream) voiceStream.getTracks().forEach(t => t.stop()); } catch (e) { /* ignore */ }
    voiceNode = voiceCtx = voiceStream = null;
    const chunks = voiceChunks;
    voiceChunks = [];
    voiceSetState('识别中…');
    if (cancel || !chunks.length) { voiceSetState('已取消'); return; }
    try {
      const wav = encodeWav(mergeFloat32(chunks), 16000);
      const fd = new FormData();
      fd.append('audio', wav, 'busy.wav');
      const resp = await fetch('/api/voice/input', {
        method: 'POST', body: fd, headers: { 'X-CSRF-Token': csrf() },
      });
      const d = await resp.json().catch(() => null);
      if (!resp.ok || !d || d.ok === false) {
        throw new Error((d && d.error) || ('HTTP ' + resp.status));
      }
      const text = String(d.text || '').trim();
      if (!text) { voiceSetState('未识别到内容'); return; }
      voiceSetState(`识别完成：${d.ms} ms（RTF ${d.rtf}，${d.seconds}s 音频）`);
      const ta = $('#at-chat-text');
      if (ta) ta.value = ta.value ? (ta.value.trim() + ' ' + text) : text;
      if ($('#at-voice-auto-send') && $('#at-voice-auto-send').checked) await sendChat();
    } catch (e) {
      voiceSetState('识别失败：' + e.message);
      toast('语音识别失败：' + e.message, 'error');
    }
  }

  function bindVoiceInput() {
    const btn = $('#btn-at-voice');
    if (!btn) return;
    btn.style.touchAction = 'none';
    btn.style.userSelect = 'none';
    btn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      voicePointerDown = true;
      try { btn.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      startVoiceInput();
    });
    btn.addEventListener('pointerup', () => { voicePointerDown = false; stopVoiceInput(false); });
    btn.addEventListener('pointercancel', () => { voicePointerDown = false; stopVoiceInput(false); });
    btn.addEventListener('lostpointercapture', () => {
      if (voiceActive && !voicePointerDown) stopVoiceInput(false);
    });
    window.addEventListener('pointerup', () => {
      if (voiceActive && !voicePointerDown) stopVoiceInput(false);
    });
  }

  // ------------------------------------------------------- 网页试听（不发射）
  async function speakToWeb() {
    const ta = $('#at-tts-text');
    const text = (ta && ta.value || '').trim();
    const st = $('#at-tts-state');
    if (!text) { toast('试听文本为空', 'error'); return; }
    try {
      if (st) st.textContent = '合成中…';
      const d = await api('/api/tts/speak', {
        method: 'POST',
        body: JSON.stringify({ text, provider: 'local', auto_play: false }),
      });
      if (st) st.textContent = `已合成 ${d.voice || ''}（${((d.size || 0) / 1024).toFixed(1)} KB）· 未发射`;
      const el = $('#at-audio');
      if (el && d.filename) {
        el.src = '/recordings/' + encodeURIComponent(d.filename) + '?t=' + Date.now();
        el.style.display = 'block';
        el.play().catch(() => toast('浏览器拦截了自动播放，请点播放键', 'error'));
      }
    } catch (e) {
      if (st) st.textContent = '合成失败：' + e.message;
      toast('合成失败：' + e.message, 'error');
    }
  }

  function init() {
    if (!$('#at-chat-history')) return;      // 不在本页
    $('#btn-at-send')?.addEventListener('click', sendChat);
    $('#at-chat-text')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    bindVoiceInput();
    $('#btn-at-say-last')?.addEventListener('click', () => sayToAir(lastReply, true));
    $('#btn-at-tts-web')?.addEventListener('click', speakToWeb);
    voiceSetState('就绪');
    setTxState('');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
