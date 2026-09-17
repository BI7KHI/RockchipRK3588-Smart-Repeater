#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成项目架构图（纯手写 SVG，无外部依赖）。

    python3 make_architecture_svg.py > ../assets/architecture.svg
"""
import html
from pathlib import Path

W, H = 1280, 1060
BG, PANEL, PANEL2, LINE = '#0b1220', '#151d2e', '#1c2740', '#2b3a5c'
TEXT, MUTED = '#e8eefc', '#93a4c8'
PRIMARY, GREEN, AMBER, PINK, CYAN = '#4a6cf7', '#2ecc71', '#f5a623', '#e06c9f', '#35c5d8'

out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
       f'font-family="Microsoft YaHei, Noto Sans SC, Segoe UI, sans-serif">',
       f'<rect width="{W}" height="{H}" fill="{BG}"/>', '<defs>',
       f'<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
       f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{MUTED}"/></marker>',
       f'<marker id="ar2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
       f'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{GREEN}"/></marker>',
       '</defs>']


def esc(s):
    return html.escape(str(s))


def text(x, y, s, size=13, fill=TEXT, anchor='start', weight='normal'):
    out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
               f'font-weight="{weight}">{esc(s)}</text>')


def box(x, y, w, h, title, sub='', color=PRIMARY, tsize=14, ssize=11, fill=PANEL):
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" '
               f'stroke="{color}" stroke-width="1.4"/>')
    cx = x + w / 2
    if sub:
        text(cx, y + h / 2 - 2, title, tsize, TEXT, 'middle', 'bold')
        text(cx, y + h / 2 + 16, sub, ssize, MUTED, 'middle')
    else:
        text(cx, y + h / 2 + 5, title, tsize, TEXT, 'middle', 'bold')


def band(y, h, cn, en, color):
    out.append(f'<rect x="36" y="{y}" width="{W - 72}" height="{h}" rx="14" fill="{PANEL2}" '
               f'opacity="0.35" stroke="{LINE}" stroke-width="1"/>')
    out.append(f'<rect x="36" y="{y}" width="7" height="{h}" rx="3.5" fill="{color}"/>')
    text(56, y + 24, cn, 15, TEXT, 'start', 'bold')
    text(56, y + 42, en, 11, MUTED)


def arrow(x1, y1, x2, y2, label='', color=MUTED, dash='', lx=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.6" '
               f'marker-end="url(#{"ar2" if color == GREEN else "ar"})"{d}/>')
    if label:
        text(lx if lx is not None else (x1 + x2) / 2 + 10, (y1 + y2) / 2 + 4, label, 11, color)


# ---------------------------------------------------------------- 标题
text(36, 46, 'RK3588 智能无线电中继系统 · 总体架构', 24, TEXT, 'start', 'bold')
text(36, 70, 'Rockchip RK3588 Smart Radio Repeater — System Architecture', 13, MUTED)
text(W - 36, 44, 'ELF2(RK3588) · 收发分离双天线 · 端侧 LLM/Agent/TTS', 12, MUTED, 'end')
text(W - 36, 64, 'Dual-antenna TX/RX · On-device LLM/TTS · Fully isolated IO', 12, MUTED, 'end')

# ---------------------------------------------------------------- ① 接入层
band(90, 100, '① 接入层', 'Clients / HTTPS Web Console', CYAN)
box(300, 140, 320, 40, '手机 / PC 浏览器 · Browser', '', CYAN, 13)
box(660, 140, 320, 40, 'HTTPS 控制台 / 实时对讲 / LLM 对话', '', CYAN, 12)
arrow(620, 160, 660, 160)
arrow(480, 190, 480, 222, 'HTTPS · eth0 100M', CYAN)

# ---------------------------------------------------------------- ② RK3588
band(222, 320, '② 端侧主控 RK3588（ELF2）', 'Edge Controller · Ubuntu 22.04 · Python 3.10 · Flask + nginx', PRIMARY)
out.append(f'<rect x="118" y="288" width="{W - 236}" height="236" rx="12" fill="none" '
           f'stroke="{LINE}" stroke-width="1" stroke-dasharray="4 4"/>')
feat = [
    ('Web 控制中心', 'Flask · 账号/审计/CSRF', PRIMARY),
    ('端侧 LLM + Agent', 'Qwen2.5-1.5B RKNPU · 8 技能', PINK),
    ('端侧 TTS / ASR', 'Piper 合成 · SenseVoice 识别', GREEN),
    ('摄像头 / 录像', 'V4L2 MJPEG · ffmpeg', AMBER),
    ('SARADC 电压采集', '12bit · 电池 CH4 / 光伏 CH6', CYAN),
    ('RS485 Modbus', '风速变送器 + 翻斗雨量计', CYAN),
    ('ALSA 音频链路', 'NAU8822 · 3.5mm AUX / MIC', GREEN),
    ('PTT 控制', 'GPIO3_A1 = 全局 GPIO 97', PINK),
]
bw, bh, gapx, gapy = 258, 86, 14, 18
x0, y0 = 132, 300
for i, (t, s, c) in enumerate(feat):
    box(x0 + (i % 4) * (bw + gapx), y0 + (i // 4) * (bh + gapy), bw, bh, t, s, c, 14, 11)

arrow(430, 542, 430, 574, 'GPIO·PTT / AUX 音频 / ADC 分压', PRIMARY)
arrow(700, 542, 700, 574, 'RS485 / 摄像头 / 调试口', PRIMARY)

# ---------------------------------------------------------------- ③ 隔离板
band(574, 120, '③ IO 隔离 / 驱动板（自研 PCB）', 'Isolation & Driver Board (custom)', AMBER)
iso = [('数字量光耦隔离', 'PC0–PC3 · 5V ↔ 3.3V', AMBER), ('PTT 隔离驱动', '3.3V → 低有效 PTT', AMBER),
       ('音频隔离 / 衰减', '隔离变压器 + 分压网络', AMBER), ('隔离电源 / RS485', '隔离 12V · 数字隔离器', AMBER)]
for i, (t, s, c) in enumerate(iso):
    box(132 + i * 272, 624, 250, 56, t, s, c, 13, 11)

arrow(430, 694, 430, 726, '隔离 PTT / 音频 IN·OUT', AMBER)
arrow(880, 694, 880, 726, '隔离 12V 供电', AMBER, '5 4')

# ---------------------------------------------------------------- ④ 控制板
band(726, 120, '④ 中继控制板（第三方）', 'Repeater Control Board', PINK)
for i, (t, s) in enumerate([('PTT 输入', '有效极性需匹配 GM3188'), ('收发切换', 'TX / RX 互斥'),
                            ('音频路由', 'MIC / SPK 分配')]):
    box(300 + i * 290, 776, 262, 56, t, s, PINK, 13, 11)

arrow(560, 846, 560, 878, 'PTT + MIC/SPK', PINK)
arrow(900, 846, 900, 878, 'RF 射频', PINK)

# ---------------------------------------------------------------- ⑤ 电台
band(878, 128, '⑤ 电台与天线（收发分离）', 'Radios & Antennas (separate TX / RX)', GREEN)
box(300, 928, 300, 58, 'RX 电台 · GM3188', '音频 → RK3588 MIC', GREEN, 13, 11)
box(650, 928, 300, 58, 'TX 电台 · GM3188', 'RK3588 AUX → 发射', GREEN, 13, 11)
text(965, 950, '↗ 天线 1 / ANT1', 12, MUTED)
text(965, 970, '↗ 天线 2 / ANT2', 12, MUTED)

# ---------------------------------------------------------------- 电源
text(36, 1040, '电源 / Power：14V 锂电池 · 25V 光伏 → IO 板隔离 12V → 中继控制板 / 电台',
     13, MUTED)
out.append('</svg>')

dest = Path(__file__).with_name('architecture.svg')
dest.write_text('\n'.join(out), encoding='utf-8')
print('wrote %s (%d bytes, %d elements)' % (dest.name, dest.stat().st_size, len(out)))
