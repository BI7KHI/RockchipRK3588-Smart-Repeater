#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ELF2 LCEDA Pro 自动化辅助：元件放置、引脚读取、星形原理图连线、网表校验。"""
import json
import sys
import time

sys.path.insert(0, r"C:\Users\Admin\.dsh\skills\jlc-eda-pro-cdp\scripts")
import api
import cdp

SYSTEM_LIB = "0819f05c4eef4c71ace90d822a990e87"


def connect():
    cdp.connect()
    for _ in range(30):
        try:
            if api.raw("typeof window._EXTAPI_ROOT_ !== 'undefined'"):
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("EXTAPI not ready")


def js(expr, t=120):
    return api.js(expr, t)


def raw(expr, t=120):
    return api.raw(expr, t)


def open_project(project_uuid):
    return js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.dmt_Project.openProject(%s));})()" % json.dumps(project_uuid), t=120)


def open_doc(doc_uuid):
    return js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.dmt_EditorControl.openDocument(%s,'editor-window-main'));})()" % json.dumps(doc_uuid), t=120)


def current_doc():
    return js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.dmt_SelectControl.getCurrentDocumentInfo());})()")


def search_device(key, limit=5):
    expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.lib_Device.search(%s,%s,null,null,%d,1); return JSON.stringify(r);}catch(e){return JSON.stringify({err:String(e&&e.message||e)});}})()"
            % (json.dumps(key), json.dumps(SYSTEM_LIB), limit))
    return json.loads(js(expr, t=60))


def device_obj(dev):
    return {"libraryUuid": dev.get("libraryUuid") or SYSTEM_LIB,
            "uuid": dev.get("uuid"),
            "name": dev.get("name")}


def create_component(dev, x, y, rotation=0, subpart="R.1"):
    expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.sch_PrimitiveComponent.create(%s,%s,%s,%s,%s,false,true,true); return JSON.stringify({ok:true,id:r.primitiveId});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
            % (json.dumps(device_obj(dev)), json.dumps(x), json.dumps(y), json.dumps(subpart), json.dumps(rotation)))
    return json.loads(js(expr, t=90))


def get_components():
    return json.loads(js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveComponent.getAll());})()", t=90))


def get_wires():
    return json.loads(js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveWire.getAll());})()", t=90))


def get_pins(primitive_id):
    return json.loads(js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveComponent.getAllPinsByPrimitiveId(%s));})()" % json.dumps(primitive_id), t=60))


def create_wire(line, net="", color=None, line_width=None, line_type=None):
    return js("(async()=>{const R=window._EXTAPI_ROOT_; try{const r=await R.sch_PrimitiveWire.create(%s,%s,%s,%s,%s); return JSON.stringify({ok:true,id:r.getState_PrimitiveId()});}catch(e){return JSON.stringify({ok:false,err:String(e&&e.message||e)});}})()"
              % (json.dumps(line), json.dumps(net), json.dumps(color), json.dumps(line_width), json.dumps(line_type)), t=60)


def delete_components(ids):
    if not ids:
        return True
    return js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveComponent.delete(%s));})()" % json.dumps(ids), t=60)


def delete_wires(ids):
    if not ids:
        return True
    return js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_PrimitiveWire.delete(%s));})()" % json.dumps(ids), t=60)


def clear_schematic():
    comps = get_components()
    ids = [c["primitiveId"] for c in comps if c.get("componentType") != "sheet"]
    delete_components(ids)
    wires = get_wires()
    delete_wires([w["primitiveId"] for w in wires])
    return len(ids), len(wires)


def save_doc():
    return js("(async()=>{const R=window._EXTAPI_ROOT_; return JSON.stringify(await R.sch_Document.save());})()", t=60)


def sch_netlist_text():
    """导出原理图网表 JSON 文本（不依赖 sch_Netlist.getNetlist）。"""
    expr = ("(async()=>{const R=window._EXTAPI_ROOT_; try{const f=await R.sch_ManufactureData.getNetlistFile('tmp_net','JLCEDA'); const buf=await f.arrayBuffer(); const b=new Uint8Array(buf); let s=''; const C=0x8000; for(let i=0;i<b.length;i+=C) s+=String.fromCharCode.apply(null,b.subarray(i,i+C)); return btoa(s);}catch(e){return JSON.stringify({err:String(e&&e.message||e)});}})()")
    r = js(expr, t=180)
    if r.startswith("{"):
        return None
    import base64
    return base64.b64decode(r).decode("utf-8", "replace")
