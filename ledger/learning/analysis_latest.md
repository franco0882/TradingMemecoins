# Learning-book analysis (2026-11-27 21:06 EST)

Paper only. All nets are after the 3% fee and 2% stop slippage. Judge on CLEAN rows (no >10 min scanner gap while open). Flag rule: clean n>=30, median>0 AND average>0. ROBUST = both chronological halves also median>0. Bucket edges were chosen before looking; with ~100 buckets tested, expect a few false positives, so a flag is a candidate for a separate paper variant, never a live change.

Data: 1354 closed scanner rows (603 clean, 17 artifacts excluded), 2356 exit-policy results (643 clean), 145 closed learning trades (47 clean), 681 scanner runs.

## 1. Exit policies (clean)

| policy | lane | clean: n / win% / avg / median | stress med (-2%) | all rows: n / median | rugs |
|---|---|---|---|---|---|
| BE15_TR25 | A | n= 28 win  10.7% avg  -47.33% med  -49.65% | -51.65 | 159 / -65.51% | 54 |
| BE15_TR25 | B | n= 37 win  13.5% avg  -54.83% med  -54.53% | -56.53 | 133 / -101.89% | 60 |
| HALF20_RUN | A | n= 29 win  10.3% avg  -46.31% med  -41.48% | -43.48 | 160 / -43.00% | 56 |
| HALF20_RUN | B | n= 40 win   7.5% avg  -50.85% med  -44.30% | -46.3 | 137 / -100.10% | 64 |
| HOLD15 | A | n= 41 win  31.7% avg   -7.08% med   -3.21% | -5.21 | 159 / -8.77% | 34 |
| HOLD15 | B | n= 39 win  53.8% avg  +22.47% med   +2.88% | 0.88 | 126 / -66.84% | 36 |
| HOLD60 | A | n=  5 win   0.0% avg -103.00% med -103.00% | -105.0 | 146 / -78.85% | 53 |
| HOLD60 | B | n=  3 win   0.0% avg -103.00% med -103.00% | -105.0 | 105 / -103.00% | 52 |
| LADDER_A | A | n= 44 win  25.0% avg  -28.40% med  -25.49% | -27.49 | 165 / -28.04% | 43 |
| LADDER_A | B | n= 43 win  18.6% avg  -47.33% med  -46.03% | -48.03 | 139 / -99.27% | 52 |
| LADDER_A(scanner) | A | n=279 win  18.3% avg  -23.75% med  -10.72% | -12.72 | 508 / -16.11% | 108 |
| LADDER_B(scanner) | B | n=183 win  18.0% avg  -49.83% med  -59.22% | -61.22 | 368 / -95.50% | 163 |
| LADDER_R(scanner) | R | n=141 win   2.8% avg  -71.05% med  -75.26% | -77.26 | 472 / -58.12% | 101 |
| QT20_S12 | A | n= 51 win  51.0% avg  -19.14% med  +17.00% | 15.0 | 163 / -22.15% | 43 |
| QT20_S12 | B | n= 73 win  50.7% avg  -20.19% med  +17.00% | 15.0 | 143 / -60.17% | 44 |
| TP30_S15_T30 | A | n= 49 win  51.0% avg  -16.73% med   +0.40% | -1.6 | 163 / -20.71% | 39 |
| TP30_S15_T30 | B | n= 70 win  50.0% avg  -18.44% med   -9.27% | -11.27 | 141 / -54.53% | 40 |
| TP50_S25 | A | n= 39 win  38.5% avg  -21.25% med  -31.35% | -33.35 | 165 / -53.62% | 53 |
| TP50_S25 | B | n= 52 win  40.4% avg  -24.30% med  -34.50% | -36.5 | 141 / -101.60% | 57 |

## 2. Learning-book strategies (clean closed)

- A-FULLPASS: n= 11 win  36.4% avg   -9.74% med   -3.21%
- A-FULLPASS-F: n=  5 win  20.0% avg   -1.49% med   -3.21%
- A-FULLPASS-V4: n=  1 win 100.0% avg  +27.00% med  +27.00%
- A-NEARMISS: n= 14 win  14.3% avg  -27.45% med  -26.79%
- A-NEARMISS-F: n=  6 win   0.0% avg  -46.79% med  -53.05%
- A-NEARMISS-V4: n=  3 win  33.3% avg  -20.28% med  -34.21%
- B-SHADOW: n=  7 win   0.0% avg  -56.55% med  -49.88%

## 3. Flagged bucket + policy combos (clean n>=30, median>0 and avg>0)

- **HOLD15 lane B | dex=pumpswap**: n= 39 win  53.8% avg  +22.47% med   +2.88%; halves median (5.06, -1.9); not robust (one half <= 0); all rows n=124 med -72.87%
- **HOLD15 lane B | repeat_veto=no_tag**: n= 39 win  53.8% avg  +22.47% med   +2.88%; halves median (5.06, -1.9); not robust (one half <= 0); all rows n=126 med -66.84%
- **HOLD15 lane B | dex=pumpswap & repeat_veto=no_tag**: n= 39 win  53.8% avg  +22.47% med   +2.88%; halves median (5.06, -1.9); not robust (one half <= 0); all rows n=124 med -72.87%

