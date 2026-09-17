# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
import eda_auto as ea
ea.connect()
ea.open_doc("ea4fc07c502623a3"); time.sleep(1.2)
pts = []
for c in ea.get_components():
    ct = c.get("componentType")
    if ct in ("part",):
        for p in ea.get_pins(c["primitiveId"]):
            pts.append((p.get("x"), p.get("y"), "%s.%s" % (c.get("designator"), p.get("pinNumber"))))
    elif ct in ("netport", "netflag"):
        pts.append((c.get("x"), c.get("y"), "%s:%s" % (ct, c.get("net"))))
pts = [p for p in pts if p[0] is not None]
print("n elements:", len(pts))
print("y histogram (每 50 单位):")
import collections
h = collections.Counter(int(p[1] // 50 * 50) for p in pts)
for k in sorted(h): print("   y=%4d..%4d : %d" % (k, k+49, h[k]))
print("x histogram:")
h2 = collections.Counter(int(p[0] // 100 * 100) for p in pts)
for k in sorted(h2): print("   x=%4d..%4d : %d" % (k, k+99, h2[k]))
print("最下方 8 个元素:")
for p in sorted(pts, key=lambda z: z[1])[:8]: print("   ", p)
print("最上方 8 个元素:")
for p in sorted(pts, key=lambda z: -z[1])[:8]: print("   ", p)
