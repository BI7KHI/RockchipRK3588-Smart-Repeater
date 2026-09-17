#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 ELF2 分压采集板原理图（嘉立创EDA专业版）。

- 电池 14V 典型，PV 25V 开路；
- T 形电阻分压 + RC 滤波 + 钳位保护；
- 0805 电阻电容；
- 输出 BAT_ADC / PV_ADC / GND 给 ELF2 ADC。
"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea

PROJECT = "b363347f0b8c5bc8672339be6ece26e3d304b1ca776b46b7ed3631d2602f6b38"
PAGE = "ea4fc07c502623a3"

# designator, library key, x, y, rotation
COMPS = [
    ("F1", "1812L110/33GR", 150, 200, 0),
    ("F2", "1812L110/33GR", 150, 520, 0),
    ("D3", "SMAJ15A", 250, 110, 0),
    ("D4", "SMAJ30A", 250, 610, 0),
    ("J1", "DB128V-5.08-2P-GN-S", 80, 260, 0),
    ("J2", "DB128V-5.08-2P-GN-S", 80, 580, 0),
    ("R1", "RT0805BRD07100KL", 400, 180, 0),
    ("R2", "RT0805BRD0712KL", 400, 300, 0),
    ("C1", "CL21B104KBCNNNC", 500, 300, 0),
    ("R3", "0805W8F1001T5E", 600, 240, 0),
    ("C3", "CL21B104KBCNNNC", 700, 240, 0),
    ("D1", "MMSZ4678T1G", 600, 350, 0),
    ("R4", "RT0805BRD07100KL", 400, 540, 0),
    ("R5", "RT0805BRD075K6L", 400, 660, 0),
    ("C2", "CL21B104KBCNNNC", 500, 660, 0),
    ("R6", "0805W8F1001T5E", 600, 600, 0),
    ("C4", "CL21B104KBCNNNC", 700, 600, 0),
    ("D2", "MMSZ4678T1G", 600, 710, 0),
    ("J3", "PZ254V-11-03P", 950, 420, 0),
]

# net -> list of (designator, pin_number)
NETS = {
    "BAT_POS": [("J1", "1"), ("F1", "1")],
    "BAT_FUSED": [("F1", "2"), ("D3", "1"), ("R1", "1")],
    "BAT_DIV": [("R1", "2"), ("R2", "1"), ("C1", "1"), ("R3", "1")],
    "BAT_ADC": [("R3", "2"), ("C3", "1"), ("D1", "1"), ("J3", "1")],
    "PV_POS": [("J2", "1"), ("F2", "1")],
    "PV_FUSED": [("F2", "2"), ("D4", "1"), ("R4", "1")],
    "PV_DIV": [("R4", "2"), ("R5", "1"), ("C2", "1"), ("R6", "1")],
    "PV_ADC": [("R6", "2"), ("C4", "1"), ("D2", "1"), ("J3", "2")],
    "GND": [
        ("J1", "2"), ("D3", "2"), ("R2", "2"), ("C1", "2"), ("C3", "2"), ("D1", "2"),
        ("J2", "2"), ("D4", "2"), ("R5", "2"), ("C2", "2"), ("C4", "2"), ("D2", "2"),
        ("J3", "3"),
    ],
}

HUBS = {
    "BAT_POS": (110, 230),
    "BAT_FUSED": (260, 170),
    "BAT_DIV": (500, 260),
    "BAT_ADC": (720, 300),
    "PV_POS": (110, 550),
    "PV_FUSED": (260, 560),
    "PV_DIV": (500, 620),
    "PV_ADC": (720, 640),
    "GND": (500, 780),
}


def place_components():
    designator_ids = {}
    for des, key, x, y, rot in COMPS:
        devs = ea.search_device(key)
        if not devs:
            raise RuntimeError(f"device not found: {key}")
        dev = devs[0]
        r = ea.create_component(dev, x, y, rot, subpart=f"{key}.1")
        if not r.get("ok"):
            raise RuntimeError(f"create failed {des}: {r}")
        designator_ids[des] = r["id"]
        time.sleep(0.25)
    # 设置位号和唯一 ID
    for idx, (des, _key, _x, _y, _rot) in enumerate(COMPS, start=1):
        cid = designator_ids[des]
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.sch_PrimitiveComponent.modify(%s,{designator:%s,uniqueId:%s}); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                % (json.dumps(cid), json.dumps(des), json.dumps(f"gge{idx}")))
        res = json.loads(ea.js(expr, t=60))
        if not res.get("ok"):
            print("modify fail", des, res)
    return designator_ids


def build_pin_map(designator_ids):
    pin_map = {}
    for des, cid in designator_ids.items():
        pins = ea.get_pins(cid)
        pin_map[des] = {p["pinNumber"]: (p["x"], p["y"], p["pinName"]) for p in pins}
    return pin_map


def route_star(net, pins, hub):
    """从每个引脚拉一条折线到 hub，形成星形连接。"""
    hx, hy = hub
    for (px, py) in pins:
        if abs(px - hx) < 1 and abs(py - hy) < 1:
            continue
        if abs(px - hx) < 1 or abs(py - hy) < 1:
            line = [px, py, hx, hy]
        else:
            line = [px, py, px, hy, hx, hy]
        r = json.loads(ea.create_wire(line, net))
        if not r.get("ok"):
            print("wire fail", net, line, r)


def main():
    ea.connect()
    ea.open_project(PROJECT)
    time.sleep(2)
    ea.open_doc(PAGE)
    time.sleep(2)
    print("clear:", ea.clear_schematic())
    ids = place_components()
    pin_map = build_pin_map(ids)
    # 输出引脚映射，便于核对
    print(json.dumps(pin_map, ensure_ascii=False, indent=2))
    # 连线
    for net, refs in NETS.items():
        pts = []
        missing = []
        for des, pin in refs:
            p = pin_map.get(des, {}).get(pin)
            if p:
                pts.append((p[0], p[1]))
            else:
                missing.append((des, pin))
        if missing:
            print("MISSING PINS", net, missing)
        route_star(net, pts, HUBS[net])
        time.sleep(0.05)
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=60)
    print("done")


if __name__ == "__main__":
    main()
