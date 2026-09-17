import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("cur:", ea.current_doc())
comps = ea.get_components(); wires = ea.get_wires(); texts = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>({x:t.x,y:t.y,c:t.content.split(String.fromCharCode(10))[0].slice(0,30)})));})()", t=30))
print("comps:", len(comps), "wires:", len(wires), "texts:", len(texts))
for t in texts: print("   text@(%s,%s): %s" % (t["x"], t["y"], t["c"]))
vals = {c.get("designator"): (c.get("otherProperty") or {}).get("Value") for c in comps if c.get("componentType")=="part"}
print("values:", json.dumps(vals, ensure_ascii=False))
