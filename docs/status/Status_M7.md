# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.25 + M7.R1 structural refactor — all scopes produce no-graduate verdicts. M7.R1 extracted M7 logic into `m7/` package. M7.A.5.25 corrects broken low-lag accounting: events_detected_low_lag was 0 due to using final-lag (block_lag) instead of detection-time-lag (event_detected_at_block - event_block). With fix: 100% same-block detection confirmed. Added PRICING_ANOMALY reject (21 reasons). Added hidden latency telemetry: registry_preload ~372ms, oracle ~101ms. Scoring pipeline still produces stale results; viable_count=0. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B closed.)  
**Updated**: 2026-04-02  
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep ($1-$10K), 8 canonical blocker tags, temporal repeatability, verdict summary, universe profiles (`narrow_7|expanded_10`), orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, subgraph seed (blocked), gas decomposition, stale/low-lag split, low-lag reject decomposition, low-lag debug diagnostic, pool-class truth, V2 direct resolve, low-lag watchlist, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, gas-floor prefilter, registry activation in ws-live, low-lag registry-direct scoring bridge, pipeline latency optimization, detection-time low-lag truth. M7.B remains closed.

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
- Tests: 152 in `test_triangular_*.py` (3 files), 447 in `test_orderflow_*.py` (9 files)

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

**M7.A.5.4** (Two-Stage Multicall Pruning): NOT VIABLE. Per-call RPC latency ~400ms irreducible; closes all public RPC paths. CI: 2869 passed.

**M7.A.5.5** (Actual-Pair Token Resolution): CONFIRMED but IMMATERIAL. 100% pairs resolved but most tokens outside narrow_7. CI: 2887 passed.

---

## M7.A.5.6–5.7: Coverage Decomposition + Enrichment Infrastructure (CLOSED)

**M7.A.5.6**: 80% events rejected at `TOKEN_NOT_ADMITTED`. 5 new reject reasons (13 total), 5 new fields (42 total). CI: 2923 passed.

**M7.A.5.7**: On-chain ERC-20 enrichment, Chainlink oracle, V3 pool-state for local-sim. 3 new fields (45 total). CI: 2950 passed.

---

## M7.A.5.8: Subgraph Seed + Gas Decomposition (CLOSED)

Subgraph BLOCKED (403). Gas decomposition: L1 data ~80%, L2 exec ~20%. GAS_EXCEEDS_GROSS dominant. 4 new fields (49 total). CI: 2961 passed.

---

## M7.A.5.9–5.11: Decimal Fix + Stale Gate + Active-Liquidity Coverage (CORRECTIVE, CLOSED)

**M7.A.5.9** (Token-Decimal-Aware Size & Gas Fix): Fixed 2 bugs: decimal-aware size bounds + gas denomination. 4 new fields (53 total). CI: 2988 passed.

**M7.A.5.10** (Stale-Gate + Zero-Liq + Provenance Fix): Fixed stale-positive false viability, zero-liq pools, provenance misattribution. Added REJECT_STALE_POSITIVE, REJECT_ZERO_LIQUIDITY. CI: 3011 passed.

**M7.A.5.11** (Active-Liquidity-Aware Coverage): Active vs inactive pool distinction. Added REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_ALL_POOLS_ZERO_LIQUIDITY (17 rejects). CI: 3036 passed.

---

## M7.A.5.12: Byte-Parsing Fix + Unified Coverage/Local-Sim Truth (BREAKTHROUGH)

**Root cause**: `batch_full_pool_data()` byte-parsing bug: `d1[0:16]` → `d1[0:32]`. Sole cause of scored_results=0 in M7.A.5.8-5.11. Unified pool state source. 2 new rejects (19 total). Evidence: 300b, **26 scored** (was 0), all stale. CI: 3059 passed.

---

## M7.A.5.13–5.15: Stale/Low-Lag Split + Reject Decomposition + Debug Diagnostic (DIAGNOSTIC, CLOSED)

**M7.A.5.13** (Stale vs Low-Lag Split): Fixed block_lag=0 falsy trap, low-lag counting, UNSCORED_REJECTS scope. Evidence: 300b 16 scored, best_net_bps_stale=-2.20 (beats M4). 0 low-lag scored. CI: 3077 passed.

