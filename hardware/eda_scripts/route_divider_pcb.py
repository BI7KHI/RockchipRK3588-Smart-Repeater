#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分压采集板 PCB 布线：顶层信号线 + 底层 GND 铺铜。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea

PCB = "55f721c46525bf2b"

# 顶层信号走线：net -> [[x1,y1],[x2,y2],...] 折线
# 顶层信号走线：net -> 多条折线路径（每条路径为 [[x,y],...]）
TRACKS = {
    "BAT_POS": [
        [[300, 800], [300, 700], [627, 700], [627, 800]],
    ],
    "BAT_FUSED": [
        [[773, 800], [800, 800], [800, 433.7], [1360.6, 433.7], [1360.6, 700]],
    ],
    "BAT_DIV": [
        [[1439.4, 700], [1400, 700], [1400, 940.6], [1660.6, 940.6], [1660.6, 980]],
        [[1660.6, 940.6], [1960.6, 940.6], [1960.6, 800]],
    ],
    "BAT_ADC": [
        [[2039.4, 800], [2260.6, 800], [2260.6, 1033.4], [2000, 1033.4]],
        [[2260.6, 1033.4], [3300, 1033.4], [3300, 1180]],
    ],
    "PV_POS": [
        [[300, 1562], [300, 1462], [627, 1462], [627, 1562]],
    ],
    "PV_FUSED": [
        [[773, 1562], [800, 1562], [800, 1755.4], [1360.6, 1755.4], [1360.6, 1382]],
    ],
    "PV_DIV": [
        [[1439.4, 1382], [1400, 1382], [1400, 1622.6], [1660.6, 1622.6], [1660.6, 1662]],
        [[1660.6, 1622.6], [1960.6, 1622.6], [1960.6, 1482]],
    ],
    "PV_ADC": [
        [[2039.4, 1482], [2260.6, 1482], [2260.6, 1715.4], [2000, 1715.4]],
        [[2260.6, 1715.4], [3400, 1715.4], [3400, 1180]],
    ],
}


M3 = [(200, 200), (3800, 200), (200, 2162), (3800, 2162)]  # 3.2mm = 126 mil


def add_m3_holes():
    # 删除旧 M3 孔（无位号、无网络的非金属化孔）
    expr = "(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitivePad.getAll(); return JSON.stringify(a.filter(p=>p.getState_PadNumber()===''&&p.getState_Hole()!=null).map(p=>p.getState_PrimitiveId()));})()"
    old = json.loads(ea.js(expr, t=60))
    if old:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitivePad.delete(%s));})()" % json.dumps(old), t=60)
    for (x, y) in M3:
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitivePad.create(12,'',%s,%s,0,['ELLIPSE',0,0,0],'',['ROUND',126],0,0,0,false,0,null,null,null,false); return JSON.stringify({ok:true,id:r.getState_PrimitiveId()});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()" % (x, y))
        r = json.loads(ea.js(expr, t=60))
        if not r.get("ok"):
            print("M3 fail", x, y, r)


def add_track(net, pts, width=12, layer=1):
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
            continue
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitiveLine.create(%s,%s,%s,%s,%s,%s,%s,false); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                % (json.dumps(net), layer, x1, y1, x2, y2, width))
        r = json.loads(ea.js(expr, t=60))
        if not r.get("ok"):
            print("track fail", net, (x1, y1, x2, y2), r)


