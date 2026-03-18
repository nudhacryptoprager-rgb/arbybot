# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one. Scan stack is productive in simulate-only mode. R28.18: Code fixes for scroll price-truth blocker (slot0 anchor unification + liquidity check), promotion contract enforcement, config tightening. 1940 tests.

## SESSION GOAL (2026-03-17, Session 10 Round 28.18)
**Goal**: R28.18 — Lead review directive: fix scroll price-truth blocker, tighten configs, enforce promotion contract. Fresh online evidence post-R28.17 guards.
**Prior (R28.17)**: Truth-quality discipline — SUSPECT_ACCOUNTING state, SANE_ROUNDTRIP_PNL_BPS_MAX=500 guard, 3-tier signal classification (diagnostic/real_quote/executable_profitable), COVERAGE truth-path parity, rolling protection. 1937 tests. No fresh online scans.

## 0) Meta
timestamp_utc: 2026-03-17T08:04:59Z
rolling_provenance: 2026-03-17T08:04:59Z (run_summary_latest.json — rolling unchanged, R28.18 is evidence + code-fix round)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260317_090447_596027
mode: CODE_FIX + FRESH_EVIDENCE
test_count: 1940 passed, 3 skipped
schema_version: start:long_scan_summary:v1.13

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.18: Fix scroll price-truth blocker (slot0 anchor unification + liquidity check), tighten configs, enforce promotion contract. Fresh online evidence post-fix. |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | executable_profitable=0 across ALL chains. arb/zksync/linea/base=PRIMARY_BLOCKER (all RT negative or suspect). mantle/scroll=CANDIDATE (0 signals, structural issues). Scroll PRICE_SANITY now catches dead pools (fix verified). |
| evidence_session_run_dirs | long_scan 6 chains 43 runs 578s (2026-03-18 batch) |
| primary_blocker_of_session | Zero executable_profitable across all chains. Code fixes (slot0 anchor, liquidity check, promotion guard) verified working. Scroll PRICE_SANITY_FAILED correctly rejects dead pools (WBTC/USDC observed=7303 vs anchor=68000). No chain yet produces profitable roundtrips under SANE_RT_PNL_MAX=500. |
| blocker_status_before | ACTIVE: scroll slot0 path bypassed price_sanity when anchor missing. Dead pools produced garbage prices. Promotion allowed ONE_LEG_ONLY chains. Debug-like config thresholds on scroll/mantle. |
| blocker_status_after | RESOLVED: slot0 uses upstream anchor_manager (unified). LIQUIDITY_ZERO secondary gate. Promotion requires realism+quality. Configs tightened (5000bps/500bps/15ticks). Verified with 43-run online scan. |
| start_metric | R28.17: 1937 tests, scroll PRICE_SCALE undetected (anchor bypass), debug configs |
| end_metric | R28.18: 1940 tests, scroll PRICE_SANITY catching dead pools, promotion contract enforced, 43 runs 578s fresh evidence |
| delta | +3 code fixes (quotes.py slot0 anchor + liquidity, start.py promotion), +2 config tightening (scroll + mantle), +3 tests, +logger fix, +43-run online scan |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R28.18 lead review directive (code fixes + config tightening + fresh online evidence)
change_summary:
  - CODE FIX: strategy/quotes.py — slot0 anchor unification. Replaced independent lookup_anchor_price_ci() with upstream anchor_price from anchor_manager. Previously, if pair had no entry in tokens_anchor_price dict, slot0 path silently SKIPPED price_sanity entirely (anchor=None → gate bypassed). Now uses same anchor_manager with fallbacks as quoter path. Root cause of scroll PRICE_SCALE violations on WBTC/USDC + WETH/USDC.
  - CODE FIX: strategy/quotes.py — slot0 liquidity check. Added secondary LIQUIDITY_ZERO gate in slot0 path. Primary gate at line ~1124 depends on multicall cache — if not cached, dead pools slip through to slot0 and return stale sqrtPriceX96.
  - CODE FIX: start.py — promotion contract enforcement. CONFIRMED_POSITIVE_CONTROL now additionally requires last_profit_realism_status != ONE_LEG_ONLY_DIAGNOSTIC AND last_quality_status != FAIL_QUALITY. Chains with diagnostic-only evidence or quality failures are capped at THIN_POSITIVE. +3 tests (1940 total).
  - CONFIG: config/onboard_scroll_stage1.yaml — tightened from debug to production-like. price_sanity_max_deviation_bps 10000→5000, suspect_spread_bps_hard 1000→500, quoter_max_ticks_crossed 40→15. Added missing anchor prices: WBTC_USDC=68000, USDC_USDT=1.0, USDC_DAI=1.0.
  - CONFIG: config/onboard_mantle_stage2.yaml — tightened. price_sanity_max_deviation_bps 10000→5000. Added missing anchor prices: WBTC_USDC=68000, USDC_USDT=1.0.
  - BUG FIX: start.py — logger NameError in update_chain_stats (R28.17 regression). logger.warning → print() (start.py uses print, not logger). Crash blocked all online scans.
  - OFFLINE VERIFICATION: 1940 tests pass, CI full pipeline ALL GATES PASS.
  - ONLINE VERIFICATION: 10-minute long scan, 43 runs, 6 chains, 578s. Scroll PRICE_SANITY now catching dead pools. executable_profitable=0.
