# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.5)

NOTES = [
    (600, 545, 20, True,
     "TX 输出通道：ELF2 DAC → 电台 MIC（外接MIC脚）"),
    (600, 515, 16, False,
     "· ELF2 DAC 满量程 1.0Vrms（NAU88C22 耳机输出，22Ω串阻）\n"
     "· R1 1kΩ + R2 150Ω 分压 ≈ -20.7dB，U1 为 1:1 隔离变压器\n"
     "· 输出 ≈260mVpp（≈92mVrms），对应电台 80mV→60% 调制度\n"
     "· C3 / C2 为串联隔直电容（1uF/50V），不可省略\n"
     "· 需微调电平：R2 120Ω 降约1dB，200Ω 升约1dB；或调 ELF2 软件音量"),
    (600, 400, 20, True,
     "RX 采集通道：电台 SPK → ELF2 MIC（耳机口 MIC 脚）"),
    (600, 370, 16, False,
     "· 电台 SPK 实测 3.5Vpp（≈1.24Vrms）\n"
     "· R3 1kΩ + R4 220Ω 分压 ≈ -17.2dB，U2 为 1:1 隔离变压器\n"
     "· 输出 ≈480mVpp（0.17Vrms，约 -15dBFS；ELF2 MIC 满量程 1.0Vrms）\n"
     "· C1 / C4 串联隔直，R5 100Ω 限流，D1 ESD 保护\n"
     "· ELF2 侧电平偏低时用 MIC PGA 增益补偿，不要改分压电阻"),
    (240, 215, 20, True,
     "音频隔离衰减 · 设计说明"),
    (240, 185, 15, False,
     "1. U1/U2 = HR228434：1:1 600:600，350Hz~3.5kHz，插入损耗≤2dB，绕组耐压1000Vrms，额定电平约1Vrms\n"
     "2. 变压器绕组不能过直流：C1~C4 为串联隔直电容（电台MIC有驻极体偏置、ELF2 MIC有MICBIAS）\n"
     "3. 衰减网络放在变压器之前（初级侧），变压器工作在小信号区，避免磁芯饱和\n"
     "4. 分压后源阻抗约100~200Ω，接近变压器600Ω设计值，低频响应好\n"
     "5. DEV GND 与 RPT GND 仅通过 U1/U2 磁耦合，两地相互隔离（PTT/RS485 也必须隔离）\n"
     "6. 电台 SPK 若为 BTL 桥式输出（附件口1/16脚均不接地）→ 本页单端接法不可用，\n"
     "    必须改为差分接入，且任何一脚都不得接 RPT GND"),
]

for i, (x, y, fs, bold, content) in enumerate(NOTES):
    expr = ("(async()=>{const R=window._EXTAPI_ROOT_;try{const t=await R.sch_PrimitiveText.create(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
            "return JSON.stringify({ok:true,id:t&&t.getState_PrimitiveId&&t.getState_PrimitiveId()});}"
            "catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
            % (json.dumps(x), json.dumps(y), json.dumps(content, ensure_ascii=False), 0,
               json.dumps(None), json.dumps(None), json.dumps(fs), json.dumps(bold),
               json.dumps(False), json.dumps(False), json.dumps(2)))
    r = ea.js(expr, t=40)
    print(i, "->", r)
    time.sleep(0.3)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
