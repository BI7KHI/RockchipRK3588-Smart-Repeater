# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.5)
ids = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>t.primitiveId));})()", t=30))
if ids:
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveText.delete(%s));})()" % json.dumps(ids), t=40)
print("deleted:", len(ids))

BODY = ("1) U1/U2 = HR228434：1:1 600:600，350Hz~3.5kHz，插入损耗≤2dB\n"
        "    绕组间耐压1000Vrms，额定电平约1Vrms\n"
        "2) 变压器绕组不能过直流，C1~C4 为串联隔直电容：\n"
        "    电台MIC有驻极体偏置，ELF2 MIC 口有 MICBIAS\n"
        "3) 衰减网络放在变压器初级之前，磁芯工作在小信号区\n"
        "4) 分压后源阻抗约100~200Ω，接近600Ω设计值，低频好\n"
        "5) DEV GND 与 RPT GND 仅通过 U1/U2 磁耦合隔离\n"
        "    （PTT / RS485 等其它连线也必须隔离）\n"
        "6) 电台 SPK 若为 BTL 桥式输出（扩展口1/16脚均不接地）\n"
        "    → 本页单端接法不可用，须改差分接入\n"
        "7) 音频地回路请从 PTT/射频走线外侧绕行，避免串扰")

NOTES = [
    (700, 690, 19, True,  "音频隔离衰减 · 设计说明"),
    (700, 660, 12, False, BODY),
    (240, 545, 14, True,  "TX: ELF2 DAC → 电台 MIC   衰减 -20.7dB，输出 ≈260mVpp"),
    (240, 380, 14, True,  "RX: 电台 SPK → ELF2 MIC   衰减 -17.2dB，输出 ≈480mVpp"),
]
for x, y, fs, bold, content in NOTES:
    r = ea.js("(async()=>{const R=window._EXTAPI_ROOT_;try{await R.sch_PrimitiveText.create(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
              "return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (json.dumps(x), json.dumps(y), json.dumps(content, ensure_ascii=False), 0, json.dumps(None),
                 json.dumps(None), json.dumps(fs), json.dumps(bold), json.dumps(False), json.dumps(False), json.dumps(2)), t=40)
    print("text ->", r); time.sleep(0.25)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
