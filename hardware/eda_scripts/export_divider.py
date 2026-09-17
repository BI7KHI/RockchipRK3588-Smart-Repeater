#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出分压采集板制造文件到 交付物/分压采集板。"""
import base64
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import eda_auto as ea

OUT_DIR = r"C:\Users\Admin\Desktop\ELF2\硬件设计\交付物\分压采集板"


def fetch_file_b64(expr, timeout=300):
    js = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const f=await (%s); if(!f) return JSON.stringify({err:'no file'}); const b=new Uint8Array(await f.arrayBuffer()); let s=''; const C=0x8000; for(let i=0;i<b.length;i+=C) s+=String.fromCharCode.apply(null,b.subarray(i,i+C)); return btoa(s);}catch(e){return JSON.stringify({err:String(e&&e.message||e)});}})()" % expr)
    r = ea.js(js, t=timeout)
    if r.startswith("{"):
        raise RuntimeError("export fail: " + r[:500])
    return base64.b64decode(r)


def save(name, expr, timeout=300):
    data = fetch_file_b64(expr, timeout)
    path = os.path.join(OUT_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    print("saved", name, len(data))
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ea.connect()
    ea.open_project("b363347f0b8c5bc8672339be6ece26e3d304b1ca776b46b7ed3631d2602f6b38")
    time.sleep(1)
    ea.open_doc("55f721c46525bf2b")
    time.sleep(2)
    # 导出
    save("分压采集板_Gerber.zip", "R.pcb_ManufactureData.getGerberFile('DividerBoard')", 300)
    save("分压采集板_PCB.pdf", "R.pcb_ManufactureData.getPdfFile('DividerBoard')", 300)
    save("分压采集板_3D.step", "R.pcb_ManufactureData.get3DFile('DividerBoard')", 300)
    save("分压采集板_BOM.xlsx", "R.pcb_ManufactureData.getBomFile('DividerBoard_BOM','xlsx')", 300)
    save("分压采集板_贴片坐标.xlsx", "R.pcb_ManufactureData.getPickAndPlaceFile('DividerBoard_Place','xlsx')", 300)
    save("分压采集板_网表.json", "R.pcb_ManufactureData.getNetlistFile('DividerBoard_Net','JLCEDA')", 300)
    # 预览图
    try:
        data = fetch_file_b64("R.dmt_EditorControl.getCurrentRenderedAreaImage()", 120)
        with open(os.path.join(OUT_DIR, "分压采集板_PCB视图.png"), "wb") as f:
            f.write(data)
        print("saved preview", len(data))
    except Exception as e:
        print("preview err", e)
    # 校验 Gerber
    try:
        zp = os.path.join(OUT_DIR, "分压采集板_Gerber.zip")
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
            print("gerber files", len(names))
            for n in names:
                if n.endswith('.GTL') or n.endswith('.GBL'):
                    txt = z.read(n).decode('latin-1', 'replace')
                    print(n, 'G36=', txt.count('G36'), 'G37=', txt.count('G37'), 'size=', len(txt))
                if n.endswith('.GKO'):
                    txt = z.read(n).decode('latin-1', 'replace')
                    print('GKO size', len(txt), 'head', txt[:200].replace('\n', ' | '))
    except Exception as e:
        print("gerber check err", e)


if __name__ == "__main__":
    main()
