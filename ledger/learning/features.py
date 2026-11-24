#!/usr/bin/env python3
"""PAPER-ONLY entry feature log (added 2026-11-19). No API calls: features come from the scanner row (and this run's snapshot) at entry time only,
so there is no look-ahead. One row per scanner row_id in features.csv (learning trades join on trades.csv scanner_row_id).
Live: learning.py calls log_new_rows() every run for every new scanner row (all classes).
Backfill: `python3 features.py backfill` rebuilds features.csv for every near_misses.csv row (clone flag replayed in time order, like filter_backtest.py),
keeping live-only columns (rising, h1_growing, filter_info) for rows that already have them.
Not available from the scanner's free data: buy/sell counts and the 5-minute price change (the snapshots carry only the 1h price change)."""
import csv, os, sys, datetime as dt
from zoneinfo import ZoneInfo
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import copycat_filter as CF
ET = ZoneInfo("America/Toronto")
COLS = ["row_id", "ts_et", "mint", "symbol", "class", "lane", "mcap", "liq", "liq_mcap", "vol5m", "vol1h", "vol1h_liq", "vol5m_liq", "vol5m_share_1h",
        "p1h_pct", "age_h", "age_basis", "dex", "source", "hour_et", "weekday", "clone", "fakeliq", "wash", "filter_pass", "repeat_veto",
        "rising", "h1_growing", "filter_info", "basis"]
def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError): return None
def T(s):
    try: return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except Exception: return None
def _r(x, n=4): return "" if x is None else round(x, n)
def feats(r, clone, snap=None, filter_info="", basis="live"):
    mc, liq, v5, v1 = _f(r.get("mcap")), _f(r.get("liq")), _f(r.get("vol5m")), _f(r.get("vol1h"))
    t = T(r.get("ts_et") or ""); d = dt.datetime.fromtimestamp(t, ET) if t else None
    lm = liq / mc if (mc and liq is not None and mc > 0) else None
    vl = v1 / liq if (liq and v1 is not None) else None
    return dict(row_id=r.get("row_id"), ts_et=r.get("ts_et"), mint=r.get("mint"), symbol=r.get("symbol"), **{"class": r.get("class")}, lane=r.get("lane"),
                mcap=r.get("mcap"), liq=r.get("liq"), liq_mcap=_r(lm), vol5m=r.get("vol5m"), vol1h=r.get("vol1h"), vol1h_liq=_r(vl, 3),
                vol5m_liq=_r(v5 / liq if (liq and v5 is not None) else None, 3), vol5m_share_1h=_r(v5 / v1 if (v1 and v5 is not None) else None, 3),
                p1h_pct=r.get("p1h_pct", ""), age_h=r.get("age_h", ""), age_basis=(r.get("age_basis") or "").split("(")[0], dex=r.get("dex", ""), source=r.get("source", ""),
                hour_et=d.hour if d else "", weekday=d.strftime("%a") if d else "", clone=int(bool(clone)),
                fakeliq=int(lm is not None and lm >= CF.LIQ_MCAP_MAX), wash=int(vl is not None and vl >= CF.VOL1H_LIQ_MAX),
                filter_pass=int(not clone and not (lm is not None and lm >= CF.LIQ_MCAP_MAX) and not (vl is not None and vl >= CF.VOL1H_LIQ_MAX)),
                repeat_veto=r.get("repeat_veto", ""), rising="" if not snap else int(bool(snap.get("rising"))),
                h1_growing="" if not snap else int(bool(snap.get("h1_growing"))), filter_info=filter_info[:200], basis=basis)
def clone_of(r, reg, t):
    ok, why = CF.check(dict(mint=r["mint"], symbol=r.get("symbol"), mcap=None, liq=r.get("liq"), vol1h=None, age_h=None), reg, t)
    return any(w.startswith("clone") for w in why)
def _append(path, rows):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        if new: w.writeheader()
        w.writerows(rows)
def log_new_rows(home, new_rows, snaps, reg, t, info_map):
    """live path: append features for this run's new scanner rows (registry already updated with this run, as the filter sees it)."""
    out = [feats(r, clone_of(r, reg, t), snaps.get(r["mint"]), info_map.get(r["row_id"], ""), "live") for r in new_rows]
    if out: _append(os.path.join(home, "features.csv"), out)
def backfill(nm_csv=os.path.join(os.path.dirname(os.path.dirname(HERE)), "ledger", "nearmiss", "near_misses.csv"), home=HERE):
    path = os.path.join(home, "features.csv"); live = {}
    if os.path.exists(path):
        for r in csv.DictReader(open(path, newline="")):
            if r.get("basis") == "live": live[r["row_id"]] = r
    nm = sorted((r for r in csv.DictReader(open(nm_csv, newline="")) if T(r["ts_et"])), key=lambda r: T(r["ts_et"]))
    reg = {}; out = []; i = 0
    while i < len(nm):
        j = i
        while j < len(nm) and nm[j]["ts_et"] == nm[i]["ts_et"]: j += 1
        t = T(nm[i]["ts_et"]); grp = nm[i:j]
        CF.registry_update(reg, [(r["mint"], r["symbol"], r["liq"]) for r in grp], t)
        for r in grp:
            if r["row_id"] in live: out.append(live.pop(r["row_id"])); continue
            out.append(feats(r, clone_of(r, reg, t), None, "", "backfill"))
        i = j
    out += list(live.values())          # live rows not (yet) in near_misses.csv
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(out)
    os.replace(tmp, path); return len(out)
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "backfill": print("features.csv rows:", backfill())
    else: print(__doc__)
