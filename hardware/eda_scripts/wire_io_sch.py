#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IO 隔离板原理图：为每个引脚拉短桩并标注网络名，生成可校验网表。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea

PROJECT = "e10fadeebbaba5d570f87dd94a16437176b2e7e3ecbf0c51e3ad48b96cccb64f"
PAGE = "ea4fc07c502623a3"

NETS_IO = {
    "VIN_12V": [("J1", "1"), ("F1", "1")],
    "VIN_12V_F": [("F1", "2"), ("D1", "1"), ("C1", "1"), ("C2", "1"),
                  ("U1", "2"), ("U1", "3"), ("U2", "2"), ("U2", "3")],
    "GND_LOGIC": [
        ("J1", "2"), ("D1", "2"), ("C1", "2"), ("C2", "2"),
        ("U1", "1"), ("U2", "1"), ("J3", "2"), ("J8", "2"),
        ("U3", "2"), ("U3", "7"), ("U3", "8"),
        ("U4", "4"), ("U5", "4"), ("U6", "4"),
        ("C7", "2"), ("C9", "2"), ("C10", "2"), ("C13", "2"),
        ("J6", "3"), ("J6", "4"), ("J7", "1"), ("J7", "5"),
        ("RV1", "3"), ("RV2", "3"),
    ],
    "VCC_LOGIC_3V3": [
        ("J3", "1"), ("U3", "1"), ("U4", "1"), ("U5", "1"), ("U6", "1"),
        ("C7", "1"), ("C9", "1"), ("C10", "1"), ("C13", "1"), ("R2", "1"),
    ],
    "VOUT_12V_ISO": [("U1", "6"), ("C3", "1"), ("C4", "1"), ("J2", "1"), ("J5", "9")],
    "VOUT_3V3_ISO": [
        ("U2", "6"), ("C5", "1"), ("C6", "1"), ("U3", "16"), ("C8", "1"),
        ("U4", "8"), ("U5", "8"), ("U6", "8"), ("C11", "1"), ("C12", "1"), ("C14", "1"),
        ("J4", "1"), ("J5", "1"),
    ],
    "GND_ISO": [
        ("U1", "7"), ("U2", "7"), ("C3", "2"), ("C4", "2"), ("C5", "2"), ("C6", "2"),
        ("J2", "2"), ("U3", "9"), ("U3", "10"), ("U3", "15"), ("C8", "2"),
        ("U4", "5"), ("U5", "5"), ("U6", "5"), ("C11", "2"), ("C12", "2"), ("C14", "2"),
        ("J4", "4"), ("J5", "2"), ("J5", "10"),
    ],
    # RS485
    "UART_TX": [("J3", "3"), ("U3", "6")],
    "UART_RX": [("J3", "4"), ("U3", "3")],
    "RS485_DE": [("J8", "1"), ("U3", "4"), ("U3", "5")],
    "RS485_A": [("U3", "12"), ("R1", "1"), ("J4", "2")],
    "RS485_B": [("U3", "13"), ("R1", "2"), ("J4", "3")],
    # 数字隔离
    "PC0": [("J3", "5"), ("U4", "2")],
    "PC1": [("J3", "6"), ("U4", "3")],
    "PC2": [("J3", "7"), ("U5", "2")],
    "PC3": [("J3", "8"), ("U5", "3")],
    "PC0_ISO": [("U4", "7"), ("J5", "3")],
    "PC1_ISO": [("U4", "6"), ("J5", "4")],
    "PC2_ISO": [("U5", "7"), ("J5", "5")],
    "PC3_ISO": [("U5", "6"), ("J5", "6")],
    "PTT": [("J3", "9"), ("U6", "3")],
    "PTT_ISO": [("U6", "6"), ("J5", "7"), ("J7", "4")],
    "BUSY_ISO": [("U6", "7"), ("J5", "8")],
    "BUSY": [("J3", "10"), ("U6", "2")],
    # 音频
    "MIC_IN": [("J6", "2"), ("R2", "2"), ("C15", "1")],
    "MIC_FILT": [("C15", "2"), ("R3", "1")],
    "MIC_LEVEL": [("R3", "2"), ("RV1", "1")],
    "MIC_OUT": [("RV1", "2"), ("J7", "2")],
    "SPK_IN": [("J7", "3"), ("C16", "1")],
    "SPK_LEVEL": [("C16", "2"), ("RV2", "1")],
    "SPK_WIPER": [("RV2", "2"), ("R4", "1")],
    "SPK_OUT": [("R4", "2"), ("J6", "1")],
}


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
        print("deleted wires", len(wires))
    # 获取元件中心与引脚
    comps = ea.get_components()
    centers = {}
    pinmap = {}
    for c in comps:
        if c.get("componentType") != "part":
            continue
        des = c.get("designator")
        centers[des] = (c.get("x"), c.get("y"))
        for p in ea.get_pins(c["primitiveId"]):
            pinmap[(des, str(p["pinNumber"]))] = (p["x"], p["y"])
    def stub_dir(des, px, py):
        cx, cy = centers.get(des, (px, py))
        if abs(px - cx) >= abs(py - cy):
            return (px + (20 if px >= cx else -20), py)
        return (px, py + (20 if py >= cy else -20))
    created = 0
    missing = []
    for net, refs in NETS_IO.items():
        for des, pin in refs:
            p = pinmap.get((des, str(pin)))
            if not p:
                missing.append((net, des, pin))
                continue
            ex, ey = stub_dir(des, p[0], p[1])
            r = json.loads(ea.create_wire([p[0], p[1], ex, ey], net))
            if not r.get("ok"):
                print("wire fail", net, des, pin, r)
            else:
                created += 1
            time.sleep(0.02)
    print("created", created, "missing", missing)
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=60)


if __name__ == "__main__":
    main()
