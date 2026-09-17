# -*- coding: utf-8 -*-
import base64, json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("85d62bb6700380a3"); time.sleep(1.2)
ts = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>({x:t.x,y:t.y,lines:t.content.split(String.fromCharCode(10)).length,fs:t.fontSize})));})()", t=30))
print("texts:", json.dumps(ts, ensure_ascii=False))
t = ea.sch_netlist_text()
open(r"C:\Users\Admin\Desktop\ELF2\硬件设计\ELF2_ADC分压采集_网表.json", "w", encoding="utf-8").write(t or "")
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.dmt_EditorControl.zoomToAllPrimitives());})()", t=30)
time.sleep(1.5)
b64 = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const f=await R.dmt_EditorControl.getCurrentRenderedAreaImage(); const buf=await f.arrayBuffer(); const b=new Uint8Array(buf); let s=''; const C=0x8000; for(let i=0;i<b.length;i+=C) s+=String.fromCharCode.apply(null,b.subarray(i,i+C)); return btoa(s);})()", t=120)
raw = base64.b64decode(b64)
p = r"C:\Users\Admin\Desktop\ELF2\硬件设计\ELF2_ADC分压采集_原理图.png"
open(p, "wb").write(raw)
print("PNG:", p, len(raw))
