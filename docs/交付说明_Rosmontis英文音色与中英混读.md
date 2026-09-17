# Rosmontis 英文音色 + 中英混读 / ICAO 朗读 交付说明（2026-09-15，v2）

## 1. 交付物
| 文件 | 说明 |
|---|---|
| `Rosmontis_en_voice_pack.zip` | 英文音色包（58 MB：`model.onnx` / `model.onnx.json` / `voice.json`） |
| `Rosmontis_en_model.onnx.json` | 剥离多码点键后的 piper 配置（161 键） |
| `en_US-lessac-medium_pack.zip` | 官方英文音色（ICAO 字母串“咬字清晰”专用，可选） |
| `板端实测样本/*.wav` | 板端 192.168.101.206 合成样本（详见第 5 节） |

## 2. 英文音色训练方案
- **文本**：PRTS wiki「迷迭香/语音记录」英文台词 38 条（mobile API 抓 wikitext；桌面站 403）。
- **音频**：GitHub `PseudoMon/arknights-audio` → `voice_en/char_391_rosmon/`，35 条英文配音，
  统一 22.05 kHz 单声道，合计 **578 秒**。
- **基座**：官方 `en_US-lessac-medium`（Piper VITS，256 符号）。
- **训练**：RTX 4070，290 epoch，best `val_mel=0.0130`，`piper-tts 1.8.0` + espeak voice `en-us`。
- **导出修正**：新版权重配置含 5 个多码点键（`aɪ/aʊ/ɔɪ/eɪ/oʊ`），2023 版板端 piper 会报
  `"aɪ" is not a single codepoint` 拒绝加载 → 已剥离为 161 键。
  训练侧音素化器实际输出单码点序列（`['a','ɪ']`），剥离**不影响发音正确性**。

## 3. 板端部署与音色分工
| 音色 | 路径 | 用途 |
|---|---|---|
| `Rosmontis_v2` | `/opt/ai/voices/Rosmontis_v2` | 中文段（默认音色） |
| `Rosmontis_en` | `/opt/ai/voices/Rosmontis_en` | 普通英文句子 |
| `en_US-lessac-medium` | `/opt/ai/voices/en_US-lessac-medium` | **ICAO 字母串专用**（咬字清晰） |
| `zh_CN-huayan-medium` | `/opt/ai/voices/zh_CN-huayan-medium` | 内置基座，受删除保护 |

网页设置页新增：**英文片段音色**、**ICAO 字母串专用音色**、**ICAO 字母解释法开关**、
**音色包管理表格**（可删除非内置音色包）。
设置键：`tts_en_voice` / `tts_icao_voice` / `tts_icao`。

## 4. 中英混读 + ICAO 实现
`tts_service.synthesize_multilingual(text, zh_voice, en_voice, icao, icao_voice)`：
1. `expand_icao(mark=True)` 把呼号/单字母展开，并用 `..` 标记区间；
2. `_split_marked()` 把它切成 `zh / en / icao` 三类片段；
3. 分别用中文音色 / 英文音色 / ICAO 专用音色合成；
4. `concat_wavs()` 段间插 120 ms 静音拼接成一条 WAV。

板端实测分段：
```
呼号 BG7XYZ，这里是 ELF2 中继站，Radio check five nine，how copy？
 → [zh ] 呼号                        -> Rosmontis_v2
 → [icao] Bravo Golf Seven X-ray Yankee Zulu  -> en_US-lessac-medium
 → [zh ] ，这里是                     -> Rosmontis_v2
 → [icao] Echo Lima Foxtrot Two       -> en_US-lessac-medium
 → [zh ] 中继站，                     -> Rosmontis_v2
 → [en ] Radio check five nine，how copy？    -> Rosmontis_en
```

## 5. 板端实测数据
| 样本 | 文本 | 时长 |
|---|---|---|
| `en_radio_check.wav` | Radio check five nine, how copy? Over. | 4.0 s |
| `en_call.wav` | Bravo Golf Seven X-ray Yankee Zulu, this is Elf Two relay station… | 12.7 s |
| `bilingual_mixed.wav` | The relay station 已切换到 145.500 MHz，请用 W A R 呼叫。 | 7.9 s |
| `zh_call_icao_off.wav` | 呼号 BG7XYZ，这里是 ELF2 中继站。（ICAO 关） | 5.4 s |
| `zh_call_icao_on.wav` | 同上（ICAO 开，全部用 Rosmontis_en 读字母） | 8.0 s |
| `bilingual_icao_hybrid.wav` | 中英混读 + ICAO（字母用 lessac / 英文用 Rosmontis_en） | 9.2 s |
| `en_icao_lessac官方对照.wav` | Papa Romeo India Mike… how copy? Over.（纯 lessac） | 7.1 s |
| `en_icao_Rosmontis_en.wav` | 同上（纯 Rosmontis_en） | 9.2 s |
| `cmp_en_text_by_cn_voice.wav` / `cmp_en_text_by_en_voice.wav` | Radio check five nine, how copy? Over.（中文音色 vs 英文音色） | 4.6 / 4.1 s |

RTF 实测 0.11 ~ 0.13（推理 0.43~0.88 s / 音频 3.4~7.1 s）。

**ASR 回读对比**（faster-whisper small，仅供参考）：
- `en_icao_lessac官方对照.wav` → `Copper Romeo India Mike Alfa Romeo Yankee This is Elf 2 Relay, Radio check 59, Hell copy. Over.`（字母串清晰可辨）
- `en_icao_Rosmontis_en.wav` → `Copy Romeo in the unlike of Romeo in P ... review took 5 minutes ...`（字母串明显糊）
- `en_radio_check.wav` → `Radio check 59, I'll copy, offer.`（短句英文可懂）
- `cmp_en_text_by_cn_voice.wav` → `Radio check 5-9. I'll copy. Over.`

结论：**Rosmontis_en 适合整句英文播报；逐字母 ICAO 字母串改用官方英文音色更清楚**，
因此默认把 ICAO 展开片段路由到 `en_US-lessac-medium`（可在设置页改回 Rosmontis_en）。

## 6. 使用建议
- 呼号写成连续大写 `BG7XYZ`（或 `B G 7 X Y Z`），ICAO 开启后自动逐字母朗读；
- 正常英文单词不会被展开（`Hotel`、`X-ray`、`MHz`、`SOS` 原样保留）；
- 想听全 Rosmontis 音色的字母读法：设置页把「ICAO 字母串专用音色」改成 `Rosmontis_en`；
- 想完全关掉字母解释法：取消勾选「ICAO 字母解释法」。
