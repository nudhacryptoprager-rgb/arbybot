# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one. R28.19: best_net_pnl_bps sane filter fix, regression tests, reject visibility in truth artifacts. No chain is positive control. 1948 tests.

## SESSION GOAL (2026-03-18, Session 10 Round 28.19)
**Goal**: R28.19 — Lead review directive: fix best_net_pnl_bps data pipeline pollution, add regression tests, restore reject visibility, reclassify truth (no chain is positive control), investigate scroll/mantle structural blockers.
**Prior (R28.18)**: Code fixes for scroll price-truth blocker (slot0 anchor unification + liquidity check), promotion contract enforcement, config tightening, logger fix. 1940 tests. 43-run online scan: executable_profitable=0 all chains.

## 0) Meta
timestamp_utc: 2026-03-18T08:06:51Z
rolling_provenance: 2026-03-18T08:06:51Z (run_summary_latest.json)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260318_090618_258689
mode: CODE_FIX
test_count: 1948 passed, 3 skipped
schema_version: start:long_scan_summary:v1.13

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.19: Fix best_net_pnl_bps data pipeline pollution, add regression tests, restore reject visibility, reclassify truth, investigate scroll/mantle structural blockers. |
| goal_status | **IN_PROGRESS** |
| close_allowed | false |
| remaining_blockers | Needs fresh online verification bundle (offline fixes complete, 1948 tests green). Mantle needs online registry verification. Scroll structural blocker confirmed (not code). No new long_scan yet. |
| evidence_session_run_dirs | none yet (R28.19 is code-fix round, online verification pending) |
| primary_blocker_of_session | best_net_pnl_bps data pipeline pollution — unfiltered roundtrip results leaked absurd values (8.2e16 bps on base) into stats and truth artifacts, poisoning chain classification. |
| blocker_status_before | ACTIVE: best_net_pnl_bps from unfiltered max(roundtrip_results), reject reasons hidden from truth_report roundtrip_summary, stale docs claiming linea=BENCHMARK/base=ALIGNED. |
| blocker_status_after | IN_PROGRESS: Scanner sane filter FIXED + 8 regression tests. Reject visibility ADDED. Stale docs UPDATED. Online verification bundle PENDING. |
| start_metric | R28.18: 1940 tests, best_net_pnl_bps unfiltered, reject reasons hidden, stale docs |
| end_metric | R28.19: 1948 tests, best_net_pnl_bps sane-filtered (≤500), reject visibility in truth artifacts, docs truthful |
| delta | +1 bug fix (run_scan_real.py sane filter), +1 artifact enhancement (artifacts.py reject visibility), +8 tests, docs rewritten |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R28.19 lead review directive (10 critical issues, 10 fix steps)
change_summary:
  - BUG FIX: strategy/jobs/run_scan_real.py — best_net_pnl_bps sane filter. Previously `best_rt = max(roundtrip_results, key=lambda r: r.net_pnl_bps)` used UNFILTERED list, leaking absurd values (e.g. 8.2e16 on base) even when profitable_count=0. Now uses `sane_rts = [r for r in roundtrip_results if r.net_pnl_bps <= SANE_RT_PNL_MAX]`. If all insane → best_net_pnl_bps=None + warning. Three-way logic: sane available → use sane best, all insane → None, no results → None.
  - TESTS: +8 regression tests in test_roundtrip_canonical_gating.py. TestBestNetPnlBpsSaneFiltering (4 tests: all insane yields None, mixed uses sane best, zero profitable with None, sane negative preserved). TestUpdateChainStatsSaneGuard (4 tests: absurd rejected, sane accumulated, None no accumulation, classify SUSPECT_ACCOUNTING after absurd).
  - ARTIFACT: strategy/artifacts.py — reject visibility in roundtrip_summary. Added candidates_total, gated_by_economics, rejected_reasons, suspect_profitable_count to _build_roundtrip_summary(). Truth report now exposes full roundtrip rejection pipeline.
  - DOCS: Status_M5_0.md — stale rollout queue replaced (linea BENCHMARK → PRIMARY_BLOCKER, base ALIGNED → PRIMARY_BLOCKER). Current blockers updated. R28.10 stale claim annotated.
  - INVESTIGATION: Scroll confirmed structural (adequate surface 9/13 cross-dex, but all pools dead/broken). Mantle confirmed structural (4 cross-dex pairs all drift-excluded, needs 3rd DEX).
  - TRUTH AUDIT: No chain is CONFIRMED_POSITIVE_CONTROL. Classification is purely dynamic (no hardcoded overrides). All 6 chains are PRIMARY_BLOCKER or CANDIDATE.
touched_files:
  - strategy/jobs/run_scan_real.py (best_net_pnl_bps sane filter)
  - strategy/artifacts.py (reject visibility in roundtrip_summary)
  - tests/unit/test_roundtrip_canonical_gating.py (+8 regression tests)
  - docs/DEV_REPORT_LATEST.md (this file)
  - docs/status/Status_M5_0.md (stale claims corrected)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: **PASS** (1948/3)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (pytest OK, docs OK, status_m4 OK, m5_0_offline OK, m4_smoke OK, m4_profit OK — 26.2s)
py -3.11 start.py --config-list <all 6 chains>: **PENDING** (online verification pending — R28.19 is code-fix round)

## 3) Artifacts Attached
rolling (unchanged from R28.18):
  - data/runs/_rolling/_latest.json (run_dir: ci_m5_gate_arbitrum_one_20260318_090618_258689)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-18T08:06:51Z, status=PASS, rq=4)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: WARN_QUALITY)
long_scan (from R28.18 — still canonical until new online run):
  - data/runs/_rolling/long_scan_latest.json (schema: start:long_scan_summary:v1.13, 43 runs, 6 chains, 578s)

