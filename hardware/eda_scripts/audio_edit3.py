import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.5)
comps = {c.get("designator"): c for c in ea.get_components() if c.get("componentType") == "part"}
tasks = [
    ("d75c3499c324ba20", {"designator": "R2", "uniqueId": "gga92", "otherProperty": {"Value": "150R"}}),
    (comps["R3"]["primitiveId"], {"otherProperty": {"Value": "1K"}}),
    (comps["R4"]["primitiveId"], {"otherProperty": {"Value": "220R"}}),
]
for pid, payload in tasks:
    m = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; try{await R.sch_PrimitiveComponent.modify(%s,%s); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (json.dumps(pid), json.dumps(payload, ensure_ascii=False)), t=30)
    print(pid, payload.get("designator") or list(payload.get("otherProperty", {}).values()), "->", m)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
