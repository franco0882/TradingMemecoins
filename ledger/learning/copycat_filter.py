#!/usr/bin/env python3
"""PAPER-ONLY copycat / fake-liquidity entry filter for the learning book's "-F" twin strategies. No API calls, no network: pure function of
data the scanner already has (this run's snapshots, the scanner's rows, and a small local symbol registry symbols.json kept by learning.py).
Rules (any one blocks; thresholds picked by backtest, see README / filter_backtest.py):
  fakeliq : liq/mcap  >= LIQ_MCAP_MAX   (pool 'liquidity' at or above half the market cap = fake/inflated liquidity; healthy tokens sit at 0.03-0.40)
  wash    : vol1h/liq >= VOL1H_LIQ_MAX  (hourly volume >= 20x the pool's liquidity = wash trading)
  clone   : another mint with the same / near-same symbol (case-insensitive, non-alphanumerics stripped, Cyrillic/Greek homoglyphs folded to Latin,
            edit distance <= 1 when both normalized symbols have >= 4 chars) was seen BEFORE this one or has MORE liquidity
  young   : pool age < MIN_AGE_H hours (age from the scanner row; unknown age never blocks). Default 0 = off (the backtest showed it blocks as many winners as rugs)."""
import unicodedata
LIQ_MCAP_MAX = 0.5; VOL1H_LIQ_MAX = 20.0; MIN_AGE_H = 0.0; CLONE_MINLEN = 4
_H = {}
for _a, _b in zip("АВЕКМНОРСТХУаеорсухѕіјԁɡ", "ABEKMHOPCTXYaeopcyxsijdg"): _H[_a] = _b          # Cyrillic lookalikes
for _a, _b in zip("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧαοντυ", "ABEZHIKMNOPTYXaonty"): _H[_a] = _b                  # Greek lookalikes
def norm(s):
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = "".join(_H.get(c, c) for c in s).casefold()
    return "".join(c for c in s if c.isalnum())
def _ed1(a, b):
    if a == b: return True
    if abs(len(a) - len(b)) > 1: return False
    if len(a) == len(b): return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b): a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))
def similar(a, b):
    if not a or not b: return False
    if a == b: return True
    return len(a) >= CLONE_MINLEN and len(b) >= CLONE_MINLEN and _ed1(a, b)
def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return None
def registry_update(reg, mints_info, t):
    """reg: mint -> {s: symbol, n: norm symbol, ft: first seen ts, liq: latest liquidity, lt: last seen ts}. mints_info: iterable of (mint, symbol, liq)."""
    for m, sym, liq in mints_info:
        e = reg.get(m)
        if e is None: e = reg[m] = dict(s=sym, n=norm(sym), ft=t, liq=0.0, lt=t)
        l = _num(liq)
        if l is not None: e["liq"] = l
        e["lt"] = t
def registry_prune(reg, t, keep_s=14 * 86400):
    for m in [m for m, e in reg.items() if t - e.get("lt", 0) > keep_s]: del reg[m]
def check(c, reg, t):
    """c: dict(mint, symbol, mcap, liq, vol1h, age_h). Returns (ok, [reasons])."""
    why = []
    mc, liq, v1, age = _num(c.get("mcap")), _num(c.get("liq")), _num(c.get("vol1h")), _num(c.get("age_h"))
    if mc and liq is not None and mc > 0 and liq / mc >= LIQ_MCAP_MAX: why.append(f"fakeliq(liq/mcap={liq / mc:.2f})")
    if liq and v1 is not None and liq > 0 and v1 / liq >= VOL1H_LIQ_MAX: why.append(f"wash(vol1h/liq={v1 / liq:.0f})")
    if MIN_AGE_H > 0 and age is not None and age < MIN_AGE_H: why.append(f"young(age={age:.2f}h)")
    n = norm(c.get("symbol")); me = reg.get(c.get("mint")); my_ft = me["ft"] if me else t; my_liq = liq or 0.0
    if n:
        for m, e in reg.items():
            if m == c.get("mint") or not similar(n, e.get("n")): continue
            if e["ft"] < my_ft or (e.get("liq") or 0.0) > my_liq:
                why.append(f"clone({e.get('s')} {m[:6]} liq={(e.get('liq') or 0):.0f}{' earlier' if e['ft'] < my_ft else ''})"); break
    return (not why), why
def seed_from_rows(reg, csv_path):
    """One-time seed of the registry from the scanner's near_misses.csv (read-only local file): first-seen = earliest row, liq = liquidity on the latest row."""
    import csv, datetime as dt
    def T(s):
        try: return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
        except Exception: return None
    rows = []
    with open(csv_path, newline="") as fh:
        for r in csv.DictReader(fh):
            t = T(r.get("ts_et") or "")
            if t and r.get("mint"): rows.append((t, r))
    rows.sort(key=lambda x: x[0])
    for t, r in rows:
        e = reg.get(r["mint"])
        if e is None: e = reg[r["mint"]] = dict(s=r.get("symbol"), n=norm(r.get("symbol")), ft=t, liq=0.0, lt=t)
        l = _num(r.get("liq"))
        if l is not None: e["liq"] = l
        e["lt"] = t
    return len(reg)
