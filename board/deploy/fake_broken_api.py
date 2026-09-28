# -*- coding: utf-8 -*-
"""假「坏掉的外部 API」：TCP 能连上（所以可达性探测会判“网络正常”），
但一连上就 RST 掉，让真实调用以**连接级错误**失败。

用途：验证 auto 模式下「探测说通、真调用断」这条最难复现的路径 ——
同一次请求必须回退到本地 LLM，而不是把这句话丢掉。

用法（板端）：python3 fake_broken_api.py [端口，缺省 18099]
"""
import socket
import struct
import sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 18099
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', port))
s.listen(32)
print('fake-broken-api listening on 127.0.0.1:%d（连上即 RST）' % port, flush=True)
while True:
    try:
        c, _ = s.accept()
    except Exception:
        break
    try:
        # 关键：**先收一点请求再 RST**。若 accept 后立刻 close，客户端可能在
        # connect() 返回之前就吃到 RST —— 那样可达性探测会判「不可达」，
        # 就构造不出「探测说通、真调用断」这个场景（实测踩过：probe 报 tcp-fail）。
        c.settimeout(3.0)
        try:
            c.recv(4096)
        except Exception:
            pass
        # SO_LINGER=1,0 → close() 直接发 RST，客户端读到 ECONNRESET（ConnectionError）
        c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        c.close()
    except Exception:
        pass
