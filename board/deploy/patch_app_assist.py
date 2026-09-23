# -*- coding: utf-8 -*-
"""给 app.py 打补丁：接入中继语音助手。

设计要点：
  * 设置项默认值与键名清单**从 assistant_service.DEFAULTS 生成**，
    不手抄，避免两处漂移（之前 APRS 就吃过手抄不一致的亏）。
  * 路由/助手函数体存在 assist_routes.py，逐字读取后整体插入，
    这样带正则和转义的代码不必再在补丁脚本里写一遍。
  * 每处替换都先断言命中次数，任何一处对不上就整体中止、不写文件。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import assistant_service as A

src = Path('app.py')
s = src.read_text(encoding='utf-8')
routes = Path('assist_routes.py').read_text(encoding='utf-8')
assert 'def _assist_ask(' in routes and '@app.route(\'/assistant\')' in routes

edits = []


def sub1(old, new, tag):
    global s
    n = s.count(old)
    assert n == 1, '[%s] 锚点命中 %d 次（期望 1）' % (tag, n)
    s = s.replace(old, new, 1)
    edits.append(tag)


# --- 1) import -------------------------------------------------------------
sub1("import voice_service\n",
     "import voice_service\nimport assistant_service\n", '1 import')

# --- 2) 实例 ---------------------------------------------------------------
sub1("aprs_service_instance = aprs_service.AprsService(DB_PATH)\n",
     "aprs_service_instance = aprs_service.AprsService(DB_PATH)\n"
     "assistant_service_instance = assistant_service.AssistantService(DB_PATH)\n",
     '2 instance')

# --- 3) DEFAULTS 默认值（由 assistant_service.DEFAULTS 生成）---------------
def _py(v):
    s_ = str(v).replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
    return "'" + s_ + "'"


aligned_wake = [k for k in A.DEFAULTS if k == 'assist_wake_words'][0]
defaults_lines = []
for k, v in A.DEFAULTS.items():
    defaults_lines.append(' ' * 8 + "'%s': %s," % (k, _py(v)))
# 唤醒词默认值随需求定为「智能中继,中继台」
defaults_block = ("        # 中继语音助手（BUSY 语音唤醒 → ASR → LLM → TTS → 受控发射）\n"
                  + '\n'.join(defaults_lines) + '\n')
sub1("        'agent_tools': '',\n",
     "        'agent_tools': '',\n" + defaults_block, '3 defaults')

# --- 4) /api/settings GET 键清单（同样由 DEFAULTS 生成）--------------------
get_keys = '\n'.join("        '%s'," % k for k in A.DEFAULTS)
sub1("        'agent_enabled', 'agent_max_iters', 'agent_tools',\n",
     "        'agent_enabled', 'agent_max_iters', 'agent_tools',\n" + get_keys + '\n',
     '4 GET keys')

# --- 5) /api/settings POST 白名单 ------------------------------------------
casters = """        # 中继语音助手
        'assist_enabled': _bool_caster,
        'assist_use_vad': _bool_caster,
        'assist_wake_fuzzy': _bool_caster,
        'assist_use_tools': _bool_caster,
        'assist_keep_llm_warm': _bool_caster,
        'assist_test_mode': _bool_caster,
        'assist_wake_words': lambda v: ','.join(
            [x.strip() for x in re.split(r'[,;\\u3001\\s]+', str(v)) if x.strip()][:8]
            ) or '\\u667a\\u80fd\\u4e2d\\u7ee7,\\u4e2d\\u7ee7\\u53f0',
        'assist_channel': lambda v: v if v in ('left', 'right', 'mix') else 'left',
        'assist_dbfs_open': lambda v: str(round(max(-80.0, min(-5.0, float(v))), 1)),
        'assist_dbfs_close': lambda v: str(round(max(-85.0, min(-5.0, float(v))), 1)),
        'assist_preroll_ms': lambda v: str(int(max(0, min(3000, int(float(v)))))),
        'assist_silence_ms': lambda v: str(int(max(150, min(5000, int(float(v)))))),
        'assist_min_speech_ms': lambda v: str(int(max(100, min(5000, int(float(v)))))),
        'assist_max_utterance': lambda v: str(round(max(2.0, min(120.0, float(v))), 1)),
        'assist_followup_seconds': lambda v: str(int(max(0, min(600, int(float(v)))))),
        'assist_ack_reply': lambda v: str(v).strip()[:40] or '\\u8bf7\\u8bb2',
        'assist_max_tx_seconds': lambda v: str(int(max(3, min(300, int(float(v)))))),
        'assist_min_gap_seconds': lambda v: str(int(max(0, min(600, int(float(v)))))),
        'assist_busy_wait_seconds': lambda v: str(int(max(1, min(120, int(float(v)))))),
        'assist_tx_guard_ms': lambda v: str(int(max(0, min(5000, int(float(v)))))),
        'assist_quiet_hours': lambda v: str(v).strip()[:80],
        'assist_max_reply_chars': lambda v: str(int(max(10, min(300, int(float(v)))))),
        'assist_max_tokens': lambda v: str(int(max(32, min(512, int(float(v)))))),
        'assist_history_turns': lambda v: str(int(max(0, min(12, int(float(v)))))),
        'assist_max_input_chars': lambda v: str(int(max(400, min(8000, int(float(v)))))),
        'assist_temperature': lambda v: str(round(max(0.0, min(1.5, float(v))), 2)),
        'assist_provider': lambda v: v if v in ('local', 'external') else 'local',
        'assist_agent_iters': lambda v: str(int(max(0, min(4, int(float(v)))))),
        'assist_llm_wait': lambda v: str(int(max(5, min(120, int(float(v)))))),
        'assist_prompt_suffix': lambda v: str(v)[:2000],
        'assist_voice': lambda v: str(v).strip()[:80],
        'assist_retention_days': lambda v: str(int(max(1, min(3650, int(float(v)))))),
