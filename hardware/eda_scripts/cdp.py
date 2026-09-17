import json, urllib.request, websocket, itertools, time

_ws = None
_id = itertools.count(1)

def connect(port=9222, target=None):
    global _ws
    lst = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list"))
    pages = [t for t in lst if t["type"] == "page"]
    if not pages:
        raise RuntimeError("no page target")
    t = pages[0]
    if target:
        for p in pages:
            if target in (p.get("title") or "") or target in p["url"]:
                t = p; break
    _ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60,
                                     max_size=200*1024*1024, suppress_origin=True)
    return t

def cmd(method, params=None, timeout=60):
    i = next(_id)
    _ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
    t0 = time.time()
    while True:
        if time.time() - t0 > timeout:
            raise TimeoutError(method)
        msg = json.loads(_ws.recv())
        if msg.get("id") == i:
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg.get("result", {})

def ev(expr, await_promise=False, by_value=True, timeout=60):
    r = cmd("Runtime.evaluate", {
        "expression": expr,
        "returnByValue": by_value,
        "awaitPromise": await_promise,
        "userGesture": True,
        "allowUnsafeEvalBlockedByCSP": True,
    }, timeout=timeout)
    if "exceptionDetails" in r:
        d = r["exceptionDetails"]
        desc = (d.get("exception") or {}).get("description") or d.get("text")
        raise RuntimeError("JS EXC: " + str(desc))
    return r.get("result", {}).get("value")

def close():
    global _ws
    if _ws:
        try: _ws.close()
        except Exception: pass
        _ws = None