touched_files:
  - strategy/quotes.py (slot0 anchor unification + liquidity check)
  - start.py (promotion contract enforcement + logger NameError fix)
  - config/onboard_scroll_stage1.yaml (tightened thresholds + anchors)
  - config/onboard_mantle_stage2.yaml (tightened thresholds + anchors)
  - tests/unit/test_start.py (+3 promotion contract tests)
  - docs/DEV_REPORT_LATEST.md (this file)
  - docs/status/Status_M5_0.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: **PASS** (1940/3)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (1940/3, all gates green, 24.4s)
py -3.11 start.py --config-list <all 6 chains> --hours 0.17 --cycles 3: **COMPLETED** (43 runs, 578s, long_scan_latest.json refreshed)

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/_latest.json (run_dir: ci_m5_gate_arbitrum_one_20260317_090447_596027)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-18T08:06:51Z, status=PASS, rq=4)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: WARN_QUALITY)
long_scan (REFRESHED — R28.18 post-fix scan):
  - data/runs/_rolling/long_scan_latest.json (schema: start:long_scan_summary:v1.13, 43 runs, 6 chains, 578s)

## 4) Key Results

```
# Fresh Long Scan (R28.18 — post-fix, v1.13, 10-minute run)
schema: start:long_scan_summary:v1.13
total_runs: 43
total_pass: 21
total_no_data: 7
total_fail: 15
total_included_signals: 288
total_net_usdc: 347.41 (paper)
total_profitable_roundtrips: 0         ← still zero across ALL chains
total_roundtrip_evaluated: 78
best_roundtrip_net_bps: -42.85        ← best sane RT negative (arbitrum, improved from -80.54)
best_measured_spread_gap_bps: 1236.22
benchmark_chain: None                  ← no chain qualifies
pass_chains: [zksync, linea]
fail_chains: [arbitrum_one, base, mantle, scroll]
accepted_fail_chains: [scroll]
unexpected_fail_chains: [arbitrum_one, base, mantle]

# 3-Tier Signal Classification (v1.13)
diagnostic_signals:      288     (raw spread detections, one-leg)
real_quote_signals:       56     (roundtrips with real DEX quotes)
executable_profitable:     0     (profitable + sane + real-quote)

# Per-chain details
arbitrum_one: PRIMARY_BLOCKER    runs=8  p/f/nd=7/1/0  sig=249  rq=28  prt=0/28  best=-42.85bps  quality=WARN realism=ROUNDTRIP_NOT_PROFITABLE
zksync:       PRIMARY_BLOCKER    runs=7  p/f/nd=7/0/0  sig=14   rq=13  prt=0/13  best=-180.55bps quality=WARN realism=ROUNDTRIP_NOT_PROFITABLE
base:         PRIMARY_BLOCKER    runs=7  p/f/nd=1/1/5  sig=4    rq=1   prt=0/9   best=None       quality=NO_DATA realism=ROUNDTRIP_NOT_PROFITABLE
linea:        PRIMARY_BLOCKER    runs=7  p/f/nd=7/0/0  sig=21   rq=14  prt=0/28  best=None       quality=WARN realism=ROUNDTRIP_NOT_PROFITABLE
mantle:       CANDIDATE          runs=7  p/f/nd=0/5/2  sig=0    rq=0   prt=0/0   best=None       quality=FAIL realism=ONE_LEG_ONLY_DIAGNOSTIC
scroll:       CANDIDATE          runs=7  p/f/nd=0/7/0  sig=0    rq=0   prt=0/0   best=None       quality=FAIL_QUALITY realism=ONE_LEG_ONLY_DIAGNOSTIC

# R28.18 FIX VERIFICATION
✓ slot0 anchor unification: scroll PRICE_SANITY now catches dead pools (WBTC/USDC observed=7303 vs anchor=68000 → REJECTED at 5000bps)
✓ slot0 liquidity check: secondary LIQUIDITY_ZERO gate active in slot0 path
✓ promotion contract: linea/base correctly PRIMARY_BLOCKER (not promoted to CONFIRMED with suspect accounting)
✓ scroll config: price_sanity_max_deviation_bps=5000 catching 11 PRICE_SANITY_FAILED per cycle (was passing undetected before)
✓ mantle config: tightened to 5000bps + WBTC_USDC/USDC_USDT anchors added
✓ logger fix: start.py update_chain_stats no longer crashes on suspect accounting path
```

