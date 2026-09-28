# -*- coding: utf-8 -*-
"""验证 rkllm-server 补丁产物本身：对话模板与 system 槽位是否真的对。

不跑服务（本地没有 librkllmrt.so 和 NPU），而是用 ast 从**打好补丁的源码**里
取出 build_prompt / _est_tokens 直接调用——测的就是要部署到板端的那份代码，
不是它的副本。

板端用法：
    python3 test_rkllm_patch.py                      # 自动找 /opt/ai/rkllm-server/flask_server.py
    python3 test_rkllm_patch.py --path /path/to.py
本机用法（拿拉回来的副本）：
    python test_rkllm_patch.py --path diag_board/rkllm/flask_server.py
"""
import argparse
import ast
import os
import sys
from pathlib import Path

FAIL, OK = [], [0]
BOARD_P = '/opt/ai/rkllm-server/flask_server.py'
NEED = ('build_prompt', '_est_tokens')
CONSTS = ('IM_START', 'IM_END', 'DEFAULT_SYSTEM')


def check(name, cond, extra=''):
    if cond:
        OK[0] += 1
        print('  OK   %s' % name)
    else:
        FAIL.append(name)
        print('  FAIL %s %s' % (name, extra))


def strip_comments(text):
    """去掉行注释，避免负向断言被补丁自带的说明文字误伤。"""
    return '\n'.join((ln[:ln.find('#')] if ln.find('#') >= 0 else ln)
                     for ln in text.splitlines())


def load(path):
    src = Path(path).read_text(encoding='utf-8')
    tree = ast.parse(src)
    consts = [n for n in tree.body if isinstance(n, ast.Assign)
              and any(getattr(t, 'id', '') in CONSTS for t in n.targets)]
    funcs = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name in NEED]
    got = {f.name for f in funcs}
    if got != set(NEED):
        return None, None, ('补丁未生效：只找到 %s' % sorted(got))
    mod = ast.Module(body=consts + funcs, type_ignores=[])
    ns = {'os': os}
    exec(compile(mod, '<patched flask_server>', 'exec'), ns)
    return ns, src, ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', default=BOARD_P)
    args = ap.parse_args()

    if not Path(args.path).exists():
        print('SKIP: %s 不存在（本机没有板端文件时属正常）' % args.path)
        return 0

    ns, src, err = load(args.path)
    if err:
        print('FAIL %s' % err)
        return 1
    build_prompt, est = ns['build_prompt'], ns['_est_tokens']

    print('=== 1. 补丁已生效 ===')
    code = strip_comments(src)
    check('源码含 ELF2_CHAT_PATCH 标记', 'ELF2_CHAT_PATCH' in src)
    check('build_prompt / _est_tokens 都在', callable(build_prompt) and callable(est))
    check('max_new_tokens 不再写死 -1（只看代码，不看注释）',
          'max_new_tokens = -1' not in code)
    check('run() 不再自己拼前后缀（只看代码）',
          'PROMPT_TEXT_PREFIX + prompt' not in code)
    check('run() 直接下发完整 prompt',
          "prompt_input = ctypes.c_char_p(prompt.encode('utf-8'))" in code)

    print('\n=== 2. system 槽位 ===')
    p = build_prompt([{'role': 'system', 'content': '你是中继台助手'},
                      {'role': 'user', 'content': '你好'}])
    check('system 内容进了 system 槽位', '<|im_start|>system\n你是中继台助手<|im_end|>' in p, p[:120])
    check('不再出现写死的英文 system', 'You are a helpful assistant.' not in p, p[:120])
    check('prompt 里没有 system 被丢进 user 槽',
          '<|im_start|>user\n你是中继台助手' not in p)
    check('以 assistant 起始标记结尾（约定模型续写）',
          p.endswith('<|im_start|>assistant\n'), repr(p[-40:]))

    p2 = build_prompt([{'role': 'system', 'content': '甲'},
                       {'role': 'system', 'content': '乙'},
                       {'role': 'user', 'content': 'q'}])
    check('多条 system 按序拼接', '甲\n乙' in p2, p2[:80])

    p3 = build_prompt([{'role': 'user', 'content': 'q'}])
    check('没有 system 时用默认值',
          ('<|im_start|>system\n%s<|im_end|>' % ns['DEFAULT_SYSTEM']) in p3, p3[:90])

    print('\n=== 3. 完整多轮（旧实现只取最后一条）===')
    p4 = build_prompt([
        {'role': 'user', 'content': '记住 741852'},
        {'role': 'assistant', 'content': '好的'},
        {'role': 'user', 'content': '是多少'},
    ])
    check('第一轮 user 被保留', '<|im_start|>user\n记住 741852<|im_end|>' in p4, p4[:200])
    check('assistant 轮被保留', '<|im_start|>assistant\n好的<|im_end|>' in p4, p4[:200])
    check('最后一轮 user 也在', p4.rstrip().endswith('是多少<|im_end|>\n<|im_start|>assistant'),
          repr(p4[-60:]))
    check('三轮都在（旧的只剩最后一轮）', p4.count('<|im_start|>user') == 2
          and p4.count('<|im_start|>assistant') == 2, p4)

    print('\n=== 4. 模板细节 ===')
    check('用换行分隔 role 与内容（旧的用空格）',
          '<|im_start|>user\n' in p and '<|im_start|>user ' not in p)
    check('空内容消息被跳过',
          build_prompt([{'role': 'user', 'content': '  '},
                        {'role': 'user', 'content': 'x'}]).count('<|im_start|>user') == 1)
    check('prompt 字段走 fallback',
          '唯一一句' in build_prompt([], fallback='唯一一句'))
    check('垃圾输入不崩', isinstance(build_prompt(None), str))

    print('\n=== 5. token 估算（超限守卫用）===')
    check('纯中文 1 字≈1 token', est('中' * 100) >= 100, str(est('中' * 100)))
    check('纯英文 4 字符≈1 token', est('a' * 400) < 150, str(est('a' * 400)))
    check('空串有最小开销', est('') >= 8, str(est('')))
    check('中文比同长度英文估得多', est('中' * 200) > est('a' * 200))
    # 实测：4615 字符不可压缩中文可通过，5015 起超限。估算要落在同一量级。
    body = ''.join('风速%d电压%d' % (i, i) for i in range(300))[:4600]
    check('4600 字实测可过 → 估算不超 4096 太多', est(body) < 5200, str(est(body)))
    body2 = ''.join('风速%d电压%d' % (i, i) for i in range(320))[:5000]
    check('5000 字实测超限 → 估算更大', est(body2) > est(body))

    print('\n' + '=' * 62)
    print('通过 %d 项，失败 %d 项' % (OK[0], len(FAIL)))
    for f in FAIL:
        print('  ✗ %s' % f)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
