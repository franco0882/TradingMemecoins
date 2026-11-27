# Learning-book analysis (2026-11-26 20:50 EST)

Paper only. All nets are after the 3% fee and 2% stop slippage. Judge on CLEAN rows (no >10 min scanner gap while open). Flag rule: clean n>=30, median>0 AND average>0. ROBUST = both chronological halves also median>0. Bucket edges were chosen before looking; with ~100 buckets tested, expect a few false positives, so a flag is a candidate for a separate paper variant, never a live change.

Data: 1304 closed scanner rows (587 clean, 17 artifacts excluded), 2206 exit-policy results (583 clean), 144 closed learning trades (47 clean), 668 scanner runs.

## 1. Exit policies (clean)

| policy | lane | clean: n / win% / avg / median | stress med (-2%) | all rows: n / median | rugs |
|---|---|---|---|---|---|
| BE15_TR25 | A | n= 25 win  12.0% avg  -43.07% med  -41.48% | -43.48 | 149 / -64.63% | 49 |
| BE15_TR25 | B | n= 32 win  15.6% avg  -48.98% med  -47.22% | -49.22 | 123 / -102.54% | 57 |
| HALF20_RUN | A | n= 26 win  11.5% avg  -42.10% med  -33.55% | -35.55 | 150 / -43.00% | 51 |
| HALF20_RUN | B | n= 34 win   8.8% avg  -45.64% med  -38.13% | -40.13 | 127 / -99.27% | 61 |
| HOLD15 | A | n= 39 win  33.3% avg   -2.16% med   -3.15% | -5.15 | 150 / -6.64% | 28 |
| HOLD15 | B | n= 38 win  55.3% avg  +25.77% med   +3.29% | 1.29 | 119 / -59.30% | 33 |
| HOLD60 | A | n=  3 win   0.0% avg -103.00% med -103.00% | -105.0 | 137 / -65.56% | 47 |
| HOLD60 | B | n=  2 win   0.0% avg -103.00% med -103.00% | -105.0 | 98 / -103.00% | 49 |
| LADDER_A | A | n= 41 win  26.8% avg  -24.42% med  -10.72% | -12.72 | 156 / -24.93% | 38 |
| LADDER_A | B | n= 38 win  21.1% avg  -41.42% med  -34.50% | -36.5 | 130 / -85.22% | 49 |
| LADDER_A(scanner) | A | n=276 win  18.5% avg  -23.11% med   -9.37% | -11.37 | 494 / -15.07% | 98 |
| LADDER_B(scanner) | B | n=178 win  18.5% avg  -48.64% med  -55.95% | -57.95 | 353 / -87.58% | 154 |
| LADDER_R(scanner) | R | n=133 win   3.0% avg  -69.41% med  -73.00% | -75.0 | 451 / -57.25% | 94 |
| QT20_S12 | A | n= 47 win  53.2% avg  -15.85% med  +17.00% | 15.0 | 153 / -21.29% | 39 |
| QT20_S12 | B | n= 67 win  55.2% avg  -14.80% med  +17.00% | 15.0 | 133 / -47.37% | 41 |
| TP30_S15_T30 | A | n= 45 win  53.3% avg  -13.29% med   +1.43% | -0.57 | 153 / -20.48% | 35 |
| TP30_S15_T30 | B | n= 64 win  54.7% avg  -12.63% med  +18.77% | 16.77 | 131 / -46.03% | 37 |
| TP50_S25 | A | n= 35 win  40.0% avg  -17.92% med  -30.43% | -32.43 | 155 / -48.90% | 49 |
| TP50_S25 | B | n= 47 win  44.7% avg  -17.07% med  -32.01% | -34.01 | 131 / -101.60% | 54 |

## 2. Learning-book strategies (clean closed)

- A-FULLPASS: n= 11 win  36.4% avg   -9.74% med   -3.21%
- A-FULLPASS-F: n=  5 win  20.0% avg   -1.49% med   -3.21%
- A-FULLPASS-V4: n=  1 win 100.0% avg  +27.00% med  +27.00%
- A-NEARMISS: n= 14 win  14.3% avg  -27.45% med  -26.79%
- A-NEARMISS-F: n=  6 win   0.0% avg  -46.79% med  -53.05%
- A-NEARMISS-V4: n=  3 win  33.3% avg  -20.28% med  -34.21%
- B-SHADOW: n=  7 win   0.0% avg  -56.55% med  -49.88%

