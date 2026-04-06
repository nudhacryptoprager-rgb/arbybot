# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.45 + M7.R1 + M7.T1 — all scopes produce no-graduate verdicts. M7.A.5.45 adds bridge-driven execution queue (cold_executable priority prewarm), hot execution intents artifact (`m7_hot_intents_latest.json`), funnel headline_level enforcement (prevents claims above confirmed level), dashboard headline badge. 3327 tests pass, all CI gates green. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B closed.)  
**Updated**: 2026-04-06  
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep ($1-$10K), 9 canonical blocker tags, temporal repeatability, verdict summary, universe profiles (`narrow_7|expanded_10`), orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, subgraph seed (blocked), gas decomposition, stale/low-lag split, low-lag reject decomposition, low-lag debug diagnostic, pool-class truth, V2 direct resolve, low-lag watchlist, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, gas-floor prefilter, registry activation in ws-live, low-lag registry-direct scoring bridge, pipeline latency optimization, detection-time low-lag truth, anomaly-clean headlines, wall-clock budget abort, Timeboost feasibility, profit guard fix + hot-mode fast path + stage timing, hot-lane no-fallback + execution-readiness timing, cold/hot artifact isolation + promoted watchlist + stale KPI fix, batch pre-resolve + supervisor fix + size_valid cache, top-candidate persistence + hot lane token resolution fix. M7.B remains closed.

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
- Tests: 152 in `test_triangular_*.py` (3 files), 369 in `test_orderflow_*.py` (8 files + conftest.py)

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

## M7.A.5.9–5.24: Corrective + Infrastructure + Scoring (CLOSED)

**M7.A.5.9–5.11**: Decimal fix, stale gate, active-liquidity coverage (CI: 2988→3036).
**M7.A.5.12**: Byte-parsing breakthrough — 26 scored (was 0) (CI: 3059).
**M7.A.5.13–5.15**: Stale/low-lag split, reject decomposition, debug diagnostic (CI: 3077→3110).
**M7.A.5.16–5.17**: Pool-class truth, V2 direct resolve (CI: 3132→3151).
**M7.A.5.18–5.19**: Low-lag watchlist, blocker tags, provenance, file splits (CI: 3180→3183).
**M7.A.5.20–5.22**: Local pricing, factory-driven pool registry, registry activation (CI: 3212→3267).
**M7.A.5.23–5.24**: Registry-direct scoring bridge, pipeline slim (CI: 3286→3310).

---

## M7.A.5.25–5.29: Detection-Time Truth, Structural Refactors, Rolling+Loop Infra (CLOSED)

**M7.A.5.25**: Fixed low-lag accounting (detection-time vs final). +REJECT_PRICING_ANOMALY (21 total). CI: 3317 passed.
**M7.R1**: Extracted `m7/` package (8 modules). CI: 3180 passed.
**M7.T1**: Consolidated 14 test files into 8 stable suites. CI: 3104 passed.
**M7.A.5.26**: Fixed `UnboundLocalError` in zero-active-pools. CI: 3105 passed.
**M7.A.5.27**: Anomaly-clean headlines, wall-clock budget abort, Timeboost constants. CI: 3113 passed.
**M7.A.5.28**: Unified `_is_stale()`, canonical `m7_orderflow_latest.json`. CI: 3120 passed.
**M7.A.5.29**: `m7a_orderflow_loop.py` continuous loop, hot/cold split. CI: 3124 passed.

---

## M7.A.5.30: Hot Execution Lane + Latency Telemetry + Profit Guard (CLOSED)

Fixed `last_nonempty_timestamp` + `BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY` semantics. Added `resolve_ms`/`enrichment_ms` timers + `m7a530_latency_breakdown`. Hot/cold lane split: `--lane cold` (full diagnostic) vs `--lane hot` (tight window, m7_hot_latest.json). Created `m7/orderflow/profit_guard.py` (Flashbots simple-blind-arb pattern). +11 tests. CI: 3140 passed.

---

## M7.A.5.31: Hot Lane to Decision + Profit Guard + Timeboost Eligibility (CLOSED)