## 4.1) Mantle Structural Analysis

```
Surface: 12 intent pairs, 4 cross-DEX (33.3%), 6 single-DEX, 2 no-pool
DEXes: agni_v3 (10 pairs), stratum (4 pairs)
stratum incremental cross-DEX: +0 (confirmed by warm_pool_cache --rank-dexes)
Suppression: drift_excluded=5/16 (31%), ALL 4 cross-DEX pairs have NOTIONAL_DRIFT_EXCLUDED on at least 1 direction
  USDC/USDT: drift 98% → 9805bps (both directions excluded)
  METH/WETH: drift 21% → 2148bps (excluded)
  WMNT/USDC: drift 66% → 6594bps (excluded)
  WETH/WMNT: drift 86% → 8555bps (excluded)
Signal path: discovery → 4 cross-dex pairs → drift exclusion → 0 surviving → signals_count=0
Verdict: STRUCTURAL CROSS-DEX DEFICIT + massive drift contamination. Not an economics problem — signal-formation failure.
Fix path: Need 3rd executable DEX with productive pairs OR fix notional drift on existing pairs.
```

## 4.2) Scroll Structural Analysis

```
Surface: 13 intent pairs, 9 cross-DEX (69.2%), 3 single-DEX, 1 no-pool — ADEQUATE
DEXes: nuri_v3 (11 pairs), sushiswap_v3 (10 pairs) — good overlap
PRICE_SCALE violations (M5 gate FAIL):
  WBTC/USDC @ sushiswap_v3:3000 → price=7330 (expected ~68000, factor ~9x low)
  WETH/USDC @ sushiswap_v3:10000 → price=41.22 (expected ~2050, pool nearly empty: out=2.01 USDC for 0.049 ETH)
  WETH/USDC @ sushiswap_v3:100 → price=1742 (low but within range)
  WETH/USDC @ nuri_v3:500 → price=2450 (reasonable)
  WETH/USDC @ nuri_v3:3000 → price=2303 (reasonable)
Other broken pools:
  USDC/DAI @ sushiswap_v3:500 → out=0.056 DAI for 100 USDC (should be ~100 DAI)
  USDC/USDT @ sushiswap_v3:500 → out=0.004 USDT for 100 USDC (pool dead)
  WETH/WBTC @ all → price=2.4e-05 to 7.4e-05 (pools have zero liquidity)
Verdict: Surface is adequate, but QUOTE-TRUTH/DIRECTION-SCALE failure on multiple pools. Not a DEX inventory problem.
Fix path: (1) Fix quote normalization between sushiswap_v3 and nuri_v3, (2) filter empty/broken pools, (3) tighten sanity thresholds from debug to production.
Config issue: onboard_scroll_stage1.yaml has debug-like thresholds (price_sanity_max_deviation_bps=10000, suspect_spread_bps_hard=1000, quoter_max_ticks_crossed=40).
```

## 4.3) Linea Analysis (positive control caveat)

