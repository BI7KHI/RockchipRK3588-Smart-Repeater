import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.5)
comps = ea.get_components()
print("comps:", len(comps))
for c in comps:
    if c.get("componentType") == "part":
        op = c.get("otherProperty") or {}
        des = c.get("designator")
        if des not in ("R1","R3","R4","R5","U1","U2","D1","C1","C2","C3","C4"):
            print("NEW PART:", json.dumps({k: c.get(k) for k in ("primitiveId","designator","x","y","rotation")}, ensure_ascii=False),
                  "dev=", json.dumps((c.get("component") or {}), ensure_ascii=False),
                  "props=", json.dumps({k: op.get(k) for k in ("Value","LCSC Part Name","Supplier Part") if k in op}, ensure_ascii=False))
            print("   pins:", json.dumps([{"n":p.get("pinNumber"),"x":p.get("x"),"y":p.get("y")} for p in ea.get_pins(c["primitiveId"])], ensure_ascii=False))