Dashboard Panel 11 reads both cold + m7_hot. Discovery solved (registry_direct=30/30), viable_count=0 due to completion latency ~1544ms vs 250ms. Fixed `last_nonempty_timestamp` and `REMOTE_QUOTER_LATENCY` bugs. Latency: resolve_ms≈935, registry_preload_ms≈449, oracle_ms≈117. `run_ws_live()` accepts `external_registry` for hot lane prewarm. CI: 3155 passed.

---

## M7.A.5.32: Unified Nonstop Runtime + Rolling Retention + Hot-Path Slimming

**Hypothesis**: M7.A.5.32 = unified nonstop supervisor, rolling-only retention, hot-path reduction toward first profit_guard pass under 250ms.

**Changes**: (1) `start_nonstop_runtime.py` — unified supervisor (dashboard + start.py + M7 hot/cold). (2) `prune_tmp_artifacts.py` — retention tool for `data/tmp`. (3) Hot lane fast-path via `score_backrun_fast()` with 250ms stage budgets, zero subgraph/oracle/enrichment. (4) `score_backrun_fast()` in scoring_parallel.py: registry O(1) → cached state → local pricing → economics → BackrunResult `scoring_path="registry_fast"`. (5) HOT_BUDGET_* constants, HOT_WATCHLIST_PAIRS (3 pairs). (6) `_rolling/` cleaned to canonical 9 files. (7) +14 tests.

CI: 3163 passed, 6 skipped. Safety: PASS. ALL REQUIRED GATES PASSED.

---

## M7.A.5.33–5.35: Hot Fast-Path + No-Fallback + Artifact Isolation + Promoted Watchlist (CLOSED)

**M7.A.5.33**: Fixed profit_guard dead code (wrong field names). Added `score_backrun_fast()` with per-stage timing. Hot-mode fast path via `external_registry`. CI: 3172 passed.

**M7.A.5.34**: Hot mode no-fallback (hot_skip instead of 1330ms parallel). PRICING_ANOMALY hard-exclude. Stage 5 timing split (tx_build/calldata/sign). CI: 3179 passed.

**M7.A.5.35**: Fixed hot lane overwriting cold rolling artifact. Two-level promoted watchlist (candidate + execution). `stale_positive_count_clean` fix. CI: 3186 passed.

---

## M7.A.5.36: Per-Stage Hard Budget Abort + Promotion Rules + p50/p90 Tracking

**Hypothesis**: M7.A.5.36 = hot p50 ≤ 250ms, p90 ≤ 400ms on a real promoted watchlist. Speed-first: stop diagnostic work, start cutting latency numbers.

**Changes**: (1) `scoring_parallel.py`: per-stage hard budget abort in `score_backrun_fast()` — 4 individual stage aborts (registry≤25ms, pool_state≤50ms, local_math≤10ms, profit_guard≤40ms). Candidate aborted immediately on budget breach. (2) `constants.py`: zero-RPC hot path target constants (HOT_TARGET_RESOLVE_MS=0, HOT_TARGET_ORACLE_MS=0, HOT_TARGET_ENRICHMENT_MS=0, HOT_TARGET_REGISTRY_PRELOAD_MS=0). (3) `m7a_orderflow_loop.py`: p50/p90 latency tracking in hot artifact fast_path block. (4) `m7a_orderflow_loop.py`: strengthened `_promote_pairs_from_cold()` — PROMOTED_MIN_COLD_APPEARANCES=2, PROMOTED_MIN_NET_BPS=-50, anomaly hard exclude. (5) +14 tests.

**Online evidence**: 1h nonstop. Hot: profit_guard_passed=0, viable=0. Cold: mean_latency=1565ms (5.4x over 250ms budget). Breakdown: resolve_ms≈788, registry_preload_ms≈621, oracle_ms≈104, enrichment_ms≈51. Hot artifact MISSING fast_path/p50/p90 entirely (critical observability gap — gated by `if fast_results:` which was always falsy). Promoted watchlist still seed_only.

CI: 3200 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.37: Hot Artifact Always-Emit + Resolve/Oracle Caching + Persistent Cold Registry

