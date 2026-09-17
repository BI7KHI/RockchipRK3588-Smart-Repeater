# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.2)
old = None
for t in json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>({id:t.primitiveId,y:t.y,lines:t.content.split(String.fromCharCode(10)).length})));})()", t=30)):
    if t["lines"] > 3:
        old = t["id"]
if old:
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveText.delete(%s));})()" % json.dumps([old]), t=40)
    print("deleted old block:", old)
BLOCK = ("音频隔离衰减 · 设计说明\n"
         "1) U1/U2 = HR228434：1:1 600:600，350Hz~3.5kHz，插入损耗≤2dB\n"
         "2) C1~C4 为串联隔直电容（电台 MIC 有偏置、ELF2 MIC 有 MICBIAS），\n"
         "    变压器绕组不能过直流\n"
         "3) 衰减网络放在变压器初级之前，磁芯工作在小信号区\n"
         "4) TX：R1 1k + R2 150 → 输出 ≈260mVpp（对应 80mV→60% 调制度）\n"
         "5) RX：R3 1k + R4 220 → 输出 ≈480mVpp（约 -15dBFS）\n"
         "6) DEV GND 与 RPT GND 仅通过 U1/U2 磁耦合隔离\n"
         "7) 电台 SPK 若为 BTL 桥式（两脚均不接地）→ 本页单端接法不可用")
expr = ("(async()=>{const R=window._EXTAPI_ROOT_;try{await R.sch_PrimitiveText.create(110,150,"
        + json.dumps(BLOCK, ensure_ascii=False) +
        ",0,null,null,11,false,false,false,2);return JSON.stringify({ok:true});}"
        "catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()")
print("new block ->", ea.js(expr, t=40))
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