**M7.A.5.14** (Low-Lag Reject Decomposition): 100% low-lag rejected at pre-econ stage. Multi-causal: TOKEN_PAIR_UNRESOLVED + NO_COUNTER_POOL + ALL_CANDIDATE_POOLS_TRULY_INACTIVE. CI: 3092 passed.

**M7.A.5.15** (Low-Lag Debug Diagnostic): Added `pair_unresolved_detail`, `low_lag_debug_rows`, `low_lag_coverage_truth`. Evidence: 300b 6 low-lag 0 scored. All `pool_read_failed`. Multi-causal blocker stack confirmed. CI: 3110 passed.

---

## M7.A.5.16–5.17: Pool-Class Truth + V2 Direct Resolve (DIAGNOSTIC + FIX, CLOSED)

**M7.A.5.16** (Pool-Class Truth): Classified low-lag pools into 3 structural classes: unsupported ABI (V2-like on V3 path), no counter-pool, inactive. Added `pool_contract_truth` field (55 total), `dex_family_guess`, 5 fine-grained `pair_unresolved_detail` causes. Evidence: multi-causal blockers (V2 ABI mismatch + NO_COUNTER_POOL + INACTIVE). CI: 3132 passed.

**M7.A.5.17** (V2 Direct Resolve): Added `pool_state_read_path` field (56 total), V2 `getReserves()` fallback bypassing `batch_token_info()` fee() revert. Evidence: V2 path implemented but 0 V2 pool events in sample windows — all low-lag hit NO_COUNTER_POOL via V3. Low-lag blocker unstable across windows. CI: 3151 passed.

---

## M7.A.5.18–5.19: Low-lag Watchlist + Blocker Tags + Quote-Fail Provenance + File Splits (DIAGNOSTIC + STRUCTURAL, CLOSED)

**M7.A.5.18** (Cross-Window Truth): Session-persistent `low_lag_watchlist` (per-pool entries across events), `blocker_tags` artifact block with 8 canonical tags. Evidence: blocker tags correctly vary per window (LOW_LAG_NONE_THIS_WINDOW in empty windows, NO_COUNTER_POOL/INACTIVE_POOL in others). 0 low-lag events scored. Still 56 fields, 19 rejects. CI: 3180 passed.

**M7.A.5.19** (Provenance + Splits): Quote-fail provenance (`quote_fail_stage/venue/exception_short` in `stage_latency`). CLI split: `cli.py` (340 lines) + `mode_ws_live.py` (854 lines). Test file split: `test_orderflow_contracts.py` → 9 files (≤995 lines), `test_triangular_contracts.py` → 3 files (≤932 lines). Still 56 fields, 19 rejects, 8 blocker tags. CI: 3183 passed.

---

## M7.A.5.20: Local-State-First Pricing (INFRASTRUCTURE)

**Hypothesis**: Local V3/V2 swap math applied to captured pool state may bypass remote quoter entirely, halving pipeline latency and enabling first positive-net scoring.

**Changes**: `m7/orderflow/v3_math.py` (NEW, ~260 lines): `compute_v3_swap_amount_out()` (single-tick V3), `compute_v2_swap_amount_out()` (V2 constant-product), `attempt_local_pricing()` orchestrator. 3 new BackrunResult fields (59 total): `local_pricing_attempted/used/failure_reason`. `scoring_parallel.py`: local pricing between Stage A and Stage B; Stage B skipped when local succeeds. `artifacts.py`: `low_lag_local_pricing` block (6 metrics).

**Evidence**: 300b: 30 events, 29/30 local pricing used (stale), best_net=+18.20 bps, mean_latency=1402ms (was ~3500ms), 1 low-lag 0 scored. 300b_b: 30 events, best_net=+13.45 bps. 1000b: 82 events, best_net=+7.77 bps, 6 low-lag 0 scored. Triangular: 67/100 measured, best_net=-16.22 bps.

**Key finding**: Local pricing works for stale events (first positive net bps observed: +18.20), pipeline latency halved. Low-lag events still blocked at coverage BEFORE reaching local pricing — `low_lag_local_pricing` correctly reports all zeros. Infrastructure progress, NOT profit progress: viable_count=0, best_net_bps_executable=null.

CI: 3212 passed, 476 orderflow + 152 triangular tests.

---

