#!/usr/bin/env python3
"""Near-miss SHADOW scanner (paper only, no LLM, no X calls, free APIs only).
One invocation = one run (cron-style); watchdog.sh calls it every 5 minutes.
See README.md. Writes only inside $DESK_ROOT/ledger/nearmiss/ (default: the folder that contains ledger/)."""
import csv, fcntl, json, os, sys, time, datetime as dt, urllib.request, urllib.error, urllib.parse
from zoneinfo import ZoneInfo

# Portability: DESK_ROOT (default = the dir that contains ledger/) -> data in $DESK_ROOT/ledger/nearmiss.
DESK_ROOT = os.environ.get("DESK_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.path.join(DESK_ROOT, "ledger", "nearmiss") if os.environ.get("DESK_ROOT") else os.path.dirname(os.path.abspath(__file__))
LEARN_PATH = os.environ.get("LEARN_CODE_DIR", os.path.join(DESK_ROOT, "ledger", "learning"))
ET = ZoneInfo("America/Toronto")
CSV = f"{HOME}/near_misses.csv"; POS = f"{HOME}/positions_shadow.json"
STATUS = f"{HOME}/status.json"; LOG = f"{HOME}/scanner.log"; SEEN = f"{HOME}/seen.json"

# ---------------- config (class gates, from the filter-audit report) ----------------
DEDUP_S = 6 * 3600
MAX_NEW_PER_RUN = 15
MAX_HOLD_S = 24 * 3600            # safety cap: close any position still open after 24h (reason max_hold_24h)
ROUND_TRIP_FEE_PCT = 3.0          # percent of position, subtracted once at close
STOP_SLIP = 0.02                  # pessimistic extra slippage on stop/trail fills (2%)
A_NM = dict(m5=25_000, liq=15_000, p1h_max_pct=200.0)           # price < 3x the 1h-ago price
A_FULL = dict(m5=50_000, liq=30_000, p1h_max_pct=200.0)
B_SH = dict(age_h=6.0, mc_lo=15_000, mc_hi=150_000, m5=10_000, liq=15_000)
R_BAND = [(100_000, 300_000), (5_000_000, 10_000_000)]; R_MIN_H1_VOL = 50_000; R_MIN_LIQ = 15_000
R_FULL_BAND = (300_000, 5_000_000)
A_MAX_MCAP = 20_000_000           # noise control (not in lane rules): ignore large caps/tokenized assets for A classes
SKIP_SYMBOLS = {"SOL", "WSOL", "USDC", "USDT", "JUP", "JLP", "ETH", "WETH", "BTC", "WBTC", "PYUSD", "USDS"}
# lane ladders. time_stop = (seconds, min gain) : exit if peak never reached +min gain within seconds.
LADDER = {
  "A": dict(stop=0.20, tp=[(0.40, 0.40), (1.00, 0.30)], be_after_first=True, trail=0.35, time_stop=(900, 0.10)),
  "B": dict(stop=0.30, tp=[(0.40, 0.40), (1.00, 0.30)], be_after_first=True, trail=0.35, time_stop=(3600, 0.10)),
  # R: catalysts are unknowable to the script -> PROXY: sell 20% of original at +50%,+100%,+200%; trail rest 35% below peak.
  "R": dict(stop=0.40, tp=[(0.50, 0.20), (1.00, 0.20), (2.00, 0.20)], be_after_first=False, trail=0.35, time_stop=None),
}
COLS = ["row_id","ts_et","mint","symbol","class","lane","failed_filters","mcap","liq","vol5m","vol1h","entry_price",
        "status","exit_ts_et","exit_reason","net_pct","peak_pct","links","repeat_veto",
        "net_basis","last_price","last_update_et","low_pct","p1h_pct","age_h","age_basis","dex","pool","catalyst","event_validity","source","notes"]

def now(): return dt.datetime.now(ET)
def ts(d=None): return (d or now()).strftime("%Y-%m-%dT%H:%M:%S%z")
def log(msg):
    with open(LOG, "a") as f: f.write(f"{ts()} {msg}\n")

CALLS = {"gecko": 0, "dex": 0, "errors": 0, "429": 0}
_last = {"gecko": 0.0, "dex": 0.0}
def http(kind, url, params=None):
    if params: url += "?" + urllib.parse.urlencode(params)
    gap = 2.4 if kind == "gecko" else 1.2
    for attempt in range(2):
        w = gap - (time.time() - _last[kind])
        if w > 0: time.sleep(w)
        _last[kind] = time.time(); CALLS[kind] += 1
        req = urllib.request.Request(url, headers={"Accept": "application/json;version=20230302", "User-Agent": "nearmiss-shadow/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                CALLS["429"] += 1
                if attempt == 0: time.sleep(12); continue
            CALLS["errors"] += 1; log(f"WARN http {e.code} {url[:110]}"); return None
        except Exception as e:
            CALLS["errors"] += 1; log(f"WARN http err {type(e).__name__} {url[:110]}"); return None
    return None

def f(x):
    try: return float(x)
    except Exception: return None

# ---------------- data collection ----------------
G = "https://api.geckoterminal.com/api/v2/networks/solana"
def collect():
    """returns dict mint -> best snapshot (highest liquidity)."""
    snaps = {}
    def put(s):
        if not s["mint"] or s["price"] is None or s["price"] <= 0: return
        if s["symbol"].upper() in SKIP_SYMBOLS: return
        cur = snaps.get(s["mint"])
        if cur is None or (s["liq"] or 0) > (cur["liq"] or 0): snaps[s["mint"]] = s
    def gecko(js, src):
        if not js: return
        for p in js.get("data", []):
            a = p["attributes"]; v = a.get("volume_usd") or {}; pc = a.get("price_change_percentage") or {}
            base = p["relationships"]["base_token"]["data"]["id"].replace("solana_", "")
            sym = (a.get("name") or "?").split(" / ")[0].strip()
            h1v, h6v, m5v, m15v = f(v.get("h1")) or 0, f(v.get("h6")) or 0, f(v.get("m5")) or 0, f(v.get("m15")) or 0
            created = a.get("pool_created_at")
            put(dict(mint=base, symbol=sym, price=f(a.get("base_token_price_usd")), mcap=f(a.get("market_cap_usd")) or f(a.get("fdv_usd")),
                     liq=f(a.get("reserve_in_usd")), m5=m5v, h1=h1v, p1h=f(pc.get("h1")),
                     rising=m5v > (m15v - m5v) / 2.0 if m15v else m5v > 0,           # 5m vol above avg of prior two 5m windows
                     h1_growing=(h1v > (h6v - h1v) / 5.0) if h6v else h1v > 0,        # 1h vol above avg of prior five hours
                     pool=a.get("address"), dex=p["relationships"]["dex"]["data"]["id"],
                     created=pdt(created), src=src))
    for pg in (1, 2, 3): gecko(http("gecko", G + "/trending_pools", {"duration": "1h", "page": pg}), f"gt_trend_p{pg}")
    for pg in (1, 2): gecko(http("gecko", G + "/pools", {"page": pg, "sort": "h24_volume_usd_desc"}), f"gt_vol24_p{pg}")
    dex_mints = []
    for url, src in (("https://api.dexscreener.com/token-profiles/latest/v1", "ds_profiles"), ("https://api.dexscreener.com/token-boosts/top/v1", "ds_boosts_top")):
        js = http("dex", url)
        if isinstance(js, list):
            for it in js:
                if it.get("chainId") == "solana" and it.get("tokenAddress"): dex_mints.append((it["tokenAddress"], src))
    return snaps, dex_mints

def pdt(s):
    if not s: return None
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None

def dex_lookup(mints, src_map, snaps, override=False):
    """batch lookup via DexScreener tokens/v1 (<=30 per call); adds snapshots for mints lacking one."""
    mints = list(dict.fromkeys(mints))
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        js = http("dex", "https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk))
        if not isinstance(js, list): continue
        best = {}
        for p in js:
            m = p["baseToken"]["address"]; l = (p.get("liquidity") or {}).get("usd") or 0
            if m not in best or l > ((best[m].get("liquidity") or {}).get("usd") or 0): best[m] = p
        for m, p in best.items():
            if m in snaps and not override: continue
            v = p.get("volume") or {}; pc = p.get("priceChange") or {}
            m5, h1 = f(v.get("m5")) or 0, f(v.get("h1")) or 0; h6 = f(v.get("h6")) or 0
            snaps[m] = dict(mint=m, symbol=p["baseToken"].get("symbol", "?"), price=f(p.get("priceUsd")), mcap=f(p.get("marketCap")) or f(p.get("fdv")),
                            liq=(p.get("liquidity") or {}).get("usd"), m5=m5, h1=h1, p1h=f(pc.get("h1")),
                            rising=m5 > h1 / 12.0 if h1 else m5 > 0, h1_growing=(h1 > (h6 - h1) / 5.0) if h6 else h1 > 0,
                            pool=p.get("pairAddress"), dex=p.get("dexId"), created=(p.get("pairCreatedAt") or 0) / 1000 or None, src=src_map.get(m, "ds_track"))

# ---------------- classification ----------------
def age_info(s, t):
    if not s["created"]: return None, "unknown"
    age = (t - s["created"]) / 3600
    if s["dex"] in ("pump-fun", "pumpfun"): return age, "mint(pump.fun curve pool = launch)"
    if s["dex"] == "pumpswap" and s["mint"].endswith("pump"): return age, "pool(pumpswap=graduation; token older)"
    return age, "pool"

def classify(s, t):
    """returns list of (class, lane, failed_filters)"""
    out = []
    liq, mc, m5, h1 = s["liq"] or 0, s["mcap"] or 0, s["m5"] or 0, s["h1"] or 0
    p1h = s["p1h"]; p1h_ok = p1h is None or p1h < A_NM["p1h_max_pct"]
    age, basis = age_info(s, t)
    if mc <= 0: return out
    # A
    if mc <= A_MAX_MCAP and m5 >= A_NM["m5"] and s["rising"] and liq >= A_NM["liq"] and p1h_ok:
        if m5 >= A_FULL["m5"] and liq >= A_FULL["liq"]:
            out.append(("FULL-PASS", "A", "none_quant(all A volume/liquidity/price gates pass); catalyst=unverified(<10min X event not checked)"))
        else:
            fails = []
            if m5 < A_FULL["m5"]: fails.append("vol5m<50k")
            if liq < A_FULL["liq"]: fails.append("liq<30k")
            out.append(("A-nearmiss", "A", ";".join(fails) + ";catalyst=unverified"))
    # B
    if age is not None and age < B_SH["age_h"] and B_SH["mc_lo"] <= mc <= B_SH["mc_hi"] and m5 >= B_SH["m5"] and s["rising"] and s["h1_growing"] and liq >= B_SH["liq"]:
        if basis.startswith("mint"):
            out.append(("FULL-PASS", "B", "only_regime:B_paused_in_COLD; narrative/verification unchecked"))
        else:
            out.append(("B-shadow", "B", "regime:B_paused_in_COLD;age_basis=" + basis.split("(")[0]))
    # R band
    if h1 >= R_MIN_H1_VOL and liq >= R_MIN_LIQ:
        for lo, hi in R_BAND:
            if lo <= mc < hi:
                out.append(("R-band", "R", f"mcap_outside_R_range_300k-5M({'below' if mc < 300000 else 'above'});event_unconfirmed(research must verify novel event+catalyst tree)"))
                break
    return out

# ---------------- ladder simulation (snapshot based) ----------------
def init_pos(row, entry, t, lane):
    return dict(row_id=row, lane=lane, entry=entry, t0=t, rem=1.0, realized=0.0, tp_done=[], stop_px=entry * (1 - LADDER[lane]["stop"]),
                peak=entry, low=entry, trailing=False, reached_10=False)

def step(pos, price, t):
    """advance one snapshot. returns (closed:bool, reason|None)."""
    L = LADDER[pos["lane"]]; E = pos["entry"]
    pos["peak"] = max(pos["peak"], price); pos["low"] = min(pos["low"], price)
    if price >= E * 1.10: pos["reached_10"] = True
    trail_px = pos["peak"] * (1 - L["trail"]) if pos["trailing"] else 0
    eff_stop = max(pos["stop_px"], trail_px)
    if price <= eff_stop:                                   # pessimistic: fill at observed price (already through stop) less slippage
        fill = min(price, eff_stop) * (1 - STOP_SLIP)
        pos["realized"] += pos["rem"] * (fill / E); pos["rem"] = 0
        return True, "trail_stop" if (pos["trailing"] and trail_px >= pos["stop_px"]) else ("stop_to_entry" if pos["stop_px"] >= E else "stop_loss")
    for i, (gain, frac) in enumerate(L["tp"]):
        if i in pos["tp_done"] or price < E * (1 + gain): continue
        sell = min(frac, pos["rem"]); pos["realized"] += sell * (1 + gain); pos["rem"] -= sell; pos["tp_done"].append(i)
        if i == 0 and L["be_after_first"]: pos["stop_px"] = max(pos["stop_px"], E)
    if len(pos["tp_done"]) == len(L["tp"]): pos["trailing"] = True   # trail the final remainder once every ladder rung is sold
    if L["time_stop"] and not pos["reached_10"] and t - pos["t0"] >= L["time_stop"][0]:
        pos["realized"] += pos["rem"] * (price / E); pos["rem"] = 0; return True, f"time_stop_{L['time_stop'][0]//60}m"
    if t - pos["t0"] >= MAX_HOLD_S:
        pos["realized"] += pos["rem"] * (price / E); pos["rem"] = 0; return True, "max_hold_24h"
    return False, None

def mark_net_pct(pos, price):
    E = pos["entry"]
    return round((pos["realized"] + pos["rem"] * price / E - 1) * 100 - ROUND_TRIP_FEE_PCT, 2)

# ---------------- io ----------------
def read_rows():
    if not os.path.exists(CSV): return []
    with open(CSV, newline="") as fh: return list(csv.DictReader(fh))
def write_rows(rows):
    tmp = CSV + ".tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    os.replace(tmp, CSV)
def jload(p, d):
    try:
        with open(p) as fh: return json.load(fh)
    except Exception: return d
def jsave(p, o):
    tmp = p + ".tmp"
    with open(tmp, "w") as fh: json.dump(o, fh, indent=1)
    os.replace(tmp, p)

def run():
    t = time.time(); t0 = t
    lockf = open(f"{HOME}/run.lock", "w")
    try: fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: log("SKIP another run in progress"); return
    rows = read_rows(); by_id = {r["row_id"]: r for r in rows}
    pos = jload(POS, {"positions": []}); plist = pos["positions"]
    seen = jload(SEEN, {})
    snaps, dex_mints = collect()
    src_map = {m: s for m, s in dex_mints}
    dex_lookup([m for m, _ in dex_mints if m not in snaps], src_map, snaps)
    open_mints = {by_id[p["row_id"]]["mint"] for p in plist if p["row_id"] in by_id}
    missing = [m for m in open_mints if m not in snaps]
    dex_lookup(missing, {}, snaps)
    t = time.time(); stamp = ts(); closed_n = 0
    # --- track open positions ---
    keep = []
    for p in plist:
        r = by_id.get(p["row_id"])
        if not r: continue
        s = snaps.get(r["mint"])
        if not s or not s["price"]:
            keep.append(p); r["notes"] = (r.get("notes") or "")[:100] + "|no_price_this_run"; continue
        price = s["price"]
        # liquidity guard (added 2026-11-17): a drained pool (rug) reports a meaningless price; book the remainder at 0
        try: e_liq = float(r.get("liq") or 0)
        except ValueError: e_liq = 0.0
        cur_liq = s.get("liq")
        if cur_liq is not None and float(cur_liq) < max(1000.0, 0.05 * e_liq):
            p["rem"] = 0
            r["last_price"] = f"{price:.10g}"; r["last_update_et"] = stamp
            r["net_pct"] = round((p["realized"] - 1) * 100 - ROUND_TRIP_FEE_PCT, 2)
            r["notes"] = (r.get("notes") or "")[:100] + f"|liq_drained({float(cur_liq):.0f})"
            r.update(status="closed", exit_ts_et=stamp, exit_reason="liq_drained_rug", net_basis="realized"); closed_n += 1
            continue
        done, reason = step(p, price, t)
        r["last_price"] = f"{price:.10g}"; r["last_update_et"] = stamp
        r["peak_pct"] = round((p["peak"] / p["entry"] - 1) * 100, 2); r["low_pct"] = round((p["low"] / p["entry"] - 1) * 100, 2)
        r["net_pct"] = mark_net_pct(p, price)
        if done:
            r.update(status="closed", exit_ts_et=stamp, exit_reason=reason, net_basis="realized"); closed_n += 1
        else:
            r.update(status="open", net_basis="mark"); keep.append(p)
    # --- new signals ---
    new = 0; skipped_cap = 0; counts = {}
    cands = []
    for m, s in snaps.items():
        for cls, lane, failed in classify(s, t):
            cands.append((m, s, cls, lane, failed))
    # FULL-PASS first, then by 5m volume
    cands.sort(key=lambda c: (c[2] != "FULL-PASS", -(c[1]["m5"] or 0)))
    for m, s, cls, lane, failed in cands:
        key = f"{m}|{cls}|{lane}"
        if t - seen.get(key, 0) < DEDUP_S: continue
        if new >= MAX_NEW_PER_RUN: skipped_cap += 1; continue
        age, basis = age_info(s, t); rid = f"NM{int(t)}-{m[:6]}-{lane}"
        if rid in by_id: continue
        row = dict(row_id=rid, ts_et=stamp, mint=m, symbol=s["symbol"], **{"class": cls}, lane=lane, failed_filters=failed,
                   mcap=round(s["mcap"] or 0), liq=round(s["liq"] or 0), vol5m=round(s["m5"] or 0), vol1h=round(s["h1"] or 0),
                   entry_price=f"{s['price']:.10g}", status="open", exit_ts_et="", exit_reason="", net_pct=round(-ROUND_TRIP_FEE_PCT, 2), peak_pct=0.0,
                   links=f"https://dexscreener.com/solana/{s['pool']} | https://www.geckoterminal.com/solana/pools/{s['pool']} | https://solscan.io/token/{m}",
                   repeat_veto="", net_basis="mark", last_price=f"{s['price']:.10g}", last_update_et=stamp, low_pct=0.0,
                   p1h_pct="" if s["p1h"] is None else round(s["p1h"], 1), age_h="" if age is None else round(age, 2), age_basis=basis, dex=s["dex"], pool=s["pool"],
                   catalyst="unverified" if lane in ("A", "R") or cls == "FULL-PASS" else "n/a(B has no timing gate)",
                   event_validity="unconfirmed" if lane == "R" else "", source=s["src"],
                   notes="R ladder uses price proxy for catalysts" if lane == "R" else "")
        rows.append(row); by_id[rid] = row; keep.append(init_pos(rid, s["price"], t, lane))
        seen[key] = t; new += 1; counts[cls + "/" + lane] = counts.get(cls + "/" + lane, 0) + 1
        log(f"SIGNAL {cls}/{lane} {s['symbol']} {m} mc={row['mcap']} liq={row['liq']} m5={row['vol5m']} {failed}")
    seen = {k: v for k, v in seen.items() if t - v < 2 * DEDUP_S}
    write_rows(rows); jsave(POS, {"updated_et": stamp, "positions": keep}); jsave(SEEN, seen)
    nopen = sum(1 for r in rows if r["status"] == "open")
    st = dict(last_run_et=stamp, duration_s=round(time.time() - t0, 1), calls=dict(CALLS), tokens_seen=len(snaps), new_rows=new, new_by_class=counts,
              skipped_by_cap=skipped_cap, closed_this_run=closed_n, rows_total=len(rows), open_positions=nopen,
              closed_total=len(rows) - nopen, errors_this_run=CALLS["errors"], pid=os.getpid())
    jsave(STATUS, st); log(f"RUN ok seen={len(snaps)} new={new} closed={closed_n} open={nopen} total={len(rows)} calls={CALLS} {round(time.time()-t0,1)}s")
    # PAPER-ONLY learning-mode hook (ledger/learning). Uses this run's snapshots; failures never affect the scanner.
    try:
        sys.path.insert(0, LEARN_PATH); import learning
        learning.after_run(sys.modules[__name__], snaps, [r for r in rows if r.get("ts_et") == stamp and r.get("status") == "open"], t, stamp)
    except Exception as e: log(f"WARN learning hook failed {type(e).__name__}: {e}")
    # PAPER-ONLY TA shadow setups (learning/ta.py): delayed 1m-candle evaluation, <=4 GeckoTerminal calls/run, own cache; never breaks the scanner.
    try:
        sys.path.insert(0, LEARN_PATH); import ta
        ta.after_run()
    except Exception as e: log(f"WARN ta hook failed {type(e).__name__}: {e}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run": run()
    elif cmd == "selftest":
        import random
        p = init_pos("x", 1.0, 0, "A"); print(step(p, 1.45, 60), p["tp_done"], p["stop_px"]); print(step(p, 2.1, 120), p["tp_done"], p["trailing"])
        print(step(p, 1.3, 180), mark_net_pct(p, 1.3))
        p = init_pos("y", 1.0, 0, "A"); print(step(p, 1.05, 900))
        p = init_pos("z", 1.0, 0, "B"); print(step(p, 0.65, 300), mark_net_pct(p, 0.65))
    else: print("usage: scanner.py [run|selftest]")
