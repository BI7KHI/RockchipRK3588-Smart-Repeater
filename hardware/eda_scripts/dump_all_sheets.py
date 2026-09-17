import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
SHEETS = {"IO光耦隔离": "3a27604a85bbad4f", "音频隔离衰减": "ea4fc07c502623a3",
          "ELF2 ADC分压采集": "85d62bb6700380a3", "RS485模块和隔离升压": "a68e58ecf0ff6fef"}
summary = {}
for name, uuid in SHEETS.items():
    ea.open_doc(uuid); time.sleep(1.5)
    comps = ea.get_components(); wires = ea.get_wires()
    rows = []
    for c in comps:
        ct = c.get("componentType")
        if ct == "part":
            op = c.get("otherProperty") or {}
            rows.append("%-6s %-26s %s" % (c.get("designator"), str((c.get("component") or {}).get("name"))[:26], op.get("Value") or op.get("Manufacturer Part") or ""))
        elif ct in ("netport", "netflag"):
            rows.append("%-6s [%s] %s" % ("", ct, c.get("net")))
    summary[name] = {"n_comp": len(comps), "n_wire": len(wires), "rows": sorted(rows)}
open("all_sheets.json", "w", encoding="utf-8").write(json.dumps(summary, ensure_ascii=False, indent=1))
for k, v in summary.items():
    print("==", k, "comps", v["n_comp"], "wires", v["n_wire"])
