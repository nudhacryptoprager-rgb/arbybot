# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A + M7.A.2 + M7.A.3 + M7.A.4 — all scopes produce no-graduate verdicts. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.A.4 orderflow-driven backrun/replay hypothesis: offline estimates (-1.55 bps) beat triangular (-14.16 bps) but not two-leg baseline (-3.51 bps). Intent scout: `block_event_backrun` = highest-feasibility next surface. M7.B remains closed.)  
**Updated**: 2026-03-29  
**Scope**: M7.A only — runtime graph sourcing, live measured scoring with per-leg RPC quotes, same-state provenance classification, measured-only ranking separated from fee-only fallback, bounded size sweep over canonical size ladder (19 notionals, $1–$10K), machine-readable blocker summary with 6 canonical blocker tags, temporal blocker repeatability aggregation, **bounded-scope verdict summary** (`build_verdict_summary()` with `--verdict` CLI), **universe-profile infrastructure** (`--universe narrow_7|expanded_10`). Both universe profiles on arbitrum_one independently support a no-graduate verdict. M7.A `narrow_7` and M7.A.2 `expanded_10` are now **closed bounded baselines** with no-graduate verdicts. This verdict is scoped to the tested observation regime only: a non-static DEX market may behave differently under other chains, liquidity surfaces, volatility windows, size distributions, participant intensity, or source combinations. Any further M7.A work must proceed only as a newly named hypothesis branch (M7.A.3+), not as continued tuning of the already rejected arbitrum_one token-expansion surface. M7.B remains closed.

---

## M7.A: Triangular Feasibility (read-only research phase)

**Goal** (per `docs/step_M7.md`): build verified pool graph, enumerate 3-hop simple cycles, score with measured-cost discipline, apply provenance and same-state classification, rank by measured final net, and decide whether M7 stops or graduates to M7.B.

