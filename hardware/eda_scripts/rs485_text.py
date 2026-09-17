# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef"); time.sleep(1.5)
ids = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>t.primitiveId));})()", t=30))
if ids:
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveText.delete(%s));})()" % json.dumps(ids), t=40)
print("deleted texts:", len(ids))

BLOCK = (
"RS485 隔离收发 / 隔离升压 · 设计说明\n"
"1) 模块选型：TD321D485H-A = 3.3V 版（VCC 3.15~3.45V，TXD/RXD 为 3.3V 电平）\n"
"    原 TD521D485H-A 是 5V 版：VCC 4.75~5.25V、TXD VIH=0.7×VCC=3.5V、\n"
"    RXD 高电平≈VCC-0.2V=4.8V，与 3.3V 的 ELF2 电平不匹配 → 必须换型\n"
"2) VO = 模块「隔离输出电源正」（≤100mA），厂方建议仅用于上拉电阻；\n"
"    本页 VO 同时给 R8 上拉与 MT3608 输入 → 12V 可用电流仅约\n"
"    3.3V×0.1A×0.8÷12V ≈ 20mA；若需更大电流，请给升压单独配\n"
"    隔离 5V（如 B0505S-1W），R8 仍从 VO 取电\n"
"3) 升压反馈：VOUT = 0.6V × (1 + R11/R12)\n"
"    = 0.6V × (1 + 38.3k/2k) = 12.09V（R11=38.3k 1%，R12=2k 1%）\n"
"    需要微调时：R11 取 36k→11.4V、39k→12.3V\n"
"4) 失效保护偏置：R8=820Ω 上拉至 VO、R9=820Ω 下拉至 RGND，\n"
"    空载差分电压 ≈ 3.3V×120/(820+120+820) ≈ 224mV（>200mV 门限）\n"
"5) 端接：R10=120Ω 固定端接；多点总线建议改为跳线/0Ω 可选\n"
"6) CN1：1=+12V(隔离) 2=B 3=A 4=RGND(隔离)；\n"
"    H7：1=DEV GND 2=TXD 3=RXD 4=3V3\n"
"7) 485 ISO GND 与 DEV GND 只通过模块内部隔离，PCB 必须留爬电距离\n"
)
NOTES = [
    (110, 745, 18, True, "① ELF2 UART ↔ RS485 隔离收发（TD321D485H-A，3.3V）"),
    (620, 745, 18, True, "② 隔离升压：VO(3.3V) → MT3608 → VOUT=12V"),
    (110, 350, 12, False, BLOCK),
]
for x, y, fs, bold, content in NOTES:
    r = ea.js("(async()=>{const R=window._EXTAPI_ROOT_;try{await R.sch_PrimitiveText.create(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
              "return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (json.dumps(x), json.dumps(y), json.dumps(content, ensure_ascii=False), 0, json.dumps(None),
                 json.dumps(None), json.dumps(fs), json.dumps(bold), json.dumps(False), json.dumps(False), json.dumps(2)), t=40)
    print("text ->", r); time.sleep(0.25)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
