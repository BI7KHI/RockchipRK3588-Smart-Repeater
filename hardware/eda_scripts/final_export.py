# -*- coding: utf-8 -*-
import base64, json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.5)
# 1) 网表
t = ea.sch_netlist_text()
open(r"C:\Users\Admin\Desktop\ELF2\硬件设计\音频隔离衰减_网表.json", "w", encoding="utf-8").write(t or "")
d = json.loads(t)
interest = {"ELF2 DAC Audio","ELF2 MIC","RPT SPK","RPT MIC","DEV GND","RPT GND"}
pins = {}
for uid, c in d["components"].items():
    p = c.get("props", {}); des = str(p.get("Designator"))
    if des in ("R1","R2","R3","R4","R5","U1","U2","D1","C1","C2","C3","C4"):
        pins[des] = {pn: pi.get("net") for pn, pi in (c.get("pinInfoMap") or {}).items()}
print("netlist pins:", json.dumps(pins, ensure_ascii=False))
# 2) 预览图
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.dmt_EditorControl.zoomToAllPrimitives());})()", t=30)
time.sleep(1.5)
b64 = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const f=await R.dmt_EditorControl.getCurrentRenderedAreaImage(); const buf=await f.arrayBuffer(); const b=new Uint8Array(buf); let s=''; const C=0x8000; for(let i=0;i<b.length;i+=C) s+=String.fromCharCode.apply(null,b.subarray(i,i+C)); return btoa(s);})()", t=120)
raw = base64.b64decode(b64)
open(r"C:\Users\Admin\Desktop\ELF2\硬件设计\音频隔离衰减_原理图.png", "wb").write(raw)
print("PNG:", len(raw), "bytes")
