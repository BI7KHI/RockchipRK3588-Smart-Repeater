import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.5)
WIRES = [
    (240,500,260,500), (300,500,320,500), (360,500,360,480), (360,480,395,480), (395,480,395,470),
    (360,440,360,430), (395,440,360,440), (455,470,455,500), (495,500,505,500), (455,440,490,440),
    (490,440,490,425),
    (240,345,260,345), (300,345,320,345), (360,345,395,345), (360,325,360,345), (360,285,360,270),
    (360,270,275,270), (395,315,395,270), (395,270,360,270), (495,345,515,345), (555,345,580,345),
    (565,345,565,335), (565,295,565,270), (565,270,500,270), (455,315,455,270), (455,270,500,270),
]
ok = 0; fails = []
for w in WIRES:
    r = ea.create_wire(list(w), "")
    try:
        d = json.loads(r)
    except Exception:
        d = {"raw": str(r)[:80]}
    if d.get("ok"):
        ok += 1
    else:
        fails.append((w, d))
    time.sleep(0.05)
print("created wires:", ok, "failed:", len(fails))
for f in fails[:8]:
    print("  FAIL", f)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved; wires now:", len(ea.get_wires()))
