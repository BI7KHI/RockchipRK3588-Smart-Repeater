# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("a68e58ecf0ff6fef"); time.sleep(1.2)
# 在悬空线端补 3V3 电源标识（H7.4 / U3.1+C5.1 / R6.2 / R7.2）
PTS = [(230, 430), (135, 540), (115, 710), (190, 710)]
for x, y in PTS:
    r = ea.js("(async()=>{const R=window._EXTAPI_ROOT_;try{const c=await R.sch_PrimitiveComponent.createNetFlag('Power','3V3',%d,%d,0,false);"
              "return JSON.stringify({ok:true,id:c&&c.primitiveId});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()" % (x, y), t=40)
    print("flag@(%d,%d) ->" % (x, y), r); time.sleep(0.25)
ea.js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=30)
print("saved")
