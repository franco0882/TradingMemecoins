#!/usr/bin/env python3
"""PAPER-ONLY offline analysis (stdlib only, read-only on the desk data, no API calls). Writes analysis_latest.md (+ analysis_latest.json).
Sources:
  1. near_misses.csv  : every scanner candidate since Nov 16 with its shadow outcome under its OWN lane ladder (LADDER_A / LADDER_B / LADDER_R).
  2. exits.csv        : multi-exit shadow results (several exit policies on the same entry; starts 2026-11-19, grows every run).
  3. trades.csv       : learning-book trades (clean only for judging).
  4. features.csv     : entry-time features (no look-ahead) joined on scanner row_id.
All net % values are already net of the 3% round-trip fee and 2% stop/trail slippage. `stress` = net minus a further 2% (extra slippage).
Clean = no >10 min scanner gap while the position was open (gaps rebuilt from scanner.log RUN lines; exits.csv/trades.csv carry their own flag).
Rugs (liq_drained_rug) count at their booked value (~-100%). Rows with net > +1000% (or peak > +2000% with a positive net) are treated as price/drained-pool ARTIFACTS:
excluded from the stats and listed (they would otherwise dominate averages).
A bucket(+policy) is FLAGGED only if CLEAN n >= 30 and median > 0 and average > 0; it is called ROBUST if both chronological halves also have median > 0.
Usage: python3 analyze.py [--quiet]"""
import csv, json, os, re, sys, statistics as st, datetime as dt, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
DESK = os.environ.get("DESK_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NM = os.environ.get("AN_NEARMISS", f"{DESK}/ledger/nearmiss/near_misses.csv"); SLOG = os.environ.get("AN_SCANLOG", f"{DESK}/ledger/nearmiss/scanner.log")
TR = f"{HERE}/trades.csv"; EX = f"{HERE}/exits.csv"; FE = f"{HERE}/features.csv"; OUT = f"{HERE}/analysis_latest.md"; OUTJ = f"{HERE}/analysis_latest.json"
NMIN = 30; GAP_S = 600; ART_NET = 1000.0; ART_PEAK = 2000.0
def fl(x):
    try:
        v = float(x); return None if v != v else v
    except (TypeError, ValueError): return None
def T(s):
    try: return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except Exception: return None
def rd(p):
    if not os.path.exists(p): return []
    with open(p, newline="") as fh: return list(csv.DictReader(fh))
# ---------- buckets (entry-time features only) ----------
def cut(edges, labels):
    def f(v):
        v = fl(v)
        if v is None: return None
        for e, l in zip(edges, labels):
            if v < e: return l
        return labels[-1]
    return f
BUCKETS = {
    "mcap":       cut([50e3, 100e3, 250e3, 1e6, 5e6], ["<50k", "50-100k", "100-250k", "250k-1M", "1-5M", ">=5M"]),
    "liq":        cut([20e3, 30e3, 60e3, 150e3], ["<20k", "20-30k", "30-60k", "60-150k", ">=150k"]),
    "liq_mcap":   cut([0.05, 0.10, 0.20, 0.50], ["<.05", ".05-.10", ".10-.20", ".20-.50", ">=.50"]),
    "vol5m":      cut([25e3, 50e3, 100e3, 250e3], ["<25k", "25-50k", "50-100k", "100-250k", ">=250k"]),
    "vol1h_liq":  cut([2, 5, 10, 20], ["<2", "2-5", "5-10", "10-20", ">=20"]),
    "vol5m_share_1h": cut([0.10, 0.20, 0.35], ["<.10", ".10-.20", ".20-.35", ">=.35"]),
    "p1h_pct":    cut([0, 25, 50, 100, 200], ["<0", "0-25", "25-50", "50-100", "100-200", ">=200"]),
    "age_h":      cut([1, 2, 6, 24, 168], ["<1h", "1-2h", "2-6h", "6-24h", "1-7d", ">=7d"]),
    "hour_et":    cut([6, 12, 18], ["00-06", "06-12", "12-18", "18-24"]),
    "dex":        lambda v: v or None,
    "source":     lambda v: (re.sub(r"_p\d$", "", v) if v else None),
    "clone":      lambda v: {"1": "clone", "0": "not_clone"}.get(str(v)),
    "filter_pass": lambda v: {"1": "F_pass", "0": "F_block"}.get(str(v)),
    "repeat_veto": lambda v: "repeat" if (v or "").startswith("1") else "no_tag",
}
def stats(v):
    if not v: return None
    return dict(n=len(v), win=round(100 * sum(x > 0 for x in v) / len(v), 1), avg=round(sum(v) / len(v), 2), med=round(st.median(v), 2),
                stress_avg=round(sum(v) / len(v) - 2, 2), stress_med=round(st.median(v) - 2, 2))
def fmt(s): return f"n={s['n']:>3} win {s['win']:5.1f}% avg {s['avg']:+7.2f}% med {s['med']:+7.2f}%"
def main(quiet=False):
    now = dt.datetime.now().astimezone()
    runs = sorted(T(l[:24]) for l in open(SLOG, errors="ignore") if " RUN ok " in l and T(l[:24])) if os.path.exists(SLOG) else []
    import bisect
    def gapped(t0, t1):
        if t0 is None or t1 is None or not runs: return True
        i = bisect.bisect_left(runs, t0 - 1); j = bisect.bisect_right(runs, t1 + 1)
        seg = runs[i:j]
        if not seg: return True
        return any(b - a > GAP_S for a, b in zip(seg, seg[1:]))
    feats = {r["row_id"]: r for r in rd(FE)}
    nm = [r for r in rd(NM) if r["status"] == "closed" and fl(r["net_pct"]) is not None]
    art = []; data = []          # data: dict(policy, lane, cls, net, clean, t, f)
    for r in nm:
        net, pk = fl(r["net_pct"]), fl(r["peak_pct"]) or 0
        if net > ART_NET or (pk > ART_PEAK and net > 0): art.append(r); continue      # rugs always count at their booked loss
        t0 = T(r["ts_et"]); clean = not gapped(t0, T(r["exit_ts_et"]))
        data.append(dict(src="scanner", policy=f"LADDER_{r['lane']}(scanner)", lane=r["lane"], cls=r["class"], net=net, clean=clean, t=t0, f=feats.get(r["row_id"]) or r,
                         rug=r["exit_reason"] == "liq_drained_rug", sym=r["symbol"]))
    ex = [r for r in rd(EX) if r.get("status") == "closed" and fl(r["net_pct"]) is not None]
    for r in ex:
        net, pk = fl(r["net_pct"]), fl(r["peak_pct"]) or 0
        if net > ART_NET or (pk > ART_PEAK and net > 0): art.append(dict(r, row_id=r["entry_id"], ts_et=r["open_ts_et"])); continue
        data.append(dict(src="exits", policy=r["policy"], lane=r["lane"], cls=r["class"], net=net, clean=str(r["gap_affected"]) != "1", t=T(r["open_ts_et"]),
                         f=feats.get(r["entry_id"], {}), rug=r["exit_reason"] == "liq_drained_rug", sym=r["symbol"]))
    trades = [r for r in rd(TR) if r["status"] == "closed"]
    L = []; P = L.append
    P(f"# Learning-book analysis ({now.strftime('%Y-%m-%d %H:%M %Z')})\n")
    P("Paper only. All nets are after the 3% fee and 2% stop slippage. Judge on CLEAN rows (no >10 min scanner gap while open). "
      f"Flag rule: clean n>={NMIN}, median>0 AND average>0. ROBUST = both chronological halves also median>0. Bucket edges were chosen before looking; "
      "with ~100 buckets tested, expect a few false positives, so a flag is a candidate for a separate paper variant, never a live change.\n")
    sc = [d for d in data if d["src"] == "scanner"]
    P(f"Data: {len(nm)} closed scanner rows ({sum(d['clean'] for d in sc)} clean, {len(art)} artifacts excluded), {len(ex)} exit-policy results "
      f"({sum(1 for d in data if d['src']=='exits' and d['clean'])} clean), {len(trades)} closed learning trades "
      f"({sum(1 for r in trades if str(r.get('gap_affected'))!='1')} clean), {len(runs)} scanner runs.\n")
    # ---- 1. policy table ----
    P("## 1. Exit policies (clean)\n")
    P("| policy | lane | clean: n / win% / avg / median | stress med (-2%) | all rows: n / median | rugs |\n|---|---|---|---|---|---|")
    pol = {}
    for d in data: pol.setdefault((d["policy"], d["lane"]), []).append(d)
    pol_rows = []
    for (p, ln), g in sorted(pol.items()):
        c = stats([d["net"] for d in g if d["clean"]]); a = stats([d["net"] for d in g])
        pol_rows.append(dict(policy=p, lane=ln, clean=c, all=a))
        P(f"| {p} | {ln} | {fmt(c) if c else 'n=0'} | {c['stress_med'] if c else ''} | {a['n']} / {a['med']:+.2f}% | {sum(d['rug'] for d in g)} |")
    if not ex: P("\n(exits.csv is empty so far: multi-exit shadow tracking started 2026-11-19; only the scanner's own lane ladders exist historically.)")
    # ---- 2. learning trades ----
    P("\n## 2. Learning-book strategies (clean closed)\n")
    sg = {}
    for r in trades:
        if str(r.get("gap_affected")) != "1": sg.setdefault(r["strategy"], []).append(fl(r["net_pct"]) or 0)
    for k, v in sorted(sg.items()): P(f"- {k}: {fmt(stats(v))}")
    # ---- 3. feature buckets ----
    flagged = []; best = []
    def bucket_rows(g, name):
        out = {}
        for d in g:
            b = BUCKETS[name](d["f"].get(name)) if d["f"] else None
            if b is not None: out.setdefault(b, []).append(d)
        return out
    def judge(label, g, extra):
        c = [d for d in g if d["clean"]]
        s = stats([d["net"] for d in c]); a = stats([d["net"] for d in g])
        if not s: return
        rec = dict(label=label, clean=s, all=a, **extra)
        if s["n"] >= NMIN:
            c.sort(key=lambda d: d["t"] or 0); h = len(c) // 2
            m1, m2 = st.median([d["net"] for d in c[:h]]), st.median([d["net"] for d in c[h:]])
            rec["halves_med"] = (round(m1, 2), round(m2, 2))
            best.append(rec)
            if s["med"] > 0 and s["avg"] > 0:
                rec["robust"] = m1 > 0 and m2 > 0; flagged.append(rec)
    groups = {}
    for d in data: groups.setdefault((d["policy"], d["lane"]), []).append(d)
    for (p, ln), g in groups.items():
        for name in BUCKETS:
            for b, gg in bucket_rows(g, name).items(): judge(f"{p} lane {ln} | {name}={b}", gg, dict(policy=p, lane=ln, conds=[(name, b)]))
        names = [n for n in BUCKETS if n not in ("hour_et",)]
        for n1, n2 in itertools.combinations(names, 2):
            for b1, g1 in bucket_rows(g, n1).items():
                for b2, g2 in bucket_rows(g1, n2).items():
                    judge(f"{p} lane {ln} | {n1}={b1} & {n2}={b2}", g2, dict(policy=p, lane=ln, conds=[(n1, b1), (n2, b2)]))
    P(f"\n## 3. Flagged bucket + policy combos (clean n>={NMIN}, median>0 and avg>0)\n")
    if flagged:
        for r in sorted(flagged, key=lambda r: (-r.get("robust", False), -r["clean"]["med"])):
            P(f"- **{r['label']}**: {fmt(r['clean'])}; halves median {r['halves_med']}; {'ROBUST' if r['robust'] else 'not robust (one half <= 0)'}; all rows n={r['all']['n']} med {r['all']['med']:+.2f}%")
    else: P("**None.** No bucket or bucket pair with clean n>=30 has a positive median and average under any exit policy measured so far.")
    P(f"\n## 4. Best candidates (clean n>={NMIN}, ranked by median; single features and pairs)\n")
    P("By median (beware: a near-zero median with a very negative average = many flat trades plus a rug tail):")
    for r in sorted(best, key=lambda r: -r["clean"]["med"])[:10]:
        P(f"- {r['label']}: {fmt(r['clean'])}; halves median {r['halves_med']}")
    P("\nBy average (what the bankroll actually earns):")
    for r in sorted(best, key=lambda r: -r["clean"]["avg"])[:10]:
        P(f"- {r['label']}: {fmt(r['clean'])}; halves median {r['halves_med']}")
    P(f"\n## 5. Single-feature buckets for the lane A ladder (clean, n>=10)\n")
    ga = groups.get(("LADDER_A(scanner)", "A"), [])
    for name in BUCKETS:
        parts = []
        for b, gg in sorted(bucket_rows([d for d in ga if d["clean"]], name).items(), key=lambda kv: -stats([d["net"] for d in kv[1]])["med"]):
            s = stats([d["net"] for d in gg])
            if s["n"] >= 10: parts.append(f"{b}: n={s['n']} med {s['med']:+.1f}% avg {s['avg']:+.1f}%")
        if parts: P(f"- {name}: " + "; ".join(parts))
    P("\n## 6. Artifacts excluded\n")
    for r in art: P(f"- {r.get('row_id')} {r.get('symbol')} {r.get('class', '')} net {r.get('net_pct')}% peak {r.get('peak_pct')}% {r.get('exit_reason')}")
    if not art: P("(none)")
    P("\n## 7. Notes for the 9 PM review\n")
    P("- Make at most one change. Prefer: (a) add a separately tracked paper variant for a ROBUST flagged combo; (b) otherwise leave entries alone and watch exits.csv fill in.\n"
      "- Exit-policy comparisons are only valid within exits.csv (same entries, same path). The scanner ladders in section 1 are a different, larger sample.\n"
      "- Gate for anything real is unchanged: 30+ clean closed, positive avg AND median, plus explicit human sign-off.")
    md = "\n".join(L) + "\n"
    tmp = OUT + ".tmp"; open(tmp, "w").write(md); os.replace(tmp, OUT)
    js = dict(generated=now.isoformat(), flagged=[dict(label=r["label"], policy=r["policy"], lane=r["lane"], conds=r["conds"], clean=r["clean"], robust=r["robust"], halves_med=r["halves_med"]) for r in flagged],
              policies=pol_rows, top_by_median=[dict(label=r["label"], clean=r["clean"], halves_med=r["halves_med"]) for r in sorted(best, key=lambda r: -r["clean"]["med"])[:10]],
              top_by_avg=[dict(label=r["label"], clean=r["clean"], halves_med=r["halves_med"]) for r in sorted(best, key=lambda r: -r["clean"]["avg"])[:10]])
    tmp = OUTJ + ".tmp"; json.dump(js, open(tmp, "w"), indent=1); os.replace(tmp, OUTJ)
    if not quiet: print(md)
    return js
if __name__ == "__main__": main("--quiet" in sys.argv)
