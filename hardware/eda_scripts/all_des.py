# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
SHEETS = {"IO光耦隔离": "3a27604a85bbad4f", "音频隔离衰减": "ea4fc07c502623a3",
          "ELF2 ADC分压采集": "85d62bb6700380a3", "RS485模块和隔离升压": "a68e58ecf0ff6fef"}
for name, uuid in SHEETS.items():
    ea.open_doc(uuid); time.sleep(1.2)
    comps = ea.get_components()
    parts = []
    for c in comps:
        if c.get("componentType") == "part":
            op = c.get("otherProperty") or {}
            parts.append("%s(%s)" % (c.get("designator"), str(op.get("Value") or (c.get("component") or {}).get("name") or "")[:14]))
    print("%-16s %2d parts: %s" % (name, len(parts), ", ".join(parts)))
