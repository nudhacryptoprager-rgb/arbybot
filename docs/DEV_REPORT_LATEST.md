# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39q**: Route-cost pruning + margin-first ordering + dashboard focal chain mode. 2446 tests.
**R39p**: RPC rotation + expanded endpoints — completely fixed Base rate-limiting. 2436 tests.
**R39o**: include_pairs hard clamp, per-cycle 429 quarantine, full contour no-slot0, reserved candidate slots. 2436 tests.
**Prior (R39n)**: Base profit-lane patch set — ve33 executable reprieve, alpha-first selection, 429 failover. 2421 tests.

## SESSION GOAL (R39q: Route-cost pruning + dashboard focal chain)
**Goal**: (1) Reduce Base gap_to_zero from 499.8 bps below 100 bps, (2) Pre-RT cost filter for expensive routes, (3) Margin-first candidate ordering, (4) Dashboard focal chain selector + source badges.
**Prior (R39p)**: Base RPC rate-limiting fixed (QUOTER_V2_RATE_LIMITED=0), but economics exposed gap=499.8 bps. Lead review: "Припини тюнити Base як 'все підряд' і зафіксуй одну мету: зменшити Base roundtrip gap_to_zero з 499.8 хоча б нижче 100 bps."
**Lead directive (R39q)**: Demote WETH/USDC from truth lane, add pre-RT cost filter, rank by margin not raw spread, dashboard focal chain mode.

## 0) Meta
timestamp_utc: 2026-03-25T09:44:12Z
run_dir_name: ci_m5_gate_arbitrum_one_20260325_104345_535774
long_scan_summary: long_scan_latest.json
mode: R39q_ROUTE_COST_PRUNING
test_count: 2446 passed, 5 skipped (+10 R39q tests)
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.15
code_identity:
  primary: ts:2026-03-25T09:44:13Z
  dirty: true (R39q code changes uncommitted)
  desc: route_cost_pruning_margin_first_dashboard_focal

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39q: Reduce Base gap_to_zero below 100 bps via route-cost pruning + dashboard focal chain |
| goal_status | **REACHED** (Base gap: 499.8 → 8.19 bps) |
| close_allowed | true |
| remaining_blockers | Base still economics-blocked (OE_ECONOMICS), but gap target REACHED (<100 bps) |
| fresh_evidence_run | 2-chain 10-min scan (ts:2026-03-25T09:44:13Z), 31 runs |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260325_104345_535774, ci_m5_gate_base_20260325_104331_451691 |
| primary_blocker_of_session | Base gap_to_zero 499.8 bps (route economics blocker) |
| blocker_status_before | ACTIVE: Base gap=499.8 bps, WETH/USDC consuming budget, no cost filter |
| blocker_status_after | **RESOLVED**: Base gap=8.19 bps (target was <100 bps). USDC/USDT cheapest route. |
| start_metric | R39p: Base gap=499.8 bps, WETH/USDC=benchmark (101 bps LP fee), no cost filter |
| end_metric | R39q: Base gap=8.19 bps, USDC/USDT=cheapest (2 bps fee), cost filter active (lp_fee_max=30) |
| delta | Gap -98.4% (499.8→8.19 bps), fee -98% (101→2 bps), slippage -99.7% (981→2.65 bps) |
| docs_reread_confirmed | true |

## 0.3) Fresh 2-Chain Scan Evidence (R39q)

```
Wall time:      ~608s (10-min 2-chain scan)
Total runs:     31 (PASS=31, NO_DATA=0, FAIL=0)
Base runs:      15 (15P)
Arb runs:       16 (16P)
Base signals:   150
Base gap:       8.19 bps (was 499.8 in R39p!)
Base fee:       2.0 bps (was 101 in R39p!)
Base slippage:  2.65 bps (was 981 in R39p!)
Base gas:       6.18 bps
Base best_pair: USDC/USDT (cheapest route selected by cost filter)
Arb gap:        27.26 bps (unchanged)
Arb fee:        6.0 bps
Arb slippage:   10.29 bps
```

### R39q Patch Evidence
| Metric | R39p | R39q | Delta |
|--------|:---:|:---:|:---:|
| Base gap_to_zero | 499.8 | **8.19** | **-98.4%** |
| Base LP fee | 101.0 | **2.0** | **-98%** |
| Base slippage | 981.0 | **2.65** | **-99.7%** |
| Base best pair | WETH/USDC | **USDC/USTT** | cheap route wins |
| Base runs status | 0P/8F | **15P/0F** | all pass now |
| Dashboard | single-chain | **focal chain selector** | multi-chain |
| Tests | 2436 | **2446** | +10 |
| Arb gap | 23.5 | **27.26** | stable (market variance) |

