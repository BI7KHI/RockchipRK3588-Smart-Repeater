# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.2)
comps = ea.get_components()
print("audio sheet comps:", len(comps))
for c in comps:
    if c.get("componentType") == "part":
        op = c.get("otherProperty") or {}
        print("  %-5s %-22s %-8s x=%-6s y=%-6s rot=%s" % (c.get("designator"), str((c.get("component") or {}).get("name"))[:22], str(op.get("Value"))[:8], c.get("x"), c.get("y"), c.get("rotation")))
    elif c.get("componentType") in ("netport", "netflag"):
        print("  %-5s [%s] %-16s x=%-6s y=%-6s" % ("", c.get("componentType"), c.get("net"), c.get("x"), c.get("y")))
t = ea.sch_netlist_text()
d = json.loads(t or "{}")
from collections import defaultdict
m = defaultdict(list)
for uid, c in d.get("components", {}).items():
    p = c.get("props", {}); des = str(p.get("Designator"))
    for pn, pi in (c.get("pinInfoMap") or {}).items():
        n = pi.get("net")
        if n: m[n].append("%s.%s" % (des, pn))
print()
for net in ("ELF2 DAC Audio", "ELF2 MIC", "RPT SPK", "RPT MIC"):
    print("  %-16s : %s" % (net, ", ".join(m.get(net, []))))
