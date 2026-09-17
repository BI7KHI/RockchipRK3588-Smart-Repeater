# -*- coding: utf-8 -*-
import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3")
t = ea.sch_netlist_text()
open(r"C:\Users\Admin\Desktop\ELF2\硬件设计\音频隔离衰减_网表.json", "w", encoding="utf-8").write(t or "")
from collections import defaultdict
d = json.loads(t or "{}"); m = defaultdict(list)
for uid, c in d.get("components", {}).items():
    p = c.get("props", {}); des = str(p.get("Designator"))
    for pn, pi in (c.get("pinInfoMap") or {}).items():
        if pi.get("net"): m[pi["net"]].append("%s.%s" % (des, pn))
for net in ("ELF2 DAC Audio", "ELF2 MIC", "RPT SPK", "RPT MIC"):
    print("  %-16s : %s" % (net, ", ".join(m.get(net, []))))
print("saved netlist")
