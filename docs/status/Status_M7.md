# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.47e. M7.A.5.47e fixes hot-rollup semantics: disentangled counters, per-window miss classification, atomic writes, first_window_at, bridge_hit_deficit adaptive logic. 3344 tests pass, all CI gates green. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B closed.)  
**Updated**: 2026-04-06
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep, 9 canonical blocker tags, temporal repeatability, verdict summary, universe profiles, orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, gas decomposition, stale/low-lag split, pool-class truth, V2 direct resolve, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, registry activation in ws-live, pipeline latency optimization, profit guard + hot-mode fast path, hot-lane no-fallback + execution-readiness timing, cold/hot artifact isolation + promoted watchlist, batch pre-resolve + supervisor fix. M7.B remains closed.

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

## M7.A.5.36–5.39: Budget Abort + Caching + Promotion + Hot Prewarm (CLOSED)

**M7.A.5.36**: Per-stage hard budget abort in `score_backrun_fast()` (4 aborts: registry≤25ms, pool_state≤50ms, local_math≤10ms, profit_guard≤40ms). p50/p90 tracking. Promoted rules (MIN_COLD_APPEARANCES=2, MIN_NET_BPS=-50). Evidence: hot fast_path gated by `if fast_results:` (observability gap). CI: 3200 passed.

**M7.A.5.37**: Critical fix — `_write_hot_artifact()` now always emits `fast_path` block (zeros when empty). Process-level `_pool_token_cache` (resolve.py), block-proximity `_oracle_cache` (pricing.py), persistent `_cold_registry`. Evidence: cache benefit strongest within-iteration; cross-iteration resolve cache effective for recurring pools. CI: 3219 passed.

**M7.A.5.38**: Session-scoped enrichment cache, oracle stale threshold 50→5000 blocks, registry stale_threshold_blocks. Evidence: latency_budget_hit_rate peaks 0.80, total_pipeline 275-290ms. CI: 3228 passed.

**M7.A.5.39**: Cold lane registry fix (was using `_hot_registry` instead of None). Two-level promotion (candidate cap 20, execution cap 10). `m7_promoted_pairs.json` for cross-lane communication. Web3 HTTPProvider reuse. CI: 3244 passed.

---

## M7.A.5.40: Batch Pre-Resolve + Supervisor Fix + Size Valid Cache (CLOSED)

**Hypothesis**: M7.A.5.40 = fresh 10–20 minute runtime proof with resolve_ms, enrichment_ms, registry_preload_ms fully eliminated from per-event scoring path via batch pre-resolve.

**Root cause analysis**: All 4 RPC-heavy stages (resolve ~683ms, enrichment ~105ms, oracle ~125ms, registry_preload ~604ms) executed PER EVENT inside `score_backrun_live_parallel()`. Even with session-scoped caches (M7.A.5.38), first events in each iteration still hit cold cache paths. Solution: batch pre-resolve ALL event pools BEFORE the scoring loop so individual scoring calls hit module-level caches.

**Changes**: (1) `m7/orderflow/resolve.py`: Added `get_cached_decimals(token_addr)` — reads from `_enrichment_cache`, returns cached decimals or None. Added `batch_pre_resolve_pools(pool_addresses, rpc_url, block_num, addr_to_symbol)` — batch-resolves pool tokens via multicall (populates `_pool_token_cache`), batch-enriches unknown tokens (populates `_enrichment_cache`, updates `addr_to_symbol`). Returns `{pool_addr: {token0, token1, fee}}`. (2) `m7/orderflow/mode_ws_live.py`: Added cold-lane pre-pass before scoring loop — collects unique pool addresses from events, calls `batch_pre_resolve_pools()`, batch-preloads each discovered pair into `session_registry.preload_pair()`. All subsequent `score_backrun_live_parallel()` calls hit warm caches. Fixed `_hot_mode` variable ordering (was referenced before assignment). (3) `m7/orderflow/scoring_parallel.py`: Added `get_cached_decimals` import. Added cache fallback for `_token_in_dec` — calls `get_cached_decimals(token_in_addr)` BEFORE the well-known stablecoin heuristic. Fixes `size_valid_for_token=false` for batch-pre-enriched tokens. (4) `scripts/start_nonstop_runtime.py`: Critical blocking I/O fix — changed `stdout=subprocess.PIPE` to `stdout=subprocess.DEVNULL` and made `drain_output()` a no-op. Original blocking `readline()` prevented supervisor from reaching deadline check. (5) `scripts/m7a_orderflow_loop.py`: Hot artifact reporting fix — `_promoted_pairs` updated from `_cross_promoted` for accurate promoted_watchlist display. (6) Rolling canonical files: added `m7_promoted_pairs.json` to allowlists. (7) +14 tests in 4 new M7.A.5.40 classes (TestM7A540BatchPreResolve, TestM7A540GetCachedDecimals, TestM7A540ColdPrePassInModeWsLive, TestM7A540SizeValidCacheFallback).

