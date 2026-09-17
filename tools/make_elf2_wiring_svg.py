from pathlib import Path
from html import escape

p26 = [
    (1, '3.3V', 'VCC_3V3', '电源', 'RS485 模块 3.3V'),
    (2, '5V', 'VCC_5V', '电源', '预留'),
    (3, 'SDA.1', 'I2C4_SDA_3V3', 'I2C', '预留'),
    (4, '5V', 'VCC_5V', '电源', '预留'),
    (5, 'SCL.1', 'I2C4_SCL_3V3', 'I2C', '预留'),
    (6, 'GND', 'GND', '地', 'RS485 地'),
    (7, 'GPIO.7', 'GPIO3_B3', 'GPIO', '预留'),
    (8, 'TXD', 'UART9_TX', 'UART', 'RS485 DI'),
    (9, 'GND', 'GND', '地', 'RS485 地'),
    (10, 'RXD', 'UART9_RX', 'UART', 'RS485 RO'),
    (11, 'GPIO.0', 'GPIO3_B5', 'GPIO', '预留'),
    (12, 'GPIO.1', 'GPIO3_B0', 'GPIO', '预留'),
    (13, 'GPIO.2', 'GPIO3_B4', 'GPIO', '预留'),
    (14, 'GND', 'GND', '地', '预留'),
    (15, 'GPIO.3', 'GPIO3_A2', 'GPIO', '预留'),
    (16, 'GPIO.4', 'GPIO3_C3', 'GPIO', '预留'),
    (17, '3.3V', 'VCC_3V3', '电源', '预留'),
    (18, 'GPIO.5', 'GPIO3_D3', 'GPIO', '预留'),
    (19, 'MOSI', 'SPI4_MOSI_3V3', 'SPI', '预留'),
    (20, 'GND', 'GND', '地', '预留'),
    (21, 'MISO', 'SPI4_MISO_3V3', 'SPI', '预留'),
    (22, 'GPIO.6', 'GPIO3_C2', 'GPIO', '预留'),
    (23, 'SCLK', 'SPI4_CLK_3V3', 'SPI', '预留'),
    (24, 'CE0', 'SPI4_CS_3V3', 'SPI', '预留'),
    (25, 'GND', 'GND', '地', '预留'),
    (26, 'CE1', 'GPIO3_D2', 'GPIO', '可选 RS485_DE'),
    (27, 'SDA.0', 'I2C7_SDA_3V3', 'I2C', '预留'),
    (28, 'SCL.0', 'I2C7_SCL_3V3', 'I2C', '预留'),
    (29, 'GPIO.21', 'GPIO3_B6', 'GPIO', 'PC0 频率选择'),
    (30, 'GND', 'GND', '地', 'PC0 参考地'),
    (31, 'GPIO.22', 'GPIO3_A6', 'GPIO', 'PC1 频率选择'),
    (32, 'GPIO.26', 'GPIO3_A1', 'GPIO', 'PTT 发射使能'),
    (33, 'GPIO.23', 'GPIO3_A4', 'GPIO', 'PC2 频率选择'),
    (34, 'GND', 'GND', '地', 'PTT 参考地'),
    (35, 'GPIO.24', 'GPIO3_A0', 'GPIO', 'PC3 频率选择'),
    (36, 'GPIO.27', 'GPIO3_A5', 'GPIO', 'BUSY 接收状态'),
    (37, 'GPIO.25', 'GPIO3_A3', 'GPIO', '预留'),
    (38, 'GPIO.28', 'GPIO3_B1', 'GPIO', '预留'),
    (39, 'GND', 'GND', '地', 'BUSY 参考地'),
    (40, 'GPIO.29', 'GPIO3_A7', 'GPIO', '预留'),
]