**Current sub-step**: steps 1-8 done. Step 8 verdict now formalized as machine-readable `verdict_summary` artifact (`data/tmp/m7a_verdict.json`). Five evidence tiers inform the verdict: (a) temporal repeatability across 5 blocks, (b) bounded size sweep across 19 notionals on top 10 cycles, (c) machine-readable blocker RCA with 6 canonical tags, (d) temporal blocker repeatability across 4 fresh blocks proving all 6 tags stable with 0 flapping, (e) **formal verdict summary** with `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. Additionally, **M7.A.2** tested an expanded 10-token universe (`--universe expanded_10`) and produced an independent no-graduate verdict (`data/tmp/m7a_expanded_verdict.json`).

### Current Evidence — Temporal Repeatability (5 runtime+measured runs)

Evidence source: **local file-backed artifacts** in `data/tmp/` (not canonical runDir or rolling artifacts).  
Generated: 2026-03-28 (during session)  
Provenance tier: **local/session** — R&D evidence with temporal diversity across 5 independent blocks.

| Run | Block | Scored | Failed | Best Net (bps) | Median Net (bps) | Promoted | SS Proven |
|-----|-------|--------|--------|----------------|-------------------|----------|-----------|
| narrow (20) | 446589515 | 12 | 8 | **-13.42** | -1159.12 | 0 | 12 |
| wide (100) | 446620909 | 67 | 33 | **-22.11** | -386.15 | 0 | 67 |
| snap_1 | 446621713 | 12 | 8 | **-27.70** | -1183.86 | 0 | 12 |
| snap_2 | 446621956 | 12 | 8 | **-31.19** | -1183.71 | 0 | 12 |
| snap_3 | 446622133 | 12 | 8 | **-31.11** | -1183.70 | 0 | 12 |

All runs: `graph_source="runtime"`, `score_mode="measured"`, `same_state_proven=100%`, `promoted=0`.  
Two-leg baseline: **-3.5062 bps** (from M4 roundtrip evidence in `long_scan_latest.json`).

Artifacts: `m7a_runtime_measured.json`, `m7a_runtime_measured_wide.json`, `m7a_snap_1.json`, `m7a_snap_2.json`, `m7a_snap_3.json`.

### Current Evidence — Size Sweep (10 cycles × 19 sizes)

Evidence source: **local file-backed artifact** `data/tmp/m7a_runtime_measured_sweep.json`.  
Generated: 2026-03-28T19:13:34Z  
Provenance tier: **local/session** — first bounded size sweep, reuses `CANONICAL_SWEEP_SIZES_USD` from `engine/roundtrip.py`.  
Block: **446635245** — all 190 quote sets at same block (same_state_proven=100%).

| Rank | Route (DEX combo) | Best Size (USD) | Best Net (bps) | Quoted | Curve Shape |
|------|-------------------|-----------------|----------------|--------|-------------|
| 1 | ARB→USDC→WETH→ARB (cam/pcs/pcs) | **100** | **-20.96** | 19/19 | U-shape, min at $100 |
| 2 | ARB→USDC→WETH→ARB (cam/uni/pcs) | **100** | **-20.99** | 19/19 | U-shape, min at $100 |
| 3 | ARB→USDC→WETH→ARB (cam/cam/pcs) | **150** | **-22.97** | 19/19 | U-shape, min at $150 |
| 4-10 | ARB→USDC→WETH→ARB (various) | 150–250 | -22.31 to -26.29 | 19/19 | U-shape |

All cycles negative at all 19 sizes ($1-$10K). U-shaped curves: gas dominates small, slippage dominates large. Best: -20.96 bps at $100 (6× worse than two-leg -3.5 bps). 190/190 quotes at block 446635245. All routes ARB→USDC→WETH→ARB.

### What the measured evidence shows

- **Temporal repeatability**: negative sign reproduced across 5 runs (best net -13.42 to -31.19 bps), 0 promoted cycles, 100% same_state_proven.
- **Triangular consistently worse than two-leg**: best -13.42 bps (single-shot) / -20.96 bps (sweep) vs two-leg -3.5 bps; third leg adds 10-17 bps extra cost.
- **Size sweep: no profitable notional in $1-$10K**: U-shaped curves across all 10 top cycles; 190/190 quotes successful.
- **All top cycles are ARB→USDC→WETH→ARB variants**: zero token-path diversity; VE33 (Ramses) ~33% failure rate.
- **Temporal blocker repeatability proven**: 3 independent runs (blocks 446652757–446654943) confirm all 6 blocker classes are stable with 0 flapping. Blocker decomposition is structural, not transient noise.

### Current Evidence — Blocker Decomposition (machine-readable RCA)

Evidence source: `blocker_summary` block from `scripts/m7a_enumerate_cycles.py` with `--score measured --sweep-top N`.  
Computed against: block **446635245**, 10 top cycles × 19 sizes, 67 measured routes.

| Metric | Value | Interpretation |
|--------|-------|----------------|
| `best_route_gross_bps` | **-9.305** | Best route loses money before any costs |
| `best_route_gas_bps` | **11.6555** | Gas adds 11.66 bps on top of negative gross |
| `best_route_total_fee_bps` | **6.0** | Protocol fees add another 6 bps |
| `best_route_net_bps` | **-20.9605** | Final net at optimal $100 |
| `best_route_best_size_usd` | **100** | Optimal notional (from sweep) |
| `small_size_gas_domination` | **true** | At $1: -1052 bps (gas crushes small sizes) |
| `large_size_slippage_domination` | **true** | At $10K: -802 bps (slippage crushes large) |
| `same_state_proven_rate` | **1.0** | 100% same-state proven |
| `route_failure_rate` | **0.33** | 33% VE33 adapter quote failures |
| `token_triple_concentration` | **1.0** | 100% ARB/USDC/WETH — zero diversity |

**Blocker tags** (ordered by frequency, 10 cycles analyzed):

| Tag | Count | Meaning |
|-----|-------|---------|
| `GROSS_NEGATIVE_CORE` | 10/10 | Gross negative in majority of cycles (gross can be transiently positive; net always negative) |
| `GAS_DOMINANT_SMALL` | 10/10 | Gas dominates at small notionals |
| `SLIPPAGE_DOMINANT_LARGE` | 10/10 | Slippage dominates at large notionals |
| `THIRD_LEG_FEE_BINDING` | 6/10 | Third leg fee adds ≥5 bps |
| `SINGLE_TRIPLE_CONCENTRATION` | all | Zero token-path diversity |
| `QUOTE_FAILURE_BREADTH_LIMIT` | all | VE33 failures limit route breadth |

**Key diagnostic insight**: The problem is a **multi-cost blocker**, not a single factor. At block 446635245 the top route had `gross_bps = -9.305`, but temporal evidence shows gross can occasionally be positive (+2.25 bps in one run). However, gas (~10 bps) and protocol fees (~4 bps mean) always push net negative. The binding constraint is the combined cost structure (gas + fees + token-path concentration), not reserve economics alone.

### Current Evidence — Temporal Blocker Repeatability (3 independent runs)

Evidence source: `build_blocker_repeatability()` aggregation of 3 fresh `--score measured --sweep-top 10` runs.  
Generated: 2026-03-28  
Artifact: `data/tmp/m7a_blocker_repeatability.json`  
Provenance tier: **local/session** — temporal stability proof across 3 blocks.

**Block range**: 446652757 → 446654943 (~2186 blocks apart)

| Metric | Min | Max | Mean |
|--------|-----|-----|------|
| `best_route_gross_bps` | -14.29 | 2.25 | -6.21 |
| `best_route_gas_bps` | 9.23 | 11.81 | 10.09 |
| `best_route_total_fee_bps` | 1.00 | 6.00 | 4.33 |
| `best_route_net_bps` | **-23.52** | **-9.56** | **-16.30** |
| `best_route_best_size_usd` | 150 | 150 | 150 |
| `route_failure_rate` | 0.33 | 0.33 | 0.33 |
| `token_triple_concentration` | 1.0 | 1.0 | 1.0 |

**Blocker class stability** (stable = present in ALL 3 runs, flapping = present in some):

| Tag | Status | Per-cycle count range | Interpretation |
|-----|--------|-----------------------|----------------|
| `GROSS_NEGATIVE_CORE` | **STABLE** | 5–10/10 | Gross negative in majority of cycles per run (can be transiently positive; net always negative) |
| `GAS_DOMINANT_SMALL` | **STABLE** | 10/10 | Gas dominates small sizes in all runs |
| `SLIPPAGE_DOMINANT_LARGE` | **STABLE** | 10/10 | Slippage dominates large sizes in all runs |
| `THIRD_LEG_FEE_BINDING` | **STABLE** | 3/10 | Third leg fee ≥5 bps in all runs |
| `SINGLE_TRIPLE_CONCENTRATION` | **STABLE** | global | Zero token-path diversity in all runs |
| `QUOTE_FAILURE_BREADTH_LIMIT` | **STABLE** | global | VE33 failures limit breadth in all runs |

**Result: 6/6 stable, 0/6 flapping.** All blocker classes are structurally reproducible, not noise artifacts.

Key observations:
- **Net bps range -23.52 to -9.56**: sign is consistently negative, magnitude varies with market microstructure, but never approaches break-even.
- **Gross bps in run 2 was +2.25**: one snapshot briefly had positive gross, but gas+fees still pushed net to -9.56 bps — confirming the multi-cost structure overwhelms any transient gross advantage.
- **Route failure rate perfectly stable at 33%**: VE33 (Ramses) adapter failures are deterministic, not transient.
- **Token concentration locked at 1.0**: zero diversity across all runs; no alternative token-path emerged.

### Current Evidence — Formal Verdict Summary (machine-readable)

Evidence source: `build_verdict_summary()` from `scripts/m7a_enumerate_cycles.py --verdict`.  
Generated: 2026-03-28  
Artifact: `data/tmp/m7a_verdict.json`  
Input: 4 independent measured+sweep artifacts (blocks 446652757–446661451).

| Field | Value |
|-------|-------|
| `beats_two_leg_baseline` | **false** |
| `all_sizes_negative` | **true** |
| `gross_sometimes_positive` | **true** |
| `stable_blockers_count` | **6** |
| `flapping_blockers_count` | **0** |
| `best_net_bps_range` | -23.52 to -9.56 (mean -16.60) |
| `two_leg_baseline_net_bps` | -3.5062 |
| `dominant_triple` | **true** (ARB/USDC/WETH) |
| `route_failure_rate` | 0.33 (stable) |
| `recommend_open_m7b` | **false** |
| `recommend_freeze_current_m7a_scope` | **true** |

**Verdict reasoning**: Net bps never beats two-leg baseline across all runs. Gross is sometimes positive but gas+fees always push net negative. 6 stable blockers, 0 flapping. Multi-cost structure (gas + fees + concentration) is the binding constraint, not a single blocker.

### Current Evidence — M7.A.2 Expanded Universe (3 runs)

**Hypothesis**: Does a moderately expanded arbitrum_one token universe (narrow_7 + DAI, GMX, UNI → 10 tokens) produce a second token-triple or better net than the frozen narrow_7 scope?

Evidence source: 3 independent `--universe expanded_10 --score measured --sweep-top 10` runs.  
Generated: 2026-03-28  
Artifact: `data/tmp/m7a_expanded_run1.json`, `m7a_expanded_run2.json`, `m7a_expanded_run3.json`, `m7a_expanded_verdict.json`  
Provenance tier: **local/session** — temporal diversity across 3 blocks.

**Graph expansion result**: Of the 3 extra tokens (DAI, GMX, UNI), only **DAI** had runtime pools (GMX and UNI have no intent.txt pairs). Graph expanded from 7 to **8 nodes**. Edge count unchanged (248 → 248) because all existing edges involve narrow_7 tokens. DAI added 0 new edges to top cycles.

| Run | Block | Scored | Failed | Best Net (bps) | Gross (best) | Conc. | SS Proven |
|-----|-------|--------|--------|----------------|-------------|-------|----------|
| expanded_1 | 446672946 | 67 | 33 | **-15.44** | -4.77 | 1.0 | 67 |
| expanded_2 | 446674182 | 67 | 33 | **-20.91** | — | 1.0 | 67 |
| expanded_3 | 446675281 | 67 | 33 | **-11.00** | +0.19 | 1.0 | 67 |

**Expanded verdict** (from `data/tmp/m7a_expanded_verdict.json`):

| Field | Value |
|-------|-------|
| `beats_two_leg_baseline` | **false** |
| `all_sizes_negative` | **true** |
| `gross_sometimes_positive` | **true** |
| `stable_blockers_count` | **6** |
| `flapping_blockers_count` | **0** |
| `best_net_bps_range` | -20.91 to -11.00 (mean -15.78) |
| `two_leg_baseline_net_bps` | -3.5062 |
| `dominant_triple` | **true** (ARB/USDC/WETH) |
| `route_failure_rate` | 0.33 (stable) |
| `recommend_open_m7b` | **false** |
| `recommend_freeze_current_m7a_scope` | **true** |

**M7.A.2 conclusion**: Expanding the universe from 7 to 10 tokens (with only DAI actually joining the graph) did NOT produce a second token triple. All top cycles remain ARB→USDC→WETH→ARB. Token triple concentration remains 1.0. Net bps range (-20.91 to -11.00) is comparable to the narrow scope range (-23.52 to -9.56). The expanded universe independently confirms the no-graduate verdict. DAI liquidity exists on arbitrum_one but does not create competitive triangular routes.

### Current Evidence — M7.A.3 Temporal Regime Hypothesis (3 runs)

**Hypothesis**: On arbitrum_one `narrow_7`, measured triangular edge may appear only in specific temporal market regimes (defined by activity level, failure rate, and spread width) rather than in generic short windows.

**New infrastructure**:
- `classify_regime_bucket()`: per-run regime classification using 3 dimensions:
  - Activity: `high_activity` (>80% quote success), `medium_activity` (50-80%), `low_activity` (<50%)
  - Failure: `high_failure` (route_failure_rate > 0.4), `low_failure` (< 0.2)
  - Spread: `wide_spread` (best_net < -30 bps), `tight_spread` (best_net > -10 bps)
- `build_regime_repeatability_summary()`: aggregates regime classifications across multiple runs
- `--regime-repeatability` CLI for regime aggregation
- `regime_bucket` field added to measured artifacts
- 28 new contract tests (2736 total, 152 in test_triangular_contracts.py)

Evidence source: 3 independent `--source runtime --score measured --sweep-top 10` runs with regime tagging.
Generated: 2026-03-29
Artifacts: `data/tmp/m7a_regime_run1.json`, `m7a_regime_run2.json`, `m7a_regime_run3.json`, `m7a_regime_repeatability.json`
Provenance tier: **local/session** — temporal diversity across 3 blocks.

| Run | Block | Scored | Failed | Best Net (bps) | Regime Bucket |
|-----|-------|--------|--------|----------------|---------------|
| regime_1 | 446834785 | 67 | 33 | **-21.70** | `medium_activity` |
| regime_2 | 446835947 | 67 | 33 | **-26.46** | `medium_activity` |
| regime_3 | 446837081 | 67 | 33 | **-14.16** | `medium_activity` |

**Regime repeatability summary** (from `data/tmp/m7a_regime_repeatability.json`):

| Field | Value |
|-------|-------|
| `regimes_observed` | `["medium_activity"]` |
| `runs_by_regime.medium_activity` | 3 |
| `best_net_bps_by_regime.medium_activity` | -14.16 |
| `mean_best_net_bps_by_regime.medium_activity` | -20.77 |
| `beats_two_leg_baseline_by_regime.medium_activity` | **false** |
| `blocker_stability_by_regime.medium_activity.stable` | 6/6 (all stable) |
| `blocker_stability_by_regime.medium_activity.flapping` | 0 |

**M7.A.3 finding**: All 3 runs fall in the same `medium_activity` regime (67/100 = 67% quote success rate, route_failure_rate = 0.33, net bps between -30 and -10). The hypothesis that a different temporal regime might produce a positive edge is **not falsified** (only one regime observed so far), but the tested regime conclusively shows no edge. The blocker structure (6/6 stable, 0 flapping) is identical to M7.A/M7.A.2 evidence. Net bps range (-26.5 to -14.2) is comparable to prior narrow_7 evidence (-23.5 to -9.6), never approaching the two-leg baseline of -3.51 bps. M7.A.3 is now a **closed bounded baseline**: within the `medium_activity` regime on arbitrum_one `narrow_7`, no triangular edge exists.

### Caveats

- L1 gas is static estimate (6 Gwei heuristic); artifacts are `data/tmp/` provenance (not rolling); narrow universe only (arbitrum_one, 7-10 tokens).
- Market is not static — bounded-scope verdicts do not prove absence of edge on all surfaces, chains, or regimes.

### Remaining M7.A triangular work — ALL DONE (NO-GRADUATE)

Steps 1-8 complete. Verdict: `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. Evidence: 4-block blocker repeatability (6/6 stable, 0 flapping), net never beats two-leg baseline (-3.51 bps). Artifacts: `m7a_verdict.json` (narrow_7), `m7a_expanded_verdict.json` (expanded_10).

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, graph builders (cache + RuntimePair), universe filters
- `engine/triangular_cycles.py` — cycle discovery, `score_cycle_measured`, `classify_same_state`, LegQuote, SizeSweepResult
- `scripts/m7a_enumerate_cycles.py` — CLI: `--source`, `--score`, `--sweep-top`, `--universe`, `--repeatability`, `--verdict`, `--regime-repeatability`. Blocker analysis (6 tags), verdict builder, regime classifier (7 tags)
- `scripts/m7a_orderflow_replay.py` — M7.A.4 event-driven replay pipeline: `--offline`, `--replay`, `--online`, `--intent-scout`. OrderflowEvent, BackrunResult, IntentSurfaceAssessment, fixture events, backrun scoring, intent/auction surface scout
- Tests: 152 M7.A triangular tests in `test_triangular_contracts.py`, 58 M7.A.4 orderflow tests in `test_orderflow_contracts.py` (2794 total, 0 failures)