**Online evidence**: 10.3-min nonstop (0 restarts) + 120-block replay. total_pipeline: 15.62ms warm (97% reduction from 1519ms cold). resolve_ms/enrichment_ms/registry_preload_ms: 0.0ms (100% elimination). Oracle only remaining RPC cost (~16-80ms). size_valid=100% warm. latency_budget_hit_rate=0.89. Promoted: 6 candidate + 6 execution. Supervisor DEVNULL fix eliminates blocking I/O.

CI: 3258 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.41–46: Hot-Lane Activation → Execution Funnel (CLOSED, compressed)

**M7.A.5.41**: Persist top candidates, fix hot fast_path token resolution (_pool_token_cache lookup instead of broken token_addresses.get). +top_executable_candidates, top_stale_positive_candidates, top_hot_candidates. CI: 3272 passed.

**M7.A.5.42**: Signal classification (4 tiers), diagnostic_raw (7 metrics), _ROLLING_EXCLUDE_KEYS, m7_cold_hot_bridge.json, hot_gap_debug counters, 3-section dashboard. CI: 3277 passed.

**M7.A.5.43**: Bridge-driven hot registry — pool_token_transport (63 entries), pool-address-first matching, near_executable tier, 3 hot-miss counters. Evidence: cold_executable_positive.count=3, best=68.69 bps. CI: 3291 passed.

**M7.A.5.44**: Execution funnel (5 stages), micro_refinement (5 size multipliers), verified_profitable check, bridge-hit counters. Evidence: first verified_profitable candidates (77.65, 73.81 bps). CI: 3310 passed.

**M7.A.5.45**: Bridge execution queue (priority_pools), hot intents artifact, headline_level enforcement. Evidence: schema intact, cold_executable_pool_count=2. CI: 3327 passed.

**M7.A.5.46**: Strip 13 legacy hypothesis blocks from live-path, compact build_replay_summary, fix hot cold_executable_positive semantic (reads from bridge, not synthesized), bridge pair fallback counter, dashboard restructure. CI: 3327 passed.

CI: 3327 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.47: Focused Hot Intake + Cumulative Rollup + Submit-Size Refinement (CLOSED)

**Changes**: Focused event intake (`bridge_pool_addresses` filter, up to 50 pools). Cumulative hot rollup (`m7_hot_rollup_latest.json`). 6 canonical hot miss counters. Submit-size refinement (multipliers, `gas_floor_gap_bps`, `verified_net_bps_after_refinement`). Dashboard rollup section.

**Online evidence**: Pending nonstop verification. CI: 3327 passed, 6 skipped. ALL GATES PASSED.

---

## M7.A.5.47b–47c: Hybrid Intake + Temporal Rollup + Activity-Aware Bridge (CLOSED)

47b: Hybrid intake (focused + broad fallback), activity-ranked selection, 4 rollup counters, split miss reason. 47c: Activity-aware bridge, hot-seen pool injection, adaptive broad fallback (50%), diagnostic histograms. 10.3-min nonstop: events=7, bridge_hits=0, ptt=56. CI: 3327 passed.

---

## M7.A.5.47d: Cross-Process Hot-Seen Backfill + 2-Bucket Bridge Ranking (CLOSED)

Cross-process bridge (hot rollup → cold → unresolved-pools list), cold priority-resolve via `batch_pre_resolve_pools()`, 2-bucket ranking (A=cold_exec, B=hot-seen resolved, fill=activity-ranked), adaptive cap 50→100. 10.2-min nonstop: hot_seen_unresolved_pool_count_max=3, events_seen_total=16, bridge_pool_hit_total=0. CI: 3327 passed.

---

## M7.A.5.47e: Hot-Rollup Semantic Correctness + Atomic Writes (CLOSED)

Counter disentanglement (watchlist_match_count, admitted_to_scoring, fast_path_scored_count), per-window 6-class dominant_hot_miss_reason, first_window_at via setdefault, atomic writes (_atomic_json_write), adaptive bridge_hit_deficit. Removed dead /api/intents. 17 new tests in test_hot_rollup_semantics.py. CI: 3344 passed.

---

## M7.A.5.47f: Funnel Concentration Diagnostics + Diversity Cap

**Hypothesis**: M7.A.5.47f = system sees 13 pair families at intake but final executable layer has near-zero — determine whether concentration is market-real or filter/ranking-induced.

