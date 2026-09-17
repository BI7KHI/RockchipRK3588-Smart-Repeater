#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IO 隔离板：用 NetFlag（网络标签）直接连接每个引脚，避免短桩合并。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea
import wire_io_sch as wi

PROJECT = "e10fadeebbaba5d570f87dd94a16437176b2e7e3ecbf0c51e3ad48b96cccb64f"
PAGE = "ea4fc07c502623a3"


def main():
    ea.connect()
    ea.open_project(PROJECT)
    time.sleep(2)
    ea.open_doc(PAGE)
    time.sleep(2)
    print("cur", ea.current_doc())
    # 删除旧走线
    wires = ea.get_wires()
    if wires:
        ea.delete_wires([w["primitiveId"] for w in wires])
    # 获取引脚坐标
    comps = ea.get_components()
    pinmap = {}
    for c in comps:
        if c.get("componentType") != "part":
            continue
        for p in ea.get_pins(c["primitiveId"]):
            pinmap[(c["designator"], str(p["pinNumber"]))] = (p["x"], p["y"])
    created = 0
    missing = []
    for net, refs in wi.NETS_IO.items():
        for des, pin in refs:
            p = pinmap.get((des, str(pin)))
            if not p:
                missing.append((net, des, pin))
                continue
            expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.sch_PrimitiveComponent.createNetFlag('Power',%s,%s,%s,0,false); return JSON.stringify({ok:true,id:r.getState_PrimitiveId?r.getState_PrimitiveId():null});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                    % (json.dumps(net), p[0], p[1]))
            r = json.loads(ea.js(expr, t=60))
            if r.get("ok"):
                created += 1
            else:
                print("flag fail", net, des, pin, r)
            time.sleep(0.02)
    print("created flags", created, "missing", missing)
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=60)


if __name__ == "__main__":
    main()
