import cdp, json
def connect(): return cdp.connect()
def call(js, t=120): return cdp.ev(js, await_promise=True, timeout=t)
def raw(js, t=120): return cdp.ev(js, await_promise=False, timeout=t)
R = "window._EXTAPI_ROOT_"
def js(expr, t=120): return call(expr, t)
def open_page(uuid):
    return call('(async()=>{const R=window._EXTAPI_ROOT_;return JSON.stringify(await R.dmt_EditorControl.openDocument(%s));})()' % json.dumps(uuid))
def comps():
    return json.loads(call('(async()=>{const R=window._EXTAPI_ROOT_;return JSON.stringify(await R.sch_PrimitiveComponent.getAll());})()'))
def wires():
    return json.loads(call('(async()=>{const R=window._EXTAPI_ROOT_;return JSON.stringify(await R.sch_PrimitiveWire.getAll());})()'))
def flags():
    return [c for c in comps() if c.get('componentType')=='netflag']
def comps_pcb():
    import json
    return json.loads(js('(async()=>{const R=window._EXTAPI_ROOT_;return JSON.stringify(await R.pcb_PrimitiveComponent.getAll());})()'))
