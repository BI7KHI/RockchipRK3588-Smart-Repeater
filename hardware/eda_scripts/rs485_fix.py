# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef"); time.sleep(1.5)

def mod(pid, payload):
    return ea.js("(async()=>{const R=window._EXTAPI_ROOT_; try{await R.sch_PrimitiveComponent.modify(%s,%s); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
                 % (json.dumps(pid), json.dumps(payload, ensure_ascii=False)), t=40)

comps = ea.get_components()
parts = {c.get("designator"): c for c in comps if c.get("componentType") == "part"}
flags = [c for c in comps if c.get("componentType") == "netflag"]

# 1) 改阻值（必须提交完整 otherProperty 字典）
NEWVAL = {"R11": "38.3K", "R8": "820R", "R9": "820R", "R6": "1K", "R7": "1K"}
for des, val in NEWVAL.items():
    c = parts[des]; op = dict(c.get("otherProperty") or {}); op["Value"] = val
    print(des, "->", val, mod(c["primitiveId"], {"otherProperty": op}))

# 2) 删除悬空 VBUS 网络标识
vb = [f for f in flags if f.get("net") == "VBUS"]
if vb:
    r = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveComponent.delete(%s));})()"
              % json.dumps([f["primitiveId"] for f in vb]), t=40)
    print("deleted VBUS flags:", len(vb), r)
else:
    print("no VBUS flags")

ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