## 3. Flagged bucket + policy combos (clean n>=30, median>0 and avg>0)

- **HOLD15 lane B | dex=pumpswap**: n= 38 win  55.3% avg  +25.77% med   +3.29%; halves median (5.06, -0.8); not robust (one half <= 0); all rows n=117 med -59.98%
- **HOLD15 lane B | repeat_veto=no_tag**: n= 38 win  55.3% avg  +25.77% med   +3.29%; halves median (5.06, -0.8); not robust (one half <= 0); all rows n=119 med -59.30%
- **HOLD15 lane B | dex=pumpswap & repeat_veto=no_tag**: n= 38 win  55.3% avg  +25.77% med   +3.29%; halves median (5.06, -0.8); not robust (one half <= 0); all rows n=117 med -59.98%

## 4. Best candidates (clean n>=30, ranked by median; single features and pairs)

By median (beware: a near-zero median with a very negative average = many flat trades plus a rug tail):
- TP50_S25 lane B | source=gt_trend: n= 30 win  53.3% avg  -15.16% med  +47.00%; halves median (47.0, -47.07)
- TP50_S25 lane B | filter_pass=F_block: n= 30 win  53.3% avg  -13.09% med  +47.00%; halves median (-34.79, 47.0)
- TP50_S25 lane B | dex=pumpswap & source=gt_trend: n= 30 win  53.3% avg  -15.16% med  +47.00%; halves median (47.0, -47.07)
- TP50_S25 lane B | dex=pumpswap & filter_pass=F_block: n= 30 win  53.3% avg  -13.09% med  +47.00%; halves median (-34.79, 47.0)
- TP50_S25 lane B | source=gt_trend & repeat_veto=no_tag: n= 30 win  53.3% avg  -15.16% med  +47.00%; halves median (47.0, -47.07)
- TP50_S25 lane B | filter_pass=F_block & repeat_veto=no_tag: n= 30 win  53.3% avg  -13.09% med  +47.00%; halves median (-34.79, 47.0)
- TP30_S15_T30 lane B | hour_et=18-24: n= 31 win  61.3% avg   -7.92% med  +27.00%; halves median (27.0, 27.0)
- TP30_S15_T30 lane B | source=gt_trend: n= 42 win  64.3% avg  -11.37% med  +27.00%; halves median (27.0, 27.0)
- TP30_S15_T30 lane B | filter_pass=F_block: n= 44 win  63.6% avg  -10.43% med  +27.00%; halves median (18.77, 27.0)
- TP30_S15_T30 lane B | age_h=<1h & source=gt_trend: n= 35 win  65.7% avg  -10.31% med  +27.00%; halves median (27.0, 27.0)

By average (what the bankroll actually earns):
- HOLD15 lane B | dex=pumpswap: n= 38 win  55.3% avg  +25.77% med   +3.29%; halves median (5.06, -0.8)
- HOLD15 lane B | repeat_veto=no_tag: n= 38 win  55.3% avg  +25.77% med   +3.29%; halves median (5.06, -0.8)
- HOLD15 lane B | dex=pumpswap & repeat_veto=no_tag: n= 38 win  55.3% avg  +25.77% med   +3.29%; halves median (5.06, -0.8)
- HOLD15 lane A | dex=pumpswap: n= 33 win  39.4% avg   -1.94% med   -3.32%; halves median (-13.92, -3.0)
- HOLD15 lane A | dex=pumpswap & repeat_veto=no_tag: n= 33 win  39.4% avg   -1.94% med   -3.32%; halves median (-13.92, -3.0)
- LADDER_A(scanner) lane A | age_h=>=7d & repeat_veto=no_tag: n= 48 win  16.7% avg   -1.97% med   -3.21%; halves median (-3.21, -3.61)
- HOLD15 lane A | repeat_veto=no_tag: n= 39 win  33.3% avg   -2.16% med   -3.15%; halves median (-3.32, -2.75)
- LADDER_A(scanner) lane A | vol5m=25-50k & age_h=>=7d: n= 49 win  16.3% avg   -2.56% med   -3.21%; halves median (-3.17, -3.36)
- LADDER_A(scanner) lane A | p1h_pct=<0 & age_h=>=7d: n= 36 win  19.4% avg   -3.11% med   -3.10%; halves median (-2.5, -3.46)
- LADDER_A(scanner) lane A | vol1h_liq=<2 & age_h=>=7d: n= 70 win  14.3% avg   -3.14% med   -3.21%; halves median (-3.12, -3.57)

