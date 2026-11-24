#!/usr/bin/env python3
"""PAPER-ONLY multi-exit shadow tracker (added 2026-11-19). No LLM, no wallets, no paid services, and NO API calls of its own:
it only reads prices from the snapshots the scanner already fetched this run (plus mints that learning.py's existing lookup batch had room for).
For every NEW lane A / lane B scanner row (whether or not the learning book took it), it simulates several exit policies on the SAME price path,
so one entry yields many data points. Each policy result is appended to exits.csv (one row per entry_id + policy) when that policy closes.
Same conventions as the scanner/learning book: 3% round-trip fee at close, stops/trails fill at min(price, stop) less 2% slippage, take-profits fill
at the target level, timed exits at the observed price. Same drained-pool rug rule as learning.py (2 consecutive numeric low-liquidity readings on
the SAME pool => remaining stake at 0). gap_affected=1 if a >10 min scanner gap or a >10 min hole in this mint's prices happened while the policy was open.
State: shadow.json. Output: exits.csv. Policy table: POLICIES below (add a policy = add a line; existing rows keep their name)."""
import csv, json, os, time

FEE = 3.0; SLIP = 0.02; GAP_S = 600; RUG_CONFIRMS = 2
MAX_TRACK = 400            # safety cap on simultaneously tracked entries
NO_DATA_GRACE_S = 2 * 3600 # a policy whose horizon passed this long ago with no usable price closes as excluded (no_data)
# name: dict(stop, tps=[(gain, frac)], be_after_first, be_at, trail, trail_at, time_stop=(secs, min_gain), max_hold)
#   stop      : initial stop as a fraction below entry (None = no stop)
#   tps       : take-profit rungs, sell `frac` of the ORIGINAL stake at +gain (fills at the target level)
#   be_after_first : after the first rung, move the stop to entry
#   be_at     : once peak >= +be_at, move the stop to entry
#   trail     : trail the remainder this fraction below peak, active once all rungs are sold or once peak >= +trail_at
#   time_stop : (secs, g) exit at market after secs if the peak never reached +g
#   max_hold  : exit at market after this many seconds
POLICIES = {
    "LADDER_A":   dict(stop=0.20, tps=[(0.40, 0.40), (1.00, 0.30)], be_after_first=True, trail=0.35, time_stop=(900, 0.10), max_hold=24 * 3600),  # current Lane A rules
    "QT20_S12":   dict(stop=0.12, tps=[(0.20, 1.00)], max_hold=3600),                               # quick take +20% / stop -12%, 60 min cap
    "TP30_S15_T30": dict(stop=0.15, tps=[(0.30, 1.00)], max_hold=1800),                             # +30% / -15%, 30 min time stop
    "TP50_S25":   dict(stop=0.25, tps=[(0.50, 1.00)], max_hold=7200),                               # +50% / -25%, 2h cap
    "BE15_TR25":  dict(stop=0.20, be_at=0.15, trail=0.25, trail_at=0.15, max_hold=7200),             # stop to breakeven after +15%, then trail 25% below peak, 2h cap
    "HALF20_RUN": dict(stop=0.15, tps=[(0.20, 0.50)], be_after_first=True, trail=0.30, trail_at=0.20, max_hold=4 * 3600),  # sell half at +20%, BE stop, trail rest 30%
    "HOLD15":     dict(max_hold=900),                                                               # no stop, exit at 15 min (pure drift measure)
    "HOLD60":     dict(max_hold=3600),                                                              # no stop, exit at 60 min
}
LANES = ("A", "B")
COLS = ["entry_id", "trade_ids", "class", "lane", "mint", "symbol", "policy", "open_ts_et", "close_ts_et", "entry_price", "exit_reason",
        "net_pct", "peak_pct", "low_pct", "hold_min", "n_obs", "gap_affected", "status"]

def _f(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError): return None

def new_state(entry):
    P = {}
    for name, c in POLICIES.items():
        P[name] = dict(rem=1.0, realized=0.0, done_tps=[], stop=(entry * (1 - c["stop"]) if c.get("stop") is not None else 0.0),
                       peak=entry, low=entry, trailing=False, gap=0, closed=False, n=0)
    return P

def step_policy(c, s, E, price, t, t0):
    """advance one observation; returns reason or None"""
    s["n"] += 1; s["peak"] = max(s["peak"], price); s["low"] = min(s["low"], price)
    if c.get("be_at") is not None and s["peak"] >= E * (1 + c["be_at"]): s["stop"] = max(s["stop"], E)
    if c.get("trail") and c.get("trail_at") is not None and s["peak"] >= E * (1 + c["trail_at"]): s["trailing"] = True
    trail_px = s["peak"] * (1 - c["trail"]) if (s["trailing"] and c.get("trail")) else 0.0
    eff = max(s["stop"], trail_px)
    if eff > 0 and price <= eff:
        fill = min(price, eff) * (1 - SLIP); s["realized"] += s["rem"] * fill / E; s["rem"] = 0.0
        return "trail_stop" if (s["trailing"] and trail_px >= s["stop"]) else ("stop_to_entry" if s["stop"] >= E else "stop_loss")
    for i, (g, fr) in enumerate(c.get("tps", [])):
        if i in s["done_tps"] or price < E * (1 + g): continue
        sell = min(fr, s["rem"]); s["realized"] += sell * (1 + g); s["rem"] -= sell; s["done_tps"].append(i)
        if i == 0 and c.get("be_after_first"): s["stop"] = max(s["stop"], E)
    if c.get("tps") and len(s["done_tps"]) == len(c["tps"]):
        if s["rem"] <= 1e-9: s["rem"] = 0.0; return "take_profit"
        if c.get("trail"): s["trailing"] = True
    ts_ = c.get("time_stop")
    if ts_ and t - t0 >= ts_[0] and s["peak"] < E * (1 + ts_[1]):
        s["realized"] += s["rem"] * price / E; s["rem"] = 0.0; return f"time_stop_{ts_[0] // 60}m"
    if t - t0 >= c["max_hold"]:
        s["realized"] += s["rem"] * price / E; s["rem"] = 0.0; return f"max_hold_{c['max_hold'] // 60}m"
    return None

