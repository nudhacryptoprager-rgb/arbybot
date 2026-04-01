# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.22 + M7.R1 structural refactor — all scopes produce no-graduate verdicts. M7.R1 extracted M7 logic into `m7/` package. M7.A.5.22 activated PoolRegistry in ws-live mode (was dormant in M7.A.5.21) — 74 pools discovered per window, NO_COUNTER_POOL eliminated. Gas-floor operational filter structural (same-block detection = preliminary_lag~0). 65 fields, 8 blocker tags, reject_reasons 20. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B closed.)  
**Updated**: 2026-04-02  
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep ($1-$10K), 8 canonical blocker tags, temporal repeatability, verdict summary, universe profiles (`narrow_7|expanded_10`), orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, subgraph seed (blocked), gas decomposition, stale/low-lag split, low-lag reject decomposition, low-lag debug diagnostic, pool-class truth, V2 direct resolve, low-lag watchlist, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, gas-floor prefilter, registry activation in ws-live. M7.B remains closed.

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

## M7.A.5.16: Low-Lag Pool-Class Truth (DIAGNOSTIC)

**Hypothesis**: Low-lag events are timely detected, but same-chain scoring still fails because low-lag pools split into three structural classes: unsupported pool ABI (token0/token1/slot0 reverts), no counter-pool, and known-but-inactive pool. Explicit pool-class truth reveals which class dominates and whether any class is fixable within the same-chain DEX domain.

**Changes**:
1. **`pool_contract_truth`**: New BackrunResult field (55 total). Per-event dict with `pool_address`, `code_present`, `token0_ok`, `token1_ok`, `slot0_ok`, `liquidity_ok`, `dex_family_guess`. Populated for TOKEN_PAIR_UNRESOLVED events with pool_address.
2. **Finer `pair_unresolved_detail`**: Split `pool_read_failed` into 5 fine-grained causes: `POOL_CODE_EMPTY`, `POOL_TOKEN0_REVERT`, `POOL_TOKEN1_REVERT`, `POOL_SLOT0_REVERT`, `POOL_LIQUIDITY_REVERT`. Each probed via individual eth_call selectors.
3. **`dex_family_guess`**: Algorithm: if token0+token1+slot0 work → `uniswap_v3_like`; if token0+token1 work but not slot0 → `uniswap_v2_like`; if only partial → `partial_erc20_pool`; else `unknown`; if no code → `no_code`.
4. **`low_lag_pool_class_truth`**: Aggregated block: `unsupported_pool_rate`, `no_counter_pool_rate`, `inactive_known_pool_rate`, `known_but_untradeable_rate`, `dex_family_histogram`, `pool_truth_count`.
5. **`low_lag_debug_rows`**: Now includes `pool_contract_truth` per event (12 keys, was 11).

**Evidence**:
- 300b: 11 events, 3 low-lag, 0 scored. `low_lag_reject_histogram: {TOKEN_PAIR_UNRESOLVED: 3}`. All 3 are `POOL_SLOT0_REVERT` + `dex_family_guess: "uniswap_v2_like"`. `unsupported_pool_rate: 1.0`, `pool_truth_count: 3`.
- 1000b: 18 events, 6 low-lag, 0 scored. `low_lag_reject_histogram: {TOKEN_PAIR_UNRESOLVED: 4, NO_COUNTER_POOL: 2}`. All 4 TOKEN_PAIR_UNRESOLVED are `POOL_SLOT0_REVERT` + `uniswap_v2_like`. 2 NO_COUNTER_POOL resolved pairs (0x1c43d05b/WETH, ZTX/WETH) but no counter-venue exists. `unsupported_pool_rate: 0.6667`, `no_counter_pool_rate: 0.3333`, `known_but_untradeable_rate: 0.3333`.