## M7.A.5.21: Factory-Driven Pool Registry + Adapter-Complete Pricing + Gas-Floor Prefilter (INFRASTRUCTURE)

**Hypothesis**: Low-lag same-chain scoring may unlock only after factory-driven pool discovery and adapter-complete local-state pricing replace narrow runtime discovery as the primary truth path. Gas-floor prefilter (measurement-first) quantifies how many events are structurally unprofitable due to gas alone.

**Changes**:
1. **`m7/orderflow/pool_registry.py`** (NEW, ~300 lines): Factory-driven persistent pool registry. `PoolRegistryEntry` with address, dex, adapter_type, fee, token_a/b, liquidity, sqrt_price_x96, tick, last_block. `PoolRegistry` session-scoped cache. `preload_pair()` queries V3/Algebra via `batch_get_pool` + `batch_full_pool_data`, V2 via direct `getPair` + `getReserves`. V2 state stored: reserve0 in sqrt_price_x96, reserve1 in tick. `lookup_pair()` O(1) cached. `_refresh_state()` for stale (>10 blocks) entries.
2. **`m7/orderflow/v3_math.py`** (MODIFIED): Added `compute_algebra_swap_amount_out()` (directional fee_zto/fee_otz dispatch). Rewrote `attempt_local_pricing()` for adapter-complete matrix: V3 → `compute_v3_swap_amount_out`, V2 → `compute_v2_swap_amount_out` (reserves from state), Algebra → `compute_v3_swap_amount_out` (with dynamic fee). Both buy and sell passes adapter-dispatched. Returns `pricing_path`: `"v3_local"|"v2_local"|"algebra_local"`.
3. **`m7/shared/constants.py`** (MODIFIED): Added `REJECT_GAS_FLOOR_EXCEEDED`, `GAS_FLOOR_BPS_ARBITRUM = 2.0`. ALL_REJECT_REASONS: 19→20. UNSCORED_REJECTS: 11→12.
4. **`m7/orderflow/contracts.py`** (MODIFIED): 6 new BackrunResult fields (59→65): `registry_pools_found`, `registry_pools_active`, `adapter_type_used`, `gas_floor_exceeded`, `gas_floor_bps`, `pricing_path`.
5. **`m7/orderflow/coverage.py`** (MODIFIED): Optional `pool_registry` parameter. Registry pool merging (deduped by address). `registry_pools_merged` in output.
6. **`m7/orderflow/scoring_parallel.py`** (MODIFIED): Registry preload, gas-floor prefilter (measure-only, NOT hard reject), new fields injected in both return paths.
7. **`m7/orderflow/artifacts.py`** (MODIFIED): `_build_adapter_histogram()`, `_build_pricing_path_histogram()`, `m7a521_registry_metrics` block (events_with_registry, total_registry_pools_found/active, gas_floor_exceeded_count, adapter_type_histogram, pricing_path_histogram).
8. **`tests/unit/test_orderflow_m7a521.py`** (NEW, ~370 lines): 32 tests. 8 existing test files updated (65 fields, 20 rejects, 12 unscored).

**Evidence**:
- 300b: 30 events, 29 scored, best_net=+23.59 bps, gas_floor_exceeded=25/30 (83%), adapter=v3_local:29, registry_pools=0 (opt-in, not instantiated in replay). Low-lag: 1 detected, 0 scored.
- 300b_b: 30 events, 29 scored, best_net=+3.68 bps, gas_floor_exceeded=16/30 (53%), adapter=v3_local:29. Low-lag: 1 detected, 0 scored.
- 1000b: 59 events, 57 scored, best_net=+14.40 bps, gas_floor_exceeded=41/59 (69%), adapter=v3_local:57. Low-lag: 2 detected, 0 scored.

**Key findings**: (1) Gas-floor measurement active: 53-83% of events exceed 2.0 bps gas floor — confirms gas remains dominant structural cost. (2) Adapter histogram: 100% v3_local on Arbitrum (expected — mostly UniswapV3 pools). (3) Registry pools=0 across all runs: registry is opt-in parameter, not yet instantiated in replay script; validates graceful degradation. (4) Local pricing continues to produce positive stale net bps (+3.68 to +23.59). (5) Low-lag events still blocked at coverage before reaching pricing — NO_COUNTER_POOL remains dominant low-lag blocker. (6) SUBGRAPH_API_KEY_REQUIRED persists as blocker tag.