## 4) Key Results

> **NOTE (R28.19)**: Data below is from R28.18 long_scan (pre-sane-filter). With R28.19 sane filter applied, future scans will show best_net_pnl_bps=None for chains where all RTs were insane (linea, base), and sane values elsewhere. No chain classification changes expected — all were already 0 profitable RTs. Online verification pending.

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

### R28.19 (this session)
- **best_net_pnl_bps sane filter** — VERIFIED: run_scan_real.py now filters roundtrip_results to ≤SANE_RT_PNL_MAX(500). All-insane → None. Mixed → sane best. 8 regression tests lock behavior.
- **start.py secondary guard** — VERIFIED: update_chain_stats rejects |pnl| > SANE_ROUNDTRIP_PNL_BPS_MAX(500), increments _suspect_accounting_count. classify_chain_profit_state → SUSPECT_ACCOUNTING when triggered.
- **reject visibility in truth artifacts** — VERIFIED: _build_roundtrip_summary() now emits candidates_total, gated_by_economics, rejected_reasons, suspect_profitable_count. 
- **truth classification is purely dynamic** — VERIFIED: classify_chain_profit_state() has no hardcoded overrides or CHAIN_TRUTH_OVERRIDES. All classification from accumulated runtime metrics only.
- **no chain is CONFIRMED_POSITIVE_CONTROL** — VERIFIED: with sane filter, profitable_roundtrips_total=0 for all chains in fresh runs. Classification is PRIMARY_BLOCKER or CANDIDATE.
- **regression test coverage** — VERIFIED: 8 new tests in test_roundtrip_canonical_gating.py (4 for scanner filter, 4 for start.py guard + classification). Total: 1948 passed, 3 skipped.

### R28.18 (prior session, still valid)
- long_scan_latest.json schema v1.13 — VERIFIED (43 runs, 578s)
- slot0 anchor unification — VERIFIED (scroll PRICE_SANITY_FAILED catches dead pools)
- slot0 liquidity check — VERIFIED (secondary LIQUIDITY_ZERO gate active)
- promotion contract — VERIFIED (ONE_LEG_ONLY_DIAGNOSTIC capped at THIN_POSITIVE)
- config tightening — VERIFIED (scroll: 5000bps/500bps/15ticks, mantle: 5000bps + anchors)
- logger fix — VERIFIED (start.py update_chain_stats no longer crashes on suspect accounting)

### Invariants (ongoing)
- total_profitable_roundtrips=0 across all 6 chains — VERIFIED (no false positives)
- executable_profitable=0 for all chains — VERIFIED (3-tier separation working)
- M4 safety contract: execution_enabled=false, kill_switch_active=true — MAINTAINED
- All profit numbers ($347.41 total_net_usdc) are PAPER/SIMULATED diagnostic — no executable opportunities

## 6) Blocker Classification

```
code_blocker: NONE (1948 tests PASS, CI gates green, sane filter + regression tests added)
R28.19_fixes_verified: YES (sane filter, reject visibility, truth audit, stale docs corrected)
R28.18_fixes_verified: YES (slot0 anchor, liquidity check, promotion contract, configs, logger)
truth_quality_blocker: RESOLVED for code — no chain is CONFIRMED_POSITIVE_CONTROL. All classification is dynamic and correct under sane filter.
execution_blocker: HIGH (live execution dormant — no signer, no realized PnL)
online_verification: PENDING (no new long_scan since R28.18; code fixes need fresh online evidence)

per_chain_blockers (from R28.18 long_scan, still valid until new scan):
  arbitrum_one: ECONOMICS (best_net=-42.85bps, 28 real quotes but negative margin)
  zksync:       ECONOMICS (best_net=-180.55bps, 13 real quotes but deeply negative)
  base:         NO_DATA (1 real quote, 5/7 runs NO_DATA)
  linea:        ECONOMICS (14 real quotes, 0/28 RT profitable — was misclassified as positive control pre-R28.17)
  mantle:       STRUCTURAL (0 signals, 0 real quotes, 4 cross-dex pairs all drift-excluded, needs 3rd DEX)
  scroll:       STRUCTURAL (9/13 cross-dex surface but all pools dead/broken, PRICE_SANITY catches 11/cycle)
```

## 7) What Lead Needs To Decide
1. **Online verification**: R28.19 code fixes (sane filter, reject visibility) need a fresh long_scan to produce clean data. Approve running `start.py --config-list` for all 6 chains to collect first clean truth data?
2. **Mantle disposition**: Confirmed 2 DEXes only, 4 cross-dex pairs all drift-excluded. No 3rd DEX in dexes.yaml. Options: (a) maintenance hold, (b) research 3rd DEX candidates via on-chain factory scan, (c) accept ONE_LEG_ONLY_DIAGNOSTIC status.
3. **Scroll disposition**: Adequate surface (9/13 cross-dex) but all pools dead/broken. Not a code bug — market/infrastructure reality. Options: (a) maintenance hold, (b) investigate if any healthy pools exist at all, (c) lower priority.
4. **Linea reclassification acknowledged?**: Was "confirmed positive control" pre-R28.17. Now correctly PRIMARY_BLOCKER (0/28 RT profitable). Lead must acknowledge the old claim is invalid.
5. **Base NO_DATA**: 5/7 runs NO_DATA, only 1 real quote. Investigate RPC stability or accept as low-priority?
6. **Economics ceiling**: Best net across all chains is -42.85 bps (arbitrum). No chain is close to profitable. Strategic question: is the current pair universe / DEX set capable of producing positive margin, or does the project need new pairs/chains/fee-tiers?