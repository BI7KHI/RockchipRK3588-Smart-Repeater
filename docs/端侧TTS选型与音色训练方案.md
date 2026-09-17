# 端侧 TTS 选型、多 API 接入与音色训练/上传方案

> 项目：ELF2/RK3588 多模态智能无线电中继
> 目标：LLM 输出文本在端侧朗读，经开发板 3.5mm AUX 输出；支持本地/外部多 API 切换、音色上传与后续微调。

---

## 1. 端侧 TTS 选型对比

| 方案 | 类型 | 资源占用 | 中文效果 | 实时性 | 音色克隆/训练 | 结论 |
|---|---|---|---|---|---|---|
| **Piper** | 本地 VITS/ONNX | 单音色约 60MB，CPU 即可 | 好 | RK3588 实测 RTF≈0.147，2.6s 音频约 0.39s 合成 | 需在 PC 上微调，导出 ONNX 后上传 | ✅ 当前首选 |
| sherpa-onnx VITS | 本地 ONNX | 单音色约 80~200MB | 好 | 较好 | 可换模型，板端训练困难 | 备选 |
| GPT-SoVITS | 本地/服务 | 模型大，需较多内存/算力 | 很好 | RK3588 同时跑 LLM 时较吃力 | 支持少样本克隆 | PC/服务器侧训练后作为外部 API 或导出 |
| CosyVoice / FishSpeech 等 | 本地/服务 | 大 | 很好 | 需要较强 GPU/CPU | 支持克隆 | 建议部署在 PC/云，板端调用外部 API |
| Edge-TTS / 云端 TTS | 外部 API | 低 | 很好 | 网络依赖 | 多音色，通常不支持私有克隆 | 外部 API 可选 |
| OpenAI 兼容 `/v1/audio/speech` | 外部 API | 低 | 取决于供应商 | 网络依赖 | 部分供应商支持 | 已接入，可配多个 |

### 当前选择

```text
本地主方案：Piper + zh_CN-huayan-medium
外部备用：任意 OpenAI 兼容 /v1/audio/speech 接口
```

已部署到：

```text
/opt/ai/piper/                 # Piper 二进制与依赖
/opt/ai/voices/zh_CN-huayan-medium/
  ├── model.onnx
  ├── model.onnx.json
  └── config.json
```

实测命令：

```bash
cd /opt/ai/piper
echo "你好，这是智能中继语音测试。" | \
  LD_LIBRARY_PATH=. ./piper \
  --model /opt/ai/voices/zh_CN-huayan-medium/model.onnx \
  --config /opt/ai/voices/zh_CN-huayan-medium/model.onnx.json \
  --output_file /tmp/piper_test.wav \
  --espeak_data /opt/ai/piper/espeak-ng-data
```

实测结果：

```text
Loaded voice in 0.44s
Real-time factor: 0.1469
audio=2.647s, infer=0.389s
```

---

## 2. 多 API 接入架构

```text
网页 → /api/tts/speak
        ├─ provider = local
        │      └─ Piper → WAV → aplay → 3.5mm AUX
        └─ provider = external:<name>
               └─ OpenAI 兼容 /v1/audio/speech → WAV → aplay → 3.5mm AUX
```

支持的外部 API 结构：

```json
{
  "name": "openai-compatible",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "tts-1",
  "voice": "alloy"
}
```

网页设置页支持：

- 新增/编辑/删除多个外部 API
- 本地 Piper 音色选择
- LLM 回复后自动朗读开关
- TTS 测试文本朗读
- 音色包上传
- 训练数据上传

---

## 3. 网页控制操作

### LLM 对话页

- 选择 TTS 提供方：本地 Piper / external API
- 选择本地音色
- 输入测试文本，点击“测试朗读”
- 勾选“自动朗读 LLM 回复”

流程：

```text
用户输入 → LLM 生成 → 回复文本 → TTS 合成 WAV → aplay 到 3.5mm AUX
```

### 流式即时朗读

当 LLM 开启流式输出且勾选“自动朗读 LLM 回复”时：

```text
LLM token 流
  → 前端按句号/问号/感叹号/分号/换行切分
  → 无标点时按 80 字或最后一个逗号/空格切分
  → /api/tts/stream/chunk
  → 后端合成 Piper WAV
  → 播放队列串行输出到 3.5mm AUX
```

