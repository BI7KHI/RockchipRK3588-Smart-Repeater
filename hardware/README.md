# 硬件设计 / Hardware Design

本目录保存自研板卡的设计资料与自动化脚本。EDA 工程源文件（嘉立创 EDA `.eprj2`）
体积较大且为二进制，**未纳入仓库**，可通过脚本重建或向作者索取。

> **EN** — Design assets for the two custom boards. The LCEDA project file (`.eprj2`) is a
> large binary and is intentionally **not** committed; the automation scripts here can rebuild
> or inspect it.

---

## 1. 板卡组成 / Boards

| 板卡 | 作用 | 状态 |
|---|---|---|
| **IO 隔离 / 驱动板** | 数字量光耦隔离（PC0–PC3）、PTT 隔离驱动、音频隔离衰减、隔离 12 V、隔离 RS485 | 🔶 原理图完成，PCB 布线/打样进行中 |
| **ADC 分压采集板** | 电池 14 V / 光伏 25 V 分压到 RK3588 SARADC 量程（0–1.8 V） | 🔶 设计/验算完成，待实机校准 |
| `ELF2_IO_Board.eprj2` | 上述两块板的嘉立创 EDA 工程（含 4 个 sheet） | 本地保存 |

EDA 工程 sheet：`ELF2 ADC分压采集`、`IO光耦隔离`、`音频隔离衰减`、`RS485模块透传与电压`。

## 2. ADC 分压验算 / Divider math

RK3588 SARADC：**12 bit，0–1.8 V**，`LSB = 1.8/4096 = 0.439453 mV`。

| 通道 | 上臂 | 下臂 | 分压比 `R下/(R上+R下)` | 倍率 `1/分压比` | 满量程 | 分辨率 |
|---|---|---|---|---|---|---|
| 电池 VBAT | 100 Ω + 91 kΩ | 10 kΩ | 0.098912 | **10.11 V/V** | 18.198 V | 4.443 mV/LSB |
| 光伏 PV | 100 Ω + 160 kΩ | 10 kΩ | 0.058789 | **17.01 V/V** | 30.618 V | 7.475 mV/LSB |

换算：`引脚电压 = (raw − 零点) × 0.43945 mV`；`实际电压 = 引脚电压 × 倍率`。
板端默认通道：电池 `VIN4`（CH4）、光伏 `VIN6`（CH6，可按硬件改 `*_adc_channel`）。

> 注：`100 Ω` 为串在输入端的限流/滤波电阻，计算分压比时已计入上臂。

## 3. PTT 与接口 / PTT & interfaces

- **PTT 通路**：`RK3588 GPIO3_A1`（Linux 全局 **GPIO 97**，`gpiochip3 line1`）
  → 隔离/驱动 → 中继控制板 PTT 端子。
- **极性与驱动**：Motorola GM3188 的 PTT 为**低有效**（拉低发射）；
  若控制板输入要求低有效，隔离板输出级需反相（光耦集电极输出天然反相，或加一级三极管）。
- **驱动能力**：RK3588 单脚典型 2–4 mA；光耦 Vf≈1.2 V ⇒ 限流电阻 `R=(3.3−1.2)/If`，
  `If=2 mA → ≈1 kΩ`，`If=5 mA → ≈420 Ω`。**电阻过小会导致引脚电压塌陷 → 间歇发射**。
- **接口核对**：`../assets/ELF2_40P20P_接线核对图.svg`、`ELF2_P26_P28_schematic.png`。

### BUSY 输入 / BUSY input（2026-09-23 实测）

- **引脚**：`P26-36`（丝印 `GPIO.27`）= `RK3588 GPIO3_A5` = Linux 全局 **GPIO 101**（`gpiochip3 line5`），
  参考地 `P26-39`。
- **方向**：**输入**，只读；软件侧 `/sys/class/gpio/gpio101/value`，0.25 s 轮询 + 电平沿计数。
- **推荐电路**：控制板 BUSY → 限流电阻 → 光耦 LED；光耦输出（集电极开路）→ ELF2 GPIO，
  **GPIO 侧 10 k 上拉到 3.3 V**，并联 100 nF 去抖。
- **⚠️ 实测数据**：未触发静噪关闭状态下引脚电平为 **0 V**（说明当前没有上拉/光耦在导通），
  90 s 内电平变化次数仅 1（导出那一次）。3.3 V 数字输入判据 **VIL≈0.99 V / VIH≈2.31 V**，
  `1.0–2.3 V` 区间读数不可靠 —— 若触发时只能拉到约 2.7 V，则与空闲 3.3 V 无法区分。
- **处理**：① 按设计补齐 **10 k 上拉到 3.3 V**；② 加大光耦驱动电流（`If=2–5 mA`，
  限流电阻按 PTT 同法计算）或在 GPIO 侧加对地下拉，确保可靠跨过门限；
  ③ 软件侧已把极性做成**运行时可切**，并用「原始电平 + 电平变化次数」判断接线是否有效
  （设置与校准 → BUSY 接收状态）。

## 4. 音频链路 / Audio path

- 板端 3.5 mm（NAU8822 codec）：`3.5mm耳机接口音频输入原理图结论.md`（见 `../docs/`）。
- 接收侧 RPT MIC 与 ELF2 MIC 共节点方案：需**隔直电容（4.7–10 µF）+ BAT54S 限幅 + RC 低通**，
  并将 PGA Boost 关闭、PGA 调整到 ≈45–50%（详见 `../docs/`）。

## 5. EDA 自动化脚本 / EDA automation

`eda_scripts/` 内的脚本通过 **CDP 驱动嘉立创 EDA 客户端**（调试端口 9222）自动建原理图、
连线、布线、导出与校验，例如：

| 脚本 | 用途 |
|---|---|
| `eda_auto.py` / `cdp.py` | CDP 连接与 EDA 操作基础库 |
| `build_io_sch*.py` / `wire_io_sch*.py` / `netflag_io_sch.py` | 生成/连线 IO 隔离板原理图 |
| `build_io_pcb*.py` / `finish_io_pcb_place.py` | IO 板 PCB 建板与布局 |
| `build_divider*.py` / `route_divider_pcb*.py` | ADC 分压板原理图与布线 |
| `adc_dump.py` / `adc_text.py` / `audio_net_export.py` / `rs485_net.py` | sheet/网络表检查 |
| `verify_final.py` / `check_nets.py` / `dump_all_sheets.py` | 设计校验与导出 |

运行方式（需本地已启动带调试端口的 EDA 客户端）：

```bash
python3 eda_scripts/eda_auto.py       # 按脚本内注释选择具体操作
```

> **EN** — Scripts drive the LCEDA desktop client over the DevTools protocol to
> create/wire/route/verify the two boards programmatically.
