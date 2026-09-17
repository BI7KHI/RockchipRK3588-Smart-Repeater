#!/bin/sh
# ELF2 PTT GPIO 初始化：GPIO3_A1 -> Linux 全局 GPIO 97
# 运行在 root 下，由 elf2-ptt-gpio.service 调用。
set -eu

GPIO="${RELAY_PTT_GPIO:-97}"
BASE=/sys/class/gpio/gpio${GPIO}

if [ ! -d /sys/class/gpio ]; then
    echo "ERROR: /sys/class/gpio 不存在，内核可能未启用 sysfs GPIO" >&2
    exit 1
fi

if [ ! -d "$BASE" ]; then
    echo "$GPIO" > /sys/class/gpio/export
    sleep 0.1
fi

if [ ! -d "$BASE" ]; then
    echo "ERROR: 导出 GPIO $GPIO 失败，请检查 GPIO3_A1 是否被其他功能占用" >&2
    exit 1
fi

echo out > "$BASE/direction"
echo 0 > "$BASE/value"

for f in direction value active_low edge; do
    [ -e "$BASE/$f" ] || continue
    chown elf:elf "$BASE/$f" 2>/dev/null || true
    chmod ug+rw "$BASE/$f" 2>/dev/null || true
done

echo "PTT GPIO3_A1 ready: $BASE"
