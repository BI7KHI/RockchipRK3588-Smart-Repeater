#!/usr/bin/env bash
# 部署 ELF2 PTT GPIO3_A1 控制到开发板。
# 用法：
#   BOARD=elf@192.168.101.215 bash deploy_ptt_gpio.sh
# 会提示输入开发板 sudo 密码（通常为 elf）。
set -euo pipefail

BOARD="${BOARD:-elf@192.168.101.215}"
KEY="${KEY:-$HOME/.ssh/id_ed25519_elf2}"
SSH_OPTS=(-i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o BatchMode=no)

for f in app.py relay-web.service elf2-ptt-gpio.service ptt_gpio_prepare.sh 99-elf2-ptt.rules; do
  if [ ! -f "$f" ]; then
    echo "缺少文件：$f，请在 web_client 目录下运行本脚本" >&2
    exit 1
  fi
done

read -rsp "开发板 sudo 密码: " SUDO_PW
echo

echo "[1/3] 上传文件..."
scp "${SSH_OPTS[@]}" app.py relay-web.service elf2-ptt-gpio.service ptt_gpio_prepare.sh 99-elf2-ptt.rules "${BOARD}:/www/"

echo "[2/3] 安装 systemd 服务与 udev 规则..."
printf '%s\n' "$SUDO_PW" | ssh "${SSH_OPTS[@]}" "$BOARD" "
sudo -S sh -c '
set -e
cp /www/ptt_gpio_prepare.sh /usr/local/sbin/elf2-ptt-gpio.sh
chmod +x /usr/local/sbin/elf2-ptt-gpio.sh
cp /www/elf2-ptt-gpio.service /etc/systemd/system/elf2-ptt-gpio.service
cp /www/relay-web.service /etc/systemd/system/relay-web.service
cp /www/99-elf2-ptt.rules /etc/udev/rules.d/99-elf2-ptt.rules
udevadm control --reload-rules
systemctl daemon-reload
systemctl enable elf2-ptt-gpio
systemctl restart elf2-ptt-gpio
systemctl restart relay-web
'
"

echo "[3/3] 服务状态..."
ssh "${SSH_OPTS[@]}" "$BOARD" "systemctl is-active elf2-ptt-gpio relay-web; ls -l /sys/class/gpio/gpio97/direction /sys/class/gpio/gpio97/value 2>/dev/null; cat /sys/class/gpio/gpio97/value 2>/dev/null"

echo "部署完成。可打开 http://192.168.101.215:8080 并访问 /api/ptt/status 验证。"
