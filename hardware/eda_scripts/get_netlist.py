import json, sys
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
print("cur:", ea.current_doc())
t = ea.sch_netlist_text()
if t is None:
    print("NETLIST FAIL")
else:
    open("proj_netlist.txt", "w", encoding="utf-8").write(t)
    print("netlist chars:", len(t))