**Key finding**: M7.A.5.16 correctly classifies unresolved low-lag pools as V2-family on a V3-only scoring path, but fresh reruns show that this is only one branch of the blocker tree. The full low-lag blocker landscape is multi-causal: TOKEN_PAIR_UNRESOLVED (V2 ABI mismatch), NO_COUNTER_POOL (pair resolves but no counter-venue), and ALL_CANDIDATE_POOLS_TRULY_INACTIVE (known pool, zero liquidity). In some samples V2 dominates; in others NO_COUNTER_POOL dominates. The claim "V2-family pools are the root cause" is correct only for the unresolved subclass, not the entire low-lag subset.

**Implication**: To unlock low-lag scoring, the pipeline needs: (a) V2 pool adapter path for TOKEN_PAIR_UNRESOLVED events, (b) broader universe for NO_COUNTER_POOL events, (c) deeper liquidity probing for inactive pools. Each class is measured separately.

CI: 3132 passed, 396 orderflow tests.

---

## M7.A.5.17: V2 Direct Resolve and Pool-State Read Path (FIX + DIAGNOSTIC)

**Hypothesis**: Low-lag same-chain scoring may unlock only if V2-family pool-state reading is added (getReserves instead of slot0), but this must be measured separately from no-counter-pool and inactive-pool classes. V2 direct resolve bypasses batch_token_info fee() revert and enables pair resolution for uniswap_v2_like pools.

**Root cause fixed**: `batch_token_info()` in `core/multicall.py` calls `fee()` selector which does not exist on V2 pools — entire multicall batch fails. The V2 direct resolve path bypasses this by resolving token0/token1 from already-probed addresses and using `getReserves()` (selector `0x0902f1ac`) instead of `slot0()`.

**Changes**:
1. **`pool_state_read_path`**: New BackrunResult field (56 total). Values: `None` | `"v3_multicall"` | `"v2_getReserves"`. Tracks which adapter path read pool state for each event.
2. **V2 direct resolve**: When `dex_family_guess == "uniswap_v2_like"` and token0+token1 are readable, the enrichment fallback bypasses `_resolve_event_tokens()` entirely. Pair is resolved directly from probed addresses, getReserves is called for state truth, and `pool_state_read_path = "v2_getReserves"` is set.
3. **`_reject()` helper**: Updated with `pct` and `psrp` parameters to propagate pool_contract_truth and pool_state_read_path through all reject paths.
4. **`low_lag_v2_truth`**: New artifact block with 6 keys: `low_lag_v2_supported_rate`, `low_lag_v2_scored_results_rate`, `low_lag_v2_no_counter_pool_rate`, `low_lag_v2_inactive_pool_rate`, `v2_resolved_count`, `v2_scored_count`.
5. **`low_lag_debug_rows`**: Now includes `pool_state_read_path` per event (13 keys, was 12).

**Evidence**:
- 300b: 18 events, 2 low-lag, 0 scored. `reject_histogram: {NO_COUNTER_POOL: 2, GAS_EXCEEDS_GROSS: 16}`. Both low-lag events: `NO_COUNTER_POOL` with `pool_state_read_path: "v3_multicall"`. `v2_resolved_count: 0`. No V2 pools in this sample window.
- 1000b: 22 events, 2 low-lag, 0 scored. `reject_histogram: {GAS_EXCEEDS_GROSS: 20, NO_COUNTER_POOL: 2}`. Both low-lag events: `NO_COUNTER_POOL` with `pool_state_read_path: "v3_multicall"`. Pairs: `0xb0ffa800/WETH`, `0x60bf4e7c/USDC`. `v2_resolved_count: 0`.

**Key finding**: V2 direct resolve path is implemented and tested (19 new unit tests, 415 total orderflow), but these evidence runs show 0 V2 pool events — all low-lag events resolved via V3 multicall and hit NO_COUNTER_POOL. M7.A.5.17 correctly implements the V2 direct read path, but fresh reruns show that the live low-lag blocker is still not stable enough to treat any single sample as dominant. Depending on the window, the system sees either pure NO_COUNTER_POOL low-lag events or no low-lag events at all, while stale-only scoring remains the dominant observed regime. The next justified branch is M7.A.5.18: accumulate low-lag pair/pool truth across windows and move the low-lag subset toward local-state pricing inside the same-chain DEX domain.

