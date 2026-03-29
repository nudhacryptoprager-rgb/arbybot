# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.13 — all scopes produce no-graduate verdicts. M7.A.5.13 added stale/low-lag scored split metrics, fixed block_lag=0 falsy trap and events_scored_low_lag_ws contract mismatch. Stale subset beats M4 baseline (best_net_bps_stale: -2.20 > -3.51) but NO low-lag scored events exist yet. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B remains closed.)  
**Updated**: 2026-03-29  
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep ($1-$10K), 6 canonical blocker tags, temporal repeatability, verdict summary, universe profiles (`narrow_7|expanded_10`), orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, subgraph seed (blocked), gas decomposition, stale/low-lag split. M7.B remains closed.

---

## M7.A: Triangular Feasibility — Consolidated Evidence

Steps 1-8 done. Verdict: `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`.

### Evidence Summary (M7.A through M7.A.3)

| Sub-step | Scope | Runs | Best Net (bps) | Two-leg baseline | Verdict |
|----------|-------|------|----------------|------------------|---------|
| M7.A narrow_7 | 5 temporal + 10×19 sweep | 5+4 | -9.56 to -31.19 | -3.51 bps | NO-GRADUATE |
| M7.A.2 expanded_10 | +DAI/GMX/UNI → 8 nodes | 3 | -11.00 to -20.91 | -3.51 bps | NO-GRADUATE |
| M7.A.3 temporal regime | medium_activity regime | 3 | -14.16 to -26.46 | -3.51 bps | NO-GRADUATE |

**Key findings**: All cycles negative at all sizes. U-shaped cost curves (gas dominates small, slippage dominates large). 6/6 blockers stable, 0 flapping. All top cycles ARB→USDC→WETH→ARB (concentration=1.0). Route failure rate 33% (VE33/Ramses). Gross sometimes positive (+2.25 bps) but gas+fees always push net negative.

**Blocker tags** (all stable): `GROSS_NEGATIVE_CORE`, `GAS_DOMINANT_SMALL`, `SLIPPAGE_DOMINANT_LARGE`, `THIRD_LEG_FEE_BINDING`, `SINGLE_TRIPLE_CONCENTRATION`, `QUOTE_FAILURE_BREADTH_LIMIT`.

Artifacts: `data/tmp/m7a_verdict.json`, `m7a_expanded_verdict.json`, `m7a_regime_repeatability.json`.

### Caveats

Market is not static — bounded-scope verdicts do not prove absence of edge on all surfaces, chains, or regimes. L1 gas is static estimate; artifacts are `data/tmp/` provenance.

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, graph builders, universe filters
- `engine/triangular_cycles.py` — cycle discovery, `score_cycle_measured`, `classify_same_state`, SizeSweepResult
- `scripts/m7a_enumerate_cycles.py` — CLI: `--source`, `--score`, `--sweep-top`, `--universe`, `--repeatability`, `--verdict`, `--regime-repeatability`
- `scripts/m7a_orderflow_replay.py` — M7.A.4/M7.A.5 event-driven replay: `--offline`, `--replay`, `--online`, `--live-blocks N`, `--ws-live`, `--intent-scout`
- Tests: 152 in `test_triangular_contracts.py`, 341 in `test_orderflow_contracts.py`

---

## M7.A.4: Orderflow-Driven Backrun/Replay Hypothesis

**Hypothesis**: Edge may emerge from event-driven replay (backrun after user trades) rather than from static AMM triangular state.

**Infrastructure**: `OrderflowEvent` (15 fields), `BackrunResult` (23 fields), `IntentSurfaceAssessment` (16 fields). 5 fixture events, offline scoring, intent scout (4 surfaces).

**Offline evidence**: 5 events, best_net=-1.55 bps (better than triangular -14.16, worse than two-leg -3.51). Intent scout: `block_event_backrun` = highest feasibility surface.

**M7.A.4 is a closed bounded baseline** for offline-estimated backrun replay.

---

## M7.A.5: Live Block-Event Backrun Replay

**Hypothesis**: `block_event_backrun` on arbitrum_one may produce viable edge with real block events and live quotes.

**Infrastructure**: `fetch_recent_swap_events()` (chunked `eth_getLogs`), `normalize_swap_log()`, `score_backrun_live()` (two-pass buy/sell via `read_quoter_v2`). `--live-blocks N` CLI.

