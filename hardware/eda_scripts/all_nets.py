# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
t = ea.sch_netlist_text()
open("all_nets.json", "w", encoding="utf-8").write(t or "")
d = json.loads(t or "{}")
from collections import defaultdict
m = defaultdict(list)
for uid, c in d.get("components", {}).items():
    p = c.get("props", {}); des = str(p.get("Designator")); nm = str(p.get("Value") or p.get("Manufacturer Part") or "")
    for pn, pi in (c.get("pinInfoMap") or {}).items():
        n = pi.get("net")
        if n: m[n].append("%s.%s" % (des, pn))
for n in sorted(m):
    if n.startswith("$"): continue
    print("%-16s (%d): %s" % (n, len(m[n]), ", ".join(m[n])[:260]))
