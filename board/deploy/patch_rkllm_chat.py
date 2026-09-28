# -*- coding: utf-8 -*-
"""修补板端 rkllm-server 的对话包装层：system 槽位 / 完整多轮 / 规范模板 / 生成长度 / 超限报错 / 流式锁。

背景（全部为板端实测，直接 HTTP 打 8001）：
  1. 请求里的 system 角色**被丢弃**——带与不带 system 两次回答逐字相同；要求回答
     含标记词也不出现。根因在源码：只取最后一条非空消息。
  2. 多轮 messages 同样被丢弃——问「刚才那个数字」，答不出来。
  3. 每条请求都被硬塞一句写死的英文 system（旧 PROMPT_TEXT_PREFIX）。
  4. max_new_tokens 写死 -1，且请求的 max_tokens 完全被忽略（请求 10，实际输出 171 字）。
  5. 提示词超限时**静默返回空串**：HTTP 200 + content='' + 0.2~0.3s，调用方零信号。
  6. 模板用空格而非换行拼接，偏离 Qwen2.5 规范 ChatML。
  7. 流式分支在 `return Response()` 时就执行了 finally，生成器还没开跑锁就放掉，
     并发下 global_text/global_state 会串台。

用法：
    python3 patch_rkllm_chat.py --dry-run     # 只看会改什么
    python3 patch_rkllm_chat.py               # 落盘（自动备份）

幂等：文件里出现 ELF2_CHAT_PATCH 就跳过。回滚：把 .bak_pre_chatfix 拷回去重启服务。
"""
import argparse
import shutil
import sys
from pathlib import Path

P = Path('/opt/ai/rkllm-server/flask_server.py')
BAK_SUFFIX = '.bak_pre_chatfix'
MARK = 'ELF2_CHAT_PATCH'

# --- 1. 常量与模板：换成规范 ChatML + 真正的 system 槽位 --------------------
OLD1 = '''PROMPT_TEXT_PREFIX = "<|im_start|>system You are a helpful assistant. <|im_end|> <|im_start|>user"
PROMPT_TEXT_POSTFIX = "<|im_end|><|im_start|>assistant"'''

NEW1 = '''# --- ELF2_CHAT_PATCH: 规范 Qwen2.5 ChatML + 真正的 system 槽位 -------------
# 原来只有下面两个常量，并在 run() 里硬拼：
#     PROMPT_TEXT_PREFIX + prompt + PROMPT_TEXT_POSTFIX
# 后果：system 永远是写死的英文；请求里除最后一条以外的消息（含 system 与多轮
# 历史）全被丢掉；模板用空格而非换行。改成下面这个渲染函数。
PROMPT_TEXT_PREFIX = "<|im_start|>system You are a helpful assistant. <|im_end|> <|im_start|>user"
PROMPT_TEXT_POSTFIX = "<|im_end|><|im_start|>assistant"
IM_START = '<|im_start|>'
IM_END = '<|im_end|>'
ELF2_CHAT_PATCH = True
DEFAULT_SYSTEM = os.environ.get('RKLLM_DEFAULT_SYSTEM') or 'You are a helpful assistant.'

# 超限判定用的粗略 token 估算：CJK/全角按 1 token/字，其余按 4 字符/token。
# 只求保守，不求精确——目的是把「静默空串」变成明确报错。
def _est_tokens(s):
    s = s or ''
    cjk = 0
    for ch in s:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:
            cjk += 1
    return cjk + (len(s) - cjk) // 4 + 8


def build_prompt(messages, fallback=''):
    """OpenAI 风格 messages -> Qwen2.5 ChatML 全文（以 assistant 起始标记结尾）。

    system 单独成一个槽位（多条则按序拼接；一条都没有时用 DEFAULT_SYSTEM），
    其余 user/assistant 按顺序原样渲染成多轮。
    """
    msgs = [m for m in (messages or [])
            if isinstance(m, dict) and str(m.get('content') or '').strip()]
    sys_parts = [str(m.get('content')).strip() for m in msgs
                 if str(m.get('role') or '').lower() == 'system']
    turns = [m for m in msgs
             if str(m.get('role') or '').lower() != 'system']
    if not turns and fallback:
        turns = [{'role': 'user', 'content': fallback}]
    out = [IM_START + 'system\\n' + ('\\n'.join(sys_parts) or DEFAULT_SYSTEM)
           + IM_END + '\\n']
    for m in turns:
        role = 'assistant' if str(m.get('role') or '').lower() == 'assistant' else 'user'
        out.append(IM_START + role + '\\n' + str(m.get('content')).strip()
                   + IM_END + '\\n')
    out.append(IM_START + 'assistant\\n')
    return ''.join(out)'''