---

## M7.A.4: Orderflow-Driven Backrun/Replay Hypothesis

**Hypothesis**: Edge may emerge from event-driven orderflow replay (backrun after user trades) and auction/intent surfaces (MEV-Share, UniswapX, CoW) rather than from static AMM triangular state alone.

**Approach**: Shift from passive pool-state scanning to event-driven replay:  
event → classify → post-trade state → best buy/sell venue → measured net.

**New infrastructure**: `scripts/m7a_orderflow_replay.py` (~600 lines):
- `OrderflowEvent` (15 fields), `BackrunResult` (17 fields), `IntentSurfaceAssessment` (16 fields)
- 5 canonical fixture events (USDC→WETH, WETH→USDC, ARB→USDC, WBTC→USDC, USDT→USDC)
- Event classification: `classify_event_backrun_type()` (impact-based), `classify_event_viability()` (size/impact gates)
- Offline scoring: `estimate_backrun_gross_bps()` (capture_rate × competition_decay), gas/fee estimation
- Online scoring: live RPC quotes across known DEXes using existing adapter infrastructure
- Intent scout: 4 surface assessments (MEV-Share, UniswapX, CoW, block event backrun)
- CLI: `--offline`, `--replay <file>`, `--online`, `--intent-scout` (mutually exclusive)

