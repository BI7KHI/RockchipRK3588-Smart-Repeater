# -*- coding: utf-8 -*-
import base64, json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
def render(uuid, outpath, label):
    ea.open_doc(uuid); time.sleep(1.5)
    ts = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>({x:t.x,y:t.y,lines:t.content.split(String.fromCharCode(10)).length,c:t.content.split(String.fromCharCode(10))[0].slice(0,26)})));})()", t=30))
    print("==", label, "texts:", len(ts))
    for t in ts: print("    ", json.dumps(t, ensure_ascii=False))
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.dmt_EditorControl.zoomToAllPrimitives());})()", t=30)
    time.sleep(1.5)
    b64 = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const f=await R.dmt_EditorControl.getCurrentRenderedAreaImage(); const buf=await f.arrayBuffer(); const b=new Uint8Array(buf); let s=''; const C=0x8000; for(let i=0;i<b.length;i+=C) s+=String.fromCharCode.apply(null,b.subarray(i,i+C)); return btoa(s);})()", t=120)
    raw = base64.b64decode(b64); open(outpath, "wb").write(raw)
    print("    PNG:", outpath, len(raw))
render("a68e58ecf0ff6fef", r"C:\Users\Admin\Desktop\ELF2\硬件设计\RS485隔离升压_原理图.png", "RS485隔离升压")
render("ea4fc07c502623a3", r"C:\Users\Admin\Desktop\ELF2\硬件设计\音频隔离衰减_原理图.png", "音频隔离衰减")
