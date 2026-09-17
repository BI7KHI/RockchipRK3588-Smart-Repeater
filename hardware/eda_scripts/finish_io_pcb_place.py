#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补齐 IO 隔离板 PCB 尚未放置的元件。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea
from build_io_sch import COMPS
from build_io_pcb import PCB_POS, PROJECT, PCB


def main():
    ea.connect()
    ea.open_project(PROJECT)
    time.sleep(2)
    ea.open_doc(PCB)
    time.sleep(2)
    comps = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitiveComponent.getAll(); return JSON.stringify(a.map(c=>({des:c.getState_Designator(),id:c.getState_PrimitiveId(),x:c.getState_X(),y:c.getState_Y()})));})()", t=60))
    present = {c["des"] for c in comps}
    ids = {c["des"]: c["id"] for c in comps}
    for idx, (des, key, _x, _y, _rot) in enumerate(COMPS, start=1):
        if des in present or des not in PCB_POS:
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
        print("placed", des)
    json.dump(ids, open("io_pcb_ids.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("present now", sorted(ids.keys()))
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.pcb_Document.save());})()", t=60)


if __name__ == "__main__":
    main()
