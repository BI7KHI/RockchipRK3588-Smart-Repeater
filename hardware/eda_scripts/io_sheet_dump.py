# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
for name, uuid in (("IO光耦隔离","3a27604a85bbad4f"),):
    ea.open_doc(uuid); time.sleep(1.5)
    comps = ea.get_components()
    print("==", name, "comps:", len(comps))
    for c in comps:
        ct = c.get("componentType")
        if ct == "part":
            op = c.get("otherProperty") or {}
            print("  %-6s %-24s %-10s x=%-6s y=%-6s rot=%s" % (c.get("designator"), str((c.get("component") or {}).get("name"))[:24], str(op.get("Value"))[:10], c.get("x"), c.get("y"), c.get("rotation")))
        elif ct in ("netport","netflag"):
            print("  %-6s [%s] %-16s x=%-6s y=%-6s" % ("", ct, c.get("net"), c.get("x"), c.get("y")))
