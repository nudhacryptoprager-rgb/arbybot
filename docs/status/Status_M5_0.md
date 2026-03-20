# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-20 (R29 cont'd — `strategy/quotes.py` staged extraction, same-session dashboard verification, fresh 72-run rolling evidence. 2084 tests PASS.)
**Tests**: 2084 passed / 14 skipped
**Schema**: start:long_scan_summary:v1.14, start:hot_loop_snapshot:v1.3
**Evidence runDirs**: R28.30: 10-min scan (60 runs, 6 chains, 660s wall). R28.28: 10-min scan (60 runs). R28.27: cap isolation.
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Strategy**: Funnel contract normalized: `opp_engine_combinations` replaces misleading `opp_candidates`, `cross_dex_pairs_count` added, 6-stage annotations. Hot cache writes atomically and preserves discovery_runtime provenance during hot re-quotes. Dashboard canonical protocol mandated (`dashboard_server` + `/api/hot`). `strategy/quotes.py` was partially decomposed into `strategy/quote_rpc.py`; the remaining quote-policy split is the next extraction target.

---

## R29 cont'd Quotes RPC Extraction + Same-Session Dashboard Verification

### Code Changes
1. **strategy/quote_rpc.py** — new low-level quote RPC module: shared web3/executor, multicall cache helpers, `read_slot0_v3`, `read_quoter_v2`, cache clear helpers.
2. **strategy/quotes.py** — imports extracted low-level helpers from `strategy.quote_rpc`; in-file shared-cache and basic V3 reader code removed. File size reduced from ~2006 to **1658** lines.
3. **tests/unit/test_start.py** — shared executor contract assertions moved to `strategy.quote_rpc`.
4. **tests/unit/test_quote_rpc_exports.py** — new compatibility tests protecting exports used by existing scanner code.

### Verification
- `py -3.11 -m pytest -q` → **2084 passed, 14 skipped**
- `py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict` → **PASS**
- Canonical online run: external `dashboard_server` + `start.py --no-dashboard`
- Same-session `/api/hot` verified: `schema=v1.3`, `is_test_session=false`, `total_runs=72`, `full_sweeps=18`, `hot_requotes=54`

### Fresh 10-min Scan Evidence
| Metric | Value |
|--------|-------|
| Wall time | 647.8s |
| Total runs | 72 |
| PASS / NO_DATA / FAIL / INFRA_FAIL | 23 / 10 / 39 / 0 |
| Included signals | 78 |
| Roundtrip evaluated | 57 |
| Profitable RT | 0 |
| Best RT | -25.38 bps |
| Pass chains | base, linea |
| Fail chains | arbitrum_one, zksync, mantle |
| Accepted fail | scroll |

### Current Blocker Readout
- **base**: quote-path blocked, but no longer “all quoters dead”; fresh rolling shows `real_quote_count=3`
- **arbitrum_one**: mixed coverage + economics; `cross_dex_pairs_count=2`, best RT still negative
- **linea**: strongest clean economics blocker; `real_quote_count=12`, best RT still negative
- **zksync**: thin-surface economics blocker
- **mantle**: liquidity/quality blocker with fragile RT path
- **scroll**: no real RT; candidate-only

---

## R28.30 Funnel Normalization + Signal-Loss RCA + Dashboard Protocol

### Code Changes (3 files)
1. **strategy/jobs/run_scan_real.py** — `filter_funnel` normalized: `opp_candidates` → `opp_engine_combinations` (with comment: pair×route×fee combinatorics, NOT downstream of spread_signals). Added `cross_dex_pairs_count` from discovery_runtime. 6-stage annotations (Stage 1: discovery → Stage 6: roundtrip profit).
2. **start.py** — Added 5 accumulated funnel productivity counters in `init_chain_stats()` and accumulation in `update_chain_stats()`: `funnel_quotes_attempted_total`, `funnel_quotes_fetched_total`, `funnel_spread_signals_total`, `funnel_rt_evaluated_total`, `funnel_rt_real_quote_total`.
3. **tests/unit/test_run_scan_real_purity.py** — Updated `opp_candidates` → `opp_engine_combinations`. Added 2 new tests: `test_filter_funnel_normalized_fields`, `test_start_funnel_accumulation_fields`.

