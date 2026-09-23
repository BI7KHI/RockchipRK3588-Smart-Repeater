#!/bin/sh
# ELF2 GPIO 初始化
#   PTT  GPIO3_A1 -> Linux 全局 GPIO 97  （输出，高有效）
#   BUSY GPIO3_A5 -> Linux 全局 GPIO 101 （输入，低有效：光耦触发时把引脚拉低）
# 由 elf2-ptt-gpio.service 以 root 调用。
set -eu

export_gpio() {  # $1 = 全局 GPIO 号
    n="$1"
    d="/sys/class/gpio/gpio$n"
    if [ ! -d "$d" ]; then
        echo "$n" > /sys/class/gpio/export 2>/dev/null || true
        sleep 0.1
    fi
    [ -d "$d" ] && return 0
    return 1
}

chown_gpio() {  # $1 = 全局 GPIO 号
    n="$1"
    for f in direction value active_low edge; do
        [ -e "/sys/class/gpio/gpio$n/$f" ] || continue
        chown elf:elf "/sys/class/gpio/gpio$n/$f" 2>/dev/null || true
        chmod ug+rw "/sys/class/gpio/gpio$n/$f" 2>/dev/null || true
    done
}

if [ ! -d /sys/class/gpio ]; then
    echo "ERROR: /sys/class/gpio 不存在，内核可能未启用 sysfs GPIO" >&2
    exit 1
fi

# ---------------- BUSY 输入（GPIO3_A5） ----------------
BUSY="${RELAY_BUSY_GPIO:-101}"
if export_gpio "$BUSY"; then
    echo in > "/sys/class/gpio/gpio$BUSY/direction"
    chown_gpio "$BUSY"
    echo "BUSY GPIO3_A5 ready: /sys/class/gpio/gpio$BUSY level=$(cat "/sys/class/gpio/gpio$BUSY/value" 2>/dev/null || echo '?')"
else
    echo "WARN: 导出 BUSY GPIO $BUSY 失败（可能被别处占用）" >&2
fi

# ---------------- PTT 输出（GPIO3_A1） ----------------
GPIO="${RELAY_PTT_GPIO:-97}"
if ! export_gpio "$GPIO"; then
    echo "ERROR: 导出 GPIO $GPIO 失败，请检查 GPIO3_A1 是否被其他功能占用" >&2
    exit 1
fi

echo out > "/sys/class/gpio/gpio$GPIO/direction"
echo 0 > "/sys/class/gpio/gpio$GPIO/value"
chown_gpio "$GPIO"

echo "PTT GPIO3_A1 ready: /sys/class/gpio/gpio$GPIO"
