#!/bin/bash
# 部署中继语音助手到 ELF2 开发板
# 用法：cd _stage6 && bash deploy_assist.sh
set -e
HOME_SSH=/c/Users/Admin/AppData/Roaming/SPB_Data
KEY="$HOME_SSH/.ssh/id_ed25519_elf2"
SSH="ssh -i $KEY -o ConnectTimeout=25 -o StrictHostKeyChecking=no elf@192.168.101.215"
SCP="scp -i $KEY -o ConnectTimeout=25"

PY_FILES="app.py agent_service.py assistant_service.py tts_service.py voice_service.py"
STATIC_FILES="assistant.js assistant.css"
TPL_FILES="assistant.html base.html"
ALL="app.py agent_service.py assistant_service.py tts_service.py voice_service.py assistant.js assistant.css assistant.html base.html"

TS=$(date +%Y%m%d_%H%M%S)
echo "=== 1. 板端备份到 /www/backup_$TS ==="
$SSH "mkdir -p /www/backup_$TS && cp -a /www/app.py /www/agent_service.py /www/tts_service.py /www/voice_service.py /www/templates/base.html /www/backup_$TS/ && ls /www/backup_$TS/"

echo "=== 2. 上传到 /tmp ==="
$SCP $ALL elf@192.168.101.215:/tmp/

echo "=== 3. 去 CR 后安装到 /www ==="
$SSH '
set -e
cd /tmp
norm() { tr -d "\r" < "$1" > "/tmp/norm_$1"; }
for f in app.py agent_service.py assistant_service.py tts_service.py voice_service.py; do
  norm "$f"; install -m 644 "/tmp/norm_$f" "/www/$f"
done
norm assistant.js;   install -m 644 /tmp/norm_assistant.js   /www/static/js/assistant.js
norm assistant.css;  install -m 644 /tmp/norm_assistant.css  /www/static/css/assistant.css
norm assistant.html; install -m 644 /tmp/norm_assistant.html /www/templates/assistant.html
norm base.html;      install -m 644 /tmp/norm_base.html      /www/templates/base.html
rm -f /tmp/norm_* /tmp/app.py /tmp/agent_service.py /tmp/assistant_service.py \
      /tmp/tts_service.py /tmp/voice_service.py /tmp/assistant.js /tmp/assistant.css \
      /tmp/assistant.html /tmp/base.html
ls -la /www/app.py /www/agent_service.py /www/assistant_service.py /www/tts_service.py /www/voice_service.py
ls -la /www/static/js/assistant.js /www/static/css/assistant.css /www/templates/assistant.html
'

echo "=== 4. 板端语法检查 ==="
$SSH "cd /www && python3 -m py_compile app.py agent_service.py assistant_service.py tts_service.py voice_service.py && echo 'py_compile OK'"

echo "=== 5. 重启 relay-web ==="
$SSH "echo elf | sudo -S systemctl restart relay-web; sleep 7; systemctl is-active relay-web"

echo "=== 6. 冒烟 ==="
$SSH "journalctl -u relay-web -n 8 --no-pager | tail -8"
echo "部署完成（备份 /www/backup_$TS）"