CI: 3245 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.22: PoolRegistry Activation in ws-live + Gas-Floor Operational Filter (ACTIVATION)

**Hypothesis**: Low-lag same-chain scoring may unlock only after PoolRegistry is actually instantiated in ws-live mode and used as the primary counter-venue discovery source before NO_COUNTER_POOL rejection.

**Root cause addressed**: M7.A.5.21 built the registry infrastructure but never instantiated it in the ws-live pipeline — `events_with_registry=0` in all M7.A.5.21 evidence. M7.A.5.22 creates a session-scoped `PoolRegistry()` in `mode_ws_live.py` and passes it to every `score_backrun_live_parallel()` call.

**Changes**:
1. **`m7/orderflow/mode_ws_live.py`** (MODIFIED): `session_registry = PoolRegistry()` created after dex_configs loaded. Passed as `pool_registry=session_registry` to every scoring call. `registry_session_stats` (5 keys: preload_calls, cache_hits, pools_discovered, pools_active, unique_pairs_queried) added to artifact. `m7a522_hypothesis` string added.
2. **`m7/orderflow/scoring_parallel.py`** (MODIFIED): Gas-floor operational filter: after gas-floor measurement, if `_gas_floor_exceeded AND _preliminary_lag > 2`, early-reject with `REJECT_GAS_FLOOR_EXCEEDED`. Saves RPC budget for stale+uneconomic events.
3. **`scripts/m7a_orderflow_replay.py`** (MODIFIED): `PoolRegistry` re-export.
4. **`tests/unit/test_orderflow_m7a522.py`** (NEW, 22 tests): 5 test classes covering registry integration, gas-floor filter, re-export, field counts, artifact stats.
5. **No new BackrunResult fields** (still 65). **No new reject reasons** (still 20). **ALL_BLOCKER_TAGS still 8**.

**Evidence** (3 runs, all Arbitrum One ws-live):
- 300b: 27 events, 24 scored, best_net=-0.887 bps. **Registry: preload=12, cache_hits=36, pools_discovered=74, pools_active=62**. events_with_registry=26/27 (96%). NO_COUNTER_POOL=0 (was 2 in M7.A.5.21). Adapter: v3_local:14, none:13. Low-lag: 1 detected, 0 scored. Blocker: `LOW_LAG_V2_UNSUPPORTED`.
- 300b_b: 28 events, 27 scored, best_net=+1.53 bps. **Registry: preload=9, cache_hits=41, pools_discovered=77, pools_active=61**. events_with_registry=28/28 (100%). NO_COUNTER_POOL=0. Adapter: v3_local:22, none:6. Low-lag: 0.
- 1000b: 21 events, 21 scored, best_net=-2.20 bps. **Registry: preload=8, cache_hits=29, pools_discovered=65, pools_active=55**. events_with_registry=21/21 (100%). NO_COUNTER_POOL=0. Adapter: v3_local:15, none:6. Gas floor: 18/21. Low-lag: 0.

**Key findings**: (1) Registry ACTIVATED: 65-77 pools discovered per session (was 0 in M7.A.5.21). Cache hit ratio 3-4x of preload calls — session persistence working. (2) **NO_COUNTER_POOL eliminated**: 0 across all 3 runs (was 2 in M7.A.5.21). Factory discovery fills the counter-venue gap. (3) Gas-floor operational filter structurally present but **does not fire in ws-live mode**: `current_block == event.block_number` (same-block detection), so `_preliminary_lag ≈ 0`, never exceeds stale threshold. This is by-design: ws-live events are fresh at detection, become stale only DURING scoring. The filter will activate in batch/replay modes with lagged `current_block`. (4) Low-lag: 0-1 per window; LOW_LAG_V2_UNSUPPORTED blocker present when 1 detected. (5) Stale-only economics: GAS_EXCEEDS_GROSS remains dominant reject (21-25 per run); best_net ranges from -2.20 to +1.53 bps.

CI: 3267 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.23: Low-Lag Registry-Direct Scoring Bridge (SCORING BRIDGE)

**Hypothesis**: Low-lag same-chain scoring may unlock only if low-lag events are routed into adapter-specific local scoring via registry-direct path before any coverage-scan rejection.