p28 = [
    (1, 'VCC_3V3', '电源', '预留'),
    (2, 'VCC_5V', '电源', '预留'),
    (3, 'GND', '地', 'ADC 模拟地'),
    (4, 'GND', '地', 'ADC 模拟地'),
    (5, 'SARADC_VIN6', 'ADC', '光伏电压采集'),
    (6, 'SARADC_VIN4', 'ADC', '电池电压采集'),
    (7, 'SARADC_VIN7', 'ADC', '预留'),
    (8, 'SARADC_VIN5', 'ADC', '预留'),
    (9, 'GND', '地', '预留'),
    (10, 'GND', '地', '预留'),
    (11, 'GPIO4_B3', 'GPIO', '预留'),
    (12, 'GPIO4_B2', 'GPIO', '预留'),
    (13, 'GND', '地', '预留'),
    (14, 'GND', '地', '预留'),
    (15, 'GPIO3_C4', 'GPIO', '预留'),
    (16, 'GPIO3_C5', 'GPIO', '预留'),
    (17, 'GND', '地', '预留'),
    (18, 'GND', '地', '预留'),
    (19, 'PWM4', 'PWM', '预留'),
    (20, 'PWM2', 'PWM', '预留'),
]


def row_fill(kind, note):
    if any(k in note for k in ['RS485', '频率', 'PTT', 'BUSY', '光伏', '电池']):
        return '#d5e8d4'
    if kind in ('电源', 'PWR'):
        return '#fff2cc'
    if kind in ('地', 'GND'):
        return '#f2f2f2'
    if kind in ('I2C', 'SPI', 'UART', 'ADC'):
        return '#e6f0ff'
    return '#ffffff'


def esc(s):
    return escape(str(s), quote=False)


parts = []
W, H = 1900, 1650
parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
parts.append('''<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#444"/>
  </marker>
</defs>''')
parts.append('''<style>
  .bg{fill:#ffffff}
  .title{font-family:"Microsoft YaHei","Arial",sans-serif;font-size:28px;font-weight:bold;fill:#111;text-anchor:middle}
  .sub{font-family:"Microsoft YaHei","Arial",sans-serif;font-size:15px;fill:#333;text-anchor:middle}
  .th{font-family:"Microsoft YaHei","Arial",sans-serif;font-size:14px;font-weight:bold;fill:#111}
  .td{font-family:"Microsoft YaHei","Arial",sans-serif;font-size:13px;fill:#111}
  .small{font-family:"Microsoft YaHei","Arial",sans-serif;font-size:11px;fill:#444}
  .box{fill:#ffffff;stroke:#333;stroke-width:1.6}
  .panel{fill:#fafafa;stroke:#666;stroke-width:1.4}
  .line{stroke:#444;stroke-width:1.5;fill:none;marker-end:url(#arrow)}
  .thin{stroke:#777;stroke-width:1;fill:none}
</style>''')
parts.append('<rect x="0" y="0" width="1900" height="1650" class="bg"/>')
parts.append('<text x="950" y="42" class="title">ELF2 RK3588 40P / 20P 全引脚核对与中继硬件接线图</text>')
parts.append('<text x="950" y="72" class="sub">40Pin 电平 3.3V；20Pin SARADC 满量程 1.8V；P26 网络名取 3588（中间）网络；绿色=本项目使用，黄色=电源，灰色=GND，蓝色=预留复用</text>')