**Evidence — M7.A.5.1 (public RPC)**: 2 runs (100/500 blocks), best_net=-18.36 bps, 0 viable, all stale (mean_lag=218), GAS_EXCEEDS_GROSS on 15/15.

**Evidence — M7.A.5.2 (Alchemy RPC)**: 100 blocks, 20 events, best_net=-19.49 bps, 0 viable, all stale (mean_lag=59.55), 0 low-lag events. Alchemy resolves correctly but sequential pipeline bakes in lag.

**M7.A.5 combined verdict**: Surface NOT VIABLE via either public or Alchemy RPC. Bottleneck is sequential block-polling architecture, not RPC provider latency.

**CI gates**: 2821 passed, 6 skipped. 85 tests in `test_orderflow_contracts.py`.

---

## M7.A.5.3–5.5: WebSocket Streaming, Multicall Pruning, Actual-Pair Resolution (CLOSED)

**M7.A.5.3** (WebSocket-Triggered Same-Block Replay): ws-live streaming architecture NOT VIABLE. Quote pipeline ~2.3s per event, 9x over 250ms block budget. All events stale. CI: 2849 passed, 113 orderflow tests.

**M7.A.5.4** (Two-Stage Multicall Pruning): Hypothesis NOT VIABLE. Multicall pruning works (20% call reduction) but per-call RPC latency ~400ms is irreducible; even 1 call > 250ms budget. Closes all public RPC architecture paths. CI: 2869 passed, 133 orderflow tests.

**M7.A.5.5** (Actual-Pair Token Resolution): Proxy-pricing hypothesis CONFIRMED but IMMATERIAL. Resolved 100% of pairs, but most on-chain tokens are outside narrow_7 universe. Counter-venue absence causes QUOTE_FAILURE regardless. CI: 2887 passed, 151 orderflow tests.

---

## M7.A.5.6–5.7: Coverage Decomposition + Enrichment Infrastructure (CLOSED)

**M7.A.5.6**: Decomposed coverage gap — 80% events rejected at `TOKEN_NOT_ADMITTED`, confirming narrow_7 universe doesn't cover most live-traded tokens. 5 new reject reasons (13 total), 5 new BackrunResult fields (42 total), `_run_size_sweep()` 5-point ladder. When tokens ARE admitted, full pipeline works. CI: 2923 passed, 187 orderflow tests.

**M7.A.5.7**: Built enrichment infrastructure — on-chain ERC-20 enrichment (`symbol()`+`decimals()`), Chainlink oracle sanity rails, V3 pool-state extraction for local-sim. Admission source tracking (4 sources). 3 new BackrunResult fields (45 total). CI: 2950 passed, 214 orderflow tests.

---

## M7.A.5.8: Subgraph Seed + Gas Decomposition (CLOSED)

Subgraph pathway BLOCKED (The Graph 403). Admission 10%→100% came from M7.A.5.7 on-chain enrichment. Gas decomposition: L1 data ~80% (120 bps), L2 exec ~20% (30 bps). GAS_EXCEEDS_GROSS now 100% dominant. 4 new BackrunResult fields (49 total). Evidence: 100b, 16 events, all GAS_EXCEEDS_GROSS. CI: 2961 passed, 225 orderflow tests.

---

## M7.A.5.9: Token-Decimal-Aware Size & Gas Fix (CORRECTIVE)

Fixed 2 measurement bugs: (1) size bounds not decimal-aware (USDC `10^15` raw = $1B), (2) gas subtracted in ETH wei from token-native gross. Added `_normalized_bounds()` + `_gas_cost_in_token_wei()`. 4 new BackrunResult fields (53 total). Evidence: 100b, bps range [-4475, 0] (was [-200B, 0]). GAS_EXCEEDS_GROSS confirmed with correct denomination. CI: 2988 passed, 252 orderflow tests.

---

## M7.A.5.10: Stale-Gate + Zero-Liq + Provenance Fix (CORRECTIVE)

Fixed 3 issues: (1) stale-positive false viability → `REJECT_STALE_POSITIVE` (viable requires block_lag≤2), (2) zero-liq pools producing results → `REJECT_ZERO_LIQUIDITY`, (3) admission provenance misattribution. Added split summary fields (best_net_bps_any/executable). Evidence: 300b, 25 events, 0 scored, ZERO_LIQUIDITY=21 (84%) now dominant. CI: 3011 passed, 275 orderflow tests.

---