## 5. Single-feature buckets for the lane A ladder (clean, n>=10)

- mcap: >=5M: n=58 med -3.2% avg -4.2%; 1-5M: n=31 med -8.7% avg -15.0%; 50-100k: n=80 med -22.3% avg -29.5%; 250k-1M: n=44 med -25.4% avg -25.6%; 100-250k: n=34 med -29.7% avg -31.0%; <50k: n=29 med -44.1% avg -38.9%
- liq: >=150k: n=82 med -3.2% avg -7.1%; 60-150k: n=88 med -8.0% avg -27.4%; 20-30k: n=31 med -30.7% avg -30.8%; 30-60k: n=37 med -31.4% avg -37.8%; <20k: n=38 med -35.0% avg -27.0%
- liq_mcap: >=.50: n=65 med -3.3% avg -35.9%; <.05: n=29 med -3.4% avg -5.6%; .05-.10: n=33 med -6.9% avg -14.4%; .10-.20: n=62 med -11.1% avg -19.2%; .20-.50: n=87 med -29.7% avg -25.6%
- vol5m: >=250k: n=57 med -3.1% avg -29.1%; 50-100k: n=69 med -7.1% avg -18.4%; 25-50k: n=116 med -9.4% avg -16.7%; 100-250k: n=34 med -36.0% avg -44.6%
- vol1h_liq: <2: n=87 med -3.4% avg -6.5%; >=20: n=62 med -11.2% avg -35.1%; 10-20: n=47 med -26.2% avg -29.4%; 2-5: n=44 med -28.2% avg -26.1%; 5-10: n=36 med -31.3% avg -30.8%
- vol5m_share_1h: .10-.20: n=80 med -6.8% avg -29.3%; .20-.35: n=53 med -6.9% avg -24.8%; <.10: n=61 med -9.6% avg -22.5%; >=.35: n=82 med -19.9% avg -16.4%
- p1h_pct: 0-25: n=75 med -3.3% avg -14.2%; <0: n=61 med -4.2% avg -11.6%; 50-100: n=61 med -26.2% avg -26.2%; 100-200: n=61 med -30.7% avg -38.3%; 25-50: n=18 med -32.8% avg -37.4%
- age_h: >=7d: n=82 med -3.3% avg -4.8%; 1-7d: n=11 med -14.2% avg -13.8%; 6-24h: n=22 med -18.4% avg -20.3%; 1-2h: n=38 med -29.0% avg -42.4%; <1h: n=113 med -30.7% avg -30.4%; 2-6h: n=10 med -33.5% avg -33.8%
- hour_et: 00-06: n=55 med -5.0% avg -26.0%; 18-24: n=69 med -7.0% avg -22.7%; 06-12: n=88 med -9.2% avg -19.7%; 12-18: n=64 med -21.9% avg -25.7%
- dex: raydium-clmm: n=27 med -3.2% avg -3.4%; meteora: n=11 med -3.2% avg -4.0%; raydium: n=14 med -6.8% avg -7.8%; pumpswap: n=219 med -25.2% avg -27.6%
- source: gt_vol24: n=29 med -3.2% avg -22.3%; gt_trend: n=184 med -6.2% avg -21.3%; ds_profiles: n=54 med -34.2% avg -27.1%
- clone: not_clone: n=143 med -6.5% avg -16.1%; clone: n=133 med -22.8% avg -30.6%
- filter_pass: F_pass: n=124 med -5.2% avg -12.3%; F_block: n=152 med -25.8% avg -31.9%
- repeat_veto: repeat: n=91 med -8.7% avg -25.1%; no_tag: n=185 med -9.6% avg -22.1%

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