### Normalized Filter Funnel (6-Stage Contract)
```
Stage 1 (Discovery): resolved_pairs, cross_dex_pairs_count
Stage 2 (Quote):     quotes_attempted, quotes_fetched, quarantined_skip, disabled_skip, missing_skip
Stage 3 (Spread):    spread_signals
Stage 4 (Engine):    opp_engine_combinations (pair×route×fee combos), opp_profitable_diagnostic
Stage 5 (Selection): rt_candidates_considered, rt_cross_dex, rt_lp_viable, rt_unique_pairs, rt_margin_filtered, rt_passed_to_eval
Stage 6 (Roundtrip): rt_evaluated, rt_real_quote, rt_profitable
```

### Signal-Loss RCA (Per-Chain, R28.30 scan)

**base**: resolved=15 → quotes_fetched=59 → spread_signals=0 → opp_engine_combinations=108 → rt_evaluated=0. **Main loss**: No cross-DEX spread signals despite 59 quotes. runtime_disabled=26 pools. The 108 opp_engine_combinations are NOT downstream of spread_signals — they represent all possible pair×route×fee combinatorics.

**linea**: resolved=11 → quotes_fetched=20 → spread_signals=4 → rt_evaluated=3 → rt_real_quote=1 → rt_profitable=0. **Main loss**: RT economics — best=-82.54 bps. SUSPECT_ACCOUNTING on 2 roundtrips (WSTETH/WETH, WEETH/WETH: extreme spread_bps but unreliable). Only WETH/USDC survives sanity → slippage 207.2 bps kills it.

**scroll**: resolved=5 → quotes_fetched=7 → spread_signals=2 → rt_lp_viable=0 → rt_evaluated=0. **Main loss**: LP fee gate blocks ALL candidates. SUSPECT_LIQUIDITY rejects (gas_estimate>3M, ticks_crossed>15 in fragile pools). NO_CANDIDATES status.

**arbitrum_one**: resolved=36 → quotes_fetched=9 → spread_signals=4 → rt_evaluated=0. **Main loss**: Hot requote mode — only 10 quotes attempted (cached surface). 4 signals but no cross-DEX candidates survive economics gate.

**mantle**: resolved=6 → quotes_fetched=7 → spread_signals=0 → rt_evaluated=1 → rt_real_quote=1 → rt_profitable=0. **Main loss**: PRICE_SANITY failures (16 of 41 attempted quotes). No spread signals but 1 RT evaluated from previous cycle state.

**zksync**: resolved=4 → quotes_fetched=7 → spread_signals=2 → rt_evaluated=1 → rt_real_quote=1 → rt_profitable=0. **Main loss**: Narrow surface (4 resolved pairs, 2 DEXes). Economics blocker.

### Dashboard Canonical Protocol (Mandatory)
Per lead directive (R28.30 step 2):
1. Start dashboard_server: `py -3.11 -m monitoring.dashboard_server --port 8099`
2. Run scan with `--no-dashboard`: `py -3.11 start.py --no-dashboard ...`
3. After scan: `Invoke-RestMethod http://127.0.0.1:8099/api/hot` as mandatory proof
4. /api/hot evidence: schema=hot_loop_snapshot:v1.3, 60 total_runs, 12 full_sweeps, 48 hot_requotes

### Accumulated Funnel Counters (Productivity DoD)
Per-chain totals across all runs in session:
| Chain | qt_attempted | qt_fetched | spread_sig | rt_eval | rt_rq |
|-------|-------------|-----------|-----------|---------|-------|
| arbitrum_one | 126 | 112 | 45 | 7 | 7 |
| base | 676 | 602 | 4 | 1 | 1 |
| linea | 272 | 200 | 40 | 30 | 10 |
| mantle | 413 | 72 | 0 | 10 | 10 |
| scroll | 238 | 70 | 20 | 0 | 0 |
| zksync | 175 | 70 | 20 | 10 | 10 |

### Pending
- **quotes.py extraction**: 1962 lines — next god-file target (lead step 4)
- **Discovery A/B audit**: Compare cross_dex_pairs_count across configs (lead step 7)
- **Short targeted runs**: Isolate specific signal-loss stages per chain (lead step 9)