"""
a5 = """        'agent_tools': lambda v: ','.join(
            [x.strip() for x in re.split(r'[,;\\s]+', str(v)) if x.strip()][:20]),
"""
assert s.count(a5) == 1, 'POST agent_tools 锚点命中 %d 次' % s.count(a5)
sub1(a5, a5 + casters, '5 POST whitelist')

# --- 6) 设置变更后失效缓存 --------------------------------------------------
sub1("""    try:
        aprs_service_instance.invalidate()
    except Exception:
        pass
    return api_ok(changed=changed)""",
     """    try:
        aprs_service_instance.invalidate()
    except Exception:
        pass
    try:
        assistant_service_instance.invalidate()
    except Exception:
        pass
    return api_ok(changed=changed)""", '6 invalidate')

# --- 7) 采集中枢喂给助手 ----------------------------------------------------
sub1("""            # APRS 常驻解码：挂在同一个采集中枢上（采集设备独占，
            # 不能再开第二路 arecord）。不受 BUSY/分段影响，全程监听。
            try:
                aprs_service_instance.feed(chunk, time.time())
            except Exception:
                pass""",
     """            # APRS 常驻解码：挂在同一个采集中枢上（采集设备独占，
            # 不能再开第二路 arecord）。不受 BUSY/分段影响，全程监听。
            try:
                aprs_service_instance.feed(chunk, time.time())
            except Exception:
                pass
            # 中继语音助手：同样挂在采集中枢上。它自己按能量分段、
            # 自己判发射余波，绝不与语音日志/APRS 抢设备。
            try:
                assistant_service_instance.feed(chunk, time.time())
            except Exception:
                pass""", '7 feed hook')

# --- 8) 采集守护：助手启用时也要保证 arecord 常驻 ---------------------------
sub1("""            if voice_service_instance.enabled():
                with MIC_CAPTURE_LOCK:
                    running = bool(MIC_CAPTURE.get('running'))
                if not running:
                    ok, msg = start_mic_capture()
                    print('[VLOG] 采集中枢拉起：%s / %s' % (ok, msg), flush=True)""",
     """            # 语音日志**或**中继语音助手任一启用，就必须保证 arecord 常驻：
            # 关掉语音日志时助手不能跟着失聪。
            if voice_service_instance.enabled() or assistant_service_instance.enabled():
                with MIC_CAPTURE_LOCK:
                    running = bool(MIC_CAPTURE.get('running'))
                if not running:
                    ok, msg = start_mic_capture()
                    print('[VLOG] 采集中枢拉起：%s / %s' % (ok, msg), flush=True)""",
     '8 capture guard')

# --- 9) 插入助手路由与函数体 ------------------------------------------------
sub1("if __name__ == '__main__':\n",
     routes.rstrip('\n') + "\n\n\nif __name__ == '__main__':\n", '9 routes')

src.write_text(s, encoding='utf-8')
print('app.py 已打补丁：%d 处' % len(edits))
for t in edits:
    print('  ok', t)
print('新大小 %d 字节' % len(s.encode('utf-8')))