def main():
    ea.connect()
    ea.open_project("b363347f0b8c5bc8672339be6ece26e3d304b1ca776b46b7ed3631d2602f6b38")
    time.sleep(1)
    ea.open_doc(PCB)
    time.sleep(2)
    print("cur", ea.current_doc())
    # 清掉旧走线/过孔/铺铜，保留元件与板框
    for cls in ["pcb_PrimitiveLine", "pcb_PrimitiveVia", "pcb_PrimitivePour"]:
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.%s.getAll(); return JSON.stringify(a.map(x=>x.getState_PrimitiveId()));})()" % cls)
        ids = json.loads(ea.js(expr, t=60))
        if ids:
            ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.%s.delete(%s));})()" % (cls, json.dumps(ids)), t=60)
    # 板框重新画
    for x1, y1, x2, y2 in [(100, 100, 3900, 100), (3900, 100, 3900, 2262), (3900, 2262, 100, 2262), (100, 2262, 100, 100)]:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitiveLine.create('',11,%s,%s,%s,%s,10,false));})()" % (x1, y1, x2, y2), t=60)
    add_m3_holes()
    # 信号线
    for net, paths in TRACKS.items():
        for pts in paths:
            add_track(net, pts)
    # GND 过孔 + 底层地线
    # (pad_x, pad_y, via_x, via_y, 是否 SMD 需要顶层短桩)
    gnd_pads = [
        (500, 800, 500, 800, False),      # J1.2 THT
        (900, 606.3, 900, 556.3, True),   # D3.2 SMD
        (1400, 1019.4, 1400, 1069.4, True),
        (1739.4, 980, 1739.4, 1030, True),
        (2000, 1166.6, 2000, 1216.6, True),
        (2339.4, 800, 2339.4, 850, True),
        (3500, 1180, 3500, 1180, False),  # J3.3 THT
        (500, 1562, 500, 1562, False),    # J2.2 THT
        (900, 1928.6, 900, 1988.6, True),
        (1400, 1701.4, 1400, 1751.4, True),
        (1739.4, 1662, 1739.4, 1712, True),
        (2339.4, 1482, 2339.4, 1532, True),
        (2000, 1848.6, 2000, 1898.6, True),
    ]
    for (px, py, vx, vy, smd) in gnd_pads:
        if smd:
            expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitiveVia.create('GND',%s,%s,12,24); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()" % (vx, vy))
            r = json.loads(ea.js(expr, t=60))
            if not r.get("ok"):
                print("via fail", px, py, r)
            add_track("GND", [[px, py], [vx, vy]], width=12, layer=1)
    # 底层 GND 母线：电池侧 y=1100，PV 侧 y=1600，并连接两侧
    gnd_bus = [
        [500, 800], [500, 1100], [900, 1100], [900, 556.3],
        [1400, 1100], [1400, 1069.4], [1739.4, 1100], [1739.4, 1030],
        [2000, 1100], [2000, 1216.6], [2339.4, 1100], [2339.4, 850],
        [3500, 1100], [3500, 1180],
    ]
    for i in range(len(gnd_bus) - 1):
        add_track("GND", [gnd_bus[i], gnd_bus[i + 1]], width=16, layer=2)
    pv_bus = [
        [500, 1562], [500, 1600], [900, 1600], [900, 1988.6],
        [1400, 1600], [1400, 1751.4], [1739.4, 1600], [1739.4, 1712],
        [2000, 1600], [2000, 1898.6], [2339.4, 1600], [2339.4, 1532],
        [1400, 1600], [1400, 1100],
    ]
    for i in range(len(pv_bus) - 1):
        add_track("GND", [pv_bus[i], pv_bus[i + 1]], width=16, layer=2)
    # 底层 GND 铺铜
    pour_expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const poly=R.pcb_MathPolygon.createPolygon(['R',120,2242,3760,2122,0,30]); const r=await R.pcb_PrimitivePour.create('GND',2,poly,'solid',false,'GND_POUR',1,10,false); return JSON.stringify({ok:true,id:r.getState_PrimitiveId?r.getState_PrimitiveId():null});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()")
    print("pour", ea.js(pour_expr, t=60))
    time.sleep(1)
    # 回填铺铜
    expr = """(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitivePour.getAll(); for(const p of a){try{const r=p.rebuildCopperRegion(); if(r&&r.then) await r.catch(()=>{});}catch(e){}} await new Promise(r=>setTimeout(r,1200)); await R.pcb_Document.save(); return 'ok';})()"""
    print("rebuild", ea.js(expr, t=120))
    print("done")


if __name__ == "__main__":
    main()