# P26 table
x0, y0 = 40, 110
row_h = 30
header_h = 36
block_w = 430
for bi, block in enumerate([p26[:20], p26[20:]]):
    bx = x0 + bi * (block_w + 10)
    parts.append(f'<rect x="{bx}" y="{y0}" width="{block_w}" height="{header_h + row_h * 20}" class="panel"/>')
    parts.append(f'<rect x="{bx}" y="{y0}" width="{block_w}" height="{header_h}" fill="#333"/>')
    parts.append(f'<text x="{bx+12}" y="{y0+24}" class="th" fill="#fff">P26 40Pin  {"1-20" if bi == 0 else "21-40"}</text>')
    parts.append(f'<text x="{bx+12}" y="{y0+58}" class="th">脚</text>')
    parts.append(f'<text x="{bx+50}" y="{y0+58}" class="th">丝印</text>')
    parts.append(f'<text x="{bx+135}" y="{y0+58}" class="th">RK3588 网络</text>')
    parts.append(f'<text x="{bx+265}" y="{y0+58}" class="th">本项目分配</text>')
    for i, (pin, std, net, kind, note) in enumerate(block):
        yy = y0 + header_h + i * row_h
        fill = row_fill(kind, note)
        parts.append(f'<rect x="{bx}" y="{yy}" width="{block_w}" height="{row_h}" fill="{fill}" stroke="#bbb" stroke-width="0.7"/>')
        parts.append(f'<text x="{bx+12}" y="{yy+20}" class="td">{pin}</text>')
        parts.append(f'<text x="{bx+50}" y="{yy+20}" class="td">{esc(std)}</text>')
        parts.append(f'<text x="{bx+135}" y="{yy+20}" class="td" font-weight="bold">{esc(net)}</text>')
        parts.append(f'<text x="{bx+265}" y="{yy+20}" class="small">{esc(note)}</text>')

# P28 table
x1 = 940
for bi, block in enumerate([p28[:10], p28[10:]]):
    bx = x1 + bi * (block_w + 10)
    parts.append(f'<rect x="{bx}" y="{y0}" width="{block_w}" height="{header_h + row_h * 10}" class="panel"/>')
    parts.append(f'<rect x="{bx}" y="{y0}" width="{block_w}" height="{header_h}" fill="#333"/>')
    parts.append(f'<text x="{bx+12}" y="{y0+24}" class="th" fill="#fff">P28 20Pin  {"1-10" if bi == 0 else "11-20"}</text>')
    parts.append(f'<text x="{bx+12}" y="{y0+58}" class="th">脚</text>')
    parts.append(f'<text x="{bx+58}" y="{y0+58}" class="th">RK3588 网络</text>')
    parts.append(f'<text x="{bx+210}" y="{y0+58}" class="th">类型</text>')
    parts.append(f'<text x="{bx+280}" y="{y0+58}" class="th">本项目分配</text>')
    for i, (pin, net, kind, note) in enumerate(block):
        yy = y0 + header_h + i * row_h
        fill = row_fill(kind, note)
        parts.append(f'<rect x="{bx}" y="{yy}" width="{block_w}" height="{row_h}" fill="{fill}" stroke="#bbb" stroke-width="0.7"/>')
        parts.append(f'<text x="{bx+12}" y="{yy+20}" class="td">{pin}</text>')
        parts.append(f'<text x="{bx+58}" y="{yy+20}" class="td" font-weight="bold">{esc(net)}</text>')
        parts.append(f'<text x="{bx+210}" y="{yy+20}" class="td">{esc(kind)}</text>')
        parts.append(f'<text x="{bx+280}" y="{yy+20}" class="small">{esc(note)}</text>')

# Bottom wiring overview
by = 810
parts.append(f'<text x="950" y="{by-18}" class="th" font-size="18" text-anchor="middle">外部接线总览（只画本项目实际使用引脚；完整未使用脚见上方全表）</text>')


def box(x, y, w, h, title, items, fill='#ffffff'):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" class="box" fill="{fill}"/>')
    parts.append(f'<text x="{x+w/2}" y="{y+24}" class="th" text-anchor="middle">{esc(title)}</text>')
    for i, it in enumerate(items):
        parts.append(f'<text x="{x+12}" y="{y+48+i*20}" class="small">{esc(it)}</text>')


box(40, by, 340, 430, 'ELF2 P26 选用引脚', [
    '8  UART9_TX  → RS485 DI',
    '10 UART9_RX  ← RS485 RO',
    '26 GPIO3_D2  → RS485 DE/RE(可选)',
    '1  VCC_3V3   → RS485 VCC',
    '6  GND       → RS485 GND',
    '29 GPIO3_B6  → PC0',
    '31 GPIO3_A6  → PC1',
    '33 GPIO3_A4  → PC2',
    '35 GPIO3_A0  → PC3',
    '32 GPIO3_A1  → PTT',
    '36 GPIO3_A5  ← BUSY',
    '30/34/39 GND → 控制板 GND',
], fill='#eef7ea')

