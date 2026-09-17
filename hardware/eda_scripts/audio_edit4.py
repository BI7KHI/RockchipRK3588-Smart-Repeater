import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.5)

# 1) 清空导线（幂等重建）
wires = ea.get_wires()
if wires:
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveWire.delete(%s));})()"
          % json.dumps([w["primitiveId"] for w in wires]), t=60)
    print("deleted wires:", len(wires))

# 2) C4 右移 10mil，让 U2.6 / C4.2 之间有一段真实导线
comps = {c.get("designator"): c for c in ea.get_components() if c.get("componentType") == "part"}
c4 = comps["C4"]
m = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; try{await R.sch_PrimitiveComponent.modify(%s,%s); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
          % (json.dumps(c4["primitiveId"]), json.dumps({"x": 485})), t=30)
print("move C4 ->", m)
time.sleep(0.5)
c4pins = ea.get_pins(c4["primitiveId"])
print("C4 pins now:", json.dumps([{"n": p.get("pinNumber"), "x": p.get("x"), "y": p.get("y")} for p in c4pins], ensure_ascii=False))

WIRES = [
    (240,500,260,500), (300,500,320,500), (360,500,360,480), (360,480,395,480), (395,480,395,470),
    (360,440,360,430), (395,440,360,440), (455,470,455,500), (495,500,505,500), (455,440,490,440),
    (490,440,490,425),
    (240,345,260,345), (300,345,320,345), (360,345,395,345), (360,325,360,345), (360,285,360,270),
    (360,270,275,270), (395,315,395,270), (395,270,360,270),
    (455,345,465,345), (505,345,515,345), (555,345,580,345),
    (565,345,565,335), (565,295,565,270), (565,270,500,270), (455,315,455,270), (455,270,500,270),
]
ok = 0; fails = []
for w in WIRES:
    r = ea.create_wire(list(w), "")
    try:
        d = json.loads(r)
    except Exception:
        d = {"raw": str(r)[:60]}
    if d.get("ok"):
        ok += 1
    else:
        fails.append((w, d))
    time.sleep(0.04)
print("wires created:", ok, "failed:", fails)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