**Root cause addressed**: M7.A.5.22 activated the registry (65-77 pools discovered), but low-lag events still died at the coverage scan because `coverage_complete` requires `quoter_v2` which V2 DEXes lack. Meanwhile, `attempt_local_pricing()` already supports V2 math directly — it doesn't need `quoter_v2`. The fix bypasses the RPC-heavy coverage scan for events where the registry already has active pools.

**Changes**:
1. **`m7/orderflow/scoring_parallel.py`** (MODIFIED): Low-lag fast path inserted between registry preload and coverage scan. If `preliminary_lag <= 2 AND registry_pools_active > 0`, builds synthetic coverage and local_sim from `PoolRegistryEntry.to_candidate_pool()` / `.to_pool_state()`, skips coverage scan entirely, goes directly to local pricing. Non-low-lag events (stale) continue through normal coverage path unchanged.
2. **`m7/orderflow/contracts.py`** (MODIFIED): New field `low_lag_scoring_path: Optional[str]` (values: None | "registry_direct"). BackrunResult now 66 fields.
3. **`m7/orderflow/mode_ws_live.py`** (MODIFIED): Session-persistent low-lag pair tracking (`_session_low_lag_pairs` dict) accumulates per-pair scoring outcomes across blocks using detection-time lag. `session_low_lag_pairs` list + `m7a523_hypothesis` string added to artifact.
4. **`m7/orderflow/artifacts.py`** (MODIFIED): New `m7a523_low_lag_fast_path` section with `low_lag_registry_direct_count` and `low_lag_registry_direct_scored_count`.
5. **`tests/unit/test_orderflow_m7a523.py`** (NEW, 19 tests): 5 test classes covering BackrunResult field contract, registry-direct fast path, artifact metrics, non-low-lag unchanged, session pair tracking.
6. **No new reject reasons** (still 20). **UNSCORED_REJECTS still 12**. **ALL_BLOCKER_TAGS still 8**.

**Evidence** (3 runs, all Arbitrum One ws-live):
- 300b: 30 events, **30/30 scored (100%)**, best_net=+43.24 bps. **All registry_direct, all local_pricing_used**. Registry: 116 discovered, 81 active. Rejects: GAS_EXCEEDS_GROSS:27, STALE_POSITIVE:3. 3 positive net events. Session pairs: 0 (detection tracking not yet active in run 1).
- 300b_b: 30 events, **30/30 scored (100%)**, best_net=+37.96 bps. **All registry_direct, all local_pricing_used**. 5 positive net events. Session pairs: 12 unique pairs, RAIN/WETH seen 5x.
- 1000b: 100 events, **99/100 scored via registry_direct**, 1 via coverage (ALL_POOLS_TRULY_INACTIVE). best_net=+32.01 bps. 9 positive net events (all STALE_POSITIVE). Registry: 168 discovered, 123 active, 37 cache hits. Session pairs: 39 unique, WETH/USDC seen 26x. Adapter: v3_local:29, v2_local:1.

**Key findings**: (1) **100% scoring rate via registry-direct path** — up from 0% events_scored_low_lag in M7.A.5.22. The coverage-scan bottleneck is completely bypassed. (2) **Local pricing via registry entries works across V3 and V2 adapters** — `attempt_local_pricing()` receives synthetic candidate_pools and pool_states from registry, dispatches to adapter-specific math. (3) **Positive net events detected (9/100 at +18-43 bps)** but all are STALE_POSITIVE (block_lag > 2 at scoring completion). The preliminary lag is ≈0 at scoring entry, but scoring itself takes 34+ blocks. (4) **Session pair tracking operational**: 39 unique pairs across 1000 blocks, WETH/USDC most frequent (26x). (5) **viable_count still 0**: positive_net + block_lag <= 2 required for viability. Scoring latency prevents any event from being "fresh" at completion. (6) **Next bottleneck** is scoring latency itself — events are fresh at detection but stale by scoring completion.

CI: 3286 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.24: Pipeline Latency Optimization (PIPELINE SLIM)

**Hypothesis**: The next meaningful target is not better stale scoring, but the first genuinely low-lag scored event through the registry_direct local-pricing path. Requires minimal pipeline (no size sweep, no Stage A multicall, no remote quoter for registry_direct), two-queue priority (low-lag first), mid-pipeline lag abort, and session prewarm.

