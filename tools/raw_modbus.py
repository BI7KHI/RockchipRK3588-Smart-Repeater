#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发送任意 Modbus RTU 十六进制帧并打印响应，用于设备识别与协议探测。

用法：
    sudo systemctl stop relay-web
    python3 raw_modbus.py 170300000014... [wait_ms]
    sudo systemctl start relay-web
"""
import sys
import time

import serial


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    tx = bytes.fromhex(sys.argv[1].replace(' ', ''))
    wait_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    port = sys.argv[3] if len(sys.argv) > 3 else '/dev/ttyS9'
    baud = int(sys.argv[4]) if len(sys.argv) > 4 else 9600
    ser = serial.Serial(port=port, baudrate=baud, bytesize=8,
                        parity='N', stopbits=1, timeout=0.05)
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(tx)
        ser.flush()
        deadline = time.time() + max(0.1, wait_ms / 1000.0)
        rx = b''
        while time.time() < deadline:
            chunk = ser.read(256)
            if chunk:
                rx += chunk
        print(f'TX {tx.hex()}')
        print(f'RX {rx.hex()}')
        print(f'LEN {len(rx)}')
    finally:
        ser.close()


if __name__ == '__main__':
    main()