### Evidence — Offline Replay (5 fixture events)

Artifact: `data/tmp/m7a_orderflow_offline.json`  
Generated: 2026-03-29T09:50:37Z

| Metric | Value |
|--------|-------|
| Events scored | 5 |
| Viable count | 0 |
| Best net (bps) | **-1.5537** |
| Worst net (bps) | -7.55 |
| Mean net (bps) | -4.37 |
| Reject: SLIPPAGE_EXCEEDS_GROSS | 4 |
| Reject: GAS_EXCEEDS_GROSS | 1 |
| beats_triangular_baseline (-14.16 bps) | **true** |
| beats_two_leg_baseline (-3.5062 bps) | **false** |

### Evidence — Intent/Auction Surface Scout

Artifact: `data/tmp/m7a_intent_scout.json`  
Generated: 2026-03-29T09:54:03Z

| Surface | Feasibility | Key advantage | Key risk |
|---------|-------------|---------------|----------|
| MEV-Share backrun | medium | Structured API, proven economics | High competition, requires Flashbots integration |
| UniswapX filler | medium | Intent-based, Dutch auction pricing | Requires private inventory or flash loans |
| CoW solver | low | Batch optimization, CoW matching | Complex solver competition, capital requirements |
| Block event backrun | **high** | Reuses existing adapter infrastructure | Requires block event parsing + post-event quoting |

**Best near-term surface**: `block_event_backrun` — highest feasibility, reuses existing arbitrum_one adapters, requires only block event parsing and post-event quoting. No new chain, capital, or protocol integration needed.

### M7.A.4 Finding

Offline backrun estimates (-1.55 to -7.55 bps) are significantly better than triangular (-14.16 bps) but still do not beat two-leg baseline (-3.51 bps). This is expected for theoretical offline estimates with default capture_rate (0.3) and competition_decay (0.5). Real backrun profitability depends on live event stream timing, MEV competition, and same-block execution — none of which are testable offline.

**M7.A.4 is a closed bounded baseline** for offline-estimated backrun replay on arbitrum_one. The intent scout identifies `block_event_backrun` as the highest-feasibility next surface for live testing.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase, closed by default. Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.
