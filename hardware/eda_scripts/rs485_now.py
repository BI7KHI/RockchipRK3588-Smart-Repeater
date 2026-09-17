# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef"); time.sleep(1.5)
print("=== RS485 页当前元件 ===")
for c in ea.get_components():
    ct = c.get("componentType")
    if ct == "part":
        op = c.get("otherProperty") or {}
        print("  %-5s %-24s %-8s x=%-6s y=%-6s rot=%s" % (c.get("designator"), str((c.get("component") or {}).get("name"))[:24], str(op.get("Value"))[:8], c.get("x"), c.get("y"), c.get("rotation")))
    elif ct in ("netport","netflag"):
        print("  %-5s [%s] %-14s x=%-6s y=%-6s" % ("", ct, c.get("net"), c.get("x"), c.get("y")))
