#!/usr/bin/env python3
"""Clean-only stats for the paper learning book. Shows CLEAN closed trades (gap_affected=0, not excluded) and ALL closed trades, per strategy,
with each "-F" twin (copycat/fake-liquidity filter) printed directly under its base strategy, plus base trades split by the filter's verdict.
Paper only. Usage: python3 clean_stats.py [--csv path]"""
import csv, json, os, sys, statistics as st
HOME = os.path.dirname(os.path.abspath(__file__))
path = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else f"{HOME}/trades.csv"
def f(x, d=0.0):
    try: return float(x)
    except Exception: return d
rows = list(csv.DictReader(open(path, newline="")))
# ---- v4 book (2026-11-23): fresh 1 SOL paper ledger, strategies "*-V4", exit TP30_S15_T30, copycat PASS + pool age >= 6h; explore=1 rows excluded from gate ----
v4 = [r for r in rows if r["strategy"].endswith("-V4")]
rows = [r for r in rows if not r["strategy"].endswith("-V4")]          # everything below = v1-v3 history (frozen for new opens since v4)
def line(label, g):
    v = [f(r["net_pct"]) for r in g]
    return f"{label:<16}{len(g):>4}{100 * sum(x > 0 for x in v) / len(v):>7.1f}{sum(v) / len(v):>9.2f}{st.median(v):>9.2f}{sum(f(r['net_sol']) for r in g):>10.5f}"
def header(title): print(f"\n== {title} ==\n{'strategy':<16}{'n':>4}{'win%':>7}{'avg%':>9}{'med%':>9}{'net_SOL':>10}")
def table(title, sel):
    header(title)
    if not sel: print("(none)"); return
    groups = {}
    for r in sel: groups.setdefault(r["strategy"], []).append(r)
    bases = sorted({k[:-2] if k.endswith("-F") else k for k in groups})
    for b in bases:                                   # base row, then its -F twin right under it
        for k in (b, b + "-F"):
            if k in groups: print(line(k, groups[k]))
    base = [r for r in sel if not r["strategy"].endswith("-F")]; fr = [r for r in sel if r["strategy"].endswith("-F")]
    if base: print(line("TOTAL base", base))
    if fr: print(line("TOTAL F twins", fr))
closed = [r for r in rows if r["status"] == "closed"]
excluded = [r for r in rows if r["status"] == "excluded"]
opn = [r for r in rows if r["status"] == "open"]
clean = [r for r in closed if str(r.get("gap_affected") or "0") != "1"]
def v4_report():
    print("######## v4 BOOK (live paper policy since 2026-11-23; gate stats = CLEAN, non-exploration) ########")
    try:
        b4 = json.load(open(f"{HOME}/book.json")).get("v4") or {}
        print(f"v4 bankroll {b4.get('bankroll_sol')} SOL of {b4.get('start_bankroll')} (realized {b4.get('realized_pnl_sol')}, unrealized {b4.get('unrealized_pnl_sol')}, deployed {b4.get('deployed_sol')}) since {b4.get('since_et')}; exit {b4.get('exit')}, min age {b4.get('min_age_h')}h, filter PASS required, size {b4.get('size_frac')} x bankroll (max {b4.get('size_max')})")
    except Exception: pass
    c4 = [r for r in v4 if r["status"] == "closed"]; cl4 = [r for r in c4 if str(r.get("gap_affected") or "0") != "1"]
    gate = [r for r in cl4 if str(r.get("explore") or "0") != "1"]; xp = [r for r in cl4 if str(r.get("explore") or "0") == "1"]
    print(f"v4 trades={len(v4)} closed={len(c4)} clean_closed={len(cl4)} open={sum(r['status'] == 'open' for r in v4)} excluded={sum(r['status'] == 'excluded' for r in v4)}")
    header("v4 CLEAN closed, GATE set (explore=0)")
    g = {}
    for r in gate: g.setdefault(r["strategy"], []).append(r)
    for k in sorted(g): print(line(k, g[k]))
    if gate: print(line("TOTAL v4 gate", gate))
    else: print("(none yet)")
    header("v4 CLEAN closed, EXPLORATION (explore=1, young pools; NOT gate evidence)")
    print(line("TOTAL explore", xp) if xp else "(none yet)")
    if gate:
        v = [f(r["net_pct"]) for r in gate]
        print(f"gate progress: {len(gate)}/30 clean trades, avg {sum(v) / len(v):+.2f}%, median {st.median(v):+.2f}% -> " + ("meets numeric gate (still needs human sign-off)" if len(gate) >= 30 and sum(v) > 0 and st.median(v) > 0 else "NOT met"))
    print("######## v1-v3 HISTORY (legacy base + F twins; no new opens since v4) ########")