**Root cause addressed**: M7.A.5.23 achieved 100% scoring rate via registry_direct, but ALL events are classified STALE at scoring completion (mean_block_lag=34+). Events are fresh at detection (preliminary_lag ≈ 0) but become stale DURING the ~2000ms scoring pipeline. The pipeline spends time on Stage A multicall (~400ms) and size sweep (multiple remote quoter calls) which are redundant for registry_direct paths.

**Changes**:
1. **`m7/orderflow/contracts.py`** (MODIFIED): Renamed field `low_lag_scoring_path` → `scoring_path` (semantic fix — was misleading since stale events also use it). BackrunResult still 66 fields.
2. **`m7/orderflow/scoring_parallel.py`** (MODIFIED, 6 changes): (a) Renamed `_low_lag_scoring_path` → `_scoring_path`. (b) Added `_is_low_lag = _preliminary_lag <= 2` flag. (c) Instant reject for low-lag + zero active pools (REJECT_ALL_POOLS_TRULY_INACTIVE). (d) Skip Stage A multicall for registry_direct (stage_a_ms=0.0). (e) ~90-line mid-pipeline lag abort block: if event was low-lag but becomes stale during scoring, returns partial result with computed economics. (f) Skip size sweep for registry_direct.
3. **`m7/orderflow/mode_ws_live.py`** (MODIFIED, 4 changes): (a) Session prewarm: preloads 6 core Arbitrum pairs (WETH/USDC, WETH/USDT, WETH/ARB, USDC/USDT, WETH/WBTC, ARB/USDC) at session start. (b) Two-queue priority: low-lag events (detection_lag ≤ 2) scored before stale events. (c) Renamed `low_lag_scoring_path` → `scoring_path` (2 refs). (d) Added `m7a524_hypothesis` to artifact.
4. **`m7/orderflow/artifacts.py`** (MODIFIED): Renamed filter reference, added `m7a524_pipeline_optimization` section with `mid_pipeline_abort_count` and `scoring_path_histogram`.
5. **`tests/unit/test_orderflow_m7a523.py`** (MODIFIED): Renamed 15 `low_lag_scoring_path` → `scoring_path` references.
6. **`tests/unit/test_orderflow_m7a524.py`** (NEW, 24 tests): 8 test classes covering field rename, two-queue priority, mid-pipeline abort, instant reject, artifact metrics, session prewarm, constants stability.
7. **No new reject reasons** (still 20). **UNSCORED_REJECTS still 12**. **ALL_BLOCKER_TAGS still 8**. **Field count still 66** (rename only).

**Evidence** (3 runs, all Arbitrum One ws-live):
- 300b: 30 events, 30/30 scored (100%). **All registry_direct, all mid_pipeline_abort=30**. best_net=-1.68 bps. mean_block_lag=209.53. mean_pipeline_ms=1927ms. stage_a_ms=0.0, stage_b_ms=0.0. 0 low-lag detected.
- 300b_b: 30 events, 30/30 scored (100%). **All registry_direct, all mid_pipeline_abort=30**. best_net=+1.01 bps (1 positive event). mean_block_lag=242.17. mean_pipeline_ms=2029ms. 0 low-lag detected.
- 1000b: 100 events, 100/100 scored (100%). **All registry_direct, all mid_pipeline_abort=100**. best_net=+154955 bps (pricing anomaly). 14 positive events (STALE_POSITIVE:14). mean_block_lag=459.85. mean_pipeline_ms=1527ms. 0 low-lag detected.

**Key findings**: (1) **Pipeline stages correctly skipped**: Stage A multicall (mean_stage_a_ms=0.0) and Stage B remote quoter (mean_stage_b_ms=0.0) both bypassed for registry_direct path. (2) **Mid-pipeline abort fires on 100% of events**: All events enter as registry_direct but become stale during local pricing; the abort catches them before Stage B would have wasted RPC budget. (3) **0 low-lag events detected** (artifact metric): This metric was subsequently found to be BROKEN — using final `block_lag` instead of detection-time lag (fixed in M7.A.5.25). Raw data shows `event_detected_at_block == event_block` for 100% of events (true same-block detection). (4) **scoring_path_histogram: {registry_direct}** in all runs — confirms all events route through optimized path. (5) **Positive events found**: best_net=+1.01 bps in run 2, 14 positive in 1000b (all STALE_POSITIVE). (6) **Pricing anomaly**: best_net=+154955 bps in 1000b is unrealistic — local pricing on low-liquidity pair (fixed in M7.A.5.25 with PRICING_ANOMALY reject). (7) **Next bottleneck**: Scoring pipeline latency (events are fresh at detection but stale by scoring completion), not event arrival latency.

