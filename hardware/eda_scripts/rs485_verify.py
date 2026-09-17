# -*- coding: utf-8 -*-
import base64, json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef"); time.sleep(1.2)
t = ea.sch_netlist_text()
open(r"C:\Users\Admin\Desktop\ELF2\硬件设计\RS485隔离升压_网表.json", "w", encoding="utf-8").write(t or "")
d = json.loads(t)
want = {"U3","U4","R6","R7","R8","R9","R10","R11","R12","C5","C6","C7","D2","L1","CN1","H7","LED1","LED2"}
for uid, c in d["components"].items():
    p = c.get("props", {}); des = str(p.get("Designator"))
    if des in want:
        pins = {pn: pi.get("net") for pn, pi in (c.get("pinInfoMap") or {}).items()}
        print("%-5s %-24s %-8s %s" % (des, str(p.get("Manufacturer Part") or p.get("DeviceName") or "")[:24],
                                      str(p.get("Value") or "")[:8], json.dumps(pins, ensure_ascii=False)))
# FB 计算核对
print()
print("VOUT = 0.6 * (1 + 38.3k/2k) = %.3f V" % (0.6*(1+38300/2000)))
print("fail-safe bias @3.3V, 820R/820R/120R = %.1f mV" % (3.3*120/(820+120+820)*1000))
# 预览图
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.dmt_EditorControl.zoomToAllPrimitives());})()", t=30)
time.sleep(1.5)
b64 = ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const f=await R.dmt_EditorControl.getCurrentRenderedAreaImage(); const buf=await f.arrayBuffer(); const b=new Uint8Array(buf); let s=''; const C=0x8000; for(let i=0;i<b.length;i+=C) s+=String.fromCharCode.apply(null,b.subarray(i,i+C)); return btoa(s);})()", t=120)
try:
    raw = base64.b64decode(b64)
    p = r"C:\Users\Admin\Desktop\ELF2\硬件设计\RS485隔离升压_原理图.png"
    open(p, "wb").write(raw)
    print("PNG:", p, len(raw))
except Exception as e:
    print("PNG ERR", e)
