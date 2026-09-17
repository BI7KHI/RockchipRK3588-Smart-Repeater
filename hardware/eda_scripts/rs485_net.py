# -*- coding: utf-8 -*-
import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef")
t = ea.sch_netlist_text()
open("rs485_netlist.json", "w", encoding="utf-8").write(t or "")
d = json.loads(t)
want = {"U3","U4","R6","R7","R8","R9","R10","R11","R12","C5","C6","C7","D2","L1","LED1","LED2","CN1","H7"}
def val(p):
    return p.get("Value") or p.get("Manufacturer Part") or p.get("LCSC Part Name") or ""
for uid, c in d["components"].items():
    p = c.get("props", {}); des = str(p.get("Designator"))
    if des in want:
        pins = {pn: pi.get("net") for pn, pi in (c.get("pinInfoMap") or {}).items()}
        print("%-5s %-22s %s" % (des, str(val(p))[:22], json.dumps(pins, ensure_ascii=False)))
# nets 汇总（只列本页相关）
names = set()
for uid, c in d["components"].items():
    p = c.get("props", {}); des = str(p.get("Designator"))
    if des in want:
        for pn, pi in (c.get("pinInfoMap") or {}).items():
            if pi.get("net"): names.add(pi["net"])
print()
print("NETS:", sorted(names))