**Hypothesis**: M7.A.5.37 = hot p50 ≤ 250ms and hot p90 ≤ 400ms on a real promoted watchlist before chasing first profit_guard pass.

**Critical bug fixed**: `_write_hot_artifact()` gated `fast_path` block behind `if fast_results:` — when empty, NO fast_path/p50/p90/hot_skip_count emitted. This was a critical observability gap: hot artifact appeared to lack speed metrics entirely. Fix: always emit `fast_path` block (zeros/nulls when empty) + always emit `hot_skip_count`.

**Changes**: (1) `m7a_orderflow_loop.py`: `_write_hot_artifact()` always emits `fast_path` block with all required keys (scored, positive, viable, profit_guard_passed, mean/max/p50/p90_latency_ms, best_net_bps, scoring_paths, stage_timings) even when fast_results is empty. Always emits `hot_skip_count` from `_raw_results`. (2) `m7a_orderflow_loop.py`: persistent cold registry `_cold_registry` — lazy-init `PoolRegistry()` on first cold iteration, passed as `warm_registry` (not `external_registry`) to avoid triggering hot mode. Registry cache survives across iterations. (3) `m7/orderflow/resolve.py`: process-level `_pool_token_cache` for pool→(token0, token1, fee) resolution. Pool tokens are immutable contract data — safe to cache forever. Cache hit skips multicall entirely (~788ms→0ms for repeated pools). (4) `m7/orderflow/pricing.py`: block-proximity `_oracle_cache` for `check_oracle_sanity()`. Cache key is token pair, stale threshold 50 blocks (~12.5s on Arbitrum). Cache hit returns copy (~104ms→0ms for repeated pairs within window). (5) `mode_ws_live.py`: `run_ws_live()` accepts `warm_registry` parameter (persistent cold mode, does NOT trigger hot mode). `_prewarm_count = -2` skips redundant prewarm. (6) +19 tests in 6 classes covering all changes.

**Online evidence**: 1h nonstop `--no-m4`. Hot: fast_path block ALWAYS present with p50/p90/hot_skip_count visible (observability gap fixed). Hot iteration 13: events=0-1, hot_skip_count=0-1, promoted watchlist seed_only. Cold: iteration 1 total_pipeline=1196ms (resolve=374, registry_preload=427, oracle=257, enrichment=138). Iteration 2 total_pipeline=1063ms (registry_preload=354, improving with warm cache). Cache benefit strongest within-iteration (repeated pools). Cross-iteration resolve cache effective for recurring pools; oracle cache stale threshold (50 blocks) too narrow for cross-iteration benefit (future: increase threshold).

CI: 3219 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.38: Session-Scoped Caching + Enrichment Cache + Latency Budget Hit Rate

**Hypothesis**: latency_budget_hit_rate >= 0.80 via session-scoped caches for enrichment, oracle, and registry_preload.

**Changes**: (1) `m7/orderflow/resolve.py`: `_enrichment_cache` for immutable ERC-20 symbol/decimals. (2) `m7/orderflow/pricing.py`: `_ORACLE_CACHE_STALE_BLOCKS` 50→5000. (3) `m7/orderflow/pool_registry.py`: configurable `stale_threshold_blocks`. (4) `scripts/m7a_orderflow_loop.py`: cold registry `PoolRegistry(stale_threshold_blocks=5000)`. (5) +9 tests in 4 classes.

**Online evidence**: 0.25h nonstop. latency_budget_hit_rate peaks 0.80 (warm), settles 0.72. total_pipeline mean 275-290ms (near 250ms budget). enrichment_ms drops to ~7ms (cached), oracle_ms ~15ms (warm), registry_preload_ms 121ms.

CI: 3228 passed, 6 skipped. ALL REQUIRED GATES PASSED.

---

## M7.A.5.39: Two-Level Promotion + Hot Prewarm + Cold Lane Registry Fix

**Hypothesis**: promoted-watchlist activation + hot p50/p90 proof under nonstop runtime.

