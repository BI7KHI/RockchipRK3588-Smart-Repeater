import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3")
t = ea.sch_netlist_text()
open("proj_netlist2.txt","w",encoding="utf-8").write(t or "")
d = json.loads(t)
interest = {"ELF2 DAC Audio","ELF2 MIC","RPT SPK","RPT MIC","DEV GND","RPT GND"}
rows=[]
for uid,c in d["components"].items():
    p=c.get("props",{}); des=p.get("Designator"); val=p.get("Value")
    for pn,pi in (c.get("pinInfoMap") or {}).items():
        net=pi.get("net")
        if net in interest:
            rows.append((net, str(des), str(pn), str(val or "")))
rows.sort()
for r in rows: print("  %-16s %-5s pin=%-3s %s" % r)
print("total audio-net pins:", len(rows))