v4_report()
print(f"trades={len(rows)} closed={len(closed)} open={len(opn)} excluded={len(excluded)} gap_affected_closed={len(closed) - len(clean)} clean_closed={len(clean)}")
table("CLEAN closed trades (gap_affected=0, not excluded)", clean)
table("ALL closed trades (includes gap_affected; excludes 'excluded')", closed)
# base trades split by the copycat filter's verdict recorded at entry (filter_info column; empty for trades opened before 2026-11-19 v2)
tagged = [r for r in closed if not r["strategy"].endswith("-F") and (r.get("filter_info") or "").startswith("F_")]
for nm, sel in (("BASE trades by filter verdict, ALL closed", tagged), ("BASE trades by filter verdict, CLEAN closed", [r for r in tagged if r in clean])):
    header(nm)
    p = [r for r in sel if r["filter_info"] == "F_pass"]; b = [r for r in sel if r["filter_info"] != "F_pass"]
    print(line("filter PASS", p) if p else "filter PASS      (none)"); print(line("filter BLOCK", b) if b else "filter BLOCK     (none)")
try:
    bk = json.load(open(f"{HOME}/book.json"))
    print(f"\nv1-v3 bankrolls (frozen): base {bk.get('bankroll_sol')} SOL (realized {bk.get('realized_pnl_sol')}); F twins {bk.get('f_bankroll_sol')} SOL of {bk.get('f_start_bankroll')} (realized {bk.get('f_realized_pnl_sol')})")
except Exception: pass
# ---- multi-exit shadow results (exits.csv; v3 2026-11-19): every exit policy on the SAME entries/price path, clean = no scanner gap / price hole ----
ex_path = os.path.join(os.path.dirname(os.path.abspath(path)), "exits.csv")
if os.path.exists(ex_path):
    ex = list(csv.DictReader(open(ex_path, newline="")))
    exc = [r for r in ex if r.get("status") == "closed"]
    def pline(label, g):
        v = [f(r["net_pct"]) for r in g]
        return f"{label:<16}{len(g):>4}{100 * sum(x > 0 for x in v) / len(v):>7.1f}{sum(v) / len(v):>9.2f}{st.median(v):>9.2f}{sum(r['exit_reason'] == 'liq_drained_rug' for r in g):>6}"
    for title, sel in (("EXIT POLICIES, CLEAN results (all lane A/B scanner entries)", [r for r in exc if str(r.get("gap_affected")) != "1"]),
                       ("EXIT POLICIES, CLEAN results, entries the learning book took", [r for r in exc if str(r.get("gap_affected")) != "1" and r.get("trade_ids")]),
                       ("EXIT POLICIES, ALL results (incl. gap-affected)", exc)):
        print(f"\n== {title} ==\n{'policy':<16}{'n':>4}{'win%':>7}{'avg%':>9}{'med%':>9}{'rugs':>6}")
        g = {}
        for r in sel: g.setdefault((r["policy"], r["lane"]), []).append(r)
        if not g: print("(none yet)")
        for (pol, ln), rr in sorted(g.items()): print(pline(f"{pol}/{ln}", rr))
    print(f"exits.csv: {len(ex)} rows, {len(exc)} closed, {sum(1 for r in ex if r.get('status') == 'excluded')} excluded (no_data)")
else: print("\n(exits.csv not created yet)")
try:
    ba = json.load(open(f"{HOME}/book.json")).get("bandit") or {}
    if ba: print("\nbandit daily caps (Thompson, clean net %): " + ", ".join(f"{a} cap {v['day_cap']} (P(best) {v['p_best']}, n {v['n_clean']})" for a, v in ba.get("alloc", {}).items()))
except Exception: pass
if opn: print(f"\nopen trades (mark-to-market, not in tables): " + ", ".join(f"{r['trade_id']} {r['strategy']} {r['symbol']} {f(r['net_pct']):+.1f}%{' [gap]' if str(r.get('gap_affected'))=='1' else ''}" for r in opn))
print("\nNote: gate for any lane needs 30+ clean closed trades with positive avg AND median net of fees; paper only. F twins are compared to their base on the same trade stream.")
# ---- TA shadow setups (2026-11-23, ta.py; paper only; 1m candles, delayed no-look-ahead evaluation; full detail in ta_report.md) ----
try:
    import ta as _TA
    print("\n######## TA SHADOW SETUPS (not traded by any book; CLEAN = no scanner gap; 'vsTP30_S'/'vsHOLD15' = baselines on the same rows) ########")
    _TA.report(compact=True)
except Exception as _e: print(f"\n(TA section unavailable: {type(_e).__name__}: {_e})")