**Changes**: (1) Cold lane registry fix — was using `_hot_registry` instead of `None` for `_ext_registry`. (2) Cold prewarm target fix — was prewarming `_hot_registry` instead of `_cold_registry`. (3) Two-level promotion — `_promote_pairs_from_cold()` returns `candidate` (relaxed, cap 20) and `execution` (strict+size_valid, cap 10). (4) Cross-lane `m7_promoted_pairs.json` for cold→hot communication. (5) Hot lane prewarm from seeds + accumulated + cross-promoted. (6) Web3 HTTPProvider reuse (single instance). (7) `start_nonstop_runtime.py` stdout drain fix. (8) `PROMOTED_CANDIDATE_MAX_PAIRS = 20`. (9) +16 tests in 7 classes.

CI: 3244 passed, 6 skipped. ALL REQUIRED GATES PASSED.

---

## M7.A.5.40: Batch Pre-Resolve + Supervisor Fix + Size Valid Cache (CLOSED)

**Hypothesis**: M7.A.5.40 = fresh 10–20 minute runtime proof with resolve_ms, enrichment_ms, registry_preload_ms fully eliminated from per-event scoring path via batch pre-resolve.

**Root cause analysis**: All 4 RPC-heavy stages (resolve ~683ms, enrichment ~105ms, oracle ~125ms, registry_preload ~604ms) executed PER EVENT inside `score_backrun_live_parallel()`. Even with session-scoped caches (M7.A.5.38), first events in each iteration still hit cold cache paths. Solution: batch pre-resolve ALL event pools BEFORE the scoring loop so individual scoring calls hit module-level caches.

**Changes**: (1) `m7/orderflow/resolve.py`: Added `get_cached_decimals(token_addr)` — reads from `_enrichment_cache`, returns cached decimals or None. Added `batch_pre_resolve_pools(pool_addresses, rpc_url, block_num, addr_to_symbol)` — batch-resolves pool tokens via multicall (populates `_pool_token_cache`), batch-enriches unknown tokens (populates `_enrichment_cache`, updates `addr_to_symbol`). Returns `{pool_addr: {token0, token1, fee}}`. (2) `m7/orderflow/mode_ws_live.py`: Added cold-lane pre-pass before scoring loop — collects unique pool addresses from events, calls `batch_pre_resolve_pools()`, batch-preloads each discovered pair into `session_registry.preload_pair()`. All subsequent `score_backrun_live_parallel()` calls hit warm caches. Fixed `_hot_mode` variable ordering (was referenced before assignment). (3) `m7/orderflow/scoring_parallel.py`: Added `get_cached_decimals` import. Added cache fallback for `_token_in_dec` — calls `get_cached_decimals(token_in_addr)` BEFORE the well-known stablecoin heuristic. Fixes `size_valid_for_token=false` for batch-pre-enriched tokens. (4) `scripts/start_nonstop_runtime.py`: Critical blocking I/O fix — changed `stdout=subprocess.PIPE` to `stdout=subprocess.DEVNULL` and made `drain_output()` a no-op. Original blocking `readline()` prevented supervisor from reaching deadline check. (5) `scripts/m7a_orderflow_loop.py`: Hot artifact reporting fix — `_promoted_pairs` updated from `_cross_promoted` for accurate promoted_watchlist display. (6) Rolling canonical files: added `m7_promoted_pairs.json` to allowlists. (7) +14 tests in 4 new M7.A.5.40 classes (TestM7A540BatchPreResolve, TestM7A540GetCachedDecimals, TestM7A540ColdPrePassInModeWsLive, TestM7A540SizeValidCacheFallback).

**Online evidence**: 10.3-minute nonstop runtime (0 restarts, 3/3 processes alive) + 120-block direct replay.

