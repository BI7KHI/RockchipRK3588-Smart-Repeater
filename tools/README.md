# 调试工具 / Bring-up Tools

板端/传感器联调用的独立脚本，均可在开发板或 PC 上直接运行（默认串口 `/dev/ttyS9`，9600 8N1）。

| 脚本 | 用途 | 用法 |
|---|---|---|
| `scan_modbus.py` | 扫描 Modbus 从站地址与常用寄存器（风速变送器） | `python3 scan_modbus.py /dev/ttyS9` |
| `scan_modbus2.py` | 二次扫描 / 多寄存器范围 | `python3 scan_modbus2.py` |
| `probe_modbus_registers.py` | 定点探测寄存器值（含 CRC 校验输出） | `python3 probe_modbus_registers.py` |
| `raw_modbus.py` | 直接收发原始帧，排查接线/电平/波特率 | `python3 raw_modbus.py` |
| `test_modbus.py` | 读取风速/雨量并打印解析结果 | `python3 test_modbus.py` |
| `debug_rs485.py` | RS485 链路自检（回环/超时/错误计数） | `python3 debug_rs485.py` |
| `make_elf2_wiring_svg.py` | 由引脚分配表生成接线核对图 SVG | `python3 make_elf2_wiring_svg.py > wiring.svg` |

依赖：`pyserial`（板端已随系统提供；PC 上 `pip install pyserial`）。

> **EN** — Standalone scripts for bringing up the RS485/Modbus sensors (anemometer and
> tipping-bucket rain gauge) and for regenerating the wiring SVG. Default port `/dev/ttyS9`
> at 9600 8N1; requires `pyserial`.
