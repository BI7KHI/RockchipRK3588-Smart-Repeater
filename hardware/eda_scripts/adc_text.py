# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("85d62bb6700380a3"); time.sleep(1.2)
ids = json.loads(ea.js("(async()=>{const R=window._EXTAPI_ROOT_; const a=await R.sch_PrimitiveText.getAll(); return JSON.stringify(a.map(t=>t.primitiveId));})()", t=30))
if ids:
    ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveText.delete(%s));})()" % json.dumps(ids), t=40)
print("deleted texts:", len(ids))

A = ("ELF2 ADC 分压采集 · 验算（RK3588 SARADC：12bit，输入 0~1.8V/AVDD18）\n"
     "CH1 = VBAT（电池）：R14 100Ω + R15 91kΩ 上臂，R16 10kΩ 下臂\n"
     "  分压比 = 10k/(100+91k+10k) = 0.09891\n"
     "  V_ADC = VBAT × 0.09891；1.8V 满量程 ↔ VBAT = 18.20V\n"
     "  14.0V → 1.385V（约 3151 码）；分辨率 ≈ 4.44mV/LSB\n"
     "CH2 = Vs（光伏）：R17 100Ω + R18 160kΩ 上臂，R19 10kΩ 下臂\n"
     "  分压比 = 10k/(100+160k+10k) = 0.05879\n"
     "  V_ADC = Vs × 0.05879；1.8V 满量程 ↔ Vs = 30.62V\n"
     "  25.0V → 1.470V（约 3344 码）；分辨率 ≈ 7.48mV/LSB")
B = ("设计要点 / 注意事项\n"
     "· 软件换算：VBAT = ADC_V×10.11，Vs = ADC_V×17.01\n"
     "  （ADC_V = 码值/4096×1.8V）\n"
     "· C8/C9 = 10nF 与戴维南阻抗(≈9.0k/9.4k) 构成 ≈1.7kHz 低通，\n"
     "  兼作采样电荷池，应紧靠 ADC 引脚；R15/16/18/19 建议用 1%\n"
     "· 功耗：CH1 ≈138µA、CH2 ≈147µA；R15/R18 耗散 1.7/3.5mW\n"
     "  （R18 两端最高 ≈29V，0603 耐压 50V 够用）\n"
     "· 保护：D3/D4 = SMF3.3CA；源阻抗 ≈9k 把故障电流限在 0.3mA 内，\n"
     "  ADC 内部钳位可承受（若要更精细可换 2.5~2.8V TVS）\n"
     "· ⚠ ADC CH1/CH2 目前未引出到 ELF2：应接 P1_36/P1_38\n"
     "  （SARADC_VIN4/VIN5，1.8V 域）；勿用 VIN0/VIN1/VIN3\n"
     "  （BOOT/RECOVERY/耳机检测已占用）")
NOTES = [(95, 560, 10.5, False, A), (620, 560, 10.5, False, B)]
for x, y, fs, bold, content in NOTES:
    expr = ("(async()=>{const R=window._EXTAPI_ROOT_;try{await R.sch_PrimitiveText.create(%d,%d,%s,0,null,null,%s,false,false,false,2);"
            "return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
            % (x, y, json.dumps(content, ensure_ascii=False), fs))
    print("text@(%d,%d) ->" % (x, y), ea.js(expr, t=40)); time.sleep(0.25)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