```
5-cycle gate: PASS, 7 pairs, 17 quotes, 2 dexes, cross_dex=11
run_summary: profit_realism_status=ROUNDTRIP_NOT_PROFITABLE, profitable_roundtrips=0
best_net_pnl_bps: 4576.25 (FILTERED as suspect by SANE_RT_PNL_MAX=500)
best_measured_spread_gap_bps: 22.39
Amplification ratio: 4576/22.39 = 204x — clearly anomalous accounting
previous claim: "linea = confirmed positive control with 14 profitable RT" — now INVALID under R28.17 guards
Current truth: linea PRODUCES real-quote signals (rqc=8) but has ZERO executable-profitable signals.
Status: PRIMARY_BLOCKER (same as arb/zksync/base)
1 PRICE_SCALE warning: WETH/USDC price=0.001476 (likely inverted direction in one low-fee pool)
```

## 4.4) Execution Infrastructure Status (unchanged)

```
execution_truth_mode: SIMULATE_ONLY (paper profit)
live_execution_wired: true (dormant probe in scanner, gated by config)
live_execution_active: false
realized_pnl_produced: false
```

## 5) Contract Checks
- long_scan_latest.json schema v1.13 — VERIFIED (43 runs, 578s, R28.18 post-fix scan)
- slot0 anchor unification — VERIFIED (scroll PRICE_SANITY_FAILED catches dead pools: WBTC/USDC observed=7303 vs anchor=68000)
- slot0 liquidity check — VERIFIED (secondary LIQUIDITY_ZERO gate in slot0 path)
- promotion contract — VERIFIED (ONE_LEG_ONLY_DIAGNOSTIC chains capped at THIN_POSITIVE, not CONFIRMED)
- config tightening — VERIFIED (scroll: 5000bps/500bps/15ticks, mantle: 5000bps + anchors)
- logger fix — VERIFIED (start.py update_chain_stats no longer crashes on suspect accounting)
- total_profitable_roundtrips=0 across all 6 chains — VERIFIED (no false positives)
- executable_profitable=0 for all chains — VERIFIED (3-tier separation working)
- M4 safety contract: execution_enabled=false, kill_switch_active=true — MAINTAINED
- All profit numbers ($347.41 total_net_usdc) are PAPER/SIMULATED diagnostic — no executable opportunities

## 6) Blocker Classification

```
code_blocker: NONE (1940 tests PASS, CI all gates green)
R28.18_fixes_verified: YES (slot0 anchor, liquidity check, promotion contract, configs, logger)
truth_quality_blocker: PARTIALLY_RESOLVED (scroll dead pools now caught; still 0 executable profitable)
execution_blocker: HIGH (live execution dormant — no signer, no realized PnL)
per_chain_blockers:
  arbitrum_one: ECONOMICS (best_net=-42.85bps, 28 real quotes but negative margin — improved from -80.54)
  zksync: ECONOMICS (best_net=-180.55bps, 13 real quotes but deeply negative)
  base: NO_DATA (1 real quote, 5/7 runs NO_DATA, accounting_sane=false)
  linea: ACCOUNTING_ANOMALY (14 real quotes, 0/28 RT profitable, quality=WARN)
  mantle: STRUCTURAL (0 signals, 0 real quotes, quality=FAIL, ONE_LEG_ONLY_DIAGNOSTIC)
  scroll: PRICE_TRUTH (0 signals, 0 real quotes, quality=FAIL_QUALITY — PRICE_SANITY now catching 11/cycle)
```

## 7) What Lead Needs To Decide
1. **Scroll next step**: PRICE_SANITY now correctly rejects dead pools (11/cycle). Scroll has adequate surface (9/13 cross-DEX) but produces 0 surviving quotes. Next: investigate why ALL scroll slot0 prices fail sanity—are there ANY healthy pools on scroll? Or is every pool dead/broken?
2. **Mantle path**: 0 signals, 0 real quotes, ONE_LEG_ONLY_DIAGNOSTIC. stratum adds +0 cross-DEX. Is there a 3rd DEX candidate? Or maintenance hold?
3. **Arb economics trend**: best_net improved from -80.54 to -42.85 bps across runs. Still negative but trending. Continue monitoring or adjust fee/gas parameters?
4. **Base NO_DATA**: 5/7 runs NO_DATA, accounting_sane=false. Investigate RPC stability or pool coverage.
5. **Linea**: 14 rq, 0/28 RT profitable, quality=WARN. Was previously "confirmed positive control" before R28.17 guards. True status: produces signals but zero profit.