## 4. Best candidates (clean n>=30, ranked by median; single features and pairs)

By median (beware: a near-zero median with a very negative average = many flat trades plus a rug tail):
- TP50_S25 lane B | filter_pass=F_block: n= 30 win  53.3% avg  -13.09% med  +47.00%; halves median (-34.79, 47.0)
- TP50_S25 lane B | dex=pumpswap & filter_pass=F_block: n= 30 win  53.3% avg  -13.09% med  +47.00%; halves median (-34.79, 47.0)
- TP50_S25 lane B | filter_pass=F_block & repeat_veto=no_tag: n= 30 win  53.3% avg  -13.09% med  +47.00%; halves median (-34.79, 47.0)
- TP30_S15_T30 lane B | source=gt_trend: n= 48 win  56.2% avg  -19.99% med  +27.00%; halves median (27.0, -38.48)
- TP30_S15_T30 lane B | filter_pass=F_block: n= 45 win  62.2% avg  -10.66% med  +27.00%; halves median (18.77, 27.0)
- TP30_S15_T30 lane B | age_h=<1h & source=gt_trend: n= 39 win  59.0% avg  -16.44% med  +27.00%; halves median (27.0, -21.62)
- TP30_S15_T30 lane B | age_h=<1h & filter_pass=F_block: n= 35 win  62.9% avg   -9.67% med  +27.00%; halves median (27.0, 27.0)
- TP30_S15_T30 lane B | dex=pumpswap & source=gt_trend: n= 48 win  56.2% avg  -19.99% med  +27.00%; halves median (27.0, -38.48)
- TP30_S15_T30 lane B | dex=pumpswap & filter_pass=F_block: n= 45 win  62.2% avg  -10.66% med  +27.00%; halves median (18.77, 27.0)
- TP30_S15_T30 lane B | source=gt_trend & filter_pass=F_block: n= 34 win  61.8% avg  -13.36% med  +27.00%; halves median (27.0, 27.0)

By average (what the bankroll actually earns):
- HOLD15 lane B | dex=pumpswap: n= 39 win  53.8% avg  +22.47% med   +2.88%; halves median (5.06, -1.9)
- HOLD15 lane B | repeat_veto=no_tag: n= 39 win  53.8% avg  +22.47% med   +2.88%; halves median (5.06, -1.9)
- HOLD15 lane B | dex=pumpswap & repeat_veto=no_tag: n= 39 win  53.8% avg  +22.47% med   +2.88%; halves median (5.06, -1.9)
- HOLD15 lane A | source=gt_trend: n= 30 win  26.7% avg   +0.26% med   -3.23%; halves median (-3.32, -3.15)
- HOLD15 lane A | source=gt_trend & repeat_veto=no_tag: n= 30 win  26.7% avg   +0.26% med   -3.23%; halves median (-3.32, -3.15)
- LADDER_A(scanner) lane A | age_h=>=7d & repeat_veto=no_tag: n= 48 win  16.7% avg   -1.97% med   -3.21%; halves median (-3.21, -3.61)
- LADDER_A(scanner) lane A | vol5m=25-50k & age_h=>=7d: n= 49 win  16.3% avg   -2.56% med   -3.21%; halves median (-3.17, -3.36)
- LADDER_A(scanner) lane A | p1h_pct=<0 & age_h=>=7d: n= 36 win  19.4% avg   -3.11% med   -3.10%; halves median (-2.5, -3.46)
- LADDER_A(scanner) lane A | vol1h_liq=<2 & age_h=>=7d: n= 70 win  14.3% avg   -3.14% med   -3.21%; halves median (-3.12, -3.57)
- LADDER_A(scanner) lane A | vol5m_share_1h=>=.35 & age_h=>=7d: n= 34 win  17.6% avg   -3.37% med   -4.74%; halves median (-3.21, -6.99)

## 5. Single-feature buckets for the lane A ladder (clean, n>=10)

