# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.2)
comps = ea.get_components()
xs = [c.get("x") for c in comps if isinstance(c.get("x"), (int, float))]
ys = [c.get("y") for c in comps if isinstance(c.get("y"), (int, float))]
print("x range:", min(xs), max(xs), " y range:", min(ys), max(ys))
ts = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>({id:t.primitiveId,x:t.x,y:t.y,fs:t.fontSize,bold:t.bold,c:t.content.split(String.fromCharCode(10))[0].slice(0,40),lines:t.content.split(String.fromCharCode(10)).length})));})()", t=30))
print("texts:", len(ts))
for t in ts: print("   ", json.dumps(t, ensure_ascii=False))