**Changes**: (1) `m7/orderflow/artifacts.py`: `funnel_by_pair_top` (top 10 pair families × 5 funnel counts: seen, positive, stale_positive, cold_executable, gas_exceeds_gross), `pair_family_concentration` KPI (top-1 share at 3 funnel stages + unique_pair_families), `best_net_bps_any_anomaly` flag (|value| > 10000 bps → thin-liquidity artifact). (2) `scripts/m7a_orderflow_loop.py`: `candidate_source_breakdown` in bridge payload (cold_exec, near_exec, stale_positive, recent_active, hot_seen_backfill, ptt_total), diversity-aware bridge fill with `_FAMILY_CAP=8` per token-pair family. (3) 16 new tests in `test_pair_concentration.py`. (4) Updated `test_orderflow_artifacts.py` schema for `best_net_bps_any_anomaly`.

**Online evidence (10.2-min nonstop)**: 12 unique pair families seen. Intake concentration moderate (seen_top1_share=0.300). Positive concentration extreme (positive_top1_share=0.900, RAIN/WETH 9/9 stale). cold_executable_top1_share=0.0 — ALL results killed by either gas_exceeds_gross (60%+) or staleness. Bridge source: cold_exec=0, near_exec=5, stale_positive=5, hot_seen_backfill=10. **Diagnosis: concentration is FILTER-INDUCED** — gas economics kills all major pairs, RAIN/WETH survives gas but all stale. CI: 3360 passed, 6 skipped. ALL GATES PASSED.

---

## M7.A.5.47g: 3-Bucket Bridge + Stale-Pin TTL + Gas-Near Sizing + Adaptive Intake

**Hypothesis**: M7.A.5.47g = split the two filter blockers (gas economics and staleness) and force first hot bridge hit by prioritising stale-recovery and gas-near pools.

**Changes**: (1) `m7/orderflow/artifacts.py`: `cost_by_pair_family_top` (top 10 families by smallest |gas_gap_bps|), `staleness_by_pair_family_top` (top 10 by stale_positive_count), gas-near extended micro-refinement (`[1.0, 1.5, 2.0, 3.0]` for GAS_EXCEEDS_GROSS candidates vs standard `[0.75, 1.0, 1.25, 1.5]`), `is_gas_near` field in micro_refinement results. (2) `scripts/m7a_orderflow_loop.py`: 3-bucket bridge ranking (C1=stale_recovery from cold_stale_positive + TTL pins, C2=gas_near_survivor from near_executable GAS_EXCEEDS_GROSS, C3=diversity-aware activity fill), stale-pin TTL lifecycle (init=4, decrement each hot window, refresh on cold stale_positive), severe deficit escalation (wwe>=3 → bridge_hit_deficit_severe). (3) `m7/orderflow/mode_ws_live.py`: 3-tier broad fallback interval (severe=1, deficit=2, normal=3). (4) 25 new tests in `test_47g_bridge_and_sizing.py`. (5) Non-v3 venue check: V2+Algebra already active; Ve33/IziSwap/SyncSwap/Ambient available but not wired to M7 discovery.

CI: 3385 passed, 6 skipped. ALL GATES PASSED.

### M7.A.5.47h (exact-pool stale-recovery + gas-near-survivor + hot-seen promotion)

**Hypothesis**: M7.A.5.47h = hot-seen pools and cold exec/stale pools are disjoint sets. Force first bridge hit by: (a) tightening C1 to recoverable_stale only (lag ≤ 2, positive, size_valid), (b) filtering C2 to gross-positive families only, (c) auto-promoting resolved hot-seen pools into the focused bridge via TTL pin.

**Fresh 47g evidence** (10-min nonstop): cold viable_count=2, hot bridge_pool_hit_total=0 (event pools disjoint from bridge). 47h added hot-seen-pin promotion, recoverable_stale C1 tightening, gross-positive C2 filter.

### M7.A.5.47i (anomaly-clean recoverable stale + bridge hit detection isolation)

**Fresh 47h evidence**: cold REGRESSED (viable_count=0). Root cause: 3 bugs — (1) PRICING_ANOMALY at 36927 bps leaking through `_is_stale()` into C1, (2) single try/except wrapping registry-match AND PTT-hit — exception in registry silently killed bridge hit counting, (3) bridge file update using undefined `_bucket_a` etc → NameError silently caught.

**Fixes**: Strict `reject_reason == STALE_POSITIVE` filter, 3 independent try/except blocks for bridge hit detection, safe variable aliases, C2 gas tolerance `-10 bps`, bridge-miss auto-promote. 26 tests. CI: 3437 passed.

### M7.A.5.47j (bridge minimum floor + focused pool count + C2 tightening)

**Diagnosis**: 47i source correct but nonstop ran with pre-47i bytecode (`.pyc` timestamps prove edits applied AFTER nonstop ended).