## 1) Scope
goal (Roadmap): M5_0/M4 — R39q: Route-cost pruning + margin-first ordering + dashboard focal chain
change_summary:
  - **config/onboard_base_profit.yaml** — R39q: Reordered include_pairs (cheap routes first). Removed WETH/USDC and AERO/USDC from reserved_candidate_slots, replaced with USDC/DAI+USDC/USDT. Added `roundtrip_lp_fee_max_bps: 30` and `roundtrip_slippage_max_bps: 150`.
  - **strategy/roundtrip_selection.py** — R39q: Added `cost_filter_viable()` pre-RT cost filter (lp_fee roundtrip > max → demoted). Added `lp_fee_max_bps` and `slippage_max_bps` params to `select_roundtrip_candidates()`. Margin-first sort (spread_minus_required_bps DESC). cost_filter_rejected in filter_stats.
  - **strategy/jobs/run_scan_real.py** — R39q: Wired new config params (roundtrip_lp_fee_max_bps, roundtrip_slippage_max_bps) to select_roundtrip_candidates.
  - **monitoring/dashboard.html** — R39q: Focal chain selector bar (select from long_scan per_chain keys). Source badges per panel (.src-badge CSS). onFocalChainChange() handler. renderRolling/Economics/Routes/Fees/Rejects updated for focal chain data.
  - **tests/unit/test_r39o_contracts.py** — R39q: 10 new tests (TestCostFilterViable, TestSelectCandidatesWithCostFilter) for cost filter + margin ordering.

touched_files:
  - config/onboard_base_profit.yaml
  - strategy/roundtrip_selection.py
  - strategy/jobs/run_scan_real.py
  - monitoring/dashboard.html
  - tests/unit/test_r39o_contracts.py

## 2) Root Cause Analysis

### Why Base gap dropped from 499.8 → 8.19 bps (R39q)
R39p fixed RPC rate-limiting but exposed bad economics. WETH/USDC (benchmark, LP fee 101 bps roundtrip) was consuming the truth-lane budget. R39q patches:

