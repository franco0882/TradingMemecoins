#!/usr/bin/env python3
"""Offline replay (read-only): applies the learning-mode entry caps to the scanner's historical rows (near_misses.csv), whose outcomes already use the same
ladder/rug/fee/slippage code. Writes nothing. Usage: replay.py"""
import csv, sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["LEARN_DIR"] = "/tmp"; import learning as L
rows = list(csv.DictReader(open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "ledger", "nearmiss", "near_misses.csv"))))
cand = []
for r in rows:
    s = L.STRATEGIES.get((r["class"], r["lane"]))
    if s: cand.append((L.parse_ts(r["ts_et"]), s, r))
cand.sort(key=lambda c: (c[0], L.PRIORITY.index(c[1]), -L.fnum(c[2]["vol5m"])))
openp = []; lastclose = {}; perday = collections.Counter(); perstrat = collections.Counter(); out = []; skips = collections.Counter(); NOW = 4e9
for t, s, r in cand:
    openp = [p for p in openp if p[0] > t]
    m = r["mint"]; day = L.et(t).strftime("%Y-%m-%d"); why = None
    if any(p[1] == m for p in openp): why = "mint_open"
    elif t - lastclose.get(m, 0) < L.REENTRY_COOLDOWN_S: why = "cooldown"
    elif len(openp) >= L.MAX_OPEN: why = "max_open"
    elif perday[day] >= L.MAX_NEW_PER_DAY: why = "daily_cap"
    elif perstrat[(day, s)] >= L.PER_STRATEGY_DAY_CAP: why = "strategy_cap"
    if why: skips[why] += 1; continue
    ct = L.parse_ts(r["exit_ts_et"]) if r["status"] == "closed" else None
    end = ct or NOW; openp.append((end, m)); perday[day] += 1; perstrat[(day, s)] += 1
    if ct: lastclose[m] = ct
    out.append((s, r["status"], L.fnum(r["net_pct"]), r["symbol"], r["exit_reason"]))
agg = collections.defaultdict(list)
for s, st, n, sym, ex in out:
    if st == "closed": agg[s].append(n)
print("trades taken:", len(out), "skips:", dict(skips), "per day:", dict(perday))
tot = 0
for s, v in agg.items():
    v2 = sorted(v); sol = sum(v) * L.SIZE / 100; tot += sol
    print(f"{s}: closed={len(v)} win%={sum(x>0 for x in v)/len(v)*100:.0f} avg={sum(v)/len(v):.1f}% median={v2[len(v2)//2]:.1f}% net={sol:+.4f} SOL")
print(f"total closed net {tot:+.4f} SOL; still open at end: {sum(1 for o in out if o[1]=='open')}")
