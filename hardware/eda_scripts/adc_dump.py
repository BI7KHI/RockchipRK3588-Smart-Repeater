# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("85d62bb6700380a3"); time.sleep(1.5)
comps = ea.get_components()
out = []
print("=== 元件 ===")
for c in comps:
    ct = c.get("componentType")
    if ct == "part":
        op = c.get("otherProperty") or {}
        pins = ea.get_pins(c["primitiveId"])
        pinmap = {str(p.get("pinNumber")): [p.get("x"), p.get("y")] for p in pins}
        print("  %-5s %-24s %-8s x=%-6s y=%-6s rot=%-4s pins=%s" % (c.get("designator"), str((c.get("component") or {}).get("name"))[:24],
              str(op.get("Value"))[:8], c.get("x"), c.get("y"), c.get("rotation"), json.dumps(pinmap, ensure_ascii=False)))
    elif ct in ("netport", "netflag"):
        print("  %-5s [%s] %-12s x=%-6s y=%-6s" % ("", ct, c.get("net"), c.get("x"), c.get("y")))
    elif ct == "sheet":
        print("  [sheet] x=%s y=%s" % (c.get("x"), c.get("y")))
t = ea.sch_netlist_text()
open(r"C:\Users\Admin\Desktop\ELF2\硬件设计\ELF2_ADC分压采集_网表.json", "w", encoding="utf-8").write(t or "")
d = json.loads(t or "{}")
want = {"R14","R15","R16","R17","R18","R19","C8","C9","D3","D4"}
print("=== 引脚网络 ===")
for uid, c in d.get("components", {}).items():
    p = c.get("props", {}); des = str(p.get("Designator"))
    if des in want:
        pins = {pn: pi.get("net") for pn, pi in (c.get("pinInfoMap") or {}).items()}
        print("  %-5s %-8s %s" % (des, str(p.get("Value") or ""), json.dumps(pins, ensure_ascii=False)))