# --- 2. 生成长度：从写死 -1 改成环境变量可配 --------------------------------
OLD2 = '        rkllm_param.max_new_tokens = -1'
NEW2 = ('        # ELF2_CHAT_PATCH: 原来写死 -1（不设上限），生成会一路吃到上下文尽头，\n'
        '        # 而请求里的 max_tokens 又完全不被采纳，等于没法约束延时。\n'
        '        rkllm_param.max_new_tokens = int(os.environ.get("RKLLM_MAX_NEW_TOKENS", "512"))')

# --- 3. run() 不再自己拼前缀后缀（调用方给完整 ChatML） ---------------------
OLD3 = ("        rkllm_input.input_data.prompt_input = "
        "ctypes.c_char_p((PROMPT_TEXT_PREFIX + prompt + PROMPT_TEXT_POSTFIX).encode('utf-8'))")
NEW3 = ("        # ELF2_CHAT_PATCH: prompt 已是完整 ChatML（见 build_prompt），不再拼前后缀\n"
        "        rkllm_input.input_data.prompt_input = ctypes.c_char_p(prompt.encode('utf-8'))")

# --- 4. 消息解析：丢掉旧的「只取最后一条」，改渲染完整对话 + 超限报错 -------
OLD4 = '''            input_prompt = None
            if 'messages' in data:
                messages = data.get('messages') or []
                # 取最后一条非空消息作为当前输入，避免把完整历史重复送入
                for m in reversed(messages):
                    if isinstance(m, dict) and m.get('content'):
                        input_prompt = str(m.get('content'))
                        break
                if input_prompt is None and messages:
                    input_prompt = str(messages[-1].get('content', ''))
            elif 'prompt' in data:
                input_prompt = str(data.get('prompt') or '')
            else:
                return jsonify({'status': 'error', 'message': 'Invalid JSON data! Need messages or prompt.'}), 400

            if not input_prompt:
                return jsonify({'status': 'error', 'message': 'Empty prompt!'}), 400
'''

NEW4 = '''            # ELF2_CHAT_PATCH: 渲染完整对话（含 system 槽位与多轮历史），并在
            # 提交前做长度检查——原来超限是静默返回空串，调用方拿不到任何信号。
            if 'messages' in data:
                raw_msgs = data.get('messages') or []
                input_prompt = build_prompt(raw_msgs)
                if not any(str(m.get('content') or '').strip()
                           for m in raw_msgs if isinstance(m, dict)):
                    return jsonify({'status': 'error', 'message': 'Empty prompt!'}), 400
            elif 'prompt' in data:
                raw = str(data.get('prompt') or '')
                if not raw:
                    return jsonify({'status': 'error', 'message': 'Empty prompt!'}), 400
                input_prompt = build_prompt([{'role': 'user', 'content': raw}])
            else:
                return jsonify({'status': 'error', 'message': 'Invalid JSON data! Need messages or prompt.'}), 400

            max_ctx = int(os.environ.get('RKLLM_MAX_CONTEXT', '4096'))
            max_new_cfg = int(os.environ.get('RKLLM_MAX_NEW_TOKENS', '512'))
            try:
                want_new = int(data.get('max_tokens') or max_new_cfg)
            except Exception:
                want_new = max_new_cfg
            # 运行时按 max_new_cfg 截断，所以余量只按实际生效的那个算
            reserve = max(16, min(want_new, max_new_cfg))
            est = _est_tokens(input_prompt)
            if est + reserve > max_ctx:
                msg = ('prompt too long: est %d tokens + reserve %d > max_context_len %d'
                       % (est, reserve, max_ctx))
                print('ELF2_CHAT_PATCH reject:', msg)
                sys.stdout.flush()
                return jsonify({'status': 'error', 'message': msg,
                                'est_prompt_tokens': est,
                                'max_context_len': max_ctx}), 400
'''