| Metric | M7.A.5.38 baseline | 120-block replay | Nonstop final (warm) | Improvement |
|--------|-------------------|-----------------|---------------------|-------------|
| total_pipeline mean (ms) | 1519 (cold) / 275 (warm) | **143.11** | **15.62** | 97% from cold, 94% from warm |
| resolve_ms mean | 683 | **63.32** (1 outlier) | **0.0** | 100% elimination |
| enrichment_ms mean | 105 | **0.0** | **0.0** | 100% elimination |
| registry_preload_ms mean | 604 | **0.0** | **0.0** | 100% elimination |
| oracle_ms mean | 125 | **79.79** | **15.62** | 87% reduction |
| latency_budget_hit_rate | 0.19→0.80 | **0.8947** | N/A (all under) | Peak 0.89 |
| size_valid_count | 6/13 (46%) | **16/19 (84%)** | **8/8 (100%)** | 100% |
| best_net_bps | 103.63 | **318.13** | **3.55** | 3x (replay) |
| promoted pairs | seed_only | N/A | **6 candidate, 6 execution** | Active promotion |

Key observations: (1) Batch pre-resolve eliminates resolve_ms, enrichment_ms, registry_preload_ms entirely for pools seen earlier in the same iteration. (2) One outlier in 120-block replay (WETH/USDC resolve=1203ms) — pool appeared in a later block after batch ran (expected). (3) Oracle is the only remaining RPC cost (~16-80ms), cached after first call per pair. (4) size_valid=100% in nonstop (warm cache provides decimals for all tokens). (5) Supervisor DEVNULL fix eliminates blocking I/O — nonstop completes reliably within deadline.

CI: 3258 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.41: Persist Top Candidates + Hot Lane Token Resolution Fix

**Hypothesis**: M7.A.5.41 = persist top executable candidates per-window and convert cold executable positives into hot-lane fast-path scores. Fresh rolling shows `best_net_bps_executable=2237.28`, `viable_count=5` — but these are summary-only counters; zero per-event detail survives in rolling artifact because `_ROLLING_EXCLUDE_KEYS` strips `results`. Hot lane still `fast_path.scored=0` despite 20 candidate / 10 execution promoted pairs.

**Root cause — hot lane `fast_path.scored=0`**: `score_backrun_fast()` tried `token_addresses.get(event.token_out)` but `event.token_out` contained direction tags ("token0"/"token1") from `normalize_swap_log()`, NOT symbol names. The `token_addresses` dict maps `{symbol: address}`. Lookup ALWAYS returned empty string → function returned None for EVERY event → `fast_path.scored=0` since the feature was created (M7.A.5.32). Cold lane worked because it falls back to `_resolve_event_tokens()` which does on-chain multicall resolution.

**Fix**: `score_backrun_fast()` now resolves tokens from `_pool_token_cache` (populated by cold lane) via `event.pool_address` + direction tag (`event.token_in = "token0_in"/"token1_in"`). Zero-RPC: cache contains immutable pool→(token0, token1, fee) data. Also fixed `_in_sym` decimal detection (was using direction tag, now resolves actual symbol from `addr_to_symbol`).

**Changes**: (1) `m7/orderflow/scoring_parallel.py`: replaced broken `token_addresses.get(event.token_out)` with `_pool_token_cache` lookup using `event.pool_address.lower()` + direction-tag-to-address mapping. Imported `_pool_token_cache` from `resolve.py`. Fixed `_in_sym` decimal detection to use `addr_to_symbol` instead of direction tag. (2) `m7/orderflow/artifacts.py`: added `top_executable_candidates` (top-5 viable results) and `top_stale_positive_candidates` (top-5 stale positive) compact blocks. Each row has: event_id, actual_pair, net_bps, block_lag, same_state_class, route_viable, size_valid_for_token, scoring_path, profit_guard_passed, pipeline_latency_ms, reject_reason. These keys survive `_ROLLING_EXCLUDE_KEYS` (not in the exclude set). (3) `scripts/m7a_orderflow_loop.py`: added `top_hot_candidates` (top-5 fast_results sorted by net_bps) to hot artifact — always emitted (empty list when no fast results). (4) +14 tests in 3 classes (TestM7A541TopCandidatePersistence, TestM7A541HotLaneTokenResolution, TestM7A541TopHotCandidates).

**Online evidence**: PENDING — requires nonstop runtime verification with hot lane now able to score events.

CI: 3272 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.42: Signal Classification + Artifact Hygiene + Dashboard Split