def net_of(s): return round((s["realized"] - 1) * 100 - FEE, 2)

def _append(path, rows):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        if new: w.writeheader()
        w.writerows(rows)

def update(home, snaps, new_rows, trade_map, t, stamp, gap_now, stamp_of, log=lambda m: None):
    """home: learning dir. new_rows: this run's new scanner rows. trade_map: scanner row_id -> [learning trade ids opened this run].
    Returns the set of mints that still need prices (for learning.py's existing lookup batch)."""
    SH = os.path.join(home, "shadow.json"); OUT = os.path.join(home, "exits.csv")
    try:
        with open(SH) as fh: st = json.load(fh)
    except Exception: st = {"entries": {}}
    ents = st.setdefault("entries", {}); out = []
    for eid, e in list(ents.items()):
        E = e["entry"]; P = e["policies"]
        open_names = [n for n, s in P.items() if not s["closed"]]
        if gap_now:
            for n in open_names: P[n]["gap"] = 1
        sn = snaps.get(e["mint"]); price = _f(sn.get("price")) if sn else None
        if price and price > 0:
            if t - e.get("last_px_t", e["t0"]) > GAP_S:
                for n in open_names: P[n]["gap"] = 1          # hole in this mint's price path
            e["last_px_t"] = t
            liq = _f(sn.get("liq")); rug = False
            if liq is not None and liq < max(1000.0, 0.05 * (e.get("entry_liq") or 0)):
                if e.get("pool") and sn.get("pool") and e["pool"] != sn["pool"]: pass     # sibling pool: inconclusive
                else:
                    e["rug_strikes"] = e.get("rug_strikes", 0) + 1; rug = e["rug_strikes"] >= RUG_CONFIRMS
            elif liq is not None: e["rug_strikes"] = 0
            for n in open_names:
                s = P[n]; c = POLICIES.get(n)
                if c is None: s["closed"] = True; continue
                if rug: s["rem"] = 0.0; reason = "liq_drained_rug"
                elif e.get("rug_strikes", 0) > 0: reason = None; s["n"] += 1      # pending rug confirmation: hold, no fills
                else: reason = step_policy(c, s, E, price, t, e["t0"])
                if reason:
                    s["closed"] = True
                    out.append(dict(entry_id=eid, trade_ids=";".join(e.get("trade_ids", [])), **{"class": e["cls"]}, lane=e["lane"], mint=e["mint"], symbol=e["symbol"],
                                    policy=n, open_ts_et=e["open_ts_et"], close_ts_et=stamp, entry_price=f"{E:.10g}", exit_reason=reason, net_pct=net_of(s),
                                    peak_pct=round((s["peak"] / E - 1) * 100, 2), low_pct=round((s["low"] / E - 1) * 100, 2), hold_min=round((t - e["t0"]) / 60, 1),
                                    n_obs=s["n"], gap_affected=s["gap"], status="closed"))
        else:
            for n in open_names:
                c = POLICIES.get(n)
                if c is None or t - e["t0"] > c["max_hold"] + NO_DATA_GRACE_S:
                    s = P[n]; s["closed"] = True
                    out.append(dict(entry_id=eid, trade_ids=";".join(e.get("trade_ids", [])), **{"class": e["cls"]}, lane=e["lane"], mint=e["mint"], symbol=e["symbol"],
                                    policy=n, open_ts_et=e["open_ts_et"], close_ts_et=stamp, entry_price=f"{E:.10g}", exit_reason="no_data", net_pct="",
                                    peak_pct=round((s["peak"] / E - 1) * 100, 2), low_pct=round((s["low"] / E - 1) * 100, 2), hold_min=round((t - e["t0"]) / 60, 1),
                                    n_obs=s["n"], gap_affected=1, status="excluded"))
        if all(s["closed"] for s in P.values()): del ents[eid]
    # new entries: every new lane A/B scanner row (taken by the learning book or not), at the scanner's entry price
    for r in new_rows:
        if r.get("lane") not in LANES or r.get("status") != "open" or r["row_id"] in ents: continue
        E = _f(r.get("entry_price"))
        if not E or E <= 0 or len(ents) >= MAX_TRACK: continue
        ents[r["row_id"]] = dict(mint=r["mint"], symbol=r.get("symbol"), cls=r.get("class"), lane=r.get("lane"), pool=r.get("pool") or "", entry=E, t0=t,
                                 entry_liq=_f(r.get("liq")) or 0.0, open_ts_et=stamp, last_px_t=t, rug_strikes=0, trade_ids=trade_map.get(r["row_id"], []),
                                 policies=new_state(E))
    if out: _append(OUT, out); log(f"EXITS closed {len(out)} shadow policy result(s); tracking {len(ents)} entries")
    st["updated_et"] = stamp; st["policies"] = list(POLICIES)
    tmp = SH + ".tmp"
    with open(tmp, "w") as fh: json.dump(st, fh)
    os.replace(tmp, SH)
    return {e["mint"] for e in ents.values()}

def needed_mints(home):
    try:
        with open(os.path.join(home, "shadow.json")) as fh: return [e["mint"] for e in json.load(fh).get("entries", {}).values()]
    except Exception: return []
