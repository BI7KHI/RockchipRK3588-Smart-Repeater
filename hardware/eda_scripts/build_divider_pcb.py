#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 ELF2 分压采集板 PCB：元件放置、网表导入、板框、M3 孔、简单布线。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea
from build_divider import NETS

PCB = "55f721c46525bf2b"

# designator -> (library key, x, y, rotation)
PCB_COMPS = {
    "F1": ("1812L110/33GR", 700, 800, 0),
    "F2": ("1812L110/33GR", 700, 1562, 0),
    "D3": ("SMAJ15A", 900, 520, 90),
    "D4": ("SMAJ30A", 900, 1842, 90),
    "J1": ("DB128V-5.08-2P-GN-S", 400, 800, 0),
    "J2": ("DB128V-5.08-2P-GN-S", 400, 1562, 0),
    "R1": ("RT0805BRD07100KL", 1400, 700, 0),
    "R2": ("RT0805BRD0712KL", 1400, 980, 90),
    "C1": ("CL21B104KBCNNNC", 1700, 980, 0),
    "R3": ("0805W8F1001T5E", 2000, 800, 0),
    "C3": ("CL21B104KBCNNNC", 2300, 800, 0),
    "D1": ("MMSZ4678T1G", 2000, 1100, 90),
    "R4": ("RT0805BRD07100KL", 1400, 1382, 0),
    "R5": ("RT0805BRD075K6L", 1400, 1662, 90),
    "C2": ("CL21B104KBCNNNC", 1700, 1662, 0),
    "R6": ("0805W8F1001T5E", 2000, 1482, 0),
    "C4": ("CL21B104KBCNNNC", 2300, 1482, 0),
    "D2": ("MMSZ4678T1G", 2000, 1782, 90),
    "J3": ("PZ254V-11-03P", 3400, 1180, 0),
}

OUTLINE = [
    # (x1,y1,x2,y2) 4000 x 2362 mil ≈ 101.6 x 60 mm
    (100, 100, 3900, 100),
    (3900, 100, 3900, 2262),
    (3900, 2262, 100, 2262),
    (100, 2262, 100, 100),
]
M3 = [(200, 200), (3800, 200), (200, 2162), (3800, 2162)]  # 3.2mm = 126 mil


def clear_pcb():
    comps = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitiveComponent.getAll(); return JSON.stringify(a.map(x=>x.getState_PrimitiveId()));})()", t=60))
    if comps:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitiveComponent.delete(%s));})()" % json.dumps(comps), t=60)
    lines = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitiveLine.getAll(); return JSON.stringify(a.map(x=>x.getState_PrimitiveId()));})()", t=60))
    if lines:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitiveLine.delete(%s));})()" % json.dumps(lines), t=60)
    vias = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitiveVia.getAll(); return JSON.stringify(a.map(x=>x.getState_PrimitiveId()));})()", t=60))
    if vias:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitiveVia.delete(%s));})()" % json.dumps(vias), t=60)
    pours = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitivePour.getAll(); return JSON.stringify(a.map(x=>x.getState_PrimitiveId()));})()", t=60))
    if pours:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitivePour.delete(%s));})()" % json.dumps(pours), t=60)


def place_components():
    pcb_ids = {}
    for idx, (des, (key, x, y, rot)) in enumerate(PCB_COMPS.items(), start=1):
        devs = ea.search_device(key)
        if not devs:
            raise RuntimeError("device not found " + key)
        dev = devs[0]
        obj = {"libraryUuid": dev["libraryUuid"], "uuid": dev["uuid"], "name": dev["name"]}
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitiveComponent.create(%s,1,%s,%s,%s,false); return JSON.stringify({ok:true,id:r.getState_PrimitiveId()});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                % (json.dumps(obj), x, y, rot))
        r = json.loads(ea.js(expr, t=90))
        if not r.get("ok"):
            raise RuntimeError(f"pcb create {des}: {r}")
        pcb_ids[des] = r["id"]
        # 设置位号 + 与原理图一致的 Unique ID
        expr2 = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitiveComponent.modify(%s,{designator:%s,uniqueId:%s}); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                 % (json.dumps(r["id"]), json.dumps(des), json.dumps(f"gge{idx}")))
        mr = json.loads(ea.js(expr2, t=60))
        if not mr.get("ok"):
            print("modify designator fail", des, mr)
        time.sleep(0.25)
    return pcb_ids


def add_outline_holes():
    for (x1, y1, x2, y2) in OUTLINE:
        ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_PrimitiveLine.create('',11,%s,%s,%s,%s,10,false));})()" % (x1, y1, x2, y2), t=60)
    for (x, y) in M3:
        # 非金属化孔：用 PAD 方式不易，先留空；用过孔占位会镀铜。后续用 DRILL 处理。
        pass


def assign_pad_nets(pcb_ids):
    """直接给每个焊盘设置网络名。"""
    pin_net = {}
    for net, refs in NETS.items():
        for des, pin in refs:
            pin_net[(des, str(pin))] = net
    ok = 0
    for des, pid in pcb_ids.items():
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(%s); return JSON.stringify(a.map(p=>({id:p.getState_PrimitiveId(),num:String(p.getState_PadNumber())})));})()" % json.dumps(pid))
        pads = json.loads(ea.js(expr, t=60))
        for p in pads:
            net = pin_net.get((des, p["num"]))
            if not net:
                print("NO NET", des, p["num"])
                continue
            expr2 = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_PrimitivePad.modify(%s,{net:%s}); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                     % (json.dumps(p["id"]), json.dumps(net)))
            r = json.loads(ea.js(expr2, t=60))
            if r.get("ok"):
                ok += 1
            else:
                print("pad net fail", des, p["num"], net, r)
    print("assigned pads", ok)
    return ok


def set_netlist_from_file():
    with open("divider_netlist_stubs.json", encoding="utf-8") as f:
        netlist = f.read()
    expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.pcb_Net.setNetlist('JLCEDA',%s); return JSON.stringify({ok:true,r});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()" % json.dumps(netlist))
    return json.loads(ea.js(expr, t=120))


def main():
    ea.connect()
    ea.open_project("b363347f0b8c5bc8672339be6ece26e3d304b1ca776b46b7ed3631d2602f6b38")
    time.sleep(2)
    ea.open_doc(PCB)
    time.sleep(2)
    print("cur", ea.current_doc())
    clear_pcb()
    pcb_ids = place_components()
    add_outline_holes()
    assign_pad_nets(pcb_ids)
    # save
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_Document.save());})()", t=60)
    print("pcb ids", json.dumps(pcb_ids, ensure_ascii=False))
    # dump pad nets
    for des, pid in pcb_ids.items():
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const a=await R.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(%s); return JSON.stringify(a.map(p=>({num:p.getState_PadNumber(),net:p.getState_Net(),x:p.getState_X(),y:p.getState_Y()})));}catch(e){return JSON.stringify({err:String(e&&e.message||e)});}})()" % json.dumps(pid))
        print(des, ea.js(expr, t=60)[:800])


if __name__ == "__main__":
    main()
