#!/bin/bash
# 在 NVMe(/opt/ai) 上创建 4GB swapfile，降低 swappiness，保留内核预留内存。
# 幂等：重复执行不会重复创建。
SW=/opt/ai/swapfile
SIZE_MB=4096

if ! mountpoint -q /opt/ai; then
  echo "ERROR: /opt/ai 未挂载，拒绝创建 swapfile"
  exit 1
fi

if swapon --show=NAME --noheadings 2>/dev/null | grep -q "^$SW$"; then
  echo "swap 已启用: $SW"
else
  if [ ! -f "$SW" ]; then
    echo "创建 $SW (${SIZE_MB} MB) ..."
    dd if=/dev/zero of="$SW" bs=1M count=$SIZE_MB status=none || exit 1
  fi
  chmod 600 "$SW"
  mkswap "$SW" >/dev/null || exit 1
  swapon -p 10 "$SW" || exit 1
  echo "已启用 swap"
fi

if ! grep -q "^$SW" /etc/fstab; then
  echo "$SW none swap sw,pri=10 0 0" >> /etc/fstab
  echo "已写入 /etc/fstab"
fi

printf 'vm.swappiness=10\nvm.vfs_cache_pressure=50\nvm.min_free_kbytes=65536\n' \
  > /etc/sysctl.d/99-elf2-swap.conf
sysctl -q -p /etc/sysctl.d/99-elf2-swap.conf

echo "--- 结果 ---"
swapon --show
free -m | head -3
echo "swappiness=$(cat /proc/sys/vm/swappiness) vfs_cache_pressure=$(cat /proc/sys/vm/vfs_cache_pressure) min_free_kbytes=$(cat /proc/sys/vm/min_free_kbytes)"
