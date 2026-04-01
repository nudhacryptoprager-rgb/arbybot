# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.20 + M7.R1 structural refactor — all scopes produce no-graduate verdicts. M7.R1 extracted M7 logic into `m7/` package. M7.A.5.20 added local-state-first V3/V2 swap math, 3 new fields (59 total). 8 blocker tags, reject_reasons 19. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B closed.)  
**Updated**: 2026-04-01  
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep ($1-$10K), 8 canonical blocker tags, temporal repeatability, verdict summary, universe profiles (`narrow_7|expanded_10`), orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, subgraph seed (blocked), gas decomposition, stale/low-lag split, low-lag reject decomposition, low-lag debug diagnostic, pool-class truth, V2 direct resolve, low-lag watchlist, blocker tags, local-state-first pricing. M7.B remains closed.

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

Fixed 3 bugs: block_lag=0 falsy trap, events_scored_low_lag_ws counting unscored, UNSCORED_REJECTS scope. Added stale/low-lag split metrics (`events_detected_low_lag`, `events_scored_low_lag`, per-class economics, `stale_low_lag_comparison`). Evidence: 300b 23 events 16 scored, `best_net_bps_stale: -2.2002`, `beats_m4_baseline_stale: true`; 1000b 12/12 scored. **0 low-lag scored** in both runs — all low-lag fail at pre-econ rejects. CI: 3077 passed, 341 orderflow tests.

---

## M7.A.5.14: Low-Lag Reject Decomposition (DIAGNOSTIC)

**Hypothesis**: Low-lag events are already being detected but fail before economics scoring; explicit low-lag reject decomposition may reveal a fixable same-chain DEX coverage/resolution gap.

**New metrics** in `build_replay_summary()`:
- `low_lag_reject_histogram`: reject reason counts for block_lag ≤ 2 only
- `low_lag_pair_resolution_rate`: fraction of low-lag events that pass pair resolution
- `low_lag_counter_coverage_rate`: fraction that pass pair + counter-venue
- `low_lag_scored_results_rate`: fraction that reach economic scoring
- `low_lag_pre_econ_reject_rate`: fraction rejected by unscored (pre-econ) reasons
- ws-live: `low_lag_reject_histogram_ws`, `low_lag_pair_resolution_rate_ws`, `low_lag_pre_econ_reject_rate_ws`

**Evidence**:
- 300b: 12 events, 4 low-lag detected, 0 scored. `low_lag_reject_histogram: {TOKEN_PAIR_UNRESOLVED: 4}`. `low_lag_pair_resolution_rate: 0.0`, `low_lag_pre_econ_reject_rate: 1.0`.
- 1000b: 10 events, 2 low-lag detected, 0 scored. `low_lag_reject_histogram: {TOKEN_PAIR_UNRESOLVED: 1, ALL_CANDIDATE_POOLS_TRULY_INACTIVE: 1}`. `low_lag_pair_resolution_rate: 0.5`, `low_lag_pre_econ_reject_rate: 1.0`.

**Key finding**: Hypothesis CONFIRMED. 100% of low-lag events are rejected at pre-econ stage. M7.A.5.14 correctly shows that low-lag events still fail before economics, but fresh reruns indicate the blocker stack is no longer singular — TOKEN_PAIR_UNRESOLVED, NO_COUNTER_POOL, and ALL_CANDIDATE_POOLS_TRULY_INACTIVE share the reject distribution roughly equally. This is a multi-causal coverage gap, not a single dominant blocker.

CI: 3092 passed, 356 orderflow tests.

---

## M7.A.5.15: Low-Lag Debug Diagnostic + Coverage Truth (DIAGNOSTIC)

**Hypothesis**: Low-lag events are detected on time, but same-block scoring still fails because token identity and active counter-pool truth are incomplete for the exact low-lag pairs; targeted low-lag pair/pool truth may unlock the first executable-scored subset without leaving the same-chain DEX domain.

**Changes**:
1. **`pair_unresolved_detail`**: New BackrunResult field (54 total) capturing causal detail for TOKEN_PAIR_UNRESOLVED: `no_pool_address`, `pool_read_failed`, `no_symbol_map`.
2. **`low_lag_debug_rows`**: Per-event diagnostic block for block_lag ≤ 2 — event_id, reject_reason, pair_resolved, actual_pair, pair_unresolved_detail, admission_source, known/active pools, counter_venue_count.
3. **`low_lag_coverage_truth`**: Aggregated coverage metrics for low-lag subset — known_pools_total, active_pools_total, active_buy/sell_venues, no_counter_pool_rate, inactive_pool_rate.
4. **Targeted enrichment fallback**: When `_resolve_event_tokens()` fails (multicall batch error), tries individual `eth_call` for token0()/token1(), enriches discovered addresses, and retries resolution. Best-effort; does not block pipeline.

**Evidence**: 300b: 6 low-lag, 0 scored (TOKEN_PAIR_UNRESOLVED: 4, NO_COUNTER_POOL: 2). 1000b: 3 low-lag, 0 scored (TOKEN_PAIR_UNRESOLVED: 3). All `pool_read_failed`. Low-lag blocker stack multi-causal: unsupported-pool reads, no-counter-pool, known-but-inactive coexist. CI: 3110 passed, 374 orderflow tests.

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
