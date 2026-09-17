#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 IO 隔离板原理图的网表直接设置为目标连接（绕过短桩合并问题）。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea
import wire_io_sch as wi

PROJECT = "e10fadeebbaba5d570f87dd94a16437176b2e7e3ecbf0c51e3ad48b96cccb64f"
PAGE = "ea4fc07c502623a3"
NETLIST = "io_netlist_stubs2.json"


def main():
    ea.connect()
    ea.open_project(PROJECT)
    time.sleep(2)
    ea.open_doc(PAGE)
    time.sleep(2)
    # 目标 pin -> net
    target = {}
    for net, refs in wi.NETS_IO.items():
        for des, pin in refs:
            target[(des, str(pin))] = net
    # 以当前导出的网表为骨架，改 pin net
    obj = json.load(open(NETLIST, encoding="utf-8"))
    changed = 0
    for uid, comp in obj.get("components", {}).items():
        des = comp.get("props", {}).get("Designator")
        for pn, pinfo in comp.get("pinInfoMap", {}).items():
            want = target.get((des, str(pn)), "")
            if pinfo.get("net") != want:
                pinfo["net"] = want
                changed += 1
    text = json.dumps(obj, ensure_ascii=False)
    expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.sch_Netlist.setNetlist('JLCEDA',%s); return JSON.stringify({ok:true,r});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()" % json.dumps(text))
    print("set", ea.js(expr, t=120))
    print("changed pins", changed)
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=60)


if __name__ == "__main__":
    main()