---

## R28.29 Lead Audit: Dedup + Discovery Productivity Contract

### Code Fixes
1. **_env_flag_enabled dedup**: Moved canonical implementation to `core/env.py:env_flag_enabled()`. Both `strategy/quotes.py` and `strategy/jobs/run_scan_real.py` now import from core.env — eliminates drift risk for feature toggles.
2. **read_slot0_v3 dead code removed**: `strategy/infra.py` had a duplicate (no callers, no multicall cache). Canonical version remains in `strategy/quotes.py` (with multicall cache support). infra.py: 824→784 lines (-40).
3. **validate_universe RUNTIME_DEPENDENT warning**: Discovery-runtime configs now get explicit warning that TOKENS=0/PAIRS=0 means signal surface is entirely runtime-dependent. PASS still means schema-correct, but does NOT prove operational productivity.

### Discovery Productivity Contract
- 39 new tests in `tests/unit/test_discovery_productivity_contract.py`
- All 5 onboarding configs: validator-clean (PASS) + zero static pairs (TOKENS=0/PAIRS=0)
- RUNTIME_DEPENDENT warning present for all discovery-runtime configs
- `resolve_universe` stats tracking verified: `universe_source`, `discovery_runtime_pairs_count`, `strategy_mode`
- `env_flag_enabled` canonical identity test: both quotes.py and run_scan_real.py import the same function
- `read_slot0_v3` no-duplicate test: infra.py must NOT export it

### Key Insight (from Lead)
> onboarding configs are validator-clean but discovery-runtime-dependent; signal loss risk now sits primarily in scan_universe + quotes, not in YAML syntax.