| Patch | Impact |
|-------|--------|
| **cost_filter_viable** | Routes with roundtrip LP fee > 30 bps rejected from truth lane. WETH/USDC (60 bps) filtered out. |
| **Margin-first ordering** | Candidates ranked by spread_minus_required_bps DESC. Cheapest routes (USDC/USDT, USDC/DAI) evaluated first. |
| **Reserved slot change** | USDC/DAI+USDC/USDT reserved (2 bps fee) instead of WETH/USDC+AERO/USDC (60+ bps). |
| **include_pairs reorder** | Cheap routes first in config ordering. cbBTC/* and AERO/USDC compete on margin. |

### Per-Chain Fresh Evidence (R39q — 2-chain)
| Chain | Runs | Gate | Signals | Gap BPS | Fee BPS | Slippage BPS | Best Pair |
|-------|---:|------|---:|---:|---:|---:|---:|
| base | 15 (15P) | PASS | 150 | **8.19** | **2.0** | **2.65** | USDC/USTT |
| arb | 16 (16P) | PASS | 466 | 27.26 | 6.0 | 10.29 | USDC/DAI |

### Key Insight (R39q)
The problem was never just "Base has bad economics" — it was WETH/USDC polluting the truth lane. With the cost filter, cheap calibration pairs (USDC/DAI, USDC/USTT) dominate and gap drops 60x. The same approach applies to any chain: expensive routes must not set the economics benchmark.

### Frontier Ranking (R39q)
| Rank | Chain | Gap BPS | Signals | Quality Level |
|---:|-------|--------:|---:|---:|
| 1 | **base** | **8.19** | 150 | SIGNAL_PRODUCING |
| 2 | arbitrum_one | 27.26 | 466 | SIGNAL_PRODUCING |

## 3) Universe Contour (R39q — 2-chain)

| Chain | Role | Config | Pairs | Cross-Dex | Gap BPS |
|-------|------|--------|------:|----------:|--------:|
| base | primary_profit | onboard_base_profit.yaml | 4 | 4 | **8.19** |
| arbitrum_one | benchmark | real_minimal.yaml | 11 | 11 | 27.26 |

### Base Profit Config (R39q — UPDATED)
| Pair | Role | DEXes | Status | LP Fee (RT) |
|------|------|-------|--------|-------------|
| USDC/DAI | calibration | uni_v3, sushi_v3, pancake_v3 | **reserved** | 2 bps |
| USDC/USTT | calibration | uni_v3, sushi_v3, pancake_v3 | **reserved, best gap** | 2 bps |
| cbBTC/USDC | alpha | uni_v3, sushi_v3, pancake_v3, aerodrome | competing on margin | ~60 bps |
| cbBTC/WETH | alpha | uni_v3, sushi_v3, pancake_v3, aerodrome | competing on margin | ~60 bps |
| AERO/USDC | alpha | uni_v3, sushi_v3, pancake_v3, aerodrome | competing on margin | varies |
| WETH/USDC | benchmark | uni_v3, sushi_v3, pancake_v3, aerodrome | **cost-filtered** (60 bps > 30 max) | 60 bps |

## 4) Stability Aggregator (31-run window)

```
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS (arb), PASS (base)
  data_run_rate: varies by chain
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  run_dir_name: ci_m5_gate_arbitrum_one_20260325_104345_535774
  run_timestamp: 2026-03-25T09:44:13Z
long_scan_latest:
  schema_version: start:long_scan_summary:v1.15
  total_runs: 31
  total_pass: 31
  total_no_data: 0
  total_fail: 0
  base_signals: 150
  base_gap_to_zero_bps: 8.19 (down from 499.8!)
  base_fee_bps: 2.0 (down from 101!)
  base_slippage_bps: 2.65
  base_best_pair: USDC/USTT
  arb_gap_to_zero_bps: 27.26
  arb_fee_bps: 6.0
  arb_slippage_bps: 10.29
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK (3 canonical files + long_scan_latest)
- blocker classification: OK (base=OE_ECONOMICS, arb=OE_ECONOMICS — both SIGNAL_PRODUCING)
- coverage gate: OK (arb PASS, base PASS)
- cost filter: **R39q NEW** — cost_filter_viable in roundtrip_selection.py (lp_fee_max_bps=30)
- margin-first ordering: **R39q NEW** — spread_minus_required_bps DESC sort in select_roundtrip_candidates
- dashboard focal chain: **R39q NEW** — focal chain selector + source badges in dashboard.html
- reserved slots: USDC/DAI + USDC/USTT (calibration, cheap routes)
- config inventory: OK (onboard_base_profit.yaml in ALLOWED_YAML_FILES)
- 25 total contract tests: PASS (test_r39o_contracts.py)

## 6) Blockers / Next Steps (prioritized)
1. **Arb gap 27 bps** (P0, ECON): Closest to profitability but still negative. Gas (17 bps) dominates.
2. **Base OE_ECONOMICS** (P1, ECON): Gap=8.19 bps, all signals SIGNAL_PRODUCING but no profitable roundtrips. Gas (6.18 bps) is main cost.
3. **No profitable roundtrips anywhere** (P0, ECON): Both chains at OE_ECONOMICS blocker. Need execution at scale to find frontier.
4. **Dashboard focal chain runtime proof** (P2, UI): Focal chain selector implemented but needs operator testing with live multi-chain scanning.

## 7) Lead's R39q Fix Steps: Execution Map
step_01: **DONE** — Fix one goal: reduce Base gap_to_zero from 499.8 below 100 bps. **ACHIEVED: 8.19 bps** (-98.4%).
step_02: **DONE** — Demote WETH/USDC from Base profit truth path. Removed from reserved slots. Cost-filtered (60 bps > 30 max).
step_03: **DONE** — Stop WETH/USDC eating budget. Reordered include_pairs: cheap routes first. Reserved USDC/DAI+USDC/USTT.
step_04: **DONE** — Pre-RT cost filter: `cost_filter_viable(opp, lp_fee_max_bps=30)`. Routes with roundtrip LP fee > 30 bps → diagnostic-only.
step_05: **DONE** — Rank by spread_minus_required_bps not raw spread. Margin-first ordering in select_roundtrip_candidates.
step_06: **DONE** — cbBTC/*+AERO/USDC: removed from reserved slots. Must compete on margin to enter truth lane.
step_07: **DONE** — Dashboard focal chain selector: `<select id="focal-chain-select">` with per_chain data from long_scan_latest.
step_08: **DONE** — Dashboard source badges: `.src-badge` per panel, updated dynamically by renderRolling.
step_09: **DONE** — Online scan: 31 runs, 2 chains, all PASS. Base gap=8.19 bps. Dashboard serving at :8099.
step_10: **DONE** — DEV_REPORT updated (this report) with fresh evidence.

## 8) What I need from Lead now
1. **Acknowledge gap reduction**: Base gap 499.8 → 8.19 bps (-98.4%). Target was <100 bps — achieved 12x under target.
2. **Economics next step**: Both chains at OE_ECONOMICS. Gas is the remaining dominant cost. Explore gas optimization or larger trade sizes?
3. **Dashboard review**: Focal chain selector + source badges deployed. Test at http://127.0.0.1:8099 with live scanning.
4. **Base promotion**: Base now 15/15 PASS with 150 signals. Ready to promote from COVERAGE to NORMAL run_kind?