# --- 5. 流式锁：交给生成器持有 ----------------------------------------------
OLD5 = '''        lock.acquire()
        try:
            is_blocking = True'''
NEW5 = '''        lock.acquire()
        # ELF2_CHAT_PATCH: 流式分支要把锁交给生成器持有。原来 finally 在
        # `return Response()` 那一刻就执行了——生成器还没开始跑锁就放掉，
        # 并发请求会串台 global_text / global_state。
        handed_off = False
        try:
            is_blocking = True'''

OLD6 = '''            def generate():
                model_thread = threading.Thread(target=rkllm_model.run, args=(input_prompt,))
                model_thread.start()
                try:'''
NEW6 = '''            handed_off = True

            def generate():
                global is_blocking
                model_thread = threading.Thread(target=rkllm_model.run, args=(input_prompt,))
                model_thread.start()
                try:'''

OLD7 = '''                finally:
                    pass

            return Response(generate(), mimetype='text/event-stream', headers={'''
NEW7 = '''                finally:
                    is_blocking = False
                    lock.release()

            return Response(generate(), mimetype='text/event-stream', headers={'''

OLD8 = '''        finally:
            lock.release()
            is_blocking = False'''
NEW8 = '''        finally:
            if not handed_off:
                lock.release()
                is_blocking = False'''

EDITS = [('常量与模板', OLD1, NEW1), ('生成长度', OLD2, NEW2),
         ('run 拼装', OLD3, NEW3), ('消息解析与超限', OLD4, NEW4),
         ('流式锁-接管标记', OLD5, NEW5), ('流式锁-生成器', OLD6, NEW6),
         ('流式锁-释放', OLD7, NEW7), ('流式锁-外层', OLD8, NEW8)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--path', default=str(P))
    args = ap.parse_args()

    path = Path(args.path)
    if not path.exists():
        print('NOT_FOUND %s' % path)
        return 1
    # 备份必须跟着 --path 走：写死板端绝对路径的话，本地拿副本试跑会直接炸，
    # 而且炸在写盘之前，看起来像「补丁没生效」。
    bak = path.parent / (path.name + BAK_SUFFIX)
    src = path.read_text(encoding='utf-8')

    if MARK in src:
        print('ALREADY_PATCHED')
        return 0

    # 先全部校验锚点，一个不对就整体不落笔——半途而废的补丁最难查
    problems = []
    for name, old, _new in EDITS:
        n = src.count(old)
        if n != 1:
            problems.append('%s: 锚点命中 %d 次（应为 1）' % (name, n))
    if problems:
        print('ANCHOR_PROBLEM')
        for p in problems:
            print('  - %s' % p)
        return 1

    out = src
    for _name, old, new in EDITS:
        out = out.replace(old, new, 1)

    if args.dry_run:
        print('DRY_RUN: %d 处将修改，%d -> %d 字节'
              % (len(EDITS), len(src.encode('utf-8')), len(out.encode('utf-8'))))
        return 0

    if not bak.exists():
        shutil.copy2(path, bak)
        print('backup -> %s' % bak)
    path.write_text(out, encoding='utf-8')
    print('PATCHED %d 处 -> %s（%d 字节）' % (len(EDITS), path, len(out.encode('utf-8'))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
