# -*- coding: utf-8 -*-
"""把 rkllm-server 的 max_context_len 从硬编码 512 改成可用环境变量配置（默认 4096）。

背景：原代码 `rkllm_param.max_context_len = 512` 导致 prompt > ~380 token 直接
报 "prompt gather than max context"，本地 LLM 无法做长文总结。
"""
import shutil
import sys
from pathlib import Path

P = Path('/opt/ai/rkllm-server/flask_server.py')
BAK = Path('/opt/ai/rkllm-server/flask_server.py.bak_ctx512')

OLD = 'rkllm_param.max_context_len = 512'
NEW = 'rkllm_param.max_context_len = int(os.environ.get("RKLLM_MAX_CONTEXT", "4096"))'

src = P.read_text(encoding='utf-8')

if 'RKLLM_MAX_CONTEXT' in src:
    print('ALREADY_PATCHED')
    sys.exit(0)

if OLD not in src:
    print('ANCHOR_NOT_FOUND')
    sys.exit(1)

if not BAK.exists():
    shutil.copy2(P, BAK)
    print('backup -> %s' % BAK)

P.write_text(src.replace(OLD, NEW, 1), encoding='utf-8')
print('PATCHED -> %s' % NEW)