**Changes**: (1) `_BRIDGE_MIN_FLOOR=20` — floor fill prevents bridge starvation. (2) `bridge_focused_pool_count` metric — tracks actual `len(_bridge_pool_addrs)` (all buckets), disambiguates from `bridge_loaded_candidate_count` (A-bucket only). (3) C2 tolerance tightened `-10` → `-5` bps. (4) All `__pycache__` cleared. (5) 24 tests.

CI: 3461 passed, 6 skipped.

### M7.A.5.47k (session-scoped rollup + stale_sub_reason + auto-pin ALL bridge-miss + route_viable split)

**Diagnosis**: Bridge race condition — cold lane overwrites bridge file without overlap/selected keys. Stale candidates lack sub-classification. Auto-promote only pinned active pools, missing direct bridge-miss events.

**Changes**: (1) Session-scoped hot rollup: `_SESSION_ID` detects supervisor restart, resets session counters. (2) Always emit `overlap`/`selected` as `[]` in cold bridge, not null. (3) `stale_sub_reason`: pipeline_abort / block_lag / state_recheck in `_compact_candidate()`. (4) Auto-pin ALL bridge-miss pools, not just `recent_active`. (5) Recoverable-stale split: `route_viable` / `not_viable` — C1 uses only route_viable. (6) C2 unknown-family safe default: skip, not admit. (7) `bridge_excluded_top` with 4 reason types. (8) 47 new tests (26 for 47k).

CI: 3487 passed, 6 skipped.

### M7.A.5.47l (cold-exec hard-pin + cold_exec_pool_trace + cut_stage_top + C1 block_lag filter)

**Hypothesis**: M7.A.5.47l = first hot bridge hit on the exact cold-executable pool `0xd13040d4fe917ee704158cfcb3338dcd2838b245`.

**Diagnosis**: Fresh 10-minute verification (April 7, 2026) confirms one cold executable-positive candidate (`0x25118290/WETH`, 110.96 bps, verified profitable) but hot conversion remains zero. The system cuts positive moments in three distinct places: broad-universe families die on gas economics (GAS_EXCEEDS_GROSS=20/30), RAIN/WETH-like families die on stale block lag (lag 3..8), and the surviving cold executable pool dies on hot overlap rather than on math.

**Changes**: (1) Cold-exec hard-pin: `_bridge_pool_addrs |= _bucket_a` after all assembly. (2) `bridge_selected_pools_top` populated at assembly time (never empty when bridge_focused_pool_count > 0). (3) `cold_exec_pool_trace` diagnostic: per-pool `in_bridge`, `hot_events_this_window`, `fast_score_attempted`, `registry_match`. (4) C1 stale filter: skip `stale_sub_reason=block_lag` (lag 3..8 not recoverable). (5) `cut_stage_top` artifact: machine-readable summary of WHERE each positive dies — `economics`, `stale_block_lag`, `stale_pipeline_abort`, `stale_state_recheck`, `viable`. (6) `bridge_excluded_top` persisted into bridge file. (7) 21 new tests.

CI: 3508 passed, 6 skipped.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase, closed by default. Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.

---

## Canonical Commands

```
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/ci_full_pipeline.py --mode ci
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5
```

## Known Blockers

1. **cold_executable_count=2** (improved from 0) — RAIN/WETH and 0x25118290/WETH at `0xd130...` viable at 37-49 bps. Gas economics kills other families.
2. **bridge_pool_hit_total=0** — hot lane events arrive at pools DISJOINT from cold exec/stale pools. 47h adds hot-seen-pin promotion (auto-bridge resolved hot-seen pools), recoverable_stale C1 tightening, gross-positive C2 filter.
3. **Subgraph 403** — enrichment breadth limited to V3 local adapter only.
4. **Truth split**: current M7 live mode = `next_block_continuation` (subscribe newHeads → eth_getLogs for mined block). NOT true same-block backrun. If goal is same-block sequencer advantage, separate track needed.

## Next steps

1. Run 10-min nonstop with 47j bytecode (all `__pycache__` cleared) — verify target fields:
   - `bridge_pool_hit_total` > 0
   - `fast_path_scored_total` > 0
   - `hot_seen_vs_bridge_overlap_top` not null (always list)
   - `cold_recoverable_stale` contains only STALE_POSITIVE (no PRICING_ANOMALY)
   - `bridge_focused_pool_count_last` shows actual bridge size (should be ≥ 20 if PTT ≥ 20)
2. Check `bridge_focused_pool_count_last` vs `bridge_loaded_candidate_count_total` to confirm bridge isn't collapsing.
3. If first bridge hit achieved, measure conversion rate of stale_recovery vs hot-seen-pin vs gas_near buckets.
4. If deficit remains, consider onboarding lower-gas chain (Base) or widening adapter surface.
