/* 中继语音助手页：状态机 / 实时电平 / 实况识别流 / 对话记录 / 设置 / 提示词预览
 *
 * 数据来源：
 *   GET  /api/assist/status   状态机 + 电平曲线 + 实况识别流 + 计数器 + 全部设置
 *   GET  /api/assist/list     对话记录（含双方音频文件名）
 *   POST /api/assist/test     手动跑一轮（默认不发射）
 *   POST /api/assist/wake     只测唤醒词匹配
 *   POST /api/assist/stop     一键停止
 *   GET  /api/assist/prompt   预览最终注入的提示词
 *   POST /api/assist/clean    TTS 清洗预览
 */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  function toast(msg, kind) {
    var el = $('#toast');
    if (!el) { console.log(msg); return; }
    el.textContent = msg;
    el.className = 'toast show' + (kind ? ' ' + kind : '');
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.className = 'toast'; }, 3600);
  }

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  function api(url, opts) {
    opts = opts || {};
    var h = Object.assign({ 'X-CSRF-Token': csrf() }, opts.headers || {});
    if (opts.body && !h['Content-Type']) h['Content-Type'] = 'application/json';
    return fetch(url, Object.assign({}, opts, { headers: h, credentials: 'same-origin' }))
      .then(function (r) {
        return r.json().catch(function () { return { ok: false, error: 'HTTP ' + r.status }; });
      });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtDur(sec) {
    sec = Number(sec) || 0;
    if (sec < 90) return sec.toFixed(0) + 's';
    if (sec < 5400) return (sec / 60).toFixed(1) + ' 分';
    return (sec / 3600).toFixed(1) + ' 小时';
  }

  function badge(el, text, kind) {
    if (!el) return;
    el.textContent = text;
    var cls = 'badge';
    if (kind === 'ok') cls += ' ok';
    else if (kind === 'warn') cls += ' warn';
    else if (kind === 'bad') cls += ' bad';
    el.className = cls;
    el.style.background = kind === 'ok' ? 'rgba(34,197,94,.18)'
      : kind === 'warn' ? 'rgba(234,179,8,.18)'
        : kind === 'bad' ? 'rgba(239,68,68,.18)' : '';
    el.style.color = kind === 'ok' ? '#86efac'
      : kind === 'warn' ? '#fde68a'
        : kind === 'bad' ? '#fca5a5' : '';
  }

  /* =================== 设置项定义 =================== */
  // 每一项：k=键 f=标签 t=类型 tip=说明 min/max/step
  var SETTINGS_SPEC = [
    {
      title: '总览与启用', hint: '启用后助手常驻监听采集流。关闭语音日志也不影响助手工作（两者共用同一路采集）。',
      items: [
        { k: 'assist_enabled', f: '启用中继语音助手', t: 'bool' },
        { k: 'assist_channel', f: '采集声道', t: 'select', opts: [['left', '左声道'], ['right', '右声道'], ['mix', '混合']] },
        { k: 'assist_test_mode', f: '测试模式（只试听不发射）', t: 'bool', tip: '首次调试务必打开' }
      ]
    },
    {
      title: '唤醒词与交互', hint: '一句话唤醒：唤醒词与问题连在一起说即可。命中后 30 秒内可直接追问，不必再喊唤醒词。',
      items: [
        { k: 'assist_wake_mode', f: '唤醒方式', t: 'select',
          tip: 'BUSY 触发 = 只有载波有效才算「检测到语音」并送 ASR（电平触发完全关闭，'
             + '下面「语音分段」那组 dBFS 阈值不再参与判定）；弱信号也能收，没人说话时不会误唤醒',
          opts: [['level', '电平唤醒（原行为）'], ['busy', 'BUSY 触发 + 唤醒词（推荐）']] },
        { k: 'assist_wake_words', f: '唤醒词（逗号分隔，最多 8 个）', t: 'text', span: 2, tip: '短词误触发多、长词更稳；改完立刻生效' },
        { k: 'assist_wake_fuzzy', f: '同音容错', t: 'bool', tip: '「中继太」「中机台」「智能中记」也能命中' },
        { k: 'assist_wake_loose', f: '宽松匹配（允许唤醒词漏一个字）', t: 'bool', tip: '「智能中继」→「智能继」也能唤醒；短词会更易误触发，默认关闭' },
        { k: 'assist_followup_seconds', f: '追问窗口（秒）', t: 'num', min: 0, max: 600, step: 5 },
        { k: 'assist_ack_reply', f: '只喊唤醒词时的应答', t: 'text' },
        { k: 'assist_use_vad', f: '用 silero VAD 收紧语音边界', t: 'bool', tip: '只做边界裁剪，不会据此丢弃唤醒词' }
      ]
    },
    {
      title: '语音分段（灵敏度调参）', hint: '「有反应但识别不到」时优先调这里：先降起判电平，再降最短有声时长。'
          + '注意：唤醒方式选「BUSY 触发」时这一组只影响电平模式，busy 模式下不参与判定。',
      items: [
        { k: 'assist_dbfs_open', f: '语音起判电平 dBFS', t: 'num', min: -80, max: -5, step: 1, tip: '越大越不灵敏；静噪良好的电台可到 -45' },
        { k: 'assist_dbfs_close', f: '语音结束电平 dBFS', t: 'num', min: -85, max: -5, step: 1, tip: '必须低于起判电平' },
        { k: 'assist_preroll_ms', f: '前置缓冲 ms', t: 'num', min: 0, max: 3000, step: 50, tip: '防止吃掉语音开头的字' },
        { k: 'assist_silence_ms', f: '静音收段 ms', t: 'num', min: 150, max: 5000, step: 50, tip: '越大越不容易把一句话切两半' },
        { k: 'assist_min_speech_ms', f: '最短有声时长 ms', t: 'num', min: 100, max: 5000, step: 50, tip: '滤掉咔哒声；喊唤醒词至少要有这么长' },
        { k: 'assist_max_utterance', f: '单段最长 秒', t: 'num', min: 2, max: 120, step: 1 }
      ]
    },
    {
      title: '发射安全', hint: '助手是自动发射，这些是硬红线，不因任何理由放宽。',
      items: [
        { k: 'assist_max_tx_seconds', f: '单次最长发射 秒', t: 'num', min: 3, max: 300, step: 1, tip: '到点强制 kill aplay 并松 PTT' },
        { k: 'assist_min_gap_seconds', f: '两次发射最短间隔 秒', t: 'num', min: 0, max: 600, step: 1 },
        { k: 'assist_busy_wait_seconds', f: '等待信道空闲最久 秒', t: 'num', min: 1, max: 120, step: 1, tip: '超时放弃本次回答，不硬插' },
        { k: 'assist_tx_guard_ms', f: '发射余波保护 ms', t: 'num', min: 0, max: 5000, step: 100, tip: '发射后这段时间不收音，防自激' },
        { k: 'assist_quiet_hours', f: '禁发时段', t: 'text', span: 2, tip: '如 23:00-07:00，可多段逗号分隔；留空不禁发' }
      ]
    },
    {
      title: '自主回答（听到就判断该不该答）',
      hint: '开了这项，助手不再只认唤醒词：每听到一段话先自己判断「要不要接」，'
          + '再叠上频率红线（每小时上限、与前一次发射的最小间隔、同呼号冷却、'
          + '白名单、禁发时段、信道忙、全局测试模式）。'
          + '判定由一个**独立的小模型调用**完成，它只输出四行：'
          + '想（判断依据）／判（答或默）／由（闭集理由）／信（置信度）；'
          + '格式解析不出来一律判「默」，「想」只进日志与页面、**绝不朗读**。'
          + '当前只开放**影子模式**：判定与记录全跑，但一次都不发射 ——'
          + '先在「手动测试 → 自主决策自测」和实况流的判定徽章上攒够证据，'
          + '确认判断靠谱了再开阶段二。',
      items: [
        { k: 'assist_auto_enabled', f: '启用自主回答判断', t: 'bool',
          tip: '关掉则回到「只认唤醒词」的老行为' },
        { k: 'assist_auto_mode', f: '自主模式', t: 'select',
          tip: '半自动/全自动的代码路径已就位，但闸门未开放，选了也会被强制回落成影子模式',
          opts: [['shadow', '影子模式（只记录不发射，阶段一）'],
                 ['half', '半自动（阶段二开放 · 现在选不了）', 1],
                 ['full', '全自动（阶段二开放 · 现在选不了）', 1]] },
        { k: 'assist_auto_max_per_hour', f: '每小时最多主动回答 次', t: 'num',
          min: 0, max: 120, step: 1, tip: '0 = 一律不主动答；影子期按此上限换算可达率' },
        { k: 'assist_auto_min_gap', f: '两次主动回答最小间隔 秒', t: 'num',
          min: 0, max: 3600, step: 10, tip: '这条是自主层的额外间隔，与「发射安全」里的通用间隔叠加生效' },
        { k: 'assist_auto_call_cooldown', f: '同一呼号冷却 秒', t: 'num',
          min: 0, max: 86400, step: 60, tip: '刚答过的人再说话，这段时间内不再插话' },
        { k: 'assist_auto_whitelist', f: '呼号白名单', t: 'text', span: 2,
          tip: '只答这些呼号（逗号分隔）；留空 = 不限呼号' },
        { k: 'assist_auto_think', f: '让模型写出判断依据（想）', t: 'bool',
          tip: '关掉省几秒生成时间，代价是页面上看不到它为什么这么判' },
        { k: 'assist_auto_think_chars', f: '「想」最多 字', t: 'num', min: 8, max: 60, step: 2,
          tip: '只在页面与日志里显示，不会被朗读出去' },
        { k: 'assist_auto_dry_answer', f: '影子期同时生成「本来会说的那句话」', t: 'bool',
          tip: '只合成试听、绝不发射；只看判答/判默无法验收答得对不对，所以默认打开' }
      ]
    },
    {
      title: 'LLM 与回复预算', hint: '防止长输入长输出挤爆本地上下文 —— 这是本地 1.5B 模型最容易空输出的原因。',
      items: [
        // LLM 提供方已统一到「设置 / 校准」页并全局生效，助手页不再重复设置
        { k: 'assist_max_reply_chars', f: '回复字数上限', t: 'num', min: 10, max: 300, step: 5, tip: '直接决定发射时长，80 字约 15~20 秒' },
        { k: 'assist_max_tokens', f: 'max_tokens', t: 'num', min: 32, max: 512, step: 16 },
        { k: 'assist_history_turns', f: '保留历史轮数', t: 'num', min: 0, max: 12, step: 1 },
        { k: 'assist_max_input_chars', f: '输入字符上限', t: 'num', min: 400, max: 8000, step: 100, tip: '超限时自动逐级砍历史、再砍系统设定' },
        { k: 'assist_temperature', f: 'temperature', t: 'num', min: 0, max: 1.5, step: 0.05 },
        { k: 'assist_use_tools', f: '允许调用实时数据工具', t: 'bool' },
        { k: 'assist_agent_iters', f: '工具调用最大轮次', t: 'num', min: 0, max: 4, step: 1 },
        { k: 'assist_keep_llm_warm', f: '启用期间保持 LLM 常驻', t: 'bool', tip: '关掉会把冷启动的 20~40 秒等进去' },
        { k: 'assist_llm_wait', f: '等 LLM 就绪最久 秒', t: 'num', min: 5, max: 120, step: 5 }
      ]
    },
    {
      title: '提示词（共用基础设定 + 语音播报约束）',
      hint: '两条链路**共用**这两份：中继语音助手（发射）与「手动测试 / 文本对话」（不发射）。'
          + '「共用基础设定」在注入时排在最前，「语音播报约束」追加在最后，变量'
          + '（如 {battery}）已展开为实时值，{max_chars} 会自动替换成回复字数上限。'
          + '排布要点：实测板端 1.5B 只可靠地理会**最后一条消息**，多项规则时也是'
          + '**最后一条最受重视** —— 所以人格/通联范式这类「设定」放上面那份，'
          + '下面的约束只留输出格式，并把最要紧的格式规则写在最后一段。'
          + '范式要写成规则、不要写可直接抄的完整例句（实测带例句时会被照抄，'
          + '问电压都答「早上好，友台，呼叫信号为59」）。数值读法已由后端确定性处理'
          + '（speech_text.speakable），不必在这里要求模型转换数字。'
          + '若模型答非所据（明明查到了数据却没用上），后端会自动带数据重试一次。',
      items: [
        { k: 'llm_system_prompt_on', f: '启用共用基础设定', t: 'bool' },
        { k: 'llm_system_prompt', f: '', t: 'textarea', span: 2,
          tip: '角色设定/人格/通联范式放这里 —— 它排在最前，不会把最后的格式规则挤掉' },
        { k: 'llm_prompt_vars', f: '展开实时变量（{battery} {pv} {cpu_temp} {wind} {rain_today}）', t: 'bool' },
        { k: 'assist_prompt_suffix', f: '语音播报约束（只写输出格式）', t: 'textarea', span: 2 }
      ]
    },
    {
      title: '音色与归档', hint: '',
      items: [
        { k: 'assist_voice', f: '播报音色', t: 'voices', tip: '留空则用网页朗读的默认音色' },
        { k: 'assist_retention_days', f: '助手录音保留天数', t: 'num', min: 1, max: 3650, step: 1 }
      ]
    }
  ];

  var voiceList = null;

  function fieldHTML(it, val) {
    var id = 'f-' + it.k;
    var span = it.span === 2 ? ' span2' : '';
    var h = '<div class="as-field' + span + '">';
    if (it.t === 'bool') {
      h += '<label for="' + id + '">' + esc(it.f) + '</label>';
      h += '<div class="as-switch"><input type="checkbox" id="' + id + '"' +
        (String(val) === '1' ? ' checked' : '') + '>' +
        (it.tip ? '<span class="tip">' + esc(it.tip) + '</span>' : '') + '</div>';
      return h + '</div>';
    }
    h += '<label for="' + id + '">' + esc(it.f) + '</label>';
    if (it.t === 'select') {
      h += '<select id="' + id + '">';
      it.opts.forEach(function (o) {
        h += '<option value="' + esc(o[0]) + '"' + (String(val) === o[0] ? ' selected' : '') +
          (o[2] ? ' disabled' : '') + '>' + esc(o[1]) + '</option>';
      });
      h += '</select>';
    } else if (it.t === 'textarea') {
      h += '<textarea id="' + id + '" rows="8">' + esc(val) + '</textarea>';
    } else if (it.t === 'voices') {
      h += '<select id="' + id + '"><option value="">（默认）</option>';
      (voiceList || []).forEach(function (v) {
        h += '<option value="' + esc(v.id) + '"' + (String(val) === v.id ? ' selected' : '') +
          '>' + esc(v.name || v.id) + (v.ready ? '' : '（不完整）') + '</option>';
      });
      h += '</select>';
    } else if (it.t === 'num') {
      h += '<input type="number" id="' + id + '" value="' + esc(val) + '"' +
        (it.min != null ? ' min="' + it.min + '"' : '') +
        (it.max != null ? ' max="' + it.max + '"' : '') +
        (it.step != null ? ' step="' + it.step + '"' : '') + '>';
    } else {
      h += '<input type="text" id="' + id + '" value="' + esc(val) + '">';
    }
    if (it.tip) h += '<span class="tip">' + esc(it.tip) + '</span>';
    return h + '</div>';
  }

  function renderForm(settings) {
    var host = $('#as-groups');
    if (!host) return;
    var html = '';
    SETTINGS_SPEC.forEach(function (g) {
      html += '<div class="as-group"><h3>' + esc(g.title) + '</h3>';
      if (g.hint) html += '<p class="hint">' + esc(g.hint) + '</p>';
      html += '<div class="as-fields">';
      g.items.forEach(function (it) {
        html += fieldHTML(it, settings[it.k] == null ? '' : settings[it.k]);
      });
      html += '</div></div>';
    });
    host.innerHTML = html;
  }

  function collectForm() {
    var out = {};
    SETTINGS_SPEC.forEach(function (g) {
      g.items.forEach(function (it) {
        var el = $('#f-' + it.k);
        if (!el) return;
        if (it.t === 'bool') out[it.k] = el.checked ? '1' : '0';
        else out[it.k] = el.value;
      });
    });
    return out;
  }

  /* =================== 状态渲染 =================== */
  var lastStage = '';
  var lastStreamKey = '';

  function renderStatus(st) {
    badge($('#as-enable-badge'), st.enabled ? '已启用' : '未启用', st.enabled ? 'ok' : '');
    badge($('#as-mic-badge'), st.mic_running ? '采集运行' : '采集停止',
      st.mic_running ? 'ok' : 'bad');
    badge($('#as-busy-badge'), 'BUSY ' + (st.busy ? '有效' : '空闲'),
      st.busy ? 'warn' : 'ok');
    badge($('#as-ptt-badge'), 'PTT ' + (st.ptt ? '发射' : '待机'),
      st.ptt ? 'bad' : 'ok');
    var w = st.llm_warm || {};
    badge($('#as-llm-badge'),
      w.ok === true ? 'LLM 就绪' : (w.ok === false ? 'LLM 不可用' : 'LLM 未探测'),
      w.ok === true ? 'ok' : (w.ok === false ? 'bad' : ''));

    var c = st.counters || {};
    var t = st.today || {};
    $('#m-turns').textContent = t.turns || 0;
    $('#m-turns-sub').textContent = '已发射 ' + (t.sent || 0) + ' · 跳过 ' + (t.skipped || 0) +
      ' · 截断 ' + (t.truncated || 0);
    $('#m-txsec').innerHTML = (Math.round(t.tx_seconds || 0)) +
      '<small style="font-size:14px;color:var(--muted)"> s</small>';
    $('#m-txsec-sub').textContent = '平均 LLM ' + Math.round(t.avg_llm || 0) + ' ms · ASR ' +
      Math.round(t.avg_asr || 0) + ' ms';
    $('#m-wake').textContent = (c.wakes || 0) + ' / ' + (c.ignored || 0);
    $('#m-wake-sub').textContent = '过短丢弃 ' + (c.asr_empty || 0) + ' · 分段 ' + (c.segments || 0);
    var fu = Number(st.follow_up_left || 0);
    $('#m-follow').textContent = fu > 0 ? (fu.toFixed(0) + ' s') : '关';
    $('#m-follow-sub').textContent = fu > 0 ? '现在可直接追问' : '需重新喊唤醒词';

    // 状态机
    var dot = $('#as-dot');
    if (dot) dot.className = 'as-stage-dot ' + (st.stage || 'off');
    $('#as-stage-name').textContent = st.stage_label || st.stage || '—';
    $('#as-stage-detail').textContent = st.stage_detail || '—';
    $('#as-stage-elapsed').textContent = (st.stage_seconds != null ? st.stage_seconds + ' s' : '—');
    $('#as-queue').textContent = '队列 ' + (st.queue || 0);
    lastStage = st.stage;

    $('#as-words').textContent = (st.wake_words || []).join(' / ') || '（未设置）';
    $('#as-fuzzy').textContent = st.fuzzy ? '开' : '关';

    // 电平
    $('#as-dbfs').textContent = (st.dbfs != null ? st.dbfs : -120) + ' dBFS';
    drawWave(st.levels || [], st.settings || {});

    // 实况识别流
    var rows = st.recent || [];
    var key = rows.length + '|' + (rows.length ? (rows[rows.length - 1].ts + rows[rows.length - 1].heard) : '');
    if (key !== lastStreamKey) {
      lastStreamKey = key;
      var box = $('#as-stream');
      if (!rows.length) {
        box.innerHTML = '<div class="as-empty">等待语音…</div>';
      } else {
        var html = '';
        rows.slice().reverse().forEach(function (r) {
          var cls = 'as-line', tag = '忽略', tagCls = '';
          if (r.wake && (r.action === 'answer' || r.action === 'ack')) {
            cls += ' hit'; tag = r.wake; tagCls = 'wake';
          } else if (r.action === 'followup') {
            cls += ' hit'; tag = '追问'; tagCls = 'follow';
          } else if (r.action === 'error') {
            cls += ' err'; tag = '错误'; tagCls = 'err';
          } else if (r.action === 'empty') {
            tag = '无语音'; tagCls = 'empty';
          } else if (r.action === 'ignored') {
            cls += ' ign'; tag = '忽略';
          } else if (r.action === 'duplicate') {
            cls += ' ign'; tag = '重复';
          } else if (r.action === 'silent') {
            cls += ' ign'; tag = '自主·默';
          } else if (r.action === 'shadow') {
            cls += ' auto'; tag = '自主·本应答';
          }
          var extra = '';
          if (r.auto) {
            var a = r.auto;
            extra = '<span class="as-auto ' + (a.would_reply ? 'yes' : 'no') + '" title="' +
              esc('判定：' + (a.decision === 'answer' ? '答' : '默') +
                  '　结论：' + (a.gate_label || a.reason) +
                  '　置信：' + (a.confidence == null ? '-' : a.confidence) +
                  '　模型理由码：' + (a.model_reason || '-') +
                  '　决策耗时：' + (a.ms || 0) + 'ms' +
                  (a.parse_ok ? '' : '　（四行格式未解析出 → 按默处理）') +
                  (a.error ? '　错误：' + a.error : '') +
                  (a.think ? '\n想：' + a.think : '')) + '">' +
              esc((a.would_reply ? '应答' : '默') + '·' + (a.gate_label || a.reason)) +
              (a.think ? '<i> 想：' + esc(a.think) + '</i>' : '') + '</span>';
          }
          html += '<div class="' + cls + '"><span class="t">' + esc(r.ts) + '</span>' +
            '<span class="as-tag ' + tagCls + '">' + esc(tag) + '</span>' +
            '<span class="x">' + (r.heard ? esc(r.heard) : '<span class="muted">（空）</span>') +
            '</span>' + extra + '<span class="t">' + (r.seconds != null ? r.seconds + 's' : '') +
            (r.asr_ms ? ' / ' + r.asr_ms + 'ms' : '') + '</span>' +
            (r.error ? '<span class="x muted">' + esc(r.error) + '</span>' : '') + '</div>';
        });
        box.innerHTML = html;
      }
    }

    renderCounters(st);
  }

  var waveOpen = -40;

  function drawWave(levels, settings) {
    var cv = $('#as-wave');
    if (!cv) return;
    waveOpen = Number(settings.assist_dbfs_open || -40);
    var ctx = cv.getContext('2d');
    var W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0d1524';
    ctx.fillRect(0, 0, W, H);

    var lo = -80, hi = 0;
    function y(db) {
      var v = (db - lo) / (hi - lo);
      v = Math.max(0, Math.min(1, v));
      return H - v * H;
    }
    // 起判门限参考线
    ctx.strokeStyle = 'rgba(234,179,8,.55)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, y(waveOpen)); ctx.lineTo(W, y(waveOpen)); ctx.stroke();
    ctx.setLineDash([]);
    // -40 / -60 / -20 刻度线
    ctx.strokeStyle = 'rgba(38,51,77,.9)';
    [-20, -40, -60].forEach(function (db) {
      ctx.beginPath(); ctx.moveTo(0, y(db)); ctx.lineTo(W, y(db)); ctx.stroke();
    });

    if (!levels.length) return;
    var n = levels.length;
    var step = W / Math.max(n, 1);
    var grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, 'rgba(239,68,68,.55)');
    grad.addColorStop(0.5, 'rgba(59,130,246,.55)');
    grad.addColorStop(1, 'rgba(34,197,94,.35)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(0, H);
    for (var i = 0; i < n; i++) {
      ctx.lineTo(i * step, y(levels[i][1]));
    }
    ctx.lineTo((n - 1) * step, H);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = 'rgba(147,197,253,.9)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var j = 0; j < n; j++) {
      var px = j * step, py = y(levels[j][1]);
      if (j === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  function renderCounters(st) {
    var c = st.counters || {};
    var items = [
      ['分段总数', c.segments, '有足够有声时长的语音段'],
      ['唤醒命中', c.wakes, '含同音容错'],
      ['未命中忽略', c.ignored, '排除在追问窗口之外的'],
      ['无有效语音', c.asr_empty, 'ASR 返回空'],
      ['完成轮次', c.turns, '含应答与失败'],
      ['成功发射', c.tx, '实际占用信道'],
      ['累计发射', fmtDur(c.tx_seconds), '信道占用总时长'],
      ['信道忙放弃', c.busy_defers, 'BUSY 一直有效'],
      ['间隔不足放弃', c.gap_waits, '距上次发射太近'],
      ['回复被截断', c.truncated, '超过字数上限'],
      ['手动停止', c.aborted, '含禁发时段拦截'],
      ['异常', c.errors, '识别/LLM/合成/发射'],
      ['自主·送模型判定', c.auto_decided, '预筛通过、真的叫了决策模型'],
      ['自主·预筛跳过', c.auto_skipped, '太短/数据音/与自己刚说的雷同'],
      ['自主·判答', c.auto_answered, '模型判「这段该答」'],
      ['自主·判默', c.auto_silent, '模型判默或格式解析失败'],
      ['自主·格式解析失败', c.auto_parse_fail, 'fail-closed：一律按默处理'],
      ['自主·被闸门拦下', c.auto_shadow_blocked, '影子期=本应发射的次数'],
      ['自主·频率超限', c.auto_rate_limited, '本小时已达上限'],
      ['自主·同呼号冷却', c.auto_cooldown, '刚答过这个人'],
      ['自主·间隔不足', c.auto_gap_blocked, '距上次主动回答太近'],
      ['自主·白名单外', c.auto_whitelist_blocked, '呼号不在白名单'],
      ['自主·回声跳过', c.auto_echo_skipped, '自己刚发射的内容又被收进来']
    ];
    $('#as-counters').innerHTML = items.map(function (x) {
      return '<div class="cell"><div class="k">' + x[0] + '</div><div class="v">' +
        (x[1] == null ? 0 : x[1]) + '</div><div class="s">' + x[2] + '</div></div>';
    }).join('');

    var t = st.today || {};
    var au = st.auto || {};
    var stat = [
      ['今日轮次', t.turns || 0, ''],
      ['今日发射', t.sent || 0, '成功占用信道次数'],
      ['今日跳过', t.skipped || 0, '信道忙/间隔不足/测试模式'],
      ['今日截断', t.truncated || 0, '超过回复字数上限'],
      ['今日信道占用', Math.round(t.tx_seconds || 0) + ' s', '发射总时长'],
      ['平均 LLM 耗时', Math.round(t.avg_llm || 0) + ' ms', ''],
      ['平均 ASR 耗时', Math.round(t.avg_asr || 0) + ' ms', ''],
      ['运行时长', fmtDur(st.uptime || 0), '服务启动至今'],
      ['自主模式', au.mode_label || '—', '当前只开放影子模式：只记录不发射'],
      ['本小时已主动答', (au.used_last_hour == null ? 0 : au.used_last_hour) +
        ' / ' + (au.max_per_hour == null ? '-' : au.max_per_hour), '实际发射计数；影子期恒为 0'],
      ['距上次主动答', au.last_auto_ago == null || au.last_auto_ago < 0
        ? '—' : fmtDur(au.last_auto_ago) + '前', ''],
      ['影子试答', au.dry_running ? '进行中' : '空闲',
        au.dry_answer ? '会同时生成「本来会说的那句话」（不发射）' : '已关闭']
    ];
    $('#as-stat').innerHTML = stat.map(function (x) {
      return '<div class="cell"><div class="k">' + x[0] + '</div><div class="v">' + x[1] +
        '</div><div class="s">' + x[2] + '</div></div>';
    }).join('');
    if (st.last_error) {
      $('#as-stat').insertAdjacentHTML('afterbegin',
        '<div class="cell" style="grid-column:1/-1;border-color:var(--red)">' +
        '<div class="k">最近错误</div><div class="s">' + esc(st.last_error) + '</div></div>');
    }
  }

  /* =================== 对话记录 =================== */
  function renderTurns(data) {
    var box = $('#as-turns');
    var items = data.items || [];
    $('#as-turn-count').textContent = '（' + (data.day || '') + '，' + items.length + ' 条）';
    if (!items.length) {
      box.innerHTML = '<div class="as-empty">暂无记录</div>';
      return;
    }
    box.innerHTML = items.map(function (r) {
      var pills = '<span class="as-pill ' + esc(r.action) + '">' + esc(r.action) + '</span>';
      if (r.kind && r.kind !== 'wake') pills += '<span class="as-pill">' + esc(r.kind) + '</span>';
      if (r.truncated) pills += '<span class="as-pill skipped">已截断</span>';
      if (r.dry) {
        pills += '<span class="as-pill skipped" title="影子记录：这一行没有发射动作">' +
          (r.would_reply ? '本应发射·未发射' : '未发射') + '</span>';
      }
      var foot = [];
      if (r.wake) foot.push('唤醒:' + esc(r.wake));
      if (r.decision) {
        foot.push('自主:' + (r.decision === 'answer' ? '答' : '默') +
          (r.reason ? '(' + esc(r.reason) + ')' : '') +
          (r.confidence ? ' 信' + r.confidence : ''));
      }
      if (r.callsigns) foot.push('呼号 ' + esc(r.callsigns));
      if (r.tx_seconds) foot.push('发射 ' + Number(r.tx_seconds).toFixed(1) + 's');
      if (r.wait_s) foot.push('等待 ' + Number(r.wait_s).toFixed(1) + 's');
      if (r.asr_ms) foot.push('ASR ' + r.asr_ms + 'ms');
      if (r.llm_ms) foot.push('LLM ' + r.llm_ms + 'ms');
      if (r.tts_ms) foot.push('TTS ' + r.tts_ms + 'ms');
      if (r.iters) foot.push('轮次 ' + r.iters);
      if (r.tools) foot.push('工具 ' + esc(r.tools));
      if (r.prompt_chars) foot.push('输入 ' + r.prompt_chars + '字');
      if (r.reply_chars) foot.push('回复 ' + r.reply_chars + '字');
      var aud = '';
      if (r.rx_wav) aud += '<button class="btn ghost" data-audio="' + r.id + '" data-which="rx">听对方</button>';
      if (r.tx_wav) aud += '<button class="btn ghost" data-audio="' + r.id + '" data-which="tx">听助手</button>';
      return '<div class="as-turn">' +
        '<div class="as-turn-head"><span class="id">#' + r.id + '</span>' +
        '<span>' + esc(r.ts) + '</span>' + pills + '</div>' +
        '<div class="as-msg"><span class="who">对方</span><span class="txt">' +
        (r.heard ? esc(r.heard) : '<span class="muted">（无）</span>') + '</span></div>' +
        '<div class="as-msg reply"><span class="who">助手</span><span class="txt">' +
        (r.reply ? esc(r.reply) : '<span class="muted">（无）</span>') + '</span></div>' +
        (r.think ? '<div class="as-msg"><span class="who">想</span><span class="txt muted">' +
          esc(r.think) + '</span></div>' : '') +
        (r.error ? '<div class="as-msg"><span class="who">错误</span><span class="txt muted">' +
          esc(r.error) + '</span></div>' : '') +
        '<div class="as-turn-foot"><span>' + foot.join(' · ') + '</span>' +
        '<span style="margin-left:auto"></span>' + aud + '</div></div>';
    }).join('');
  }

  function loadTurns() {
    return api('/api/assist/list?limit=80').then(function (d) {
      if (!d.ok) { toast(d.error || '记录加载失败'); return; }
      renderTurns(d);
    });
  }

  /* =================== 轮询 =================== */
  var pollTimer = null;
  function poll() {
    api('/api/assist/status').then(function (d) {
      if (!d.ok) return;
      renderStatus(d);
    }).catch(function () { /* 轮询失败静默，下一轮再试 */ });
  }

  function bindTabs() {
    $$('.as-tabs .tab-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        $$('.as-tabs .tab-btn').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        var t = b.getAttribute('data-atab');
        $$('.as-pane').forEach(function (p) {
          p.classList.toggle('active', p.getAttribute('data-apane') === t);
        });
      });
    });
  }

  /* =================== 启动 =================== */
  function init() {
    bindTabs();

    api('/api/tts/voices').then(function (d) {
      voiceList = (d && d.voices) || [];
      return api('/api/assist/status');
    }).then(function (d) {
      if (d && d.ok) {
        renderForm(d.settings || {});
        renderStatus(d);
      }
    }).catch(function () {
      api('/api/assist/status').then(function (d) {
        if (d && d.ok) { renderForm(d.settings || {}); renderStatus(d); }
      });
    });

    loadTurns();
    // 不重叠轮询：上一次返回之后才排下一次（见 static/js/poll.js）
    pollTimer = ELF2Poll.loop(poll, 1500, { immediate: true });
    ELF2Poll.loop(loadTurns, 15000);

    $('#btn-as-refresh').addEventListener('click', function () {
      poll(); loadTurns(); toast('已刷新');
    });

    $('#btn-as-list-refresh').addEventListener('click', function () { loadTurns(); });

    $('#btn-as-stop').addEventListener('click', function () {
      api('/api/assist/stop', { method: 'POST', body: '{}' }).then(function (d) {
        toast(d.ok ? ('已停止，清空 ' + (d.cleared || 0) + ' 条待处理语音') : (d.error || '停止失败'));
        poll();
      });
    });

    $('#btn-as-reload').addEventListener('click', function () {
      api('/api/assist/status').then(function (d) {
        if (d.ok) { renderForm(d.settings || {}); toast('已还原为当前生效值'); }
      });
    });

    $('#as-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var btn = e.target.querySelector('button[type=submit]');
      btn.disabled = true;
      $('#as-save-state').textContent = '保存中…';
      api('/api/settings', { method: 'POST', body: JSON.stringify(collectForm()) })
        .then(function (d) {
          btn.disabled = false;
          if (d.ok) {
            var n = Object.keys(d.changed || {}).length;
            $('#as-save-state').textContent = '已保存 ' + n + ' 项，' + new Date().toLocaleTimeString();
            toast('设置已保存（' + n + ' 项），即时生效');
            poll();
          } else {
            $('#as-save-state').textContent = '';
            toast(d.error || '保存失败');
          }
        }).catch(function () {
          btn.disabled = false;
          $('#as-save-state').textContent = '';
          toast('保存请求失败');
        });
    });

    // 手动测试
    $('#btn-as-test').addEventListener('click', function () {
      var text = $('#as-test-text').value.trim();
      if (!text) { toast('请输入测试问题'); return; }
      var tx = !!($('#as-test-tx') && $('#as-test-tx').checked);
      if (tx && !confirm('会真的发射到无线电（占用信道，其他台能听到）。确定继续？')) return;
      this.disabled = true;
      var btn = this;
      toast(tx ? '已提交：生成后走受控发射（会占用信道）' : '已提交，结果稍后出现在右侧「对话记录」');
      api('/api/assist/test', { method: 'POST', body: JSON.stringify({ text: text, tx: tx }) })
        .then(function (d) {
          btn.disabled = false;
          if (!d.ok) toast(d.error || '提交失败');
          else if (d.test_mode && tx) toast('全局「测试模式」开着：本次仍然只合成不发射');
          else if (d.test_mode) toast('测试模式：只合成不发射');
          setTimeout(function () { poll(); loadTurns(); }, 800);
          setTimeout(loadTurns, 4000);
          setTimeout(loadTurns, 9000);
        }).catch(function () { btn.disabled = false; toast('请求失败'); });
    });

    $('#btn-as-test-wake').addEventListener('click', function () {
      var text = $('#as-test-text').value.trim();
      var busyEl = $('#as-test-busy');
      var body = { text: text };
      if (busyEl) body.busy = !!busyEl.checked;
      api('/api/assist/wake', { method: 'POST', body: JSON.stringify(body) })
        .then(function (d) {
          $('#as-wake-out').textContent = d.ok ? JSON.stringify(d, null, 2) : (d.error || '失败');
          if (d.ok) {
            if (d.matched && d.would_wake === false) {
              toast('命中「' + d.matched + '」但 ' + (d.reason || '被唤醒方式拦下'));
            } else {
              toast(d.matched ? ('命中「' + d.matched + '」，问题：' + (d.question || '（空）'))
                : (d.near ? ('未命中；最接近「' + d.near + '」相似度 ' + d.near_ratio)
                          : '未命中任何唤醒词'));
            }
          }
        });
    });

    // 只发射这段文本（不过 LLM）：合成 → 受控发射
    $('#btn-as-say').addEventListener('click', function () {
      var text = $('#as-test-text').value.trim();
      if (!text) { toast('请输入要发射的文本'); return; }
      var tx = !!($('#as-say-tx') && $('#as-say-tx').checked);
      if (tx && !confirm('会真的发射到无线电（占用信道，其他台能听到）。确定继续？')) return;
      this.disabled = true;
      var btn = this;
      api('/api/assist/say', { method: 'POST', body: JSON.stringify({ text: text, tx: tx }) })
        .then(function (d) {
          btn.disabled = false;
          if (!d.ok) toast(d.error || '提交失败');
          else if (d.test_mode && tx) toast('全局「测试模式」开着：本次仍然只合成不发射');
          else toast(tx ? '已提交发射（受控：禁发时段/信道占用/间隔/上限都生效）' : '已提交试听');
          setTimeout(function () { poll(); loadTurns(); }, 800);
          setTimeout(loadTurns, 4000);
        }).catch(function () { btn.disabled = false; toast('请求失败'); });
    });

    // 自主决策自测：给一句话，看决策层与闸门怎么判（不发射）
    $('#btn-as-auto-test').addEventListener('click', function () {
      var text = ($('#as-auto-text').value || '').trim();
      if (!text) { toast('请输入要判定的语音内容'); return; }
      var btn = this;
      var body = {
        text: text,
        busy: !!($('#as-auto-busy') && $('#as-auto-busy').checked),
        store: !!($('#as-auto-store') && $('#as-auto-store').checked)
      };
      btn.disabled = true;
      $('#as-auto-state').textContent = '判定中…（要叫一次决策模型，板端约几秒）';
      api('/api/assist/auto/test', { method: 'POST', body: JSON.stringify(body) })
        .then(function (d) {
          btn.disabled = false;
          if (!d.ok && !d.decision) {
            $('#as-auto-state').textContent = d.error || '失败';
            $('#as-auto-out').textContent = d.error || '失败';
            return;
          }
          var verdict = d.decision === 'answer' ? '判：答' : '判：默';
          var concl = d.would_reply ? '本应发射（影子模式：未发射）'
            : ('不发射 · ' + (d.gate_label || d.gate));
          $('#as-auto-state').textContent = verdict + ' · ' + concl + ' · ' +
            (d.ms || 0) + 'ms';
          var lines = [
            '预筛：' + (d.prefilter === 'pass' ? '通过（值得叫模型）' : ('直接跳过（' + d.prefilter + '）')),
            '是否在叫我们：' + (d.called ? '是' : '否') +
              (d.callsigns && d.callsigns.length ? '　呼号：' + d.callsigns.join(',') : ''),
            '模型四行原文：',
            (d.raw || '（无输出）'),
            '',
            '解析：' + (d.parse_ok ? '成功' : '失败 → fail-closed 按默处理') +
              '　判定=' + d.decision + '　模型理由码=' + d.reason +
              '　置信=' + d.confidence,
            '闸门结论：' + (d.gate || '-') + '（' + (d.gate_label || '') + '）' +
              (d.gate_note ? '　' + d.gate_note : ''),
            '本应发射：' + (d.would_reply ? '是（影子期不发射）' : '否'),
            '想（不会朗读）：' + (d.think || '（无）'),
            '自述：已答过的内容=' + JSON.stringify(d.own || []) +
              '　设置上限=' + JSON.stringify(d.limits || {}),
            '通道：' + (d.provider || '-') + ' / ' + (d.model || '-') +
              '　耗时=' + (d.ms || 0) + 'ms' +
              (d.error ? '　错误：' + d.error : ''),
            '提示词字数：' + (d.prompt_chars || 0)
          ];
          $('#as-auto-out').textContent = lines.join('\n');
          if (body.store) setTimeout(loadTurns, 600);
        }).catch(function () {
          btn.disabled = false;
          $('#as-auto-state').textContent = '请求失败';
        });
    });

    $$('[data-fill]').forEach(function (b) {
      b.addEventListener('click', function () {
        $('#as-test-text').value = b.getAttribute('data-fill');
      });
    });

    $$('[data-afill]').forEach(function (b) {
      b.addEventListener('click', function () {
        $('#as-auto-text').value = b.getAttribute('data-afill');
      });
    });

    // 提示词预览
    function loadPrompt() {
      var q = $('#as-prompt-q').value || '';
      $('#as-prompt-state').textContent = '生成中…';
      api('/api/assist/prompt?q=' + encodeURIComponent(q)).then(function (d) {
        if (!d.ok) { $('#as-prompt-state').textContent = d.error || '失败'; return; }
        $('#as-prompt-out').textContent = d.prompt;
        $('#pk-chars').textContent = d.prompt_chars;
        $('#pk-maxin').textContent = d.max_input;
        $('#pk-maxreply').textContent = d.max_reply;
        $('#pk-maxtok').textContent = d.max_tokens;
        $('#pk-hist').textContent = d.history_turns;
        $('#as-prompt-state').textContent = '';
      });
    }
    $('#btn-as-prompt').addEventListener('click', loadPrompt);

    function loadClean() {
      var t = $('#as-clean-in').value;
      api('/api/assist/clean', { method: 'POST', body: JSON.stringify({ text: t }) })
        .then(function (d) {
          if (!d.ok) { $('#as-clean-state').textContent = d.error || '失败'; return; }
          $('#as-clean-out').textContent = d.cleaned || '（清洗后为空，不会朗读）';
          $('#as-clean-state').textContent = d.raw_len + ' 字 → ' + d.cleaned_len + ' 字';
        });
    }
    $('#btn-as-clean').addEventListener('click', loadClean);
    loadClean();

    // 试听助手音频
    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-audio]');
      if (!b) return;
      var rid = b.getAttribute('data-audio');
      var which = b.getAttribute('data-which');
      new Audio('/api/assist/' + rid + '/audio?which=' + which).play()
        .catch(function () { toast('音频播放失败或不存在'); });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
