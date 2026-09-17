# -*- coding: utf-8 -*-
import json, sys
sys.path.insert(0, ".")
d = json.load(open('rs485_dump.json', encoding='utf-8'))
idx = {}
for p in d['parts']:
    for pn, xy in p['pins'].items():
        idx.setdefault((xy[0], xy[1]), []).append('%s.%s' % (p['des'], pn))
for f in d['flags']:
    idx.setdefault((f['x'], f['y']), []).append('FLAG:' + str(f['net']))
for q in d['ports']:
    idx.setdefault((q['x'], q['y']), []).append('PORT:' + str(q['net']))
def who(pt):
    return '/'.join(idx.get((pt[0], pt[1]), ['?']))
for w in d['wires']:
    ln = w.get('getState_Line')
    if not ln: continue
    pts = [(ln[i], ln[i+1]) for i in range(0, len(ln), 2)]
    print('%-16s net=%-14s %s ==> %s   %s' % (w['id'], str(w.get('net'))[:14], who(pts[0]), who(pts[-1]), pts))
