import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3")
comps = ea.get_components(); wires = ea.get_wires()
print("comps:", len(comps), "wires:", len(wires))
for c in sorted([c for c in comps if c.get("componentType") == "part"], key=lambda z: str(z.get("designator"))):
    op = c.get("otherProperty") or {}
    print("  %-4s %-22s %-8s x=%-6s y=%-6s rot=%-4s" % (c.get("designator"),
          str((c.get("component") or {}).get("name"))[:22], op.get("Value") or op.get("LCSC Part Name") or "",
          c.get("x"), c.get("y"), c.get("rotation")))
print("texts:", len(json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>t.content.slice(0,20)));})()", t=30))))
