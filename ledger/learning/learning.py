#!/usr/bin/env python3
"""PAPER-ONLY LEARNING MODE book. No LLM, no X calls, no wallets, no paid services, NO extra API calls in the normal path.
Hooked at the end of ledger/nearmiss/scanner.py run() (every 5 min): learning.after_run(scanner_module, snaps, new_rows, t, stamp).
Opens a 0.025 SOL paper trade for each new scanner row of class FULL-PASS/A, A-nearmiss/A, B-shadow/B (and FULL-PASS/B if it ever appears),
then manages exits with the scanner's own ladder code (Lane A / Lane B exits, rug rule, 3% round trip, 2% stop slippage).
Completely separate from any real-money rules. See README.md."""
import csv, json, os, sys, time, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copycat_filter as CF      # paper-only copycat / fake-liquidity filter used by the "-F" twin strategies (no API calls)
import exits as EXITS            # multi-exit shadow tracker (exits.csv; no API calls of its own)
import features as FEAT          # entry feature log (features.csv)
import random, hashlib

DESK_ROOT = os.environ.get("DESK_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOME = os.environ.get("LEARN_DIR") or (os.path.join(DESK_ROOT, "ledger", "learning") if os.environ.get("DESK_ROOT") else os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo("America/Toronto")
TRADES = f"{HOME}/trades.csv"; BOOK = f"{HOME}/book.json"; SYMREG = f"{HOME}/symbols.json"; LOG = f"{HOME}/learning.log"; STOPFILE = f"{HOME}/STOP"
OPEN_POS_FILE = os.environ.get("LEARN_OPEN_POSITIONS", os.path.join(DESK_ROOT, "ledger", "open_positions.json"))

# ---- config ----
START_BANKROLL = 1.0; RESERVE = 0.05; SIZE = 0.025
# Caps (v2, 2026-11-19): MAX_OPEN is global (base + F twins); each family (base / "-F" twins) also has its own open, daily and per-strategy limits.
# The daily caps count ONLY trades that are not gap_affected (gap-hit trades do not burn the cap); HARD_DAY_CAP_PER_FAMILY counts everything as a safety ceiling.
MAX_OPEN = 16; MAX_OPEN_PER_FAMILY = 10; MAX_NEW_PER_DAY = 30; PER_STRATEGY_DAY_CAP = 12; HARD_DAY_CAP_PER_FAMILY = 100
F_START_BANKROLL = 1.0       # the F twins have their OWN 1 SOL paper bankroll (book.json f_*), so the base bankroll/reserve logic stays exactly as before
REENTRY_COOLDOWN_S = 6 * 3600
GAP_S = 600            # a gap between consecutive scanner runs longer than this flags every open trade gap_affected=1
RUG_CONFIRMS = 2       # consecutive numeric low-liquidity readings (same pool) required before a rug close
MAX_HOLD_S = 24 * 3600
# strategy tag -> (scanner class, scanner lane). Priority = order (FULL-PASS first).
STRATEGIES = {("FULL-PASS", "A"): "A-FULLPASS", ("A-nearmiss", "A"): "A-NEARMISS", ("FULL-PASS", "B"): "B-FULLPASS"}
PRIORITY = ["A-FULLPASS", "B-FULLPASS", "A-NEARMISS", "B-SHADOW"]
# ---- X variants (v3, 2026-11-19): separately tracked paper strategies that take only the rows of their source strategies whose ENTRY features match
# every (feature, bucket) condition (bucket names exactly as in analyze.py BUCKETS / analysis_latest.json "conds"). Own family "X": own 1 SOL paper
# bankroll, own caps; base and F strategies are untouched. Empty = none. Example:
#   VARIANTS = {"A-NEARMISS-X1": {"from": ["A-NEARMISS"], "conds": [["mcap", ">=5M"], ["age_h", ">=7d"]]}}
VARIANTS = {}
X_START_BANKROLL = 1.0
# ---- adaptive allocation (v3): Thompson sampling on CLEAN closed net % per strategy, within each family (base / F / X). Each strategy's daily cap =
# max(BANDIT_MIN_CAP, round(share * MAX_NEW_PER_DAY)), share = BANDIT_MIN_SHARE + (1 - k*BANDIT_MIN_SHARE) * P(best). Size stays fixed at SIZE.
# ---- v4 book (2026-11-23): fresh 1 SOL paper ledger, family "V4" (strategies "<base>-V4"). See TUNING_LOG.md / README.md.
#   exit  : EXITS.POLICIES[V4_EXIT] (TP +30% full / stop -15% (2% slip) / 30 min time stop), same rug rule + 3% fee as everything else
#   entry : same scanner classes as STRATEGIES, copycat_filter PASS REQUIRED (risk rule, never relaxed, also for exploration),
#           pool age >= V4_MIN_AGE_H (unknown age = blocked). Rows that fail ONLY the age rule may open as EXPLORATION (explore=1),
#           ~V4_EXPLORE_P% of them (deterministic hash of row_id), at most V4_EXPLORE_SHARE of the day's v4 trades (min 1/day).
#           Exploration trades are excluded from the gate stats and from the bandit.
#   size  : min(V4_SIZE_MAX, V4_SIZE_FRAC * current v4 bankroll) -> a full -100% loss (+fee) costs <= ~2.6% of the bankroll.
# Legacy v1-v3 families (base "B" and "-F" twins) stop opening new trades (LEGACY_OPEN=False); their history and any open trades are kept and managed as before.
V4_EXIT = "TP30_S15_T30"; V4_START_BANKROLL = 1.0; V4_SIZE_FRAC = 0.025; V4_SIZE_MAX = 0.025; V4_MIN_AGE_H = 6.0
V4_EXPLORE_P = 35; V4_EXPLORE_SHARE = 0.15; V4_SINCE = "2026-11-23T16:10:00-0500"; LEGACY_OPEN = False
BANDIT_MIN_SHARE = 0.15; BANDIT_MIN_CAP = 3; BANDIT_PRIOR_N = 2; BANDIT_SD_FLOOR = 25.0; BANDIT_DRAWS = 2000
SHADOW_PIGGYBACK = True   # add shadow-tracked mints to the free slots of a DexScreener batch that learning.py is ALREADY sending (never an extra call)
AUTO_ANALYZE_HOUR = 20    # run analyze.py (local, ~0.2s) once per ET day on the first scanner run at/after 20:30 ET, for the 9 PM review
# Optional local position mirror for a separate watcher: "off" (default; always off on CI), "fullpass" (only A-FULLPASS) or "all".
WATCH_MODE = "off" if (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")) else os.environ.get("LEARN_WATCH_MODE", "off")
COLS = ["trade_id", "strategy", "class", "lane", "open_ts_et", "close_ts_et", "mint", "symbol", "entry_price", "size_sol", "exit_reason",
        "net_pct", "net_sol", "peak_pct", "low_pct", "status", "scanner_row_id", "last_price", "entry_mcap", "entry_liq", "net_basis", "gap_affected", "filter_info", "book", "explore"]
def fam_of(strategy):
    s = str(strategy)
    if s.endswith("-V4"): return "V4"
    return "F" if s.endswith("-F") else ("X" if s in VARIANTS or "-X" in s else "B")      # B = base family (not lane B!), X = feature variants

def et(ts=None): return dt.datetime.fromtimestamp(ts or time.time(), ET)
def stamp_of(ts): return et(ts).strftime("%Y-%m-%dT%H:%M:%S%z")
def parse_ts(s):
    try: return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except Exception: return None
def log(msg):
    with open(LOG, "a") as fh: fh.write(f"{stamp_of(time.time())} {msg}\n")
def jload(p, d):
    try:
        with open(p) as fh: return json.load(fh)
    except Exception: return d
def jsave(p, o):
    tmp = p + ".tmp"
    with open(tmp, "w") as fh: json.dump(o, fh, indent=1)
    os.replace(tmp, p)
def read_trades():
    if not os.path.exists(TRADES): return []
    with open(TRADES, newline="") as fh: return list(csv.DictReader(fh))
def write_trades(rows):
    tmp = TRADES + ".tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    os.replace(tmp, TRADES)
def fnum(x, d=0.0):
    try: return float(x)
    except Exception: return d

def after_run(sc, snaps, new_rows, t, stamp):
    """sc = scanner module (step, init_pos, mark_net_pct, ROUND_TRIP_FEE_PCT, dex_lookup). Never raises into the scanner (caller wraps)."""
    book = jload(BOOK, None) or dict(start_bankroll=START_BANKROLL, reserve=RESERVE, size_sol=SIZE, realized_pnl_sol=0.0, positions=[], next_id=1, created_et=stamp_of(t))
    trades = read_trades(); by_id = {r["trade_id"]: r for r in trades}
    plist = book["positions"]; closed_n = 0; opened = []
    # ---- gap detection: time since previous scanner run (box pauses when idle; exits then fill at stale/gapped prices) ----
    last_run = book.get("last_run_t"); gap_now = bool(last_run and t - last_run > GAP_S)
    if gap_now: log(f"WARN GAP {round((t - last_run) / 60)} min since last scanner run: {len(plist)} open trade(s) flagged gap_affected=1")
    # ---- manage open positions (same data as the scanner; one extra dex lookup only if a mint has no snapshot this run) ----
    missing = [p["mint"] for p in plist if p["mint"] not in snaps]
    if missing and SHADOW_PIGGYBACK:
        missing = list(dict.fromkeys(missing)); room = -len(missing) % 30         # free slots in the batch(es) already going out; never adds a call
        if room:
            try: missing += [m for m in dict.fromkeys(EXITS.needed_mints(HOME)) if m not in snaps and m not in missing][:room]
            except Exception as e: log(f"WARN shadow piggyback failed {type(e).__name__}")
    if missing:
        try: sc.dex_lookup(missing, {}, snaps)
        except Exception as e: log(f"WARN dex_lookup failed {type(e).__name__}")
    keep = []
    for p in plist:
        tr = by_id.get(p["trade_id"])
        if not tr: continue
        if gap_now: tr["gap_affected"] = 1; p["gap"] = 1          # trade was alive across a >10 min gap in scanner runs
        s = snaps.get(p["mint"])
        if not s or not s.get("price"):
            keep.append(p); continue
        price = s["price"]; cur_liq = s.get("liq")
        # liquidity reading must be a real number; None / missing / non-numeric = no information, NEVER a rug
        try: cur_liq = None if cur_liq is None else float(cur_liq)
        except (TypeError, ValueError): cur_liq = None
        if cur_liq is not None and cur_liq != cur_liq: cur_liq = None      # NaN
        tr["last_price"] = f"{price:.10g}"
        suspect = cur_liq is not None and cur_liq < max(1000.0, 0.05 * fnum(p.get("entry_liq")))
        if suspect and p.get("pool") and s.get("pool") and p["pool"] != s["pool"]:
            # snapshot is a different (sibling) pool than the one we entered: its liquidity says nothing about our pool -> inconclusive, hold
            log(f"WARN {p['trade_id']} {tr['symbol']} low liq {cur_liq:.0f} but snapshot pool {str(s['pool'])[:6]} != entry pool {str(p['pool'])[:6]}: inconclusive, holding")
            if t - p["t0"] >= MAX_HOLD_S:
                tr.update(status="excluded", close_ts_et=stamp, exit_reason="invalid_unverified_pool", net_basis="excluded"); p["closed_t"] = t
                log(f"CLOSE {p['trade_id']} {tr['strategy']} {tr['symbol']} invalid_unverified_pool (excluded)"); closed_n += 1
            else: keep.append(p)
            continue
        if suspect:
            p["rug_strikes"] = p.get("rug_strikes", 0) + 1
            if p["rug_strikes"] < RUG_CONFIRMS:
                log(f"WARN {p['trade_id']} {tr['symbol']} liq {cur_liq:.0f} below rug threshold, reading {p['rug_strikes']}/{RUG_CONFIRMS}: waiting for confirmation")
                keep.append(p); continue
            p["rem"] = 0; reason = "liq_drained_rug"; done = True      # confirmed on consecutive readings
            net = round((p["realized"] - 1) * 100 - sc.ROUND_TRIP_FEE_PCT, 2)
        elif fam_of(p.get("strategy")) == "V4":
            if cur_liq is not None: p["rug_strikes"] = 0
            reason = EXITS.step_policy(EXITS.POLICIES[p.get("exit", V4_EXIT)], p, p["entry"], price, t, p["t0"]); done = bool(reason)
            net = sc.mark_net_pct(p, price)
        else:
            if cur_liq is not None: p["rug_strikes"] = 0
            done, reason = sc.step(p, price, t)
            net = sc.mark_net_pct(p, price)
        tr["peak_pct"] = round((p["peak"] / p["entry"] - 1) * 100, 2); tr["low_pct"] = round((p["low"] / p["entry"] - 1) * 100, 2)
        psz = fnum(p.get("size"), SIZE) or SIZE
        tr["net_pct"] = net; tr["net_sol"] = round(psz * net / 100, 6)
        if done:
            tr.update(status="closed", close_ts_et=stamp, exit_reason=reason, net_basis="realized")
            rk = {"F": "f_realized_pnl_sol", "X": "x_realized_pnl_sol", "V4": "v4_realized_pnl_sol"}.get(fam_of(tr["strategy"]), "realized_pnl_sol")
            book[rk] = round(book.get(rk, 0.0) + psz * net / 100, 6); closed_n += 1
            p["closed_t"] = t
            log(f"CLOSE {p['trade_id']} {tr['strategy']} {tr['symbol']} {reason} net={net}% ({tr['net_sol']} SOL) peak={tr['peak_pct']}% low={tr['low_pct']}%" + (" GAP_AFFECTED" if str(tr.get("gap_affected")) == "1" else ""))
        else:
            tr["net_basis"] = "mark"; keep.append(p)
    book["positions"] = plist = keep
    # ---- symbol registry (local file, built from snapshots the scanner already fetched; no API calls) ----
    reg = jload(SYMREG, None)
    if reg is None:
        reg = {}
        try: log(f"symbol registry seeded from near_misses.csv: {CF.seed_from_rows(reg, os.environ.get('LEARN_NEARMISS_CSV', os.path.join(DESK_ROOT, 'ledger', 'nearmiss', 'near_misses.csv')))} mints")
        except Exception as e: log(f"WARN registry seed failed {type(e).__name__}: {e}")
    try:
        CF.registry_update(reg, [(m, sn.get("symbol"), sn.get("liq")) for m, sn in snaps.items()], t); CF.registry_prune(reg, t); jsave(SYMREG, reg)
    except Exception as e: log(f"WARN symbol registry update failed {type(e).__name__}: {e}")
    # ---- new entries ----
    trade_map = {}
    if not os.path.exists(STOPFILE):
        today = et(t).strftime("%Y-%m-%d")
        clean = lambda r: str(r.get("gap_affected") or "0") != "1"
        n_day = {"B": 0, "F": 0, "X": 0, "V4": 0}; n_hard = {"B": 0, "F": 0, "X": 0, "V4": 0}; n_strat = {}; n_v4 = {"main": 0, "explore": 0}
        alloc = bandit_alloc(book, trades, t)
        for r in trades:
            if (r["open_ts_et"] or "")[:10] != today: continue
            fm = fam_of(r["strategy"]); n_hard[fm] += 1
            if fm == "V4": n_v4["explore" if str(r.get("explore") or "0") == "1" else "main"] += 1
            if clean(r):
                n_day[fm] += 1
                if str(r.get("explore") or "0") != "1": n_strat[r["strategy"]] = n_strat.get(r["strategy"], 0) + 1      # gap-hit trades do NOT count toward the daily caps
        open_keys = {(p["mint"], fam_of(p.get("strategy"))) for p in plist}
        n_open = {k: sum(1 for p in plist if fam_of(p.get("strategy")) == k) for k in ("B", "F", "X", "V4")}
        last_close = {}
        for r in trades:
            ct = parse_ts(r["close_ts_et"]) if r["status"] == "closed" else None
            if ct: k = (r["mint"], fam_of(r["strategy"])); last_close[k] = max(last_close.get(k, 0), ct)
        banks = {"B": book["start_bankroll"] + book["realized_pnl_sol"], "F": F_START_BANKROLL + book.get("f_realized_pnl_sol", 0.0), "X": X_START_BANKROLL + book.get("x_realized_pnl_sol", 0.0),
                 "V4": V4_START_BANKROLL + book.get("v4_realized_pnl_sol", 0.0)}
        dep = {k: sum(fnum(p.get("size"), SIZE) or SIZE for p in plist if fam_of(p.get("strategy")) == k) for k in banks}
        share = lambda st_: alloc.get(st_, {}).get("share", 0.0)
        cands = []; info_map = {}
        for r in new_rows:
            strat = STRATEGIES.get((r.get("class"), r.get("lane")))
            if not (strat and r.get("status") == "open"): continue
            try: okf, whyf = CF.check(dict(mint=r["mint"], symbol=r.get("symbol"), mcap=r.get("mcap"), liq=r.get("liq"), vol1h=r.get("vol1h"), age_h=r.get("age_h")), reg, t)
            except Exception as e: okf, whyf = False, [f"filter_error:{type(e).__name__}"]; log(f"WARN filter failed {type(e).__name__}: {e}")
            info = "F_pass" if okf else "F_block:" + ";".join(whyf)
            info_map[r["row_id"]] = info
            # ---- v4 entry rule ----
            age = fnum(r.get("age_h"), None) if str(r.get("age_h") or "") != "" else None
            v4n = strat + "-V4"
            if not okf: log(f"V4_BLOCK {v4n} {r['symbol']} {r['mint'][:8]} copycat_filter")
            elif age is not None and age >= V4_MIN_AGE_H: cands.append((-share(v4n), -fnum(r.get("vol5m")), -1, v4n, r, "F_pass|v4_main"))
            elif int(hashlib.sha1(r["row_id"].encode()).hexdigest(), 16) % 100 < V4_EXPLORE_P:
                cands.append((0.0, -fnum(r.get("vol5m")), 3, v4n, r, f"F_pass|v4_explore:age_h={age}"))
            else: log(f"V4_BLOCK {v4n} {r['symbol']} {r['mint'][:8]} young_pool age_h={age} (<{V4_MIN_AGE_H})")
            if not LEGACY_OPEN: continue
            cands.append((-share(strat), -fnum(r.get("vol5m")), 0, strat, r, info))
            if okf: cands.append((-share(strat + "-F"), -fnum(r.get("vol5m")), 1, strat + "-F", r, "F_pass"))
            for vn, vc in VARIANTS.items():
                try: vok = strat in vc.get("from", []) and variant_match(vc.get("conds", []), r, reg, t)
                except Exception as e: vok = False; log(f"WARN variant {vn} check failed {type(e).__name__}: {e}")
                if vok: cands.append((-share(vn), -fnum(r.get("vol5m")), 2, vn, r, info))
            else: log(f"FILTER_BLOCK {strat}-F {r['symbol']} {r['mint'][:8]} {'; '.join(whyf)}")
        cands.sort(key=lambda c: (c[0], c[1], c[2]))
        for _, _, _, strat, r, info in cands:
            m = r["mint"]; fm = fam_of(strat); why = None; xp = "v4_explore" in info
            sz = round(min(V4_SIZE_MAX, V4_SIZE_FRAC * banks["V4"]), 6) if fm == "V4" else SIZE
            if (m, fm) in open_keys: why = "mint_already_open"
            elif xp and n_v4["explore"] >= max(1, int(V4_EXPLORE_SHARE * (n_v4["main"] + n_v4["explore"] + 1))): why = "explore_share_cap"
            elif t - last_close.get((m, fm), 0) < REENTRY_COOLDOWN_S: why = "closed_within_6h"
            elif len(plist) >= MAX_OPEN: why = "max_open"
            elif n_open[fm] >= MAX_OPEN_PER_FAMILY: why = "max_open_family"
            elif n_day[fm] >= MAX_NEW_PER_DAY: why = "daily_cap"
            elif n_hard[fm] >= HARD_DAY_CAP_PER_FAMILY: why = "hard_daily_cap"
            elif not xp and n_strat.get(strat, 0) >= alloc.get(strat, {}).get("day_cap", PER_STRATEGY_DAY_CAP): why = "strategy_daily_cap"
            elif banks[fm] - RESERVE - dep[fm] < sz or sz < 0.001: why = "bankroll_reserve"
            if why:
                log(f"SKIP {strat} {r['symbol']} {m[:8]} ({why})"); continue
            lane = r["lane"]; entry = fnum(r["entry_price"]); tid = f"L{book['next_id']:04d}"; book["next_id"] += 1
            if fm == "V4":
                pos = dict(row_id=tid, lane=lane, entry=entry, t0=t, exit=V4_EXIT, size=sz, explore=int(xp), **EXITS.new_state(entry)[V4_EXIT])
                pos.pop("closed", None)
            else: pos = sc.init_pos(tid, entry, t, lane)
            pos.update(trade_id=tid, mint=m, symbol=r["symbol"], strategy=strat, entry_liq=fnum(r.get("liq")), pool=r.get("pool") or "", gap=0)
            plist.append(pos); open_keys.add((m, fm)); n_open[fm] += 1; n_day[fm] += 1; n_hard[fm] += 1; dep[fm] += sz
            if fm == "V4": n_v4["explore" if xp else "main"] += 1
            if not xp: n_strat[strat] = n_strat.get(strat, 0) + 1
            row = dict(trade_id=tid, strategy=strat, **{"class": r["class"]}, lane=lane, open_ts_et=stamp, close_ts_et="", mint=m, symbol=r["symbol"],
                       entry_price=f"{entry:.10g}", size_sol=sz, exit_reason="", net_pct=round(-sc.ROUND_TRIP_FEE_PCT, 2), net_sol=round(-sz * sc.ROUND_TRIP_FEE_PCT / 100, 6),
                       peak_pct=0.0, low_pct=0.0, status="open", scanner_row_id=r["row_id"], last_price=f"{entry:.10g}", entry_mcap=r.get("mcap"), entry_liq=r.get("liq"), net_basis="mark", gap_affected=0, filter_info=info[:200], book="v4" if fm == "V4" else "v3", explore=int(xp))
            trades.append(row); by_id[tid] = row; opened.append(tid); trade_map.setdefault(r["row_id"], []).append(tid)
            log(f"OPEN {tid} {strat} lane={lane} {r['symbol']} {m} entry={row['entry_price']} mcap={r.get('mcap')} liq={r.get('liq')} size={sz} SOL {info[:120]}")
    # ---- entry features (every new scanner row) + multi-exit shadow tracking + daily analysis: local only, never break the book ----
    try: FEAT.log_new_rows(HOME, new_rows, snaps, reg, t, locals().get("info_map") or {})
    except Exception as e: log(f"WARN features failed {type(e).__name__}: {e}")
    try: EXITS.update(HOME, snaps, new_rows, trade_map, t, stamp, gap_now, stamp_of, log)
    except Exception as e: log(f"WARN exits failed {type(e).__name__}: {e}")
    # ---- persist ----
    write_trades(trades)
    pb = [p for p in plist if fam_of(p.get("strategy")) == "B"]; pf = [p for p in plist if fam_of(p.get("strategy")) == "F"]
    ur = lambda L: sum(fnum(by_id[p["trade_id"]]["net_sol"]) for p in L if p["trade_id"] in by_id)
    fr = book.get("f_realized_pnl_sol", 0.0)
    # existing keys (open_count, open_ids, bankroll_sol, realized_pnl_sol, unrealized_pnl_sol, deployed_sol, closed_total, trades_total) now describe the BASE strategies only; F twins have f_* keys
    book.update(last_run_t=t, updated_et=stamp, open_count=len(pb), open_ids=[p["trade_id"] for p in pb], bankroll_sol=round(book["start_bankroll"] + book["realized_pnl_sol"], 6),
                unrealized_pnl_sol=round(ur(pb), 6), deployed_sol=round(SIZE * len(pb), 6), reserve_sol=RESERVE,
                closed_total=sum(1 for r in trades if r["status"] == "closed" and fam_of(r["strategy"]) == "B"), trades_total=sum(1 for r in trades if fam_of(r["strategy"]) == "B"),
                f_realized_pnl_sol=round(fr, 6), f_bankroll_sol=round(F_START_BANKROLL + fr, 6), f_start_bankroll=F_START_BANKROLL, f_open_count=len(pf), f_open_ids=[p["trade_id"] for p in pf],
                f_unrealized_pnl_sol=round(ur(pf), 6), f_deployed_sol=round(SIZE * len(pf), 6),
                f_closed_total=sum(1 for r in trades if r["status"] == "closed" and fam_of(r["strategy"]) == "F"), f_trades_total=sum(1 for r in trades if fam_of(r["strategy"]) == "F"),
                x_realized_pnl_sol=round(book.get("x_realized_pnl_sol", 0.0), 6), x_bankroll_sol=round(X_START_BANKROLL + book.get("x_realized_pnl_sol", 0.0), 6), x_start_bankroll=X_START_BANKROLL,
                x_open_ids=[p["trade_id"] for p in plist if fam_of(p.get("strategy")) == "X"], variants=VARIANTS,
                v4=dict(since_et=book.get("v4", {}).get("since_et", V4_SINCE), start_bankroll=V4_START_BANKROLL, realized_pnl_sol=round(book.get("v4_realized_pnl_sol", 0.0), 6),
                        bankroll_sol=round(V4_START_BANKROLL + book.get("v4_realized_pnl_sol", 0.0), 6), open_ids=[p["trade_id"] for p in plist if fam_of(p.get("strategy")) == "V4"],
                        unrealized_pnl_sol=round(ur([p for p in plist if fam_of(p.get("strategy")) == "V4"]), 6),
                        deployed_sol=round(sum(fnum(p.get("size"), SIZE) for p in plist if fam_of(p.get("strategy")) == "V4"), 6),
                        closed_total=sum(1 for r in trades if r["status"] == "closed" and fam_of(r["strategy"]) == "V4"), trades_total=sum(1 for r in trades if fam_of(r["strategy"]) == "V4"),
                        exit=V4_EXIT, min_age_h=V4_MIN_AGE_H, require_filter_pass=True, size_frac=V4_SIZE_FRAC, size_max=V4_SIZE_MAX,
                        explore_p=V4_EXPLORE_P, explore_share=V4_EXPLORE_SHARE, legacy_open=LEGACY_OPEN),
                open_count_total=len(plist), stopped=os.path.exists(STOPFILE),
                caps=dict(max_open=MAX_OPEN, max_open_per_family=MAX_OPEN_PER_FAMILY, max_new_per_day_per_family_clean_only=MAX_NEW_PER_DAY, per_strategy_day_cap_clean_only=PER_STRATEGY_DAY_CAP,
                          hard_day_cap_per_family_all_trades=HARD_DAY_CAP_PER_FAMILY, reentry_cooldown_h=6),
                watch_mode=WATCH_MODE, filter=dict(liq_mcap_max=CF.LIQ_MCAP_MAX, vol1h_liq_max=CF.VOL1H_LIQ_MAX, min_age_h=CF.MIN_AGE_H, clone_minlen=CF.CLONE_MINLEN))
    jsave(BOOK, book)
    write_open_positions(plist, by_id, stamp)
    maybe_analyze(t)
    if opened or closed_n: log(f"RUN opened={len(opened)} closed={closed_n} open={len(plist)} realized={book['realized_pnl_sol']} SOL f_realized={book.get('f_realized_pnl_sol', 0.0)} SOL v4_realized={book.get('v4_realized_pnl_sol', 0.0)} SOL")

def arms_of(fam):
    base = [s for s in STRATEGIES.values()]
    return {"B": base, "F": [s + "-F" for s in base], "X": list(VARIANTS), "V4": [s + "-V4" for s in base]}[fam]

def bandit_alloc(book, trades, t):
    """Thompson sampling per family on CLEAN closed net % (clipped to [-100, 300]). Gaussian posterior with BANDIT_PRIOR_N pseudo-trades at 0%
    (optimistic vs the data, so untested arms get explored) and sd floor BANDIT_SD_FLOOR. Deterministic per ET day + data, logged in book.json."""
    out = {}; today = et(t).strftime("%Y-%m-%d")
    for fam in ("B", "F", "X", "V4"):
        seen = {r["strategy"] for r in trades}
        arms = [a for a in arms_of(fam) if a in seen]      # arms that never traded (e.g. B-FULLPASS) keep the fixed PER_STRATEGY_DAY_CAP until their first trade
        if not arms: continue
        d = {a: [max(-100.0, min(300.0, fnum(r["net_pct"]))) for r in trades if r["strategy"] == a and r["status"] == "closed" and str(r.get("gap_affected") or "0") != "1" and str(r.get("explore") or "0") != "1"] for a in arms}
        rng = random.Random(f"{today}|{fam}|{sum(len(v) for v in d.values())}")
        post = {}
        for a, v in d.items():
            n = len(v); m = sum(v) / (n + BANDIT_PRIOR_N)
            sd = max(BANDIT_SD_FLOOR, (sum((x - sum(v) / n) ** 2 for x in v) / (n - 1)) ** 0.5 if n > 1 else BANDIT_SD_FLOOR) / (n + BANDIT_PRIOR_N) ** 0.5
            post[a] = (n, m, sd)
        wins = {a: 0 for a in arms}
        for _ in range(BANDIT_DRAWS):
            wins[max(arms, key=lambda a: rng.gauss(post[a][1], post[a][2]))] += 1
        k = len(arms); ms = min(BANDIT_MIN_SHARE, 0.9 / k)
        for a in arms:
            pb = wins[a] / BANDIT_DRAWS; sh = ms + (1 - k * ms) * pb
            out[a] = dict(n_clean=post[a][0], post_mean=round(post[a][1], 2), post_sd=round(post[a][2], 2), p_best=round(pb, 3), share=round(sh, 3),
                          day_cap=max(BANDIT_MIN_CAP, round(sh * MAX_NEW_PER_DAY)))
    prev = (book.get("bandit") or {}).get("alloc", {})
    if {a: v["day_cap"] for a, v in out.items()} != {a: v.get("day_cap") for a, v in prev.items()}:
        log("BANDIT " + " ".join(f"{a}:cap={v['day_cap']}(p_best={v['p_best']},n={v['n_clean']},mean={v['post_mean']})" for a, v in out.items()))
    book["bandit"] = dict(updated_et=stamp_of(t), method="thompson_gaussian_clean_net_pct", min_share=BANDIT_MIN_SHARE, min_cap=BANDIT_MIN_CAP, alloc=out)
    return out

def variant_match(conds, r, reg, t):
    import analyze as AN
    f = FEAT.feats(r, FEAT.clone_of(r, reg, t))
    return all(AN.BUCKETS[name](f.get(name)) == b for name, b in conds)

def maybe_analyze(t):
    d = et(t)
    if (d.hour, d.minute) < (AUTO_ANALYZE_HOUR, 30): return
    mark = f"{HOME}/.analyzed_day"
    try:
        if open(mark).read().strip() == d.strftime("%Y-%m-%d"): return
    except Exception: pass
    open(mark, "w").write(d.strftime("%Y-%m-%d"))
    try:
        import analyze as AN; js = AN.main(quiet=True)
        log(f"ANALYZE wrote analysis_latest.md: flagged={len(js.get('flagged', []))}")
    except Exception as e: log(f"WARN analyze failed {type(e).__name__}: {e}")

def write_open_positions(plist, by_id, stamp):
    """Optionally mirror open learning positions into a local open_positions.json (watcher schema). Default OFF. Merge-only: never touches non-learning entries."""
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"): return      # never touch files outside the repo on CI
    if WATCH_MODE == "off" and not os.path.exists(f"{HOME}/.watch_was_on"): return
    existing = jload(OPEN_POS_FILE, [])
    if not isinstance(existing, list): return
    mine = [e for e in existing if isinstance(e, dict) and e.get("source") == "learning_mode"]
    others = [e for e in existing if not (isinstance(e, dict) and e.get("source") == "learning_mode")]
    new = []
    if WATCH_MODE != "off":
        open(f"{HOME}/.watch_was_on", "w").close()
        for p in plist:
            if p["strategy"].endswith("-F"): continue          # F twins are never mirrored to the watcher
            if WATCH_MODE == "fullpass" and p["strategy"] != "A-FULLPASS": continue
            tr = by_id[p["trade_id"]]
            new.append(dict(position_id=p["trade_id"], candidate_id=p["trade_id"], mint=p["mint"], symbol=p["symbol"], lane="LEARN", learn_lane=p["lane"], strategy=p["strategy"],
                            source="learning_mode", entry_time_et=tr["open_ts_et"], entry_price=p["entry"], entry_liquidity_usd=p["entry_liq"], size_sol=SIZE,
                            remaining_pct=round(p["rem"] * 100), status="open", stop_pct=-100 * (0.20 if p["lane"] == "A" else 0.30)))
    elif os.path.exists(f"{HOME}/.watch_was_on"):
        os.remove(f"{HOME}/.watch_was_on")      # mode switched off: strip our entries once
    if new != mine or WATCH_MODE == "off":
        if mine or new:
            jsave(OPEN_POS_FILE, others + new)

def summary():
    rows = read_trades(); book = jload(BOOK, {})
    print(json.dumps({k: book.get(k) for k in ("bankroll_sol", "realized_pnl_sol", "unrealized_pnl_sol", "open_count", "closed_total", "trades_total", "updated_et", "stopped")}, indent=1))
    agg = {}
    for r in rows:
        a = agg.setdefault(r["strategy"], dict(n=0, closed=0, wins=0, sum=0.0, sol=0.0)); a["n"] += 1
        if r["status"] == "closed":
            a["closed"] += 1; a["sum"] += fnum(r["net_pct"]); a["sol"] += fnum(r["net_sol"]); a["wins"] += fnum(r["net_pct"]) > 0
    for k, a in agg.items(): print(k, dict(trades=a["n"], closed=a["closed"], win_rate=round(a["wins"] / a["closed"] * 100, 1) if a["closed"] else None, avg_net_pct=round(a["sum"] / a["closed"], 2) if a["closed"] else None, net_sol=round(a["sol"], 5)))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if cmd == "summary": summary()
    else: print("usage: learning.py summary   (the book is driven by scanner.py's run hook)")
