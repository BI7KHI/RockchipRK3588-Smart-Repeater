# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef"); time.sleep(1.2)
ids = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>t.primitiveId));})()", t=30))
if ids:
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveText.delete(%s));})()" % json.dumps(ids), t=40)
print("deleted texts:", len(ids))

B1 = ("RS485 隔离收发 · 设计要点\n"
      "· 模块选型：TD321D485H-A = 3.3V 版（VCC 3.15~3.45V，\n"
      "  TXD/RXD 均为 3.3V 电平，可与 ELF2 直连）\n"
      "· 原 TD521D485H-A 为 5V 版（VCC 4.75~5.25V，\n"
      "  TXD VIH=3.5V、RXD 高电平≈4.8V）→ 3.3V 系统不匹配\n"
      "· 自动流控，无需 DE/RE 控制脚\n"
      "· 两端隔离 2500V：485 ISO GND 与 DEV GND 不可相连，\n"
      "  PCB 需留爬电距离\n"
      "· H7：1=DEV GND  2=TXD  3=RXD  4=3V3\n"
      "· LED 限流 R6/R7 = 1K（约 1.3mA）")
B2 = ("隔离升压 · 设计要点\n"
      "· VO = 模块「隔离输出电源正」(≤100mA)，厂方建议仅作上拉；\n"
      "  本页 VO 兼顾 R8 上拉与 MT3608 输入 → 12V 可用电流\n"
      "  ≈3.3V×0.1A×0.8÷12V ≈ 20mA；更大电流请给升压单独配\n"
      "  隔离 5V（如 B0505S-1W），R8 仍从 VO 取电\n"
      "· VOUT = 0.6V × (1 + R11/R12) = 0.6 × (1 + 38.3k/2k)\n"
      "  = 12.09V（R11 = 38.3k 1%，R12 = 2k 1%）\n"
      "· 失效保护偏置：R8/R9 = 820Ω + R10 = 120Ω →\n"
      "  空载差分 ≈ 224mV（>200mV 门限）\n"
      "· R10 = 120Ω 固定端接，多点总线建议改为跳线可选\n"
      "· CN1：1=+12V(隔离)  2=B  3=A  4=RGND(隔离)")
NOTES = [
    (110, 755, 17, True, "① ELF2 UART ↔ RS485 隔离收发（TD321D485H-A，3.3V）"),
    (620, 755, 17, True, "② 隔离升压：VO(3.3V) → MT3608 → VOUT = 12V"),
    (110, 205, 12, False, B1),
    (620, 205, 11, False, B2),
]
for x, y, fs, bold, content in NOTES:
    r = ea.js("(async()=>{const R=window._EXTAPI_ROOT_;try{await R.sch_PrimitiveText.create(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
              "return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (json.dumps(x), json.dumps(y), json.dumps(content, ensure_ascii=False), 0, json.dumps(None),
                 json.dumps(None), json.dumps(fs), json.dumps(bold), json.dumps(False), json.dumps(False), json.dumps(2)), t=40)
    print("text ->", r); time.sleep(0.25)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