CI: 3151 passed, 415 orderflow tests.

---

## M7.A.5.18: Low-lag Watchlist, Blocker Tags, Cross-window Truth (DIAGNOSTIC)

**Hypothesis**: Same-chain low-lag scoring may unlock only if low-lag pair/pool truth is accumulated across windows and priced from local pool state, without expanding outside the current DEX domain.

**Root cause addressed**: Low-lag surface is temporally variant — some windows show NO_COUNTER_POOL events, others show INACTIVE pools, others show none. Without cross-window accumulation, each run's low-lag truth is incomplete. Without a blocker-tag summary, the structural stoppers are buried in per-event data.

**Changes**:
1. **`low_lag_watchlist`**: New artifact block. A list of per-pool entries with 10 fields: `pair`, `pool_address`, `first_seen_block`, `last_seen_block`, `seen_count`, `reject_reason`, `pair_unresolved_detail`, `pool_state_read_path`, `known_pools`, `active_pools`. Entries are deduplicated by pool_address; seen_count increments across events from the same pool. Only tracks low-lag events (block_lag ≤ 2) where a pool address is discoverable.
2. **`blocker_tags`**: New artifact block with `active_tags` (list), `active_count` (int), `all_canonical_tags` (sorted list). 7 canonical tags: `LOW_LAG_NONE_THIS_WINDOW`, `LOW_LAG_NO_COUNTER_POOL`, `LOW_LAG_V2_UNSUPPORTED`, `LOW_LAG_INACTIVE_POOL`, `LOW_LAG_REMOTE_QUOTER_LATENCY`, `GAS_L1_DATA_DOMINANT`, `SUBGRAPH_API_KEY_REQUIRED`. Tags activate based on per-window evidence.
3. **`ALL_BLOCKER_TAGS`**: Module-level frozenset of 7 canonical tags with individual constants.
4. **`m7a518_hypothesis`**: Hypothesis string added to ws-live artifacts.
5. **No new BackrunResult fields** (still 56). **No new reject reasons** (still 19). Changes are artifact-level only.

**Evidence**:
- 300b: 21 events, 3 low-lag, 0 scored. `reject_histogram: {GAS_EXCEEDS_GROSS: 19, NO_COUNTER_POOL: 2}`. `low_lag_reject_histogram: {ALL_CANDIDATE_POOLS_TRULY_INACTIVE: 2, NO_COUNTER_POOL: 1}`. Watchlist: 1 entry (pool `0xdd91...`, pair `0x44f49ff0/USDT`, seen_count=2, reject=ALL_CANDIDATE_POOLS_TRULY_INACTIVE, known_pools=1, active_pools=0). Blocker tags: `LOW_LAG_NO_COUNTER_POOL`, `LOW_LAG_REMOTE_QUOTER_LATENCY`, `GAS_L1_DATA_DOMINANT`, `SUBGRAPH_API_KEY_REQUIRED` (4 active).
- 300b_b: 20 events, 3 low-lag, 0 scored. `reject_histogram: {GAS_EXCEEDS_GROSS: 16, NO_COUNTER_POOL: 3, STALE_POSITIVE: 1}`. All 3 low-lag: NO_COUNTER_POOL. Watchlist: empty (NO_COUNTER_POOL → no candidate_pools). Blocker tags: `LOW_LAG_NO_COUNTER_POOL`, `LOW_LAG_REMOTE_QUOTER_LATENCY`, `SUBGRAPH_API_KEY_REQUIRED` (3 active).
- 1000b: 22 events, 0 low-lag, 0 scored. 3 STALE_POSITIVE, `best_net_bps=14.3358` (stale). `LOW_LAG_NONE_THIS_WINDOW` correctly activates. Watchlist: empty. Blocker tags: `LOW_LAG_NONE_THIS_WINDOW`, `SUBGRAPH_API_KEY_REQUIRED` (2 active).

