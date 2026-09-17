#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版式自检：SVG 元素是否越界 / 文本框是否溢出 / 方块是否重叠。"""
import re
import sys
import xml.etree.ElementTree as ET

NS = '{http://www.w3.org/2000/svg}'
path = sys.argv[1] if len(sys.argv) > 1 else 'architecture.svg'
root = ET.parse(path).getroot()
W = float(root.get('width'))
H = float(root.get('height'))
print('画布 %.0f x %.0f' % (W, H))

rects, texts, problems = [], [], []
for el in root.iter():
    tag = el.tag.replace(NS, '')
    if tag == 'rect':
        r = {k: float(el.get(k, 0)) for k in ('x', 'y', 'width', 'height')}
        r['stroke'] = el.get('stroke', '')
        rects.append(r)
    elif tag == 'text':
        texts.append({'x': float(el.get('x', 0)), 'y': float(el.get('y', 0)),
                      'size': float(el.get('font-size', 12)), 'anchor': el.get('text-anchor', 'start'),
                      's': el.text or ''})


def width_of(s, size):
    w = 0.0
    for ch in s:
        w += size * (1.0 if ord(ch) > 0x2e80 else 0.56)
    return w


# 1) 越界检查
for r in rects:
    if r['x'] < 0 or r['y'] < 0 or r['x'] + r['width'] > W + 0.5 or r['y'] + r['height'] > H + 0.5:
        problems.append('矩形越界: %s' % r)
for t in texts:
    if t['x'] < -1 or t['x'] > W + 1 or t['y'] < 0 or t['y'] > H + 1:
        problems.append('文本越界: %r @%.0f,%.0f' % (t['s'][:20], t['x'], t['y']))

# 2) 小方块重叠检查（band 背景 rect 宽>1200 或高>200 视为容器）
small = [r for r in rects if r['width'] <= 600 and r['height'] <= 130]
for i in range(len(small)):
    for j in range(i + 1, len(small)):
        a, b = small[i], small[j]
        ox = min(a['x'] + a['width'], b['x'] + b['width']) - max(a['x'], b['x'])
        oy = min(a['y'] + a['height'], b['y'] + b['height']) - max(a['y'], b['y'])
        if ox > 2 and oy > 2:
            problems.append('方块重叠: (%.0f,%.0f,%.0fx%.0f) <-> (%.0f,%.0f,%.0fx%.0f)'
                            % (a['x'], a['y'], a['width'], a['height'],
                               b['x'], b['y'], b['width'], b['height']))

# 3) 文本溢出所属方块（取文本中心所在的最近方块）
for t in texts:
    for r in small:
        if (r['x'] <= t['x'] <= r['x'] + r['width']) and (r['y'] - t['size'] <= t['y'] <= r['y'] + r['height']):
            w = width_of(t['s'], t['size'])
            avail = r['width'] - 16
            if w > avail:
                problems.append('文本可能溢出: %r 需 %.0f 可用 %.0f (框 %.0f 宽)' %
                                (t['s'][:26], w, avail, r['width']))
            break

if problems:
    print('发现 %d 个问题:' % len(problems))
    for p in problems[:25]:
        print('  -', p)
else:
    print('版式自检通过：无越界/重叠/溢出')
print('统计：矩形 %d，文本 %d' % (len(rects), len(texts)))