box(410, by, 260, 430, '隔离 / 电平转换板', [
    '4×PC817 或 74LVC245：PC0-PC3',
    '1×光耦/NPN：PTT 驱动',
    '1×光耦：BUSY 输入隔离',
    'GPIO 侧 3.3V，控制板侧按实际',
    'BUSY 输出 10k 上拉 + 100nF',
    'PTT 默认释放，PC 默认全低',
], fill='#fff7e6')

box(700, by, 320, 430, '第三方中继控制板', [
    'PC0-PC3：频率/信道编码',
    'PTT：发射机使能',
    'BUSY：接收机状态',
    'MIC：来自 ELF2 音频输出',
    'SPK/DF：送往 ELF2 音频输入',
    'GND：与控制板共地',
], fill='#e6f0ff')

box(1060, by, 240, 150, 'TTL-RS485 模块', [
    'VCC：3.3V（P26-1）',
    'GND：P26-6',
    'DI：P26-8 UART9_TX',
    'RO：P26-10 UART9_RX',
    'DE/RE：P26-26（可选）',
], fill='#eef7ea')

box(1330, by, 240, 150, '气象站', [
    'Modbus RTU 从站',
    'A/B 双绞线',
    '9600 8N1',
    '120Ω 终端（长线）',
], fill='#f7f7f7')

box(1060, by+180, 240, 200, 'ADC 分压网络', [
    'SARADC_VIN6：P28-5 光伏',
    'SARADC_VIN4：P28-6 电池',
    '100k/12k → 电池',
    '100k/5.6k → 光伏',
    '100nF + 1k + 1.8V 钳位',
    '必须共地，禁止超 1.8V',
], fill='#e6f0ff')

box(1330, by+180, 240, 200, '电池 / 光伏', [
    '12V 电池：最高约 14.6V',
    '12V 光伏：Voc 约 22V',
    '分压后送 P28 ADC',
    '高压侧注意绝缘/爬电',
    '建议运放缓冲后进 ADC',
], fill='#f7f7f7')

box(1060, by+410, 240, 210, '音频隔离/衰减板', [
    'SPK/DF → 衰减 → 隔离 → MIC',
    'HP → 隔直 → 衰减 → MIC',
    '600:600Ω 音频变压器',
    '10uF 无极性耦合电容',
    '屏蔽线单端接地',
    'PTT 时建议静音/防自激',
], fill='#fff7e6')

box(1330, by+410, 240, 210, '3.5mm AUX / USB', [
    'ELF2 3.5mm CTIA 音频座',
    'Tip/Ring1：耳机输出',
    'Ring2：GND',
    'Sleeve：MIC 输入',
    'USB-A → USB UVC 摄像头',
    '远离天线/RF 功放',
], fill='#f7f7f7')

# arrows
parts.append(f'<path d="M380 {by+100} L410 {by+100}" class="line"/>')
parts.append(f'<path d="M670 {by+100} L700 {by+100}" class="line"/>')
parts.append(f'<path d="M1020 {by+100} L1060 {by+100}" class="line"/>')
parts.append(f'<path d="M1300 {by+75} L1330 {by+75}" class="line"/>')
parts.append(f'<path d="M1060 {by+300} L1000 {by+300} L1000 {by+430} L1020 {by+430}" class="line"/>')
parts.append(f'<path d="M1300 {by+280} L1330 {by+280}" class="line"/>')
parts.append(f'<path d="M1020 {by+515} L1060 {by+515}" class="line"/>')
parts.append(f'<text x="380" y="{by+96}" class="small" text-anchor="end">3.3V 信号</text>')
parts.append(f'<text x="675" y="{by+96}" class="small">隔离后</text>')

parts.append('</svg>')

out = Path('智能中继架构/ELF2_40P20P_接线核对图.svg')
out.write_text('\n'.join(parts), encoding='utf-8')
print(out, out.stat().st_size)