CI: 3310 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.25: Detection-Time Low-Lag Truth + PRICING_ANOMALY + Hidden Latency Telemetry (CORRECTIVE)

**Hypothesis**: Executable progress requires correct detection-time low-lag accounting plus anomaly-safe local pricing. Without these, profit evidence remains diagnostically polluted — low-lag metrics report 0 when all events are genuinely detected at same-block, and absurd net_bps from thin-liquidity pairs mask real signal.

**Root causes addressed**:
1. **Broken low-lag accounting**: `events_detected_low_lag`, `same_block_count`, and all `_low_lag_all` metrics used FINAL `block_lag` (= `quote_finished_block - event_block`, includes 26-965 blocks of scoring time) instead of DETECTION-TIME lag (= `event_detected_at_block - event_block`, always 0 for ws-live). This made `events_detected_low_lag=0` when 100% of events are genuinely same-block-detected. Meanwhile, `session_low_lag_pairs_count` (which correctly used detection-time lag) reported 11/15/33, creating an irreconcilable contradiction.
2. **Pricing anomaly pollution**: `best_net_bps=+154955` in M7.A.5.24 1000b run came from local pricing on thin-liquidity pair with `size_valid_for_token=false`. No reject mechanism existed for absurd returns.
3. **Hidden pipeline latency**: No per-stage timing for admission, oracle, and registry preload — the dominant scoring bottlenecks were invisible.

**Changes**:
1. **`m7/orderflow/artifacts.py`** (MODIFIED): Added `_detection_lag(r)` helper (uses `event_detected_at_block - event_block`, returns 999 if either field is None). `_low_lag_all` now uses `_detection_lag(r) <= 2` (was `_lag(r) <= 2`). `positive_net_count_low_lag` uses detection-time lag. `stale_positive_count` retains final `_lag(r)` (correct for scoring-completion staleness).
2. **`m7/orderflow/mode_ws_live.py`** (MODIFIED): Added `_det_lag(r)` helper. `same_block_count`, `next_block_count`, `stale_count` in `live_state_metrics` now use detection-time lag (was `same_state_class`). `low_lag` subset uses `_det_lag(r) <= 2` (was `same_state_class in ("same_block", "next_block")`). `stale` subset uses `_det_lag(r) > 2`. `ws_low_lag_summary.same_block_count/next_block_count` use detection-time lag.
3. **`m7/shared/constants.py`** (MODIFIED): Added `REJECT_PRICING_ANOMALY = "PRICING_ANOMALY"`. ALL_REJECT_REASONS: 20→21. UNSCORED_REJECTS unchanged (12) — PRICING_ANOMALY is a scored reject.
4. **`m7/orderflow/scoring_parallel.py`** (MODIFIED): (a) PRICING_ANOMALY gate: `if abs(net_bps) > 10000` → reject with PRICING_ANOMALY (in both success path and mid-pipeline abort path). (b) Hidden latency telemetry: `admission_ms`, `oracle_ms`, `registry_preload_ms` injected into `stage_latency` dict (both normal and mid-pipeline abort paths).
5. **`tests/unit/test_orderflow_m7a524.py`** (MODIFIED): Added 7 tests: `TestPricingAnomalyReject` (4 tests: in ALL_REJECT_REASONS, not in UNSCORED, value, result), `TestDetectionTimeLag` (3 tests: same-block, different-from-final, artifact detection-time).
6. **12 existing test files updated**: All `len(ALL_REJECT_REASONS) == 20` → `== 21` (18 assertions). Test fixtures updated with `event_block`/`event_detected_at_block` fields to match detection-time lag semantics (~50 fixtures across 5 files).
7. **No new BackrunResult fields** (still 66). **ALL_BLOCKER_TAGS still 8**. **UNSCORED_REJECTS still 12**.