- mcap: >=5M: n=58 med -3.2% avg -4.2%; 1-5M: n=31 med -8.7% avg -15.0%; 250k-1M: n=45 med -25.6% avg -27.0%; 50-100k: n=82 med -25.8% avg -30.7%; 100-250k: n=34 med -29.7% avg -31.0%; <50k: n=29 med -44.1% avg -38.9%
- liq: >=150k: n=82 med -3.2% avg -7.1%; 60-150k: n=88 med -8.0% avg -27.4%; 20-30k: n=31 med -30.7% avg -30.8%; 30-60k: n=38 med -32.8% avg -39.2%; <20k: n=40 med -36.1% avg -29.6%
- liq_mcap: >=.50: n=65 med -3.3% avg -35.9%; <.05: n=29 med -3.4% avg -5.6%; .05-.10: n=34 med -7.6% avg -16.6%; .10-.20: n=63 med -12.6% avg -20.5%; .20-.50: n=88 med -29.7% avg -25.9%
- vol5m: >=250k: n=57 med -3.1% avg -29.1%; 50-100k: n=71 med -8.8% avg -19.9%; 25-50k: n=116 med -9.4% avg -16.7%; 100-250k: n=35 med -37.7% avg -46.3%
- vol1h_liq: <2: n=87 med -3.4% avg -6.5%; >=20: n=62 med -11.2% avg -35.1%; 10-20: n=48 med -26.5% avg -30.9%; 2-5: n=44 med -28.2% avg -26.1%; 5-10: n=38 med -34.6% avg -33.0%
- vol5m_share_1h: .10-.20: n=80 med -6.8% avg -29.3%; <.10: n=61 med -9.6% avg -22.5%; .20-.35: n=54 med -10.4% avg -26.1%; >=.35: n=84 med -20.8% avg -17.9%
- p1h_pct: 0-25: n=75 med -3.3% avg -14.2%; <0: n=61 med -4.2% avg -11.6%; 50-100: n=61 med -26.2% avg -26.2%; 100-200: n=64 med -31.2% avg -40.4%; 25-50: n=18 med -32.8% avg -37.4%
- age_h: >=7d: n=82 med -3.3% avg -4.8%; 1-7d: n=11 med -14.2% avg -13.8%; 6-24h: n=22 med -18.4% avg -20.3%; 1-2h: n=38 med -29.0% avg -42.4%; <1h: n=116 med -31.2% avg -31.8%; 2-6h: n=10 med -33.5% avg -33.8%
- hour_et: 00-06: n=55 med -5.0% avg -26.0%; 06-12: n=88 med -9.2% avg -19.7%; 18-24: n=71 med -10.7% avg -24.8%; 12-18: n=65 med -22.1% avg -26.1%
- dex: raydium-clmm: n=27 med -3.2% avg -3.4%; meteora: n=11 med -3.2% avg -4.0%; raydium: n=14 med -6.8% avg -7.8%; pumpswap: n=222 med -25.6% avg -28.3%
- source: gt_vol24: n=29 med -3.2% avg -22.3%; gt_trend: n=187 med -6.5% avg -22.3%; ds_profiles: n=54 med -34.2% avg -27.1%
- clone: not_clone: n=145 med -7.0% avg -17.0%; clone: n=134 med -24.0% avg -31.1%
- filter_pass: F_pass: n=126 med -5.8% avg -13.4%; F_block: n=153 med -25.8% avg -32.3%
- repeat_veto: repeat: n=91 med -8.7% avg -25.1%; no_tag: n=188 med -11.7% avg -23.1%

## 6. Artifacts excluded

- NM1795015235-9hjBLB-A DCTY A-nearmiss net 5190.3% peak 21738.35% max_hold_24h
- NM1795122334-B34nXK-B FIONA B-shadow net 501.9% peak 2553.44% trail_stop
- NM1795122334-B34nXK-R FIONA R-band net 678.86% peak 2553.44% trail_stop
- NM1795490685-3cL47o-A GROKIA A-nearmiss net 225.31% peak 3384.21% trail_stop
- NM1795490685-3cL47o-B GROKIA B-shadow net 225.31% peak 3384.21% trail_stop
- NM1795490685-3cL47o-R GROKIA R-band net 310.07% peak 3384.21% trail_stop
- NM1795122334-B34nXK-B FIONA B-shadow net 501.9% peak 2553.44% trail_stop
- NM1795490685-3cL47o-A GROKIA A-nearmiss net 2755.67% peak 2758.67% max_hold_120m
- NM1795490685-3cL47o-A GROKIA A-nearmiss net 1386.34% peak 2758.67% max_hold_240m
- NM1795490685-3cL47o-A GROKIA A-nearmiss net 2755.67% peak 2758.67% max_hold_15m
- NM1795490685-3cL47o-A GROKIA A-nearmiss net 2755.67% peak 2758.67% max_hold_60m
- NM1795490685-3cL47o-B GROKIA B-shadow net 2755.67% peak 2758.67% max_hold_120m
- NM1795490685-3cL47o-B GROKIA B-shadow net 1386.34% peak 2758.67% max_hold_240m
- NM1795490685-3cL47o-B GROKIA B-shadow net 2755.67% peak 2758.67% max_hold_15m
- NM1795490685-3cL47o-B GROKIA B-shadow net 2755.67% peak 2758.67% max_hold_60m
- NM1795490685-3cL47o-A GROKIA A-nearmiss net 225.31% peak 3384.21% trail_stop
- NM1795490685-3cL47o-B GROKIA B-shadow net 225.31% peak 3384.21% trail_stop

## 7. Notes for the 9 PM review

- Make at most one change. Prefer: (a) add a separately tracked paper variant for a ROBUST flagged combo; (b) otherwise leave entries alone and watch exits.csv fill in.
- Exit-policy comparisons are only valid within exits.csv (same entries, same path). The scanner ladders in section 1 are a different, larger sample.
- Gate for anything real is unchanged: 30+ clean closed, positive avg AND median, plus explicit human sign-off.
