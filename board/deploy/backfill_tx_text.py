# -*- coding: utf-8 -*-
"""把历史「本机发射」段里 ASR 猜出来的文字，换成语音助手的真原文。

背景：修好之前，本机发射的声音也被送进 ASR，于是日志里留下
「电池电压是3.15伏特光，除电压12.83伏特秒。」这种文字（真原文是
「电池电压十三点一五伏特，光伏电压十二点八三伏特喵」）。

能补的只有**语音助手发的那些**——它的原文留在 assist_turns.reply 里。
定时播报的文字只存在内存（_announce_log），重启即失，补不回来；APRS 信标本来
就没有文本。这些段脚本会原样留着并统计出来，不做任何改动。

匹配靠时间窗（录音段窗口 vs 回合的发射窗口），并要求**唯一**：窗口里出现两个
候选时，除非最像的那个重叠明显更大，否则判为有歧义、不动 —— 宁可不补，也不把
别人的回复贴到这一段上。

原 ASR 文本不会被丢掉：改写后写进 note（「原 ASR 文本：…」），日志里仍可追溯。

用法（先看清单，再决定）：
    python3 backfill_tx_text.py                       # 预演，只打印
    python3 backfill_tx_text.py --apply               # 真写
    python3 backfill_tx_text.py --day 2026-09-26      # 只处理某天
    python3 backfill_tx_text.py --db /www/relay.db
"""
import argparse
import datetime as dt
import sqlite3
import sys

NOTE_PREFIX = '历史回填：文字取自语音助手回合'
MIN_OVERLAP = 1.0        # 至少重叠 1 秒才算配上
AMBIG_RATIO = 1.5        # 最佳候选要通过这个倍数压过第二名，否则算有歧义


def iso_epoch(s):
    try:
        return dt.datetime.fromisoformat(str(s)).timestamp()
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='/www/relay.db')
    ap.add_argument('--day', default='')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--limit', type=int, default=500)
    a = ap.parse_args()

    # 预演一律只读打开：看清单这个动作绝不能碰到库
    c = sqlite3.connect('file:%s%s' % (a.db, '' if a.apply else '?mode=ro'), uri=True)
    c.row_factory = sqlite3.Row

    lead = 3.0
    try:
        r = c.execute("SELECT value FROM settings WHERE key='vlog_pre_roll'").fetchone()
        if r and r[0]:
            lead = float(r[0])
    except Exception:
        pass

    turns = []
    for r in c.execute("SELECT id,ts,reply,tx_seconds,action FROM assist_turns "
                       "WHERE reply IS NOT NULL AND reply<>'' ORDER BY id"):
        e = iso_epoch(r['ts'])
        dur = float(r['tx_seconds'] or 0) or 0.0
        if e and dur <= 0.2:                 # 没记发射时长的老回合，按字数粗估
            dur = max(1.0, len(r['reply']) / 5.0)
        if e:
            turns.append({'id': r['id'], 'e': e, 'dur': dur,
                          'reply': r['reply'].strip()})

    sql = ("SELECT id,ts,ts_epoch,seconds,asr_status,asr_text,category,note "
           "FROM voice_logs WHERE kind='tx' AND IFNULL(asr_status,'')<>'tx' "
           "AND IFNULL(asr_status,'')<>'skip'")
    args = []
    if a.day:
        sql += ' AND substr(ts,1,10)=?'
        args.append(a.day)
    sql += ' ORDER BY id LIMIT ?'
    args.append(a.limit)
    rows = c.execute(sql, args).fetchall()

    plan, no_src, ambiguous = [], [], []
    for r in rows:
        seg_e = float(r['ts_epoch'] or 0)
        seg_dur = float(r['seconds'] or 0)
        if not seg_e:
            no_src.append((r, '没有 ts_epoch'))
            continue
        s0, s1 = seg_e - lead, seg_e + seg_dur
        cands = []
        for t in turns:
            t0, t1 = t['e'] - t['dur'] - 5.0, t['e'] + 5.0
            ov = min(s1, t1) - max(s0, t0)
            if ov >= MIN_OVERLAP:
                cands.append((ov, t))
        if not cands:
            no_src.append((r, '时间窗内没有助手回合（多半是定时播报/信标）'))
            continue
        cands.sort(key=lambda x: x[0], reverse=True)
        if len(cands) > 1 and cands[1][0] * AMBIG_RATIO > cands[0][0]:
            ambiguous.append((r, cands[:2]))
            continue
        plan.append((r, cands[0][1], round(cands[0][0], 1)))

    print('候选段 %d 条：可回填 %d / 无来源 %d / 有歧义 %d'
          % (len(rows), len(plan), len(no_src), len(ambiguous)))
    print('（pre-roll 补偿 %.1fs；匹配窗口 = 段 [ts-%.1f, ts+len] ∩ 回合 [发射前, 发射后+5s]）'
          % (lead, lead))

    print('\n=== 可回填（原 ASR 文字 → 真原文）===')
    for r, t, ov in plan:
        print('#%-5s %s  重叠%.1fs' % (r['id'], (r['ts'] or '')[5:19], ov))
        print('       原[%s]' % (r['asr_text'] or '').strip()[:70])
        print('       新[%s]' % t['reply'][:70])

    if ambiguous:
        print('\n=== 有歧义，不动 ===')
        for r, cs in ambiguous:
            print('#%-5s %s  候选：%s' % (
                r['id'], (r['ts'] or '')[5:19],
                ' | '.join('%s(%.1fs)' % (x[1]['reply'][:20], x[0]) for x in cs)))

    print('\n=== 无来源，保持原样 ===')
    for r, why in no_src[:30]:
        print('#%-5s %s  %s  [%s]' % (r['id'], (r['ts'] or '')[5:19], why,
                                      (r['asr_text'] or '').strip()[:40]))
    if len(no_src) > 30:
        print('… 另有 %d 条同类的' % (len(no_src) - 30))

    if not a.apply:
        print('\n（预演）加 --apply 才真的改写；原 ASR 文字会写进 note 以便追溯')
        return 0

    n = 0
    for r, t, _ov in plan:
        old = (r['asr_text'] or '').strip()
        note = '%s #%s；原 ASR 文本：%s' % (NOTE_PREFIX, t['id'], old or '（空）')
        c.execute("UPDATE voice_logs SET asr_text=?, asr_status='tx', note=?, "
                  "category='voice', asr_json='', asr_ms=0, rtf=0 WHERE id=?",
                  (t['reply'], note, r['id']))
        n += 1
    c.commit()
    print('\n已回填 %d 条，跳过 %d 条无来源 / %d 条有歧义' % (n, len(no_src), len(ambiguous)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
