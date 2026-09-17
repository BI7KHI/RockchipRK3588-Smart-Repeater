# 板端 TTS 后处理（低通 + 去齿音）接入说明

目的：在板端 Piper 合成完成后，对 wav 再做一次后处理，压掉气声 / 齿音 / 过亮。

## 1. 文件
- `postfilter.py`：自包含脚本，仅依赖 numpy（板端没有 scipy 时自动退化为纯 Python biquad 实现）

## 2. 部署
```
scp postfilter.py elf@<板卡IP>:/tmp/
ssh elf@<板卡IP> 'sudo mkdir -p /opt/ai/piper && sudo cp /tmp/postfilter.py /opt/ai/piper/postfilter.py'
```

## 3. 修改 /www/tts_service.py

在 `piper_speak()` 里，`proc = subprocess.run(cmd, ...)` 校验通过之后、`return str(out_path)` 之前插入：

```python
    # --- 可选后处理：低通 + 去齿音（抑制气声/齿音）---
    if os.environ.get('RELAY_TTS_FILTER', '1') == '1':
        tmp_filt = str(out_path) + '.filt.wav'
        pf = subprocess.run(
            ['python3', '/opt/ai/piper/postfilter.py', str(out_path), tmp_filt,
             '--lp', os.environ.get('RELAY_TTS_LP', '8000'),
             '--shelf-db', os.environ.get('RELAY_TTS_SHELF', '-2'),
             '--deess-max', os.environ.get('RELAY_TTS_DEESS', '5')],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if pf.returncode == 0 and Path(tmp_filt).exists():
            os.replace(tmp_filt, str(out_path))
```

说明：`os`、`subprocess`、`Path` 在该文件里已经 import，无需新增 import。

## 4. 服务文件加环境变量（/etc/systemd/system/relay-web.service 的 [Service] 段）

```
Environment=RELAY_TTS_FILTER=1
Environment=RELAY_TTS_LP=8000
Environment=RELAY_TTS_SHELF=-2
Environment=RELAY_TTS_DEESS=5
```

然后：
```
sudo systemctl daemon-reload && sudo systemctl restart relay-web
```

## 5. 关闭后处理
把 `RELAY_TTS_FILTER` 改成 `0` 再重启服务即可，不需要改代码。

## 6. 参数含义
| 参数 | 默认 | 说明 |
|---|---|---|
| `--lp` | 8000 | 低通截止频率 Hz，越小越闷 |
| `--shelf-db` | -2 | 3.5kHz 以上高架衰减量 dB |
| `--deess-max` | 5 | 去齿音最大衰减 dB |
| `--deess-thr` | 4 | 去齿音触发门限（相对该句 75 分位，dB） |
| `--deess-lo/hi` | 4500 / 9000 | 齿音检测频段 |

## 7. 备注
- 后处理只作用于**本地 Piper 合成**的音频；外部 OpenAI 兼容 TTS 不经过这里。
- 单次后处理在 RK3588 上约 0.2~0.5 秒（4 秒音频），不会明显增加播报延迟。
- v2 音色包（Rosmontis_v2，已用高频衰减数据集重训）实测：模型原始输出谱质心 2294 Hz，套用上面默认参数（lp=8000 / shelf=-2 / deess=5）后为 **1895 Hz**，与 huayan 原音色（1812 Hz）基本一致 —— 所以 **v2 也直接沿用默认参数**，无需改动。
- 若仍觉偏亮：把 `RELAY_TTS_LP` 降到 7000、`RELAY_TTS_SHELF` 改成 -3；若觉得发闷：把 `RELAY_TTS_FILTER` 设为 0 关闭后处理（v2 原声 2294 Hz，仍比 v1 暗很多）。