## M7.A.5.11: Active-Liquidity-Aware Coverage + Granular Rejects (CLOSED)

Coverage scan now distinguishes active (liquidity>0) from inactive pools. Added `REJECT_NO_ACTIVE_COUNTER_POOL` + `REJECT_ALL_POOLS_ZERO_LIQUIDITY` (17 rejects total). Pre-econ metrics: `active_coverage_rate`, `inactive_coverage_false_positive_rate`. live_state_metrics fix: early-reject results now get `same_state_class`.

Evidence: 300b, 25 events, 0 scored. `ALL_POOLS_ZERO_LIQUIDITY: 19, NO_ACTIVE_COUNTER_POOL: 2`. `active_coverage_rate: 0.76` but all rejected at local-sim zero-liq gate. Blocker confirmed as market structure (inactive pools). CI: 3036 passed, 300 orderflow tests.

---

## M7.A.5.12: Byte-Parsing Fix + Unified Coverage/Local-Sim Truth (BREAKTHROUGH)

**Root cause**: `batch_full_pool_data()` in `core/multicall.py` had byte-parsing bug: `d1[0:16]` read zero-padded MSB half of ABI uint128, always returning 0. Fix: `d1[0:32]`. This was the sole cause of `scored_results=0` in M7.A.5.8-5.11.

**Changes**: Unified pool state source (coverage + local-sim use one `batch_full_pool_data` call). 2 new rejects: `COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO`, `ALL_CANDIDATE_POOLS_TRULY_INACTIVE` (19 total). Per-pool debug block. Consistency metrics.

**Evidence**: 300b, 28 events, **26 scored** (was 0). `GAS_EXCEEDS_GROSS: 25`, `STALE_POSITIVE: 1` (+1987 bps, lag=1136), `coverage_local_mismatch_count: 0`, `quote_reachability_rate: 1.0`. However: **all 26 scored are stale** (block_lag >> 2). No low-lag scored evidence yet. CI: 3059 passed, 323 orderflow tests.

---

## M7.A.5.13: Stale vs Low-Lag Scored Split + Contract Fixes

**Hypothesis**: M7.A.5.12's 26/28 scored results are ALL stale — the project lacks truthful low-lag scored evidence. `events_scored_low_lag_ws` had a contract mismatch (counted all low-lag events, not just scored). Need explicit stale/low-lag split metrics.

**Bugs fixed**:
1. **block_lag=0 falsy trap**: `(r.block_lag or 999)` treats 0 as unknown (Python `0 or 999 == 999`). Fixed with `_lag(r)` helper using `is not None`.
2. **events_scored_low_lag_ws contract**: counted all low-lag events including unscored (TOKEN_PAIR_UNRESOLVED etc). Now filters through `UNSCORED_REJECTS` before counting.
3. **UNSCORED_REJECTS**: promoted to module-level frozenset (11 members) for reuse across ws-live and live-blocks paths.

**New metrics** in `build_replay_summary()`:
- `events_detected_low_lag` / `events_scored_low_lag`: detection vs scoring split
- `best_net_bps_stale` / `best_net_bps_low_lag_scored` / `mean_net_bps_stale` / `mean_net_bps_low_lag_scored`: per-class economics
- `stale_low_lag_comparison`: machine-readable block with `stale_scored_count`, `low_lag_scored_count`, `beats_m4_baseline_stale/low_lag` (baseline: -3.5062 bps)

**Evidence**:
- 300b: 23 events, 16 scored. `events_detected_low_lag: 7, events_scored_low_lag: 0` (all 7 low-lag had unscored rejects). `stale_scored_count: 16`, `best_net_bps_stale: -2.2002` (RAIN/WETH), `beats_m4_baseline_stale: true`, `beats_m4_baseline_low_lag: false`.
- 1000b: 12 events, 12 scored. `stale_scored_count: 12`, `best_net_bps_stale: -2.2002`, `beats_m4_baseline_stale: true`.
- `events_scored_low_lag_ws: 0` in both runs (contract fix verified — was counting 7 before fix).

**Key finding**: Stale subset beats M4 baseline (-2.20 > -3.51 bps) but NO low-lag scored events exist yet. Low-lag events are detected but all fail at pre-econ rejects (TOKEN_PAIR_UNRESOLVED, NO_COUNTER_POOL). Low-lag scored truth remains the gap.

CI: 3077 passed, 341 orderflow tests.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase, closed by default. Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.
