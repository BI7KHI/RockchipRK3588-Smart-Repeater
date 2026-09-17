import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea

AUDIO_PAGE = "ea4fc07c502623a3"
RES_0603 = {"libraryUuid": "0819f05c4eef4c71ace90d822a990e87", "uuid": "313ff7d3e0f72116", "name": "Res_0603"}

ea.connect()
ea.open_doc(AUDIO_PAGE); time.sleep(2)
print("cur:", ea.current_doc())

comps = ea.get_components()
wires = ea.get_wires()
byd = {c.get("designator"): c for c in comps if c.get("componentType") == "part"}
print("R2 old:", json.dumps({k: byd["R2"].get(k) for k in ("primitiveId", "designator", "x", "y", "rotation")}, ensure_ascii=False))

# 1) 删除全部导线（稍后按新拓扑重画）
if wires:
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveWire.delete(%s));})()"
          % json.dumps([w["primitiveId"] for w in wires]), t=60)
    print("deleted wires:", len(wires))

# 2) 删除旧 R2（10k 电位器），换成 150R 固定电阻（同位置同朝向）
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveComponent.delete(%s));})()"
      % json.dumps([byd["R2"]["primitiveId"]]), t=60)
time.sleep(0.5)

r = json.loads(ea.create_component(RES_0603, 360, 460, rotation=270, subpart="电阻.1"))
print("new R2 create:", r)
if r.get("ok"):
    pid = r["id"]
    m = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; try{await R.sch_PrimitiveComponent.modify(%s,%s); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (json.dumps(pid), json.dumps({"designator": "R2", "uniqueId": "gga92",
                                              "otherProperty": {"Value": "150R"}}, ensure_ascii=False)), t=60)
    print("modify R2:", m)
    pins = ea.get_pins(pid)
    print("new R2 pins:", json.dumps([{ "n": p.get("pinNumber"), "x": p.get("x"), "y": p.get("y")} for p in pins], ensure_ascii=False))

# 3) 改 R3/R4 阻值
for des, val in (("R3", "1K"), ("R4", "220R")):
    pid = byd[des]["primitiveId"]
    m = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; try{await R.sch_PrimitiveComponent.modify(%s,%s); return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (json.dumps(pid), json.dumps({"otherProperty": {"Value": val}}, ensure_ascii=False)), t=60)
    print("modify", des, val, "->", m)

ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=60)
print("saved")