特点：

- 不再等待 LLM 整段输出完成；
- 第一段通常在一句话结束后立即开始合成和播放；
- 后端采用“合成线程 + 播放线程”流水线：
  - 当前段播放时，下一段已开始合成；
  - 避免所有语音在 LLM 结束后才依次播放。
- 句末标点会触发切分，长句无标点时按逗号/空格/80 字兜底切分。

后端接口：

```text
POST /api/tts/stream/start
POST /api/tts/stream/chunk
POST /api/tts/stream/end
POST /api/tts/stream/stop
```

### 设置页

- 默认 TTS 提供方
- Piper 音色
- 外部 API 列表维护
- 上传音色包 zip
- 上传训练数据 zip

---

## 4. 音色克隆 / 训练 / 上传方案

### 4.1 板端限制

RK3588 当前同时运行：

- RKLLM NPU 大模型（约 2GB 内存）
- Flask 网页服务
- Piper 本地推理

板端剩余内存/算力不足以直接训练 TTS 神经网络。建议：

```text
训练/微调在 PC 或服务器完成
板端只负责推理部署
```

### 4.2 推荐流程 A：Piper 音色微调

1. 在 PC/服务器准备 1~5 小时目标说话人录音，16kHz 以上，wav。
2. 使用 Piper 训练仓库进行数据预处理、训练、导出。
3. 导出：
   ```text
   model.onnx
   model.onnx.json
   config.json
   ```
4. 打包：
   ```bash
   zip -r myvoice.zip model.onnx model.onnx.json config.json
   ```
5. 网页“设置 → TTS → 上传音色包”上传这个 zip。
6. 选择音色并测试朗读。

板端落地目录：

```text
/opt/ai/voices/<voice_id>/
```

### 4.3 推荐流程 B：GPT-SoVITS / CosyVoice 少样本克隆

适合只想上传 1~5 分钟参考音频的情况，但模型较大：

1. 在 PC/服务器部署 GPT-SoVITS 或 CosyVoice。
2. 上传参考音频，训练/微调音色。
3. 两种落地方式：
   - 部署为 OpenAI 兼容 TTS API，ELF2 作为外部 API 调用；
   - 或导出较小推理模型，评估能否在 RK3588 与 LLM 共存运行。
4. 网页“设置 → 外部 TTS API”增加该服务地址。
5. 在 LLM 对话页切换到 `external:<name>` 即可。

### 4.4 音色数据上传（当前已实现）

网页入口：

```text
设置 / 校准 → TTS 语音朗读设置 → 训练数据 zip
```

板端保存：

```text
/opt/ai/voice_training/<dataset_id>/
```

当前状态：

- 训练数据仅保存，不在板端训练；
- 后续可由 PC 拉取数据完成微调；
- 返回后再上传音色包即可上岗。

---

## 5. 接口清单

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/tts/providers` | GET | TTS 提供方列表、本地音色、外部 API |
| `/api/tts/voices` | GET | 本地音色列表 |
| `/api/tts/speak` | POST | 合成语音并可选播放到 AUX |
| `/api/tts/upload_voice` | POST | 上传音色包 zip |
| `/api/tts/training/upload` | POST | 上传训练数据 zip |
| `/api/tts/training/jobs` | GET | 训练数据任务列表 |
| `/api/intercom/recordings` | GET | 所有录音/朗读 WAV 列表 |

---

## 6. 注意事项

1. Piper 与 espeak-ng 数据必须在 `/opt/ai/piper` 下运行，`LD_LIBRARY_PATH=.`。
2. 音色包必须包含 `model.onnx` 与 `model.onnx.json`。
3. 外部 TTS API Key 在网页 GET 中被脱敏，更新时留空会保留旧 Key。
4. 板端不训练大模型，训练数据上传只作为数据集缓存。
5. 自动朗读会增加 CPU/AUX 占用；可随时在 LLM 页关闭。
6. 3.5mm AUX 实际输出需要外接耳机/喇叭验证。
7. 若 `aplay` 正常但无声，先检查 NAU88C22 混音器：
   ```bash
   amixer -c 1 sset 'Headphone' 80% unmute
   amixer -c 1 sset 'Speaker' 80% unmute
   sudo alsactl store
   ```