**Key findings**: Blocker tags correctly vary per window while SUBGRAPH_API_KEY_REQUIRED is always present. Watchlist captures pool addresses when candidate_pools exist (300b had 1 entry from ALL_CANDIDATE_POOLS_TRULY_INACTIVE). NO_COUNTER_POOL events produce empty watchlists (no pool to track). LOW_LAG_NONE_THIS_WINDOW wins in 1000b (temporal instability confirmed). Stale-positive events reach up to +14.34 bps but are rejected by STALE_POSITIVE gate. No low-lag event has ever been economically scored.

CI: 3180 passed, 444 orderflow tests.

---

## M7.A.5.19: Quote-Fail Provenance + File Splits (DIAGNOSTIC + STRUCTURAL)

**Hypothesis**: Post-refactor low-lag scoring may unlock only after blocker-tag stabilization and local-state pricing are applied to the low-lag watchlist inside the same-chain DEX domain. Prerequisite: diagnostic infrastructure improvements.

**Changes**:
1. **Quote-fail provenance in `scoring_parallel.py`**: Added `_buy_fail_info` list to capture (dex_name, exception_class) tuples when buy quotes fail. When `venues_quoted == 0`, injects `quote_fail_stage`, `quote_fail_venue`, `quote_fail_exception_short` into `stage_latency` dict. `artifacts.py` reads these into `low_lag_debug_rows`. 3 new tests (TestM7A519QuoteFailProvenance).
2. **CLI split**: Extracted ws_live mode from `cli.py` into `mode_ws_live.py` (cli.py 340 lines, mode_ws_live.py 854 lines).
3. **Test file split**: `test_orderflow_contracts.py` (6086 lines, 107 classes) → 9 files (max 995 lines). `test_triangular_contracts.py` (2247 lines, 21 classes) → 3 files (max 932 lines). All 3183 tests pass with 0 regressions.
4. **No new BackrunResult fields** (still 56). **No new reject reasons** (still 19). **ALL_BLOCKER_TAGS still 8**.

**Evidence**:
- 300b: 30 events, 27 scored, 3 low-lag, 0 low-lag scored. `reject_histogram: {GAS_EXCEEDS_GROSS: 27, ALL_CANDIDATE_POOLS_TRULY_INACTIVE: 2, NO_COUNTER_POOL: 1}`. `best_net_bps: -0.54`. Blocker tags: 4 active.
- 300b_b: 30 events, 29 scored, 1 low-lag, 0 low-lag scored. `reject_histogram: {GAS_EXCEEDS_GROSS: 29, NO_COUNTER_POOL: 1}`. `best_net_bps: -2.41`. Blocker tags: 3 active.
- 1000b: 38 events, 35 scored, 3 low-lag, 0 low-lag scored. `reject_histogram: {GAS_EXCEEDS_GROSS: 35, NO_COUNTER_POOL: 2, ALL_CANDIDATE_POOLS_TRULY_INACTIVE: 1}`. `best_net_bps: -2.20`. Blocker tags: 4 active.
- Triangular: 67/100 measured, best_net=-22.74 bps, regime_bucket=medium_activity.

**Key finding**: Quote-fail provenance is correctly null for all low-lag events (rejected at NO_COUNTER_POOL/INACTIVE_POOL before reaching quoting stage). The provenance will activate when events pass structural checks and reach the buy-quote stage but all venues fail. Stale subset continues to beat M4 baseline (best_net = -0.54 to -2.20 > -3.51 bps).

CI: 3183 passed, 447 orderflow + 152 triangular tests across 12 files (max 995 lines each).

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
