#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 ELF2 IO 隔离板原理图元件并输出引脚映射。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea

PROJECT = "e10fadeebbaba5d570f87dd94a16437176b2e7e3ecbf0c51e3ad48b96cccb64f"
PAGE = "ea4fc07c502623a3"

COMPS = [
    # 电源
    ("J1", "DB128V-5.08-2P-GN-S", 150, 120, 0),
    ("F1", "1812L110/33GR", 380, 120, 0),
    ("D1", "SMAJ15A", 610, 120, 0),
    ("U1", "VRB1212S-6WR3", 840, 120, 0),
    ("C3", "CL21B104KBCNNNC", 1070, 120, 0),
    ("C4", "CL21A106KAYNNNE", 1300, 120, 0),
    ("C1", "CL21B104KBCNNNC", 150, 320, 0),
    ("C2", "CL21A106KAYNNNE", 380, 320, 0),
    ("U2", "VRB1203S-6WR3", 610, 320, 0),
    ("C5", "CL21B104KBCNNNC", 840, 320, 0),
    ("C6", "CL21A106KAYNNNE", 1070, 320, 0),
    ("J2", "DB128V-5.08-2P-GN-S", 1300, 320, 0),
    # ELF2 接口
    ("J3", "PZ254V-11-10P", 150, 520, 0),
    ("J8", "PZ254V-11-02P", 380, 520, 0),
    ("U4", "ADUM1200CRZ-RL7", 610, 520, 0),
    ("U5", "ADUM1200CRZ-RL7", 840, 520, 0),
    ("U6", "ADUM1201BR", 1070, 520, 0),
    ("C9", "CL21B104KBCNNNC", 1300, 520, 0),
    # 数字隔离去耦
    ("C10", "CL21B104KBCNNNC", 150, 720, 0),
    ("C11", "CL21B104KBCNNNC", 380, 720, 0),
    ("C12", "CL21B104KBCNNNC", 610, 720, 0),
    ("C13", "CL21B104KBCNNNC", 840, 720, 0),
    ("C14", "CL21B104KBCNNNC", 1070, 720, 0),
    # 隔离 RS485
    ("U3", "CA-IS3082W", 1300, 720, 0),
    ("C7", "CL21B104KBCNNNC", 150, 920, 0),
    ("C8", "CL21B104KBCNNNC", 380, 920, 0),
    ("R1", "0805W8F1200T5E", 610, 920, 0),
    ("J4", "DB128V-5.08-4P-GN-S", 840, 920, 0),
    ("J5", "PZ254V-11-10P", 1070, 920, 0),
    # 音频
    ("J6", "PJ-320D", 1300, 920, 0),
    ("RV1", "3314J-1-103E", 150, 1120, 0),
    ("RV2", "3314J-1-103E", 380, 1120, 0),
    ("C15", "CL21A105KAFNNNE", 610, 1120, 0),
    ("C16", "CL21A106KAYNNNE", 840, 1120, 0),
    ("R2", "0805W8F2201T5E", 1070, 1120, 0),
    ("R3", "0805W8F1000T5E", 1300, 1120, 0),
    ("R4", "0805W8F1000T5E", 150, 1320, 0),
    ("J7", "PZ254V-11-05P", 380, 1320, 0),
]


def main():
    ea.connect()
    ea.open_project(PROJECT)
    time.sleep(2)
    ea.open_doc(PAGE)
    time.sleep(2)
    print("cur", ea.current_doc())
    print("clear", ea.clear_schematic())
    ids = {}
    for idx, (des, key, x, y, rot) in enumerate(COMPS, start=1):
        devs = ea.search_device(key)
        if not devs:
            print("NOT FOUND", key)
            continue
        dev = devs[0]
        r = ea.create_component(dev, x, y, rot, subpart=f"{key}.1")
        if not r.get("ok"):
            print("CREATE FAIL", des, r)
            continue
        ids[des] = r["id"]
        expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.sch_PrimitiveComponent.modify(%s,{designator:%s,uniqueId:%s}); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                % (json.dumps(r["id"]), json.dumps(des), json.dumps(f"io{idx:03d}")))
        mr = json.loads(ea.js(expr, t=60))
        if not mr.get("ok"):
            print("MODIFY FAIL", des, mr)
        time.sleep(0.25)
    # 保存并输出引脚
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=60)
    pin_dump = {}
    for des, pid in ids.items():
        pins = ea.get_pins(pid)
        pin_dump[des] = {p["pinNumber"]: {"name": p.get("pinName"), "x": p["x"], "y": p["y"]} for p in pins}
    with open("io_pins.json", "w", encoding="utf-8") as f:
        json.dump(pin_dump, f, ensure_ascii=False, indent=2)
    print(json.dumps(pin_dump, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