### Pending
- **quotes.py extraction**: 1882 lines — next god-file target (issue #1)
- **Discovery A/B audit**: Compare resolved_pairs/cross_dex_pairs_count across onboarding configs (step 7)
- **10-min verification scan**: Pending for this session

---

## R28.28 God-File Extraction (run_scan_real.py → 5 strategy modules)

### Extraction Results
| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| run_scan_real.py lines | 1724 | 1371 | -353 (-20.5%) |
| Extracted modules | 0 | 5 | +5 |
| Total tests | 1979 | 2017 | +38 |
| Purity threshold | 1900 | 1500 | -400 lines headroom |

### New Modules
- `strategy/scan_universe.py` (~165 lines) — universe resolution
- `strategy/roundtrip_selection.py` (~110 lines) — candidate selection
- `strategy/dynamic_sweep_runtime.py` (~200 lines) — sweep orchestration
- `strategy/execution_probe.py` (~120 lines) — live execution probe
- `strategy/live_stream.py` (~95 lines) — operator candidate stream

### Verification Scan (10 min, 6 chains)
- 60 runs: PASS=7, NO_DATA=6, FAIL=47, INFRA_FAIL=0
- 61 signals, $68.95 net USDC, 0 profitable roundtrips
- Sweep gap: 16.33 bps (WETH/USDT @ $25, arbitrum_one)
- All extracted modules correctly invoked (hot_requote cache, sweep, selection visible in logs)

### Bug Fixes
1. `_us` NameError in `_emit_phase` → `stats.get("universe_source", "config")`
2. test_force_intent.py target updated: scan_universe.py
3. test_scan_universe mock path corrected

### Pending
- **Adapter expansion**: base ve33/aerodrome, zksync SyncSwap/SpaceFi
- **Market conditions**: sweep gap 16.33 bps, 0 profitable RT

---

## R28.26 Suppression Layer Isolation (4-Layer Ladder)

### Experiment Design
4-layer ladder, each 10-min scan across 6 chains (arb/zksync/base/mantle/linea/scroll):
- **L0**: ARBY_DISABLE_RUNTIME_SUPPRESSION=1 (all suppression OFF)
- **L1**: ARBY_DISABLE_RUNTIME_QUARANTINE=1 (quarantine OFF, runtime_disabled ON)
- **L2**: ARBY_DISABLE_RUNTIME_DISABLED=1 (runtime_disabled OFF, quarantine ON)
- **L3**: baseline (all ON)

### Results (aggregate, all 6 chains)
| Metric | L0 (all OFF) | L1 (quar OFF) | L2 (rtdis OFF) | L3 (baseline) |
|--------|-------------|----------------|-----------------|---------------|
| quotes_fetched | 241 | 233 | 244 | 233 |
| spread_signals | 29 | 53 | 31 | 58 |
| rt_real_quote | **7** | **13** | **7** | **12** |
| rt_profitable | **0** | **0** | **0** | **0** |
| quarantined_skip | 0 | 0 | 0 | 0 |
| runtime_disabled_skip | 0 | 147 | 0 | 147 |

### Key Findings
1. **Quarantine = ZERO impact**: quarantined_skipped=0 in all 4 layers, all 6 chains
2. **runtime_disabled = perf cache**: 147 pools are LIQUIDITY_ZERO cached. OFF = worse (L0=7 vs L3=12 rt_real_quote)
3. **0 profitable RT in ALL layers**: suppression NOT the cause of zero profitability
4. **base = quote-path blocker**: 0 rt_real_quote regardless of suppression (LIQUIDITY_ZERO=41)

### Pending
- **Hard caps isolation**: roundtrip_max_candidates, discovery_runtime_max_pairs, min_spread_bps in run_scan_real.py
- **LIQUIDITY_ZERO investigation**: 61 arb pools permanently zero-liquidity
- **Anchor refresh**: Prices stale since 2026-02-17

---

## R28.25 Lead Audit: Filter-Layer RCA + 10-Step Fix

### RCA Correction
R28.24 overclaimed "zero-profit = market efficiency, not infra bug." Lead audit (R28.25) corrects: **filter/quote-path funnel is a material blocker alongside market efficiency**. З 235 pool universe лише 63 usable quotes (27%) — multi-stage фільтрація (slot0 failures, runtime_disabled 3600s TTL, quarantine 300s, SUSPECT_LIQUIDITY, NOTIONAL_DRIFT, ALGEBRA_NEEDS_QUOTER) суттєво звужує поверхню до roundtrip evaluation.

### Code Changes (12 files)
1. **config/real_minimal.yaml** — +roundtrip_max_candidates=50, +roundtrip_top_n=15, discovery_runtime_max_pairs 20→30
2. **5× onboard configs** — aligned: target_usd_notional=150, paper_size_usd=150, min_spread_bps=5, +RT caps, +discovery=30
3. **start.py** — +last_filter_funnel, +last_roundtrip_truth_status in per-chain stats (propagated from scan_stats)
4. **strategy/quarantine.py** — probation mode: SUSPECT_LIQUIDITY uses 60s quarantine (vs 300s full)
5. **strategy/runtime_disabled.py** — per-error TTL: SUSPECT_LIQUIDITY=300s (vs 3600s default)
6. **m4/policy.py** — compute_status() +roundtrip_profitable_count param → returns roundtrip_truth_status
7. **m4/gates.py** — propagates roundtrip_truth_status to run_summary output
8. **strategy/quotes.py** — Algebra quoter failure: improved logging (ALGEBRA_QUOTER_FAILED at info level)

### 10 Steps (Lead Directive)
| Step | Description | Status |
|------|-------------|--------|
| 1 | Working mode: 10-min canonical runs | DONE (operational) |
| 2 | Filter funnel first-class artifact | DONE (start.py propagation) |
| 3 | Remove hardcoded early caps | DONE (explicit in all configs) |
| 4 | Align economics: all chains 150 USD / 5 bps | DONE |
| 5 | Elevate roundtrip_truth_status | DONE (policy.py + gates.py) |
| 6 | Suppression reform: probation mode | DONE (quarantine 60s, TTL 300s) |
| 7 | Ve33 for base | DONE (aerodrome excluded R28.24, slot0 ABI incompatible) |
| 8 | Algebra quote gap | DONE (globalState ≠ slot0, kept as filter loss) |
| 9 | Mantle/scroll DoD | PARTIAL (monitored by coverage scans) |
| 10 | Docs: filter-layer RCA | DONE (this update) |

### Pending
- **Verification scan**: 10-min multi-chain canonical run to measure filter funnel improvement
- **Anchor refresh**: Prices stale since 2026-02-17 (35 NOTIONAL_DRIFT rejects)

---

## Historical Rounds (R28.22 and earlier — condensed)

**R28.22 Live-Stream Truth Contract**: is_actionable field, spread_bps non-null, final_net_pnl_usd, dashboard actionable/diagnostic split. Fresh 30 runs verified.

**R28.22-cont Dashboard Operational Coherence**: WORKFLOW.md canonical run contract, stale banner, idle-state messaging. All rolling artifacts synchronized.

**R28.24-R28.23 Deep RCA + Config Regeneration**: Phantom spread analysis, filter funnel, 8 config regenerations, chain-specific RCA. Detailed evidence preserved in git history and superseded by R29/R29 cont'd current-state sections above.
**R28.22-cont-2 Per-Chain Targeted Fixes**: +14 tokens NO_USD_PRICE, zombie quarantine fix, 97.7-min bundle (406 runs). base 0→54 signals. mantle structural confirmed. arb slippage 500-9900 bps.

**R28.21-final Code Fixes**: Multicall batch chunking (arb 64.6s→32.4s), roundtrip contamination fix (SANE_RT_PNL_MIN=-500), +11 USD token prices, Algebra quoter timeout 10s→5s.

**R28.20**: warm_pool_cache fixes, reject_histogram+reject_samples in truth data, actionable_signals_count, mantle/scroll configs. 54-run online verification.

**R28.19**: best_net_pnl_bps sane filter fix (base 8e16 contamination), +8 regression tests, reject visibility in truth_report.

**R28.18**: Scroll price-truth fix (slot0 anchor unification), slot0 LIQUIDITY_ZERO gate, promotion contract enforcement. 43-run scan.

**R28.17**: SUSPECT_ACCOUNTING state, accumulation guard, 3-tier signal classification, COVERAGE truth-path parity. All chains reset to non-profitable.

**R28.16**: Phase-level visibility in live stream. Scanner emits ARBY_PHASE JSON lines. Dashboard phase badges. /api/hot endpoint.

**R28.15**: Live execution infrastructure (simulator, dex_dex_executor). Dormant in production. +38 tests.

**R28.14**: Benchmark chain (linea). Unified truth standard. Arb gap=3.25 bps (historical best).

**R28.13**: Truth contract alignment. hot_loop_latest.json schema. PairHotQueue. Cross-pair parallel quoter (8x speedup).

**R28.12**: DirtySetTracker, hot_loop_latest.json, WS block pass-through, truth_path_alignment.

**R28.11**: Hot re-quote loop + pair-level dashboard visibility. Dual-cycle architecture.

**R28.10**: Profit truth propagation chain. KPI separation. RCA: linea 0-fee pools, arb fee structure blocker.

**R28.7**: Economics engine. executable_candidates_count KPI. dynamic_sweep core. Gap 18→15 bps.

**R28.6**: RunDir collision fix (chain-scoped unique dirs). 0 collisions in parallel.

**R28.5**: Bounded parallel coverage. 37 runs/52 signals in 556s. 15s/run.

**R27**: Strategy shift — staged onboarding. Scroll nuri_v3 fix. ve33 adapter. Config audit (15 stale YAMLs deleted).

---

## Architecture Contract (R28.21 — unchanged)

> **Static-looking scans are caused by cache-backed discovery and a tiny surviving route surface; live-market target requires real-time quote refresh plus event-driven hot re-quote, not full registry RPC refresh every cycle.**

Live scanning operates with THREE refresh cadences:
1. **QUOTES/BLOCKS** (live RPC every cycle) — ✅ Working. `real_quote_count > 0` on signal-producing chains.
2. **HOT RE-QUOTE** (event-driven target) — ❌ Timer-based (`FULL_SWEEP_INTERVAL=5`), not WebSocket event-driven. `ws_connected=0`.
3. **REGISTRY/DISCOVERY** (periodic cold refresh) — ❌ Cache-backed (`pools_from_rpc=0` for all chains), no TTL.

**Artifact visibility (R28.21)**: `last_full_refresh_utc`, `last_hot_requote_utc`, `pools_from_cache`, `pools_from_rpc` now exposed in per_chain stats and hot_loop/long_scan artifacts.

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> **R28.26**: 4-layer ladder proves suppression NOT the surface killer. runtime_disabled = perf cache (147 LIQUIDITY_ZERO). 0 profitable RT in all layers. Next: hard caps.
> **R28.25**: Lead audit corrects filter-layer RCA. 10-step fix: config alignment, suppression reform, roundtrip_truth_status elevation.
> **R28.24**: Deep pipeline analysis. Phantom spread root cause. Filter funnel artifact. Config-driven RT caps.
> **R28.22**: Live-stream truth: is_actionable, spread_bps, dashboard split. Dashboard coherence.
> **R28.21**: Multicall batch chunking, roundtrip contamination fix, architecture contract (3 cadences).
> **R28.20**: Reject histogram in truth artifacts, actionable_signals_count, mantle/scroll configs.
> **R28.19**: Sane filter fix. Truth reclassification. All chains non-profitable.
> **R28.18**: Scroll price-truth fix. Promotion enforcement. LIQUIDITY_ZERO gate.
> **R28.17**: SUSPECT_ACCOUNTING. 3-tier signal classification. COVERAGE truth-path parity.
> **R28.16**: Phase-level visibility. ARBY_PHASE lines. /api/hot endpoint.
> **R28.15**: Live execution infrastructure (dormant). simulator + dex_dex_executor. +38 tests.
> R28.14-R25: See "Historical Rounds" section above for details.

---

## Chain Quality Classification (R28.26 — ladder evidence)

| Chain | Quality | Blocker | Key Metric (L3 baseline) |
|-------|---------|---------|------------|
| arbitrum_one | SIGNAL_PRODUCING | ECONOMICS + LIQUIDITY_ZERO | qt=98, sig=47, rq=8, prt=0, rtdis=61 |
| linea | SIGNAL_PRODUCING | ECONOMICS | qt=20, sig=4, rq=1, prt=0, rtdis=12 |
| zksync | SIGNAL_PRODUCING | ECONOMICS | qt=15, sig=2, rq=2, prt=0, rtdis=10 |
| base | INFRA_READY | QUOTE_PATH | qt=81, sig=2, rq=0, prt=0, rtdis=41 |
| mantle | SIGNAL_PRODUCING | ECONOMICS | qt=9, sig=1, rq=1, prt=0, rtdis=3 |
| scroll | CANDIDATE | DEAD_POOLS | qt=10, sig=2, rq=0, prt=0, rtdis=20 |

**R28.26 suppression ladder**: Disabling suppression does NOT improve any chain. runtime_disabled caches LIQUIDITY_ZERO pools (improving throughput).

**Rollout Queue**: arb → linea → zksync → base → mantle → scroll.

**Onboard Stage Configs**: See config/onboard_*.yaml (6 configs, all aligned to 150 USD / 5 bps in R28.25).

---

## Operational Contracts

```powershell
# Offline gate (deterministic, no secrets)
py -3.11 scripts/ci_m5_0_gate.py --offline --strict

# Online gate (requires RPC)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1

# Online with rolling refresh
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3 --refresh-rolling --refresh-rolling-strict --prune-keep 50

# Unit tests
py -3.11 -m pytest tests/unit -q

# Full CI pipeline
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

---

## Invariants Validated by Gate

| # | Invariant |
|---|-----------|
| 1 | `execution_enabled=false` (always in M5_0) |
| 2 | `current_block` consistent across artifacts |
| 3 | `chain_id` consistent across artifacts |
| 4 | `run_mode` consistent across artifacts |
| 5 | `quotes_total` consistent (scan == truth) |
| 6 | `schema_version` supported |
| 7 | No sentinel blocks (online only) |

---

## Current Blockers (R29 cont'd)

- **All chains**: `profitable_roundtrips=0`; no positive control exists on fresh same-session evidence.
- **Arb**: mixed coverage + economics. `cross_dex_pairs_count=2`, `best_roundtrip_net_bps=-25.38`.
- **Base**: quote-path blocked. `cross_dex_pairs_count=15`, `real_quote_count=3`, but still no executable spread frontier.
- **Linea**: cleanest economics blocker. `real_quote_count=12`, best RT still negative.
- **Mantle**: liquidity/quality blocker. Surface exists but is fragile and still non-profitable.
- **Scroll**: candidate-only. `real_quote_count=0`, no RT path yet.
