import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("55f721c46525bf2b"); time.sleep(2)
print("cur:", ea.current_doc())
rows = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.pcb_PrimitiveComponent.getAll(); return JSON.stringify(a.map(c=>({d:c.designator||c.getState_Designator&&c.getState_Designator(), name:(c.component||{}).name, x:c.x, y:c.y})));})()", t=60)
try:
    d = json.loads(rows)
    print("pcb comps:", len(d))
    for c in sorted(d, key=lambda z: str(z.get("d")))[:80]:
        print("   %-7s %s" % (c.get("d"), c.get("name")))
except Exception as e:
    print("ERR", e, str(rows)[:300])
