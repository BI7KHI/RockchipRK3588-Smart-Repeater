#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测指定 Modbus 从站的寄存器值，用于确认降水量寄存器映射。

用法：
    sudo systemctl stop relay-web
    python3 probe_modbus_registers.py [port] [baud] [slave] [func] [start_reg] [end_reg]
    sudo systemctl start relay-web
"""
import sys
import time

import serial


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def parse_values(rx, addr, func):
    n = len(rx)
    i = 0
    while i <= n - 5:
        if rx[i] != addr:
            i += 1
            continue
        f = rx[i + 1]
        if f == (func | 0x80) and i + 5 <= n:
            frame = rx[i:i + 5]
            if crc16(frame[:-2]) == frame[-2] | (frame[-1] << 8):
                return {'exception': frame[2], 'frame': frame.hex()}
            i += 1
            continue
        if f != func:
            i += 1
            continue
        if i + 3 > n:
            break
        bc = rx[i + 2]
        frame_len = 3 + bc + 2
        if i + frame_len > n:
            i += 1
            continue
        frame = rx[i:i + frame_len]
        if crc16(frame[:-2]) != (frame[-2] | (frame[-1] << 8)):
            i += 1
            continue
        values = [(frame[3 + j * 2] << 8) | frame[4 + j * 2] for j in range(bc // 2)]
        return {'values': values, 'frame': frame.hex()}
    return None


def request(addr, func, register, quantity=1):
    body = bytes([
        addr & 0xFF, func & 0xFF,
        (register >> 8) & 0xFF, register & 0xFF,
        (quantity >> 8) & 0xFF, quantity & 0xFF,
    ])
    return body + crc16(body).to_bytes(2, 'little')


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyS9'
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
    slave = int(sys.argv[3]) if len(sys.argv) > 3 else 23
    func = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    start = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    end = int(sys.argv[6]) if len(sys.argv) > 6 else 63
    ser = serial.Serial(port=port, baudrate=baud, bytesize=8,
                        parity='N', stopbits=1, timeout=0.02)
    try:
        for reg in range(start, end + 1):
            req = request(slave, func, reg, 1)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(req)
            ser.flush()
            deadline = time.time() + 0.2
            rx = b''
            while time.time() < deadline:
                chunk = ser.read(256)
                if chunk:
                    rx += chunk
                    if len(rx) >= 7:
                        break
            parsed = parse_values(rx, slave, func)
            if parsed is None:
                continue
            if 'exception' in parsed:
                print(f'reg=0x{reg:04X} exception={parsed["exception"]:02X}', flush=True)
            else:
                print(f'reg=0x{reg:04X} values={parsed["values"]} rx={parsed["frame"]}',
                      flush=True)
    finally:
        ser.close()


if __name__ == '__main__':
    main()
