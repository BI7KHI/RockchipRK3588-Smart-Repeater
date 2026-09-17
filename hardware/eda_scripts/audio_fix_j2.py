# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.2)
target = None
for c in ea.get_components():
    if c.get("componentType") == "netport" and c.get("net") == "ELF2 DAC Audio":
        x, y = c.get("x"), c.get("y")
        if abs(x - 695) < 12 and abs(y - 305) < 12:      # J2.2 旁的那个
            target = c
print("target netport:", json.dumps({k: target.get(k) for k in ("primitiveId","net","x","y","rotation","component")}, ensure_ascii=False) if target else None)
if target:
    info = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveComponent.getAll(); const t=a.find(c=>c.primitiveId===%s); return JSON.stringify({rot:t.rotation, mirror:t.mirror, comp:t.component});})()" % json.dumps(target["primitiveId"]), t=30)
    print("detail:", info)
    d = json.loads(info)
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveComponent.delete(%s));})()" % json.dumps([target["primitiveId"]]), t=40)
    time.sleep(0.4)
    kind = "OUT" if "OUT" in str(d["comp"].get("name","")) else ("IN" if "IN" in str(d["comp"].get("name","")) else "BI")
    r = ea.js("(async()=>{const R=window._EXTAPI_ROOT_;try{const c=await R.sch_PrimitiveComponent.createNetPort('%s','RPT MIC',%s,%s,%s,%s);"
              "return JSON.stringify({ok:true,id:c&&c.primitiveId});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (kind, json.dumps(target["x"]), json.dumps(target["y"]), json.dumps(d.get("rot") or 0), json.dumps(bool(d.get("mirror")))), t=40)
    print("create RPT MIC netport:", r)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
