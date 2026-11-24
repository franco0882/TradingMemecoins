#!/usr/bin/env python3
"""Offline backtest (read-only, writes nothing, no API calls) of copycat_filter.py against (1) every closed A/B scanner row in near_misses.csv and
(2) the learning book's own trades.csv. The symbol registry is rebuilt in time order from near_misses.csv, so there is no look-ahead.
Usage: python3 filter_backtest.py   (optional env overrides: CF_LIQ_MCAP, CF_VOL1H_LIQ, CF_MIN_AGE, CF_CLONE=0)"""
import csv, os, sys, statistics as st, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import copycat_filter as CF
CF.LIQ_MCAP_MAX = float(os.environ.get("CF_LIQ_MCAP", CF.LIQ_MCAP_MAX)); CF.VOL1H_LIQ_MAX = float(os.environ.get("CF_VOL1H_LIQ", CF.VOL1H_LIQ_MAX)); CF.MIN_AGE_H = float(os.environ.get("CF_MIN_AGE", CF.MIN_AGE_H))
_D = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NM = os.path.join(_D, "ledger", "nearmiss", "near_misses.csv"); TR = os.environ.get("CF_TRADES", os.path.join(_D, "ledger", "learning", "trades.csv"))
def fl(x):
    try: return float(x)
    except Exception: return None
def T(s): return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
nm = sorted(csv.DictReader(open(NM, newline="")), key=lambda r: T(r["ts_et"]))
LANES = {("FULL-PASS", "A"), ("A-nearmiss", "A"), ("B-shadow", "B"), ("FULL-PASS", "B")}
reg = {}; verdict = {}; i = 0
while i < len(nm):
    j = i
    while j < len(nm) and nm[j]["ts_et"] == nm[i]["ts_et"]: j += 1          # same scanner run: update registry first, then evaluate (mirrors live)
    t = T(nm[i]["ts_et"]); grp = nm[i:j]
    CF.registry_update(reg, [(r["mint"], r["symbol"], r["liq"]) for r in grp], t)
    for r in grp:
        if (r["class"], r["lane"]) in LANES:
            ok, why = CF.check(dict(mint=r["mint"], symbol=r["symbol"], mcap=r["mcap"], liq=r["liq"], vol1h=r["vol1h"], age_h=r["age_h"]), reg, t)
            if os.environ.get("CF_CLONE") == "0": why = [w for w in why if not w.startswith("clone")]; ok = not why
            verdict[r["row_id"]] = (ok, why)
    i = j
def rug(reason, net): return reason == "liq_drained_rug" or (net is not None and net <= -90)
def report(title, items):
    """items: list of (ok, why, net, reason)"""
    R = [x for x in items]; B = [x for x in R if not x[0]]; K = [x for x in R if x[0]]
    nets = lambda L: [x[2] for x in L]
    f = lambda L: f"avg {sum(nets(L)) / len(L):+.1f}% med {st.median(nets(L)):+.1f}%" if L else "n/a"
    print(f"\n== {title}: {len(R)} closed ==")
    print(f"  rugged trades        : {sum(rug(x[3], x[2]) for x in R):3d}  blocked by filter: {sum(rug(x[3], x[2]) for x in B):3d}  still taken: {sum(rug(x[3], x[2]) for x in K):3d}")
    print(f"  winners (net>0)      : {sum(x[2] > 0 for x in R):3d}  blocked by filter: {sum(x[2] > 0 for x in B):3d}")
    print(f"  big winners (net>10%): {sum(x[2] > 10 for x in R):3d}  blocked by filter: {sum(x[2] > 10 for x in B):3d}")
    print(f"  blocked ({len(B)}): {f(B)}   |   kept ({len(K)}): {f(K)}   |   all: {f(R)}")
    reasons = {}
    for x in B:
        for w in x[1]: reasons[w.split('(')[0]] = reasons.get(w.split('(')[0], 0) + 1
    print(f"  block reasons (a trade may hit several): {reasons}")
sc = [r for r in nm if r["row_id"] in verdict and r["status"] == "closed" and fl(r["net_pct"]) is not None]
for lane in ("A", "B"):
    report(f"scanner rows lane {lane} (FULL-PASS + A-nearmiss / B-shadow)", [(*verdict[r["row_id"]], fl(r["net_pct"]), r["exit_reason"]) for r in sc if r["lane"] == lane])
report("scanner rows ALL", [(*verdict[r["row_id"]], fl(r["net_pct"]), r["exit_reason"]) for r in sc])
if os.path.exists(TR):
    tr = [r for r in csv.DictReader(open(TR, newline="")) if r["status"] == "closed" and not r["strategy"].endswith("-F") and r["scanner_row_id"] in verdict]
    report("learning book trades.csv (base strategies, all closed)", [(*verdict[r["scanner_row_id"]], fl(r["net_pct"]), r["exit_reason"]) for r in tr])
    report("learning book trades.csv (base, clean only)", [(*verdict[r["scanner_row_id"]], fl(r["net_pct"]), r["exit_reason"]) for r in tr if str(r.get("gap_affected")) != "1"])
    print("\nBlocked learning trades detail:")
    for r in tr:
        ok, why = verdict[r["scanner_row_id"]]
        if not ok: print(f"  {r['trade_id']} {r['strategy']:11} {r['symbol'][:10]:10} net {fl(r['net_pct']):+7.1f}%  {r['exit_reason']:16} {'; '.join(why)}")
    print("Taken (passed) learning trades:", ", ".join(f"{r['trade_id']} {r['symbol'][:8]} {fl(r['net_pct']):+.0f}%" for r in tr if verdict[r['scanner_row_id']][0]))