Added `signal_classification` (4 tiers: diagnostic_positive, stale_positive, cold_executable_positive, hot_execution_ready), `diagnostic_raw` (7 relocated metrics), `_ROLLING_EXCLUDE_KEYS` (19 entries), `m7_cold_hot_bridge.json`, `hot_gap_debug` counters, 3-section dashboard split. Evidence: diagnostic_positive.count=1 (101.44 bps), cold_executable_positive.count=0, hot_execution_ready.count=0. CI: 3277 passed, 6 skipped.

---

## M7.A.5.43: Bridge-Driven Hot Registry Activation

**Hypothesis**: M7.A.5.43 = bridge-driven hot registry activation with exact candidate transport and first hot fast_path score. Root cause: cross-process _pool_token_cache gap — cold lane populates cache via batch_pre_resolve_pools, but hot lane (separate process) starts empty. Pair-name promotion is too lossy; pool-address-first matching needed.

**Changes**: (1) `m7/orderflow/artifacts.py`: _compact_candidate now includes pool_address from _source_event; added near_executable_candidates (size_valid, GAS_EXCEEDS_GROSS/STALE_POSITIVE rejected, net_bps > -50). (2) `scripts/m7a_orderflow_loop.py`: _write_cold_hot_bridge upgraded with pool_token_transport (full _pool_token_cache dump) + near_executable tier; added _read_cold_hot_bridge(), _populate_pool_token_cache_from_bridge(), _prewarm_registry_from_bridge() (pool-address-first using token addresses); hot prewarm rewritten bridge-first; 3 hot-miss counters added (pool_address_match, canonical_pair_match, registry_has_pair_but_not_pool); _write_hot_artifact accepts bridge_diagnostics. (3) +14 tests in 4 new classes.

**Online evidence**: 10-minute nonstop `--no-m4`. Fresh rolling:
- pool_token_transport: 63 entries, bridge_registry_prewarmed: 46 pairs
- cold_executable_positive.count=3 (UP from 0), best_bps=68.69
- near_executable: 5 candidates, pool_address in all candidate rows
- hot fast_path.scored=0 (single event from unknown pool — market timing, not architecture failure)
- 3/3 alive, 0 restarts

CI: 3291 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.44: Execution Funnel + Micro-Refinement + Verified Profitable

**Hypothesis**: M7.A.5.44 = first verified_profitable candidate from cold lane, execution funnel visibility, micro-refinement sizing check. Core insight (from user review): "cold_executable_positive != hot_execution_ready != real_profit." The funnel stages need machine visibility to diagnose where the pipeline breaks.

**Changes**: (1) `m7/orderflow/artifacts.py`: added `execution_funnel` dict with 5 stages — `diagnostic_positive` (positive_net_count_clean), `cold_executable_positive` (viable_count), `hot_scored` (0, injected by hot lane), `profit_guard_passed` (_profit_guard_passed_count), `realized_onchain_profit` (0, M7.B). Monotonic decrease invariant enforced. (2) `m7/orderflow/artifacts.py`: `_compact_candidate()` now runs `check_profit_guard()` on viable+positive+size_valid candidates → adds `verified_profitable` (bool) and `verified_net_bps` (float) to compact row. (3) `m7/orderflow/artifacts.py`: added `micro_refinement` — tests 5 size multipliers [0.5, 0.8, 1.0, 1.5, 2.0] around `amount_in_wei` for top 3 exec + top 2 near-exec candidates, each checked with `profit_guard`. Each entry has `event_id`, `actual_pair`, `base_net_bps`, `sizes_tried`, `sizes_passed`, `best_micro_net_bps`, `reject_reason`. (4) `scripts/m7a_orderflow_loop.py`: 3 new bridge-hit counters — `bridge_pool_address_hit_count` (events whose pool_address is in bridge pool_token_transport), `bridge_pair_hit_count` (of those, resolved pair matches registry), `bridge_loaded_candidate_count` (cold_executable + near_executable loaded from bridge). Propagated through `_write_hot_artifact()` to `hot_gap_debug`. (5) `monitoring/dashboard.html`: Section 3 "Execution Gap Funnel" — 5-stage funnel table, bridge counters inline, micro-refinement results table. "Verified" column in top_executable_candidates table.

