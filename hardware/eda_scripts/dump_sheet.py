import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
print("cur:", ea.current_doc())
comps = ea.get_components()
wires = ea.get_wires()
open("audio_sheet_comps.json", "w", encoding="utf-8").write(json.dumps(comps, ensure_ascii=False, indent=1))
open("audio_sheet_wires.json", "w", encoding="utf-8").write(json.dumps(wires, ensure_ascii=False, indent=1))
print("comps:", len(comps), "wires:", len(wires))
for c in comps:
    print("  %-8s %-26s typ=%-10s x=%-7s y=%-7s rot=%s" % (
        c.get("designator"), (c.get("name") or c.get("device") or "")[:26],
        c.get("componentType"), c.get("x"), c.get("y"), c.get("rotation")))
