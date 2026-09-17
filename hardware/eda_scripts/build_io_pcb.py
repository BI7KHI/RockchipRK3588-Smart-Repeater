#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IO 隔离板 PCB：元件放置 + 焊盘网络分配 + 板框/M3 孔。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea
from build_io_sch import COMPS
from wire_io_sch import NETS_IO

PROJECT = "e10fadeebbaba5d570f87dd94a16437176b2e7e3ecbf0c51e3ad48b96cccb64f"
PCB = "55f721c46525bf2b"

PCB_POS = {
    # y = 3400 行：电源输入/隔离电源
    "J1": (300, 3400), "F1": (700, 3400), "D1": (1000, 3400), "U1": (1500, 3400),
    "C3": (1900, 3400), "C4": (2200, 3400), "J2": (2600, 3400),
    # y = 2900 行
    "C1": (300, 2900), "C2": (600, 2900), "U2": (1000, 2900), "C5": (1400, 2900),
    "C6": (1700, 2900),
    # y = 2400 行：接口/数字隔离
    "J3": (300, 2400), "J8": (700, 2400), "U4": (1100, 2400), "U5": (1500, 2400),
    "U6": (1900, 2400), "C9": (2300, 2400),
    # y = 1900 行
    "C10": (300, 1900), "C11": (600, 1900), "C12": (900, 1900), "C13": (1200, 1900),
    "C14": (1500, 1900), "U3": (1900, 1900),
    # y = 1400 行：RS485 与接口
    "C7": (300, 1400), "C8": (600, 1400), "R1": (900, 1400), "J4": (1300, 1400),
    "J5": (1700, 1400), "J6": (2100, 1400),
    # y = 900 行：音频
    "RV1": (300, 900), "RV2": (600, 900), "C15": (900, 900), "C16": (1200, 900),
    "R2": (1500, 900), "R3": (1800, 900),
    # y = 400 行
    "R4": (300, 400), "J7": (600, 400),
}

M3 = [(150, 150), (3787, 150), (150, 3787), (3787, 3787)]
OUTLINE = [(100, 100, 3837, 100), (3837, 100, 3837, 3837), (3837, 3837, 100, 3837), (100, 3837, 100, 100)]


def clear_pcb():
    for cls in ["pcb_PrimitiveComponent", "pcb_PrimitiveLine", "pcb_PrimitiveVia", "pcb_PrimitivePour"]:
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.%s.getAll(); return JSON.stringify(a.map(x=>x.getState_PrimitiveId?x.getState_PrimitiveId():x.primitiveId));})()" % cls)
        ids = json.loads(ea.js(expr, t=60))
        if ids:
            ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.%s.delete(%s));})()" % (cls, json.dumps(ids)), t=60)


def place_components():
    ids = {}
    for idx, (des, key, _x, _y, _rot) in enumerate(COMPS, start=1):
        if des not in PCB_POS:
            print("no pos", des)
            continue
        x, y = PCB_POS[des]
        devs = ea.search_device(key)
        if not devs:
            print("not found", key)
            continue
        dev = devs[0]
        obj = {"libraryUuid": dev["libraryUuid"], "uuid": dev["uuid"], "name": dev["name"]}
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitiveComponent.create(%s,1,%s,%s,0,false); return JSON.stringify({ok:true,id:r.getState_PrimitiveId()});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                % (json.dumps(obj), x, y))
        r = json.loads(ea.js(expr, t=60))
        if not r.get("ok"):
            print("create fail", des, r)
            continue
        ids[des] = r["id"]
        expr2 = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitiveComponent.modify(%s,{designator:%s,uniqueId:%s}); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                 % (json.dumps(r["id"]), json.dumps(des), json.dumps(f"io{idx:03d}")))
        mr = json.loads(ea.js(expr2, t=60))
        if not mr.get("ok"):
            print("modify fail", des, mr)
        time.sleep(0.15)
    return ids


def assign_nets(ids):
    pin_net = {}
    for net, refs in NETS_IO.items():
        for des, pin in refs:
            pin_net[(des, str(pin))] = net
    total = 0
    unassigned = []
    for des, pid in ids.items():
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(%s); return JSON.stringify(a.map(p=>({id:p.getState_PrimitiveId(),num:String(p.getState_PadNumber())})));})()" % json.dumps(pid))
        pads = json.loads(ea.js(expr, t=60))
        for p in pads:
            net = pin_net.get((des, p["num"]))
            if not net:
                unassigned.append((des, p["num"]))
                continue
            expr2 = ("(async()=>{const R=window._EXTAPI_ROOT_; try{await R.pcb_PrimitivePad.modify(%s,{net:%s}); return 'ok';}catch(e){return 'err';}})()" % (json.dumps(p["id"]), json.dumps(net)))
            ea.js(expr2, t=30)
            total += 1
    print("assigned", total, "unassigned", unassigned)


def add_outline_m3():
    for x1, y1, x2, y2 in OUTLINE:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitiveLine.create('',11,%s,%s,%s,%s,10,false));})()" % (x1, y1, x2, y2), t=30)
    for x, y in M3:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitivePad.create(12,'',%s,%s,0,['ELLIPSE',0,0,0],'',['ROUND',126],0,0,0,false,0,null,null,null,false));})()" % (x, y), t=30)


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "place"
    ea.connect()
    ea.open_project(PROJECT)
    time.sleep(2)
    ea.open_doc(PCB)
    time.sleep(2)
    print("cur", ea.current_doc())
    if stage == "clear":
        clear_pcb()
    elif stage == "place":
        clear_pcb()
        ids = place_components()
        json.dump(ids, open("io_pcb_ids.json", "w", encoding="utf-8"), ensure_ascii=False)
    elif stage == "nets":
        ids = json.load(open("io_pcb_ids.json", encoding="utf-8"))
        assign_nets(ids)
    elif stage == "outline":
        add_outline_m3()
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_Document.save());})()", t=60)
    print("done", stage)
