#!/usr/bin/env python3
"""PAPER-ONLY technical-setup shadow tester (added 2026-11-23). No wallets, no buys, no paid services, no LLM.
Data: GeckoTerminal public 1m OHLCV (free), cached to ta_cache/<pool>.json. One call (limit=1000, before_timestamp) covers a row's whole window.
DELAYED evaluation, identical for backtest and live: a scanner row (lanes A/B/R; v4 candidates are A/B rows) is evaluated once its window
[T, T+WATCH] + MAX_HOLD has fully passed. No look-ahead: a signal at candle i uses only candles <= i (all closed), entry = OPEN of candle i+1
x (1+SLIP_IN). Exits on 1m candles: stop checked before target in the same candle (conservative); stop fills at min(open, stop) x (1-SLIP);
if a candle crashes to <= -70% vs entry the fill is that candle's close x (1-SLIP) (rug); target fills at max(open, target); time exit at the
open of the first candle at/after the horizon (or the last close if trading stopped). FEE 3% round trip, SLIP 2% (same as exits.py).
One trade per setup per row (first signal in the window); identical trades from several rows of the same coin are merged (lanes joined).
Baselines TP30_S15_T30 and HOLD15 are re-simulated on the same candles from the scanner row time (next 1m open, same slippage), so the
comparison is apples to apples. Parameters are fixed and pre-declared below (no per-coin fitting).
CLI: python3 ta.py backfill [max_calls] [sleep_s] | report | eval   (eval = re-evaluate all rows from cache, no API calls)"""
import csv, json, os, sys, time, bisect, fcntl, statistics as st, urllib.request, datetime as dt
from zoneinfo import ZoneInfo
HOME = os.path.dirname(os.path.abspath(__file__))
DESK = os.environ.get("DESK_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NM = os.path.join(DESK, "ledger", "nearmiss", "near_misses.csv")
SLOG = os.path.join(DESK, "ledger", "nearmiss", "scanner.log")
CACHE = os.path.join(HOME, "ta_cache"); SIG = os.path.join(HOME, "ta_signals.csv"); EXI = os.path.join(HOME, "ta_exits.csv")
STATE = os.path.join(HOME, "ta_state.json"); LOCK = os.path.join(HOME, "ta.lock"); LOG = os.path.join(HOME, "ta.log"); REPORT = os.path.join(HOME, "ta_report.md")
ET = ZoneInfo("America/Toronto")
FEE = 3.0; SLIP = 0.02; SLIP_IN = 0.01; RUG_FRAC = 0.30
WATCH_S = 120 * 60        # signals allowed from the scanner row time T until T+120 min
HOLD_S = 60 * 60          # max hold for TA setups
LOOKBACK_S = 4 * 3600     # VWAP anchor = max(pool launch, t - 4h)
MIN_HIST = 30             # candles of history needed before a signal
MAX_ENTRY_GAP_S = 600     # entry candle must open within 10 min of the signal candle
STOP_MIN, STOP_MAX = 0.03, 0.25   # stop distance bounds (tighter -> widened to 3%, wider -> no trade)
LIVE_CALLS_PER_RUN = 2; LIVE_TIME_BUDGET_S = 30; CALL_GAP_S = 4; COOLDOWN_429_S = 900
LANES = ("A", "B", "R")
GAP_PRE_S = 900            # gap_affected = scanner hole > 10 min within the 15 min before the row (signal may be stale)
BACKFILL = False
API = "https://api.geckoterminal.com/api/v2/networks/solana/pools/{p}/ohlcv/minute?aggregate=1&limit=1000&currency=usd&token=base&before_timestamp={b}"

def log(m):
    with open(LOG, "a") as fh: fh.write(f"{dt.datetime.now(ET).strftime('%Y-%m-%dT%H:%M:%S%z')} {m}\n")
def T(s):
    try: return dt.datetime.strptime(s[:24], "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except Exception: return None
def et(t): return dt.datetime.fromtimestamp(t, ET).strftime("%Y-%m-%dT%H:%M:%S%z")
def fl(x):
    try: v = float(x); return None if v != v else v
    except Exception: return None
def jload(p, d):
    try:
        with open(p) as fh: return json.load(fh)
    except Exception: return d
def jsave(p, o):
    with open(p + ".tmp", "w") as fh: json.dump(o, fh, separators=(",", ":"))
    os.replace(p + ".tmp", p)

# ---------------- cache ----------------
def cache_load(pool): return jload(os.path.join(CACHE, pool + ".json"), {"c": {}, "win": []})
def covered(cc, lo, hi): return any(a <= lo and b >= hi for a, b in cc["win"])
def fetch(pool, before, state):
    url = API.format(p=pool, b=int(before))
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "paper-desk-ta/1.0"})
    state["calls"] = state.get("calls", 0) + 1; state.setdefault("calls_by_day", {}); d = dt.datetime.now(ET).strftime("%Y-%m-%d")
    state["calls_by_day"][d] = state["calls_by_day"].get(d, 0) + 1
    try:
        with urllib.request.urlopen(req, timeout=12) as r: js = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429: state["cooldown_until"] = time.time() + COOLDOWN_429_S; state["n429"] = state.get("n429", 0) + 1; log(f"429 on {pool}; cooldown"); return "429"
        log(f"HTTP {e.code} {pool}"); return "err%d" % e.code
    except Exception as e: log(f"ERR {pool} {type(e).__name__}"); return "err"
    lst = (((js.get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
    cc = cache_load(pool)
    for row in lst: cc["c"][str(int(row[0]))] = [float(x) for x in row[1:6]]
    lo = 0 if len(lst) < 1000 else min(int(r[0]) for r in lst)     # fewer than 1000 => we have the pool's full history up to `before`
    cc["win"].append([lo, int(before)])
    jsave(os.path.join(CACHE, pool + ".json"), cc)
    return "ok"

# ---------------- indicators ----------------
def series(cc):
    ks = sorted(int(k) for k in cc["c"])
    return ks, [cc["c"][str(k)] for k in ks]       # [o,h,l,c,v]
def build(ts, C):
    n = len(ts); cl = [c[3] for c in C]; vol = [c[4] for c in C]
    tp = [(c[1] + c[2] + c[3]) / 3 for c in C]
    pv = [0.0]; vv = [0.0]; p2 = [0.0]
    for i in range(n): pv.append(pv[-1] + tp[i] * vol[i]); vv.append(vv[-1] + vol[i]); p2.append(p2[-1] + tp[i] * tp[i] * vol[i])
    def ema(k):
        a = 2 / (k + 1); out = []; e = cl[0] if n else 0
        for x in cl: e = a * x + (1 - a) * e; out.append(e)
        return out
    e9, e21 = ema(9), ema(21)
    va = [None] * n; s = 0.0
    for i in range(n):
        if i >= 20: va[i] = s / 20; s -= vol[i - 20]
        s += vol[i]
    return dict(cl=cl, vol=vol, pv=pv, vv=vv, p2=p2, e9=e9, e21=e21, va=va)
def vwap(ts, I, i, launch):
    anchor = max(ts[i] - LOOKBACK_S, launch or 0); j = bisect.bisect_left(ts, anchor)
    V = I["vv"][i + 1] - I["vv"][j]
    if V <= 0: return None, None
    m = (I["pv"][i + 1] - I["pv"][j]) / V; var = max((I["p2"][i + 1] - I["p2"][j]) / V - m * m, 0.0)
    return m, var ** 0.5

# ---------------- setups: f(ts, C, I, i, ctx) -> None | (stop_px, tp_ratio, info) ; all use candles <= i only ----------------
def _stop(close, sp):
    d = 1 - sp / close
    if d > STOP_MAX: return None
    return min(sp, close * (1 - STOP_MIN))
def s_vwap(ts, C, I, i, ctx):
    o, h, l, c, v = C[i]; va = I["va"][i]
    if va is None or v < 1.5 * va or c <= o: return None
    m, sd = vwap(ts, I, i, ctx["launch"])
    if m is None or c <= m: return None
    if not any(C[k][3] < vwap(ts, I, k, ctx["launch"])[0] for k in range(max(0, i - 6), i)): return None
    sp = _stop(c, min(x[2] for x in C[max(0, i - 10):i + 1]) * 0.99)
    if sp is None: return None
    return sp, min(max((m + 2 * sd) / c, 1.20), 1.30), f"vwap={m:.4g} vr={v / va:.1f}"
def s_sweep(ts, C, I, i, ctx):
    if i < 23: return None
    RL = min(x[2] for x in C[i - 21:i - 1]); c = C[i][3]
    if c <= RL or c <= C[i][0]: return None
    for j in (i - 1, i):
        vaj = I["va"][j]
        if vaj and C[j][2] < RL * 0.995 and C[j][4] >= 2 * vaj:
            sp = _stop(c, min(C[j][2], C[i][2]) * 0.99)
            if sp is None: return None
            return sp, 1.25, f"rangelow={RL:.4g} wick={C[j][2]:.4g} vr={C[j][4] / vaj:.1f}"
    return None
def _retest(C, i, H, brk_from):
    o, h, l, c, v = C[i]
    if not any(C[k][3] >= H * 1.02 for k in range(brk_from, i)): return None
    if not (l <= H * 1.02 and c > H): return None
    return _stop(c, min(H * 0.95, l * 0.99))
def s_brk(ts, C, I, i, ctx):
    if i < 41: return None
    H = max(x[1] for x in C[i - 40:i - 10]); sp = _retest(C, i, H, i - 10)
    return None if sp is None else (sp, 1.25, f"rangehigh={H:.4g}")
def s_orb(ts, C, I, i, ctx):
    L = ctx["launch"]
    if not L or L < ts[0] - 120 or ts[i] < L + 1800 or ts[i] > L + 24 * 3600: return None
    a = bisect.bisect_left(ts, L); b = bisect.bisect_left(ts, L + 1800)
    if b - a < 5: return None
    H = max(x[1] for x in C[a:b]); sp = _retest(C, i, H, max(b, i - 30))
    return None if sp is None else (sp, 1.25, f"orbhigh={H:.4g}")
def s_capit(ts, C, I, i, ctx):
    if i < 20: return None
    o, h, l, c, v = C[i]
    if c <= o: return None
    if C[i - 1][3] > max(x[1] for x in C[i - 15:i]) * 0.80: return None
    for j in (i - 1, i - 2):
        vaj = I["va"][j]
        if vaj and C[j][4] >= 3 * vaj and C[j][3] < C[j][0] and c > (C[j][1] + C[j][2]) / 2:
            sp = _stop(c, min(x[2] for x in C[j:i + 1]) * 0.99)
            if sp is None: return None
            return sp, 1.25, f"climax_vr={C[j][4] / vaj:.1f}"
    return None
def s_ema(ts, C, I, i, ctx):
    if not (I["e9"][i - 1] <= I["e21"][i - 1] and I["e9"][i] > I["e21"][i]): return None
    va = I["va"][i]; c = C[i][3]
    if va is None or C[i][4] < va: return None
    m, _ = vwap(ts, I, i, ctx["launch"])
    if m is None or c <= m: return None
    sp = _stop(c, min(x[2] for x in C[i - 5:i + 1]) * 0.99)
    return None if sp is None else (sp, 1.20, "ema9x21")
BASE = {"VWAP_RECLAIM": s_vwap, "LIQ_SWEEP": s_sweep, "BRK_RETEST": s_brk, "ORB30_RETEST": s_orb, "CAPITULATION": s_capit, "EMA_CROSS": s_ema}
SETUPS = dict(BASE)
for _k, _f in list(BASE.items()):
    if _k != "EMA_CROSS": SETUPS[_k + "+M"] = (lambda f: (lambda ts, C, I, i, ctx: f(ts, C, I, i, ctx) if I["e9"][i] > I["e21"][i] else None))(_f)
BASELINES = {"TP30_S15_T30": (0.15, 1.30, 1800), "HOLD15": (None, None, 900)}

# ---------------- exit sim ----------------
def sim(ts, C, k, stop_px, tp_px, hold):
    E = C[k][0] * (1 + SLIP_IN); t0 = ts[k]; peak = low = E; j = k
    for j in range(k, len(ts)):
        o, h, l, c, v = C[j]
        if ts[j] - t0 >= hold: px, why = o, "time"; break
        peak = max(peak, h); low = min(low, l)
        if l <= E * RUG_FRAC: px, why = c * (1 - SLIP), "rug"; break
        if stop_px and l <= stop_px: px, why = min(o, stop_px) * (1 - SLIP), "stop"; break
        if tp_px and h >= tp_px: px, why = max(o, tp_px), "tp"; break
    else: px, why = C[-1][3], "data_end"
    if why == "time" and px <= E * RUG_FRAC: why = "rug"
    return dict(entry_px=E, exit_t=ts[j], net=round((px / E - 1) * 100 - FEE, 2), peak=round((peak / E - 1) * 100, 2),
                low=round((low / E - 1) * 100, 2), hold=round((ts[j] - t0) / 60, 1), why=why)

def evaluate(row, cc, runs):
    """all trades for one scanner row -> list of dicts"""
    t = T(row["ts_et"]); ts, C = series(cc)
    if len(ts) < 5: return []
    age = fl(row.get("age_h")); launch = t - age * 3600 if age is not None else None
    I = build(ts, C); ctx = {"launch": launch}; out = []
    gap = gapped(runs, t - GAP_PRE_S, t)   # candles are exchange data (box pauses don't touch the fills); a gap only matters if the row itself came from a late run
    base = dict(row_id=row["row_id"], lane=row["lane"], cls=row["class"], mint=row["mint"], symbol=row["symbol"], pool=row["pool"],
                age_h=age, gap_affected=int(gap))
    k0 = bisect.bisect_left(ts, t)
    if k0 < len(ts) and ts[k0] - t <= MAX_ENTRY_GAP_S:
        for name, (sd, tr, hold) in BASELINES.items():
            E = C[k0][0] * (1 + SLIP_IN)
            r = sim(ts, C, k0, E * (1 - sd) if sd else None, E * tr if tr else None, hold)
            out.append(dict(base, setup=name, signal_t=t, entry_t=ts[k0], stop_px=E * (1 - sd) if sd else "", tp_px=E * tr if tr else "", info="baseline", **r))
    i_lo = bisect.bisect_left(ts, t - 60); i_hi = bisect.bisect_right(ts, t + WATCH_S - 60)
    for name, fn in SETUPS.items():
        for i in range(max(i_lo, MIN_HIST), min(i_hi, len(ts) - 1)):
            try: s = fn(ts, C, I, i, ctx)
            except (IndexError, ZeroDivisionError, TypeError): s = None
            if not s: continue
            k = i + 1
            if ts[k] - ts[i] > MAX_ENTRY_GAP_S: continue
            sp, tr, info = s; E = C[k][0] * (1 + SLIP_IN)
            if sp >= E: continue          # opened below the stop: no trade
            r = sim(ts, C, k, sp, C[k][0] * tr, HOLD_S)
            out.append(dict(base, setup=name, signal_t=ts[i] + 60, entry_t=ts[k], stop_px=sp, tp_px=C[k][0] * tr, info=info, **r)); break
    return out

def load_runs():
    try: return sorted(x for x in (T(l[:24]) for l in open(SLOG, errors="ignore") if " RUN ok " in l) if x)
    except Exception: return []
def gapped(runs, a, b):
    """True if the scanner had a >10 min hole between runs anywhere in [a, b] (box paused)."""
    if not runs or a > runs[-1]: return False
    i = max(bisect.bisect_right(runs, a) - 1, 0); j = bisect.bisect_right(runs, b) + 1; pts = runs[i:j]
    if runs[0] > a + 600: return True
    if pts[-1] < b and pts[-1] == runs[-1] and b - pts[-1] > 600 and b < time.time() - 600: return True
    return any(y - x > 600 for x, y in zip(pts, pts[1:]))

SCOLS = ["setup", "row_id", "lane", "cls", "mint", "symbol", "pool", "age_h", "gap_affected", "signal_ts_et", "entry_ts_et", "entry_px", "stop_px", "tp_px", "info", "mode"]
XCOLS = ["setup", "row_id", "lane", "mint", "symbol", "age_h", "gap_affected", "entry_ts_et", "exit_ts_et", "exit_reason", "net_pct", "peak_pct", "low_pct", "hold_min", "rug", "mode"]
def write(trades, mode, append=True):
    for path, cols, conv in ((SIG, SCOLS, lambda d: dict(d, signal_ts_et=et(d["signal_t"]), entry_ts_et=et(d["entry_t"]), entry_px=f"{d['entry_px']:.10g}",
                                                         stop_px=f"{d['stop_px']:.10g}" if d["stop_px"] != "" else "", tp_px=f"{d['tp_px']:.10g}" if d["tp_px"] != "" else "", mode=mode)),
                             (EXI, XCOLS, lambda d: dict(d, entry_ts_et=et(d["entry_t"]), exit_ts_et=et(d["exit_t"]), exit_reason=d["why"], net_pct=d["net"], peak_pct=d["peak"],
                                                         low_pct=d["low"], hold_min=d["hold"], rug=int(d["why"] == "rug" or d["net"] <= -70), mode=mode))):
        new = not os.path.exists(path) or not append
        with open(path, "a" if append else "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            if new: w.writeheader()
            for d in trades: w.writerow(conv(d))

def pending(state, now):
    done = set(state.get("done", []))
    rows = [r for r in csv.DictReader(open(NM, newline="")) if r.get("lane") in LANES and r.get("pool") and r["row_id"] not in done and T(r["ts_et"])]
    return [r for r in rows if T(r["ts_et"]) + WATCH_S + HOLD_S + 300 <= now]

def process(max_calls, sleep_s, time_budget, mode):
    """evaluate pending rows; fetch at most max_calls; returns (n_rows_done, calls)"""
    state = jload(STATE, {}); now = time.time()
    if state.get("cooldown_until", 0) > now: max_calls = 0     # after a 429: no fetching, but rows already in cache are still evaluated
    rows = sorted(pending(state, now), key=lambda r: -T(r["ts_et"]))     # newest first
    runs = load_runs(); calls = 0; ndone = 0; t_start = time.time(); done = state.setdefault("done", []); trades = []
    for r in rows:
        if time.time() - t_start > time_budget: break
        t = T(r["ts_et"]); lo, hi = t - LOOKBACK_S - 3600, t + WATCH_S + HOLD_S
        cc = cache_load(r["pool"])
        if not covered(cc, lo, hi):
            if calls >= max_calls: continue
            if calls: time.sleep(sleep_s)
            while BACKFILL and (time.time() % 300 <= 75 or time.time() % 300 >= 270): time.sleep(1)   # stay out of the scanner's own call window (:x0:20/:x5:20)
            res = fetch(r["pool"], min(hi + 120, now), state); calls += 1
            if res == "429": break
            cc = cache_load(r["pool"])
            if res != "ok":
                if res.startswith("err4"): done.append(r["row_id"]); state.setdefault("no_data", []).append(r["row_id"])
                continue
        tr = evaluate(r, cc, runs)
        if not tr: state.setdefault("no_data", []).append(r["row_id"])
        trades += tr; done.append(r["row_id"]); ndone += 1
    # merge identical trades (same coin/setup/entry candle) from several rows: keep first, join lanes/row_ids
    seen_keys = set(state.get("keys", [])); keep = []
    for d in trades:
        key = f"{d['mint']}|{d['setup']}|{d['entry_t']}"
        if key in seen_keys:
            continue
        seen_keys.add(key); keep.append(d)
    lanes_by_key = {}
    for d in trades: lanes_by_key.setdefault(f"{d['mint']}|{d['setup']}|{d['entry_t']}", set()).add(d["lane"])
    for d in keep: d["lane"] = "".join(sorted(lanes_by_key[f"{d['mint']}|{d['setup']}|{d['entry_t']}"]))
    state["keys"] = sorted(seen_keys)
    if keep: write(keep, mode)
    state["updated_et"] = et(time.time()); jsave(STATE, state)
    if ndone or calls: log(f"{mode} rows={ndone} trades={len(keep)} calls={calls} pending_left={len(rows) - ndone}")
    return ndone, calls

def after_run():
    """scanner hook (paper only): small budget per run; skips if a backfill holds the lock"""
    fh = open(LOCK, "a")
    try: fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: return
    try: process(LIVE_CALLS_PER_RUN, CALL_GAP_S, LIVE_TIME_BUDGET_S, "live")
    finally: fcntl.flock(fh, fcntl.LOCK_UN); fh.close()

# ---------------- report ----------------
def stats(v):
    if not v: return None
    return dict(n=len(v), win=100 * sum(x > 0 for x in v) / len(v), avg=sum(v) / len(v), med=st.median(v))
def agebin(a):
    a = fl(a)
    if a is None: return "age?"
    return "age<1h" if a < 1 else "age1-6h" if a < 6 else "age6-24h" if a < 24 else "age>=24h"
def report(quiet=False, compact=False):
    if not os.path.exists(EXI): return "TA: no results yet"
    rows = list(csv.DictReader(open(EXI, newline="")))
    art = [r for r in rows if fl(r["net_pct"]) is not None and fl(r["net_pct"]) > 1000]
    rows = [r for r in rows if fl(r["net_pct"]) is not None and fl(r["net_pct"]) <= 1000]
    order = list(BASELINES) + list(SETUPS)
    def ln(label, g):
        s = stats([fl(r["net_pct"]) for r in g])
        if not s: return f"  {label:<10} n=  0"
        return f"  {label:<10} n={s['n']:>4} win {s['win']:5.1f}% avg {s['avg']:+7.2f}% med {s['med']:+7.2f}% rugs {sum(r['rug'] == '1' for r in g):>3}"
    L = [f"TA shadow setups (paper; 1m GeckoTerminal candles; fee 3% + slip; entry next open +1%). rows={len(rows)} artifacts(net>+1000%) excluded={len(art)}"]
    for s in order:
        g = [r for r in rows if r["setup"] == s]
        if not g: continue
        L.append(f"{s}:")
        L.append(ln("ALL", g)); L.append(ln("CLEAN", [r for r in g if r["gap_affected"] == "0"])); L.append(ln("GAP", [r for r in g if r["gap_affected"] == "1"]))
        if s not in BASELINES:      # paired comparison on the SAME scanner rows (candle-simulated baselines)
            ids = {r["row_id"] for r in g}
            for b in BASELINES:
                bb = [r for r in rows if r["setup"] == b and r["row_id"] in ids]
                L.append(ln("vs" + b[:6], bb).replace("  vs", "  vs", 1))
        if compact: continue
        for lane in LANES: L.append(ln("lane" + lane, [r for r in g if lane in r["lane"]]))
        for b in ("age<1h", "age1-6h", "age6-24h", "age>=24h", "age?"):
            gg = [r for r in g if agebin(r["age_h"]) == b]
            if gg: L.append(ln(b, gg))
    out = "\n".join(L)
    if not quiet: print(out)
    return out

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "backfill":
        mc = int(sys.argv[2]) if len(sys.argv) > 2 else 700; sl = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
        fh = open(LOCK, "a"); fcntl.flock(fh, fcntl.LOCK_EX); BACKFILL = True
        tot = 0
        while tot < mc:
            s0 = jload(STATE, {})
            if s0.get("cooldown_until", 0) > time.time():      # after a 429 the backfill waits out the full 15 min cooldown (resumable: done rows persist in ta_state.json)
                time.sleep(min(s0["cooldown_until"] - time.time() + 1, 60)); continue
            n, c = process(min(25, mc - tot), sl, 10 ** 9, "backtest"); tot += c
            s1 = jload(STATE, {}); open(os.path.join(HOME, "ta_backfill.progress"), "w").write(f"{et(time.time())} calls_this_backfill={tot} rows_done={len(s1.get('done', []))} total_calls={s1.get('calls')} n429={s1.get('n429', 0)}\n")
            if c == 0 and jload(STATE, {}).get("cooldown_until", 0) <= time.time(): break
            time.sleep(sl)
        print("backfill calls", tot)
    elif cmd == "eval":       # rebuild ta_signals/ta_exits from cache (no API calls); live-mode rows keep mode=backtest after rebuild
        st0 = jload(STATE, {}); st0["done"] = []; st0["keys"] = []; jsave(STATE, st0)
        for p in (SIG, EXI):
            if os.path.exists(p): os.remove(p)
        process(0, 0, 10 ** 9, "backtest")
    else:
        txt = report(); open(REPORT, "w").write("```\n" + txt + "\n```\n")