**Evidence** (3 runs, all Arbitrum One ws-live):
- 300b: 21 events, 21/21 scored, **events_detected_low_lag=21 (was 0)**, **same_block_count=21 (was 0)**. best_net=+14.05 bps. Rejects: GAS_EXCEEDS_GROSS:19, STALE_POSITIVE:2. PRICING_ANOMALY:0. Blocker tags: LOW_LAG_REMOTE_QUOTER_LATENCY + SUBGRAPH_API_KEY_REQUIRED (LOW_LAG_NONE_THIS_WINDOW no longer fires).
- 300b_b: 30 events, 30/30 scored, **events_detected_low_lag=30 (was 0)**. best_net=+66.62 bps. positive_low_lag=4. PRICING_ANOMALY:0.
- 1000b: 100 events, 100/100 scored, **events_detected_low_lag=100 (was 0)**. best_net=+66.62 bps. positive_low_lag=19. **PRICING_ANOMALY:4** (all SOL-paired, abs(net_bps)>10000, size_valid=false). Rejects: GAS_EXCEEDS_GROSS:77, STALE_POSITIVE:19, PRICING_ANOMALY:4.

**Hidden latency telemetry** (100-event sample):
- `registry_preload_ms`: mean=372ms, max=1235ms — **dominant hidden latency**
- `oracle_ms`: mean=101ms, max=141ms — significant fixed cost per event
- `admission_ms`: 0ms — instant (in-memory check)
- Combined pre-scoring latency: ~470ms before economics even begins

**Key findings**:
1. **M7.A.5.24 "event arrival latency bottleneck" diagnosis was WRONG**: Raw artifact fields prove `event_detected_at_block == event_block` for 100% of events. Events ARE detected at same block. The `events_detected_low_lag=0` metric was an artifact of broken accounting (using final lag, not detection-time lag).
2. **With detection-time fix, 100% of events are same-block-detected**: `same_block_count` jumps from 0 to N/N in all runs. `LOW_LAG_NONE_THIS_WINDOW` blocker tag correctly no longer fires.
3. **PRICING_ANOMALY gate catches 4/100 events** in 1000b run. All are SOL-paired thin-liquidity local pricing artifacts with `abs(net_bps) > 10000` and `size_valid_for_token=false`. Previously these inflated `best_net_bps` and positive counts.
4. **Registry preload is the primary hidden latency bottleneck** at ~372ms mean (max 1235ms). Oracle adds ~101ms. Combined ~470ms of pre-scoring latency pushes events from fresh to stale DURING scoring — but detection IS fresh.
5. **viable_count remains 0**: All positives are STALE_POSITIVE (stale at scoring completion, even though detected at same block). The path to viability requires reducing scoring pipeline time to < block_time_ms (250ms on Arbitrum).
6. **Discovery is solved**: `registry_direct=100%` confirms factory-driven pool discovery works. Stop investigating discovery.

CI: 3317 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.R1: Structural Refactor — Extract m7/ Package (COMPLETED)

**Goal**: Extract all M7 logic from monolithic scripts into a dedicated lowercase `m7/` package, preserving CLI flags, artifact schemas, reject codes, and milestone semantics.

**Changes**:
1. **`m7/shared/constants.py`** (171 lines): All M7 constants, reject reasons, blocker tags, event types, surfaces, thresholds. Added 8th canonical blocker tag.
2. **`m7/orderflow/`** (8 modules): contracts, events, resolve, coverage, pricing, scoring_parallel, artifacts, cli (340 lines) + mode_ws_live (854 lines).
3. **`m7/triangular/`** (5 modules, 1828 lines total): graph, scoring, verdicts, repeatability, cli.
4. **Shims**: `scripts/m7a_orderflow_replay.py` (154), `scripts/m7a_enumerate_cycles.py` (94), `engine/triangular_*.py` (19-23) — thin re-export wrappers.

**Blocker tag addition**: `BLOCKER_LOW_LAG_RPC_QUOTE_FAIL` added as 8th canonical tag. Separately tracked from `LOW_LAG_REMOTE_QUOTER_LATENCY`.

**Evidence**: Both CLIs produce identical artifact schemas. Orderflow 300b verify: 30 events, 1 low-lag, 4 blocker tags active. Triangular verify: 500 cycles, 67/100 measured, best_net=-20.18 bps.

CI: 3180 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase, closed by default. Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.
