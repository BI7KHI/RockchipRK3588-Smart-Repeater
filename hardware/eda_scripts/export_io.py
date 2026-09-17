#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 IO 隔离板原理图/PCB 交付文件（PCB 尚未完成布线）。"""
import base64
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea

OUT_DIR = r"C:\Users\Admin\Desktop\ELF2\硬件设计\交付物\IO隔离板"
PROJECT = "e10fadeebbaba5d570f87dd94a16437176b2e7e3ecbf0c51e3ad48b96cccb64f"
SCH_PAGE = "ea4fc07c502623a3"
PCB = "55f721c46525bf2b"


def fetch_b64(expr, timeout=300):
    js = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const f=await (%s); if(!f) return JSON.stringify({err:'no file'}); const b=new Uint8Array(await f.arrayBuffer()); let s=''; const C=0x8000; for(let i=0;i<b.length;i+=C) s+=String.fromCharCode.apply(null,b.subarray(i,i+C)); return btoa(s);}catch(e){return JSON.stringify({err:String(e&&e.message||e)});}})()" % expr)
    r = ea.js(js, t=timeout)
    if r.startswith("{"):
        raise RuntimeError(r[:300])
    return base64.b64decode(r)


def save(name, expr, timeout=300):
    data = fetch_b64(expr, timeout)
    with open(os.path.join(OUT_DIR, name), "wb") as f:
        f.write(data)
    print("saved", name, len(data))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ea.connect()
    ea.open_project(PROJECT)
    time.sleep(2)
    # 原理图
    ea.open_doc(SCH_PAGE)
    time.sleep(2)
    for name, expr in [
        ("IO隔离板_原理图.pdf", "R.sch_ManufactureData.getExportDocumentFile('IO_SCH','PDF')"),
        ("IO隔离板_原理图BOM.xlsx", "R.sch_ManufactureData.getBomFile('IO_SCH_BOM','xlsx')"),
    ]:
        try:
            save(name, expr, 300)
        except Exception as e:
            print("sch export fail", name, e)
    # PCB
    ea.open_doc(PCB)
    time.sleep(2)
    for name, expr in [
        ("IO隔离板_PCB.pdf", "R.pcb_ManufactureData.getPdfFile('IO_PCB')"),
        ("IO隔离板_3D.step", "R.pcb_ManufactureData.get3DFile('IO_PCB')"),
        ("IO隔离板_Gerber.zip", "R.pcb_ManufactureData.getGerberFile('IO_PCB')"),
        ("IO隔离板_BOM.xlsx", "R.pcb_ManufactureData.getBomFile('IO_PCB_BOM','xlsx')"),
        ("IO隔离板_贴片坐标.xlsx", "R.pcb_ManufactureData.getPickAndPlaceFile('IO_PCB_Place','xlsx')"),
    ]:
        try:
            save(name, expr, 300)
        except Exception as e:
            print("pcb export fail", name, e)
    try:
        data = fetch_b64("R.dmt_EditorControl.getCurrentRenderedAreaImage()", 120)
        with open(os.path.join(OUT_DIR, "IO隔离板_PCB视图.png"), "wb") as f:
            f.write(data)
        print("saved preview", len(data))
    except Exception as e:
        print("preview fail", e)


if __name__ == "__main__":
    main()
