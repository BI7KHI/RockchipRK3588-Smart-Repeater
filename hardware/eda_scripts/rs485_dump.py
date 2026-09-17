# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef"); time.sleep(1.5)
comps = ea.get_components(); wires = ea.get_wires()
out = {"parts": [], "ports": [], "flags": [], "wires": []}
for c in comps:
    ct = c.get("componentType")
    if ct == "part":
        op = c.get("otherProperty") or {}
        pins = ea.get_pins(c["primitiveId"])
        out["parts"].append({"des": c.get("designator"), "dev": (c.get("component") or {}).get("name"),
                             "val": op.get("Value"), "x": c.get("x"), "y": c.get("y"), "rot": c.get("rotation"),
                             "lcsc": op.get("LCSC Part Name"), "spn": op.get("Supplier Part"),
                             "pins": {str(p.get("pinNumber")): (p.get("x"), p.get("y")) for p in pins}})
    elif ct in ("netport", "netflag"):
        out[("ports" if ct == "netport" else "flags")].append({"net": c.get("net"), "x": c.get("x"), "y": c.get("y")})
    elif ct == "sheet":
        out["sheet"] = {"x": c.get("x"), "y": c.get("y")}
# 导线几何
expr = ("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveWire.getAll();"
        "return JSON.stringify(a.map(w=>{const o={id:w.primitiveId,net:w.net,keys:Object.keys(w)};"
        "for (const m of ['getState_Points','getState_Line','getState_X1','getState_Y1','getState_X2','getState_Y2']){try{if(typeof w[m]==='function'){const v=w[m](); if(v!==undefined) o[m]=v;}}catch(e){}}"
        "return o;}));})()")
try:
    wl = json.loads(ea.js(expr, t=60))
    out["wires"] = wl
except Exception as e:
    out["wires"] = [{"err": str(e)}]
open("rs485_dump.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
print("parts:", len(out["parts"]), "ports:", len(out["ports"]), "flags:", len(out["flags"]), "wires:", len(out["wires"]))
print("sheet:", out.get("sheet"))