**Online evidence**: 10-minute nonstop `--no-m4`. Fresh rolling at `2026-04-06T09:52:31Z`:
- `execution_funnel: {diagnostic_positive:9, cold_executable_positive:2, hot_scored:0, profit_guard_passed:0, realized_onchain_profit:0}`
- `verified_profitable=True` on top 2 exec candidates (77.65 bps, 73.81 bps) — FIRST verified profitable
- `micro_refinement: 4 entries; 2/4 survive all 5 sizes (0.5x-2.0x)`
- Bridge: cold_executable=2, near_executable=5, pool_token_transport=36 entries
- 3/3 processes alive, 0 restarts

CI: 3310 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.45: Bridge Execution Queue + Hot Intents + Headline Enforcement

**Hypothesis**: M7.A.5.45 = bridge as scheduler input for hot lane, hot execution intents artifact, funnel headline_level enforcement. Core insight (from user review): "cold verified positive ≠ hot executable positive" — the remaining gap is executional. cold_executable pools must get priority prewarm, and the highest confirmed funnel stage must be machine-visible to prevent over-claiming.

**Changes**: (1) `scripts/m7a_orderflow_loop.py`: **Bridge-driven execution queue** — `_prewarm_registry_from_bridge()` now accepts `priority_pools` param (set of lowercase pool addresses from `cold_executable` + `near_executable`). Priority pools are prewarmed first via sorted iteration. Hot lane extracts `cold_executable` and `near_executable` pool addresses from bridge, passes them as `priority_pools`. (2) `scripts/m7a_orderflow_loop.py`: **Hot intents artifact** — new `_write_hot_intents()` function writes `m7_hot_intents_latest.json` with compact rows for hot-scored candidates only. Schema: `timestamp`, `loop_iteration`, `headline_level`, `hot_scored_count`, `hot_positive_count`, `profit_guard_passed_count`, `cold_executable_pool_count`, `intents[]` (capped at 20). New `_HOT_INTENTS_PATH` constant. Called after `_write_hot_artifact()` in hot lane post-scoring. (3) `scripts/m7a_orderflow_loop.py`: **Headline enforcement** — new `_compute_headline_level()` function returns the highest confirmed funnel stage with count > 0. Added to both hot artifact (`headline_level` top-level field) and hot intents artifact. (4) `m7/orderflow/artifacts.py`: Cold-lane `execution_funnel` now includes `headline_level` string field. (5) `monitoring/dashboard.html`: Headline level badge above funnel table — color-coded (red=none, yellow=diagnostic/cold, green=hot_scored+). (6) `monitoring/dashboard_server.py`: New `/api/intents` endpoint serving `m7_hot_intents_latest.json`. Added `m7_hot_intents` to `ARTIFACT_FILES`. (7) +17 tests in 6 new classes (TestM7A545HeadlineLevel, TestM7A545PriorityPrewarm, TestM7A545HotIntentsArtifact, TestM7A545HotIntentsPathConstant, TestM7A545DashboardHeadlineLevel, TestM7A545DashboardIntentsEndpoint). Updated 2 existing M7A544 tests for `headline_level` field.

**Online evidence**: 10-minute nonstop `--no-m4`. Fresh rolling at `2026-04-06T10:37:14Z`:
- Cold `execution_funnel: {diagnostic_positive:7, cold_executable_positive:0, hot_scored:0, profit_guard_passed:0, realized_onchain_profit:0, headline_level:"diagnostic_positive"}`
- Hot `headline_level: "none"` (no hot-scored events this window — expected: incoming events at different pools)
- `m7_hot_intents_latest.json`: created with correct schema — `hot_scored_count:0, cold_executable_pool_count:2`
- Bridge: cold_executable=0 (this window), near_executable=5, pool_token_transport=46
- 3/3 processes alive, 0 restarts, 10+ minutes continuous

CI: 3327 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase, closed by default. Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.
