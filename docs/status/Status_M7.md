# Status: M7 (Triangular Feasibility)

**Status**: **M7.E1.4 OPEN — convergence fields + viable_total prove repeatable Base signal** (M7 Arbitrum mainline FROZEN per 47s. E1.4 adds cold-hot convergence fields (pool_address, family, selected_bucket, same_pool_as_cold_exec) to hot intents and viable_total counter to rollup. 3x consecutive 10-min Base runs: cumulative fast_path_positive_total=31, viable_total=19, profit_guard_passed_total=31, matched_then_scored_positive_total=14. Each run added 3-4 positive events — repeatability confirmed. CI: 3741 passed, 6 skipped.)  
**Updated**: 2026-04-08
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

**Key findings**: All cycles negative at all sizes. U-shaped cost curves. 6/6 blockers stable. All top cycles ARB→USDC→WETH→ARB. Route failure 33%. Gross sometimes positive but gas+fees push net negative. Bounded-scope — does not prove absence of edge on other surfaces/chains.

**Blocker tags**: `GROSS_NEGATIVE_CORE`, `GAS_DOMINANT_SMALL`, `SLIPPAGE_DOMINANT_LARGE`, `THIRD_LEG_FEE_BINDING`, `SINGLE_TRIPLE_CONCENTRATION`, `QUOTE_FAILURE_BREADTH_LIMIT`.

### Modules

- `engine/triangular_graph.py`, `engine/triangular_cycles.py` — graph, cycle discovery, scoring
- `scripts/m7a_enumerate_cycles.py` — CLI for sweep/verdict/repeatability
- `scripts/m7a_orderflow_replay.py` — M7.A.4/M7.A.5 event-driven replay and ws-live
- Tests: 152 in `test_triangular_*.py`, 369 in `test_orderflow_*.py`

---

## M7.A.4: Orderflow-Driven Backrun/Replay Hypothesis

**Offline evidence**: 5 events, best_net=-1.55 bps (better than triangular, worse than two-leg). Intent scout: `block_event_backrun` = highest feasibility. M7.A.4 is a closed bounded baseline.

---

## M7.A.5: Live Block-Event Backrun Replay

**Hypothesis**: `block_event_backrun` on arbitrum_one may produce viable edge with real block events and live quotes.

**Infrastructure**: `fetch_recent_swap_events()` (chunked `eth_getLogs`), `normalize_swap_log()`, `score_backrun_live()` (two-pass buy/sell via `read_quoter_v2`). `--live-blocks N` CLI.

**Evidence — M7.A.5.1 (public RPC)**: 2 runs (100/500 blocks), best_net=-18.36 bps, 0 viable, all stale (mean_lag=218), GAS_EXCEEDS_GROSS on 15/15.

**Evidence — M7.A.5.2 (Alchemy RPC)**: 100 blocks, 20 events, best_net=-19.49 bps, 0 viable, all stale (mean_lag=59.55), 0 low-lag events. Alchemy resolves correctly but sequential pipeline bakes in lag.

**M7.A.5 combined verdict**: Surface NOT VIABLE via either public or Alchemy RPC. Bottleneck is sequential block-polling architecture, not RPC provider latency.

**CI gates**: 2821 passed, 6 skipped. 85 tests in `test_orderflow_contracts.py`.

---

## M7.A.5.3–5.29: WebSocket, Pruning, Resolution, Coverage, Enrichment, Scoring, Refactors (CLOSED, compressed)

**5.3–5.5**: WS-live NOT VIABLE (quote pipeline ~2.3s per event). Two-stage multicall NOT VIABLE. Actual-pair resolution CONFIRMED but IMMATERIAL. CI: 2849→2887.
**5.6–5.8**: Coverage decomposition (80% TOKEN_NOT_ADMITTED, 13 reject reasons). Enrichment infra. Gas decomposition (L1 80%, L2 20%). Subgraph BLOCKED (403). CI: 2923→2961.
**5.9–5.24**: Decimal fix, stale gate, byte-parsing breakthrough (26 scored, was 0), stale/low-lag split, pool-class truth, V2 direct resolve, local pricing, factory-driven registry, pipeline slim. CI: 2988→3310.
**5.25–5.29**: Detection-time truth, m7/ package extraction, test consolidation, continuous loop, hot/cold split. CI: 3104→3124.

---

## M7.A.5.30: Hot Execution Lane + Latency Telemetry + Profit Guard (CLOSED)

Fixed `last_nonempty_timestamp` + `BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY` semantics. Added `resolve_ms`/`enrichment_ms` timers + `m7a530_latency_breakdown`. Hot/cold lane split: `--lane cold` (full diagnostic) vs `--lane hot` (tight window, m7_hot_latest.json). Created `m7/orderflow/profit_guard.py` (Flashbots simple-blind-arb pattern). +11 tests. CI: 3140 passed.

---

## M7.A.5.31: Hot Lane to Decision + Profit Guard + Timeboost Eligibility (CLOSED)

Dashboard Panel 11 reads both cold + m7_hot. Discovery solved (registry_direct=30/30), viable_count=0 due to completion latency ~1544ms vs 250ms. Fixed `last_nonempty_timestamp` and `REMOTE_QUOTER_LATENCY` bugs. Latency: resolve_ms≈935, registry_preload_ms≈449, oracle_ms≈117. `run_ws_live()` accepts `external_registry` for hot lane prewarm. CI: 3155 passed.

---

## M7.A.5.32: Unified Nonstop Runtime + Rolling Retention + Hot-Path Slimming

`start_nonstop_runtime.py` — unified supervisor. `prune_tmp_artifacts.py` — retention. `score_backrun_fast()` with 250ms stage budgets, zero subgraph/oracle/enrichment. HOT_BUDGET_* constants, HOT_WATCHLIST_PAIRS. `_rolling/` cleaned to canonical 9 files. +14 tests. CI: 3163 passed.

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

Batch pre-resolve ALL event pools BEFORE scoring loop — eliminates per-event resolve/enrichment/registry_preload RPC. `batch_pre_resolve_pools()` in resolve.py, cold-lane pre-pass in mode_ws_live.py, `get_cached_decimals()` fallback in scoring_parallel.py. Supervisor blocking I/O fix (PIPE→DEVNULL). Evidence: total_pipeline 15.62ms warm (97% reduction), resolve/enrichment/registry_preload=0ms. CI: 3258 passed.

---

## M7.A.5.41–46: Hot-Lane Activation → Execution Funnel (CLOSED, compressed)

**M7.A.5.41**: Persist top candidates, fix hot fast_path token resolution (_pool_token_cache lookup instead of broken token_addresses.get). +top_executable_candidates, top_stale_positive_candidates, top_hot_candidates. CI: 3272 passed.

**M7.A.5.42**: Signal classification (4 tiers), diagnostic_raw (7 metrics), _ROLLING_EXCLUDE_KEYS, m7_cold_hot_bridge.json, hot_gap_debug counters, 3-section dashboard. CI: 3277 passed.

**M7.A.5.43**: Bridge-driven hot registry — pool_token_transport (63 entries), pool-address-first matching, near_executable tier, 3 hot-miss counters. Evidence: cold_executable_positive.count=3, best=68.69 bps. CI: 3291 passed.

**M7.A.5.44**: Execution funnel (5 stages), micro_refinement (5 size multipliers), verified_profitable check, bridge-hit counters. Evidence: first verified_profitable candidates (77.65, 73.81 bps). CI: 3310 passed.

**M7.A.5.45**: Bridge execution queue (priority_pools), hot intents artifact, headline_level enforcement. Evidence: schema intact, cold_executable_pool_count=2. CI: 3327 passed.

**M7.A.5.46**: Strip 13 legacy hypothesis blocks from live-path, compact build_replay_summary, fix hot cold_executable_positive semantic (reads from bridge, not synthesized), bridge pair fallback counter, dashboard restructure. CI: 3327 passed, 6 skipped. Safety: PASS.

---

## M7.A.5.47: Focused Hot Intake + Cumulative Rollup + Submit-Size Refinement (CLOSED)

**Changes**: Focused event intake (`bridge_pool_addresses` filter, up to 50 pools). Cumulative hot rollup (`m7_hot_rollup_latest.json`). 6 canonical hot miss counters. Submit-size refinement (multipliers, `gas_floor_gap_bps`, `verified_net_bps_after_refinement`). Dashboard rollup section.

**Online evidence**: Pending nonstop verification. CI: 3327 passed, 6 skipped. ALL GATES PASSED.

---

## M7.A.5.47b–47g: Hybrid Intake + Rollup + Activity Bridge + 3-Bucket + Stale-Pin (CLOSED, compressed)

47b–47c: Hybrid intake (focused + broad fallback), activity-ranked selection, hot-seen pool injection. 47d: Cross-process hot-seen backfill, 2-bucket bridge ranking, adaptive cap 50→100. 47e: Counter disentanglement, atomic writes, adaptive deficit. 47f: Funnel concentration diagnostics, diversity cap. 47g: 3-bucket bridge (C1=stale_recovery, C2=gas_near_survivor, C3=activity fill), stale-pin TTL, severe deficit escalation. CI: 3327→3385.

### M7.A.5.47h–47n (bridge truth convergence, compressed)

**47h–47j**: Exact-pool stale-recovery, anomaly-clean, bridge hit isolation, bridge minimum floor, focused pool count, hot-seen pin promotion. C2 gas tolerance tightened from -10 to -5 bps. CI: 3437→3461.
**47k–47n**: Session-scoped rollup, auto-pin, cold-exec hard-pin, truthful bridge diagnostics, run_context, cross-artifact truth, exact-pool session trace. Fixed cold/hot race condition. CI: 3487→3551.

### M7.A.5.47o–47r (architecture blocker convergence, compressed)

**47o**: Session reset fix, gas-hopeless C3 tightening, other_live_pool_trace. `bridge_focused_pool_count=37`. CI: 3582.
**47p**: Cross-artifact trace, bridge_selection_diff, live-miss auto-pin, family_unresolved sentinel. CI: 3609.
**47q**: Family-level event trace, sibling-pool pinning, stale separation. `exact_family_trace` confirms family-wide starvation: ALL 10 families with `reason_if_zero=no_events_at_any_family_pool`. CI: 3645.
**47r**: Cross-artifact contract closure, `architecture_blocker_trace` canonical (25 families selected, 0 with events, `blocker_class=event_source_absence`). `family_unresolved` excluded at 4 points. 26 new tests. CI: 3671.

### M7.A.5.47s (FREEZE — final peak-hours proof confirms event-source ceiling)

**Goal**: M7.A.5.47s = freeze mainline on event-source ceiling unless one final peak-hours proof shows family-level events.

**No code changes in 47s.** 47r code is the final M7 mainline state.

**Evidence** (10-min nonstop, April 7, 18:39-18:50Z — tail of peak window): `architecture_blocker_trace`: `families_selected_count=25`, `families_with_any_hot_events=0`, `families_with_exact_hits=0`, `blocker_class=event_source_absence`. `session_windows_seen=6`, `session_events_seen_total=4` (some events exist but not at bridge pools). `session_bridge_pool_hit_total=0`. `bridge_selected_family_diff_top`: 25 families, 0 with events. `family_unresolved=0` in bridge. Cold lane: `cold_executable_positive=0`, `diagnostic_positive=2 (30.6 bps)`, `stale_positive=2`.

**Freeze decision**: Per escalation rule (47q → 47r → 47s): 3 consecutive runs, all show `families_with_any_hot_events=0` and `session_bridge_pool_hit_total=0`. M7 mainline is **FROZEN** on event-source ceiling.

Fresh M7.A.5.47r evidence confirms that the main blocker is no longer bridge selection, scoring, or cross-artifact inconsistency — 25 resolved families are selected, bridge contracts are fully consistent, and the architecture_blocker_trace canonically classifies the blocker as `event_source_absence`. The current `newHeads + logs` event source on Arbitrum One does not deliver family-level swap events at bridge-selected pools during any proof window. Public 2026 evidence (flashbots/simple-arbitrage profitability analysis, MEV-in-Binance-Builder (2602.15395), Optimistic MEV in L2s (2506.14768)) confirms that profitable graph/cyclic arb requires privileged orderflow, protocol-native positioning, builder/ordering edge, or ultra-low-latency infra — none of which M7 has. The diagnostic toolkit (architecture_blocker_trace, bridge_selected_family_diff_top, exact_family_trace) is proven and ready for any new chain/event-source assessment.

**Recommendation**: Open `M7.E1 = event-source pilot` research track. Priorities: (1) alternative chain with higher event density (Base), (2) provider-specific early feed, (3) private/privileged orderflow, (4) ordering/inclusion experiments — only after a setup that produces family-level events. Source plane first, not Timeboost.

CI: 3671 passed, 6 skipped (no code changes — 47r tests are the final mainline baseline).

---

## M7.E1: Base Flashblocks Event-Source Pilot (OPEN)

**Hypothesis**: Base chain delivers abundant V3 Swap events via standard newHeads+logs, enabling low-hop graph/backrun arbitrage scoring that was impossible on Arbitrum (event_source_absence).

**Infrastructure changes**:
- `m7/shared/constants.py`: Chain-aware helpers (get_prewarm_pairs, get_chainlink_feeds, get_gas_floor_bps) + Base-specific constants (PREWARM_PAIRS_BASE, CHAINLINK_FEEDS_BASE, GAS_FLOOR_BPS_BASE=0.5)
- `m7/orderflow/mode_ws_live.py`: Chain-aware prewarm, Flashblocks WS preference with connectivity test + fallback, chain param to build_replay_summary
- `m7/orderflow/artifacts.py`: build_replay_summary accepts chain parameter
- `scripts/start_nonstop_runtime.py`: --chain argument passthrough to M7 lanes
- 27 new tests in `test_e1_base_chain_aware.py`

**Evidence — M7.E1 pilot (April 7, 19:42-19:47Z)**:

| Metric | Value |
|--------|-------|
| chain | base |
| blocks_processed | 10 |
| raw_logs_total | 734 (73.4/block avg) |
| events_scored | 10 |
| same_block_count | 10 (100%) |
| best_net_bps | -2.28 (5-block), -10.20 (10-block) |
| reject_histogram | GAS_EXCEEDS_GROSS: 10 |
| latency_budget_ms | 2000 |
| latency_budget_hit_rate | 1.0 |
| mean_pipeline_latency_ms | 57.8-103.2 |
| known_pools | 35 |
| active_pools | 19 |
| sub_block_capable | true |
| ws_provider | alchemy |
| flashblocks_ws | DNS unreachable (fallback to Alchemy) |

**Key findings**:
1. Base delivers 183x more swap events per block than Arbitrum One (73.4 vs ~0.4).
2. All events scored at same-block (lag=0) — 2000ms block time provides ample scoring budget.
3. Sole blocker is GAS_EXCEEDS_GROSS (best -2.28 bps, close to breakeven), NOT event_source_absence.
4. Flashblocks WS (`base.flashblocks.base.org`) DNS unreachable; Alchemy WS fallback works.
5. Near-executable signal found: AMONGUS/WETH at -10.20 bps.

External 2025–2026 evidence aligns with the local freeze result: profitable short-hop graph arbitrage on L2s requires either rich event flow (now confirmed on Base) or privileged ordering. Base preconfirm feeds (Flashblocks) are a candidate for structural timing advantage if DNS issues are resolved.

CI: 3698 passed, 6 skipped.

### M7.E1.1: Full Hot/Cold Nonstop Validation (April 7, 20:23-20:33Z)

**Goal**: Prove Base remains gas-blocked after full 10-min hot/cold nonstop, not just cold-only pilot.

**Code changes**: `artifacts.py` — per-candidate gas breakdown (l1_data_gas_bps, l2_exec_gas_bps, total_gas_bps, gap_to_zero_bps). 4 new tests. CI: 3702 passed, 6 skipped.

**Evidence (10-min nonstop, 20:23-20:33Z)**:

| Metric | E1 (cold) | E1.1 (hot+cold) |
|--------|-----------|------------------|
| events_scored | 10 | 30 |
| GAS_EXCEEDS_GROSS | 10/10 | 26/30 (86.7%) |
| best_near_exec_bps | -10.20 | **-2.20** |
| bridge_selected_pools | 0 | 30 |
| hot_windows / events | 0/0 | 177/82 |
| l1_data / l2_exec / total gas bps | N/A | 0.16 / 0.04 / 0.20 |
| supervisor restarts | N/A | 0 (3/3 alive) |

**Findings**: (1) Hot/cold bridge exercised — 30 pools selected, 38 focused, promoted_watchlist=5 pairs. (2) Hot artifacts Base-origin (was Arbitrum-era). (3) GAS_EXCEEDS_GROSS sole blocker — L1 data 80% of gas. (4) Near-executable frontier narrowed -10.20→-2.20 bps. (5) USDC/WETH narrow contour at -9.16 gap; wider pairs closer to breakeven. (6) AMONGUS/WETH in watchlist but NOT near-executable. (7) Flashblocks untested (separate subtask).

CI: 3702 passed, 6 skipped (3698 + 4 new gas breakdown tests).

### M7.E1.2: Hot Blocker Separation — Arbitrum Contamination Fix (April 7, 21:38-21:41Z)

**Goal**: Separate Base cold gas blocker from Base hot overlap/registry blocker. E1.1 review found that `architecture_blocker_trace` still showed Arbitrum-era values (`blocker_class=event_source_absence`, `pool_address=0xd13040...`, `family=family_unresolved`) on Base — a false diagnosis caused by hardcoded Arbitrum target pool.

**Code changes (3 files)**:
- `scripts/m7a_orderflow_loop.py` — (1) Dynamic `_TARGET_POOL` selection from `bridge_selected_at_assembly` (picks first A_cold_exec, falls back to any pool, None if empty). (2) Four new event-to-bridge classification counters: `events_in_bridge_total`, `events_not_in_bridge_total`, `matched_then_gas_rejected_total`, `matched_then_scored_positive_total`. (3) Three-way `blocker_class`: `event_source_absence` | `events_not_reaching_bridge` | `gas_economics_only` | `selection_or_scoring`. (4) `families_with_any_hot_events` now cumulative across ALL bridge families.
- `m7/orderflow/mode_ws_live.py` — Fixed `KeyError: 'stage_a_ms'` in stage latency aggregation (`.get()` instead of `[]` indexing) — this bug silently crashed every hot iteration, preventing rollup writes.
- `tests/unit/test_47r_cross_artifact_contract.py` — Updated `_build_architecture_blocker_trace` helper for three-way classification; added `test_families_with_any_hot_events_uses_all_families`.
- `tests/unit/test_e1_base_chain_aware.py` — 3 new test classes (14 tests): `TestE1_2_DynamicTargetPoolSelection` (4), `TestE1_2_EventBridgeClassification` (6), `TestE1_2_BlockerClassification` (4). Includes source-level invariant `test_no_hardcoded_arbitrum_pool_in_production`.

CI: 3718 passed, 6 skipped (3702 + 16 new E1.2 tests).

**Evidence (3-min nonstop, 21:38-21:41Z)**:

| Metric | E1.1 (pre-fix) | E1.2 (post-fix) |
|--------|----------------|------------------|
| `blocker_class` | `event_source_absence` (FALSE) | **`gas_economics_only`** (CORRECT) |
| `families_with_any_hot_events` | 0 (single-family check) | **9/17** (all-family check) |
| `exact_pool_trace.pool_address` | `0xd13040...` (Arbitrum) | **`0x6f79e0...`** (Base) |
| `exact_family_trace.family` | `family_unresolved` | **`0x8335.../0xe0cd...`** (resolved) |
| `events_in_bridge_total` | N/A | **12** |
| `events_not_in_bridge_total` | N/A | **7** |
| `matched_then_gas_rejected_total` | N/A | **12** (all) |
| `matched_then_scored_positive_total` | N/A | **0** |
| `bridge_pool_hit_total` | 0 (never 0 — rollup not written) | **16** |
| `session_bridge_pool_hit_total` | 0 | **14** |
| hot rollup written? | NO (`stage_a_ms` crash) | **YES** |

**Findings**:
1. **Arbitrum contamination is the root cause**: Hardcoded `_TARGET_POOL = 0xd13040...` (Arbitrum) meant all trace diagnostics were chain-foreign on Base. `exact_pool_trace` always showed `not_in_bridge` (Arbitrum pool not in Base bridge). `exact_family_trace` couldn't resolve family via PTT (Arbitrum pool → `family_unresolved`). `architecture_blocker_trace.families_with_any_hot_events` checked only the unresolved family → 0 → false `event_source_absence`.
2. **Hot lane was silently crashing**: `mode_ws_live.py` stage latency aggregation used `dict["stage_a_ms"]` instead of `.get()`. When live results had `pipeline_stage_latency_ms` without `stage_a_ms` key, every hot iteration raised `KeyError` — caught by the outer try/except, hot continued retrying but never reached `_update_hot_rollup()`. 3/3 supervisor "alive" masked the failure.
3. **Base hot lane IS gas-blocked, not architecture-blocked**: With fixed traces, 12/12 bridge-matching events are gas-killed. 9/17 bridge families see hot events. `blocker_class=gas_economics_only` is the correct three-way classification.
4. **E1.1 conclusion was correct but unprovable**: The "gas economics sole blocker" narrative was true for both cold and hot lanes, but E1.1 artifacts couldn't prove it due to contamination. E1.2 now proves it with clean chain-native traces.

### M7.E1.3: Registry vs Gas Counter Separation + Chain-Purity Invariant (April 8, 07:10-07:21Z)

**Goal**: Reconcile Base hot artifacts with Base cold gas blocker. E1.2 review found `matched_then_gas_rejected` conflated two orthogonal blocker types (registry rejection vs gas rejection). Separate them to determine if Base hot zero-hit is a registry/overlap issue or truly gas-only.

**Code changes (2 files)**:
- `scripts/m7a_orderflow_loop.py` — (1) Split conflated `matched_then_gas_rejected_total` in rollup into `matched_then_registry_rejected_total` (in bridge + hot_skip) + `matched_then_gas_rejected_total` (in bridge + registry_fast + net<=0). Added `matched_then_scored_positive_total` (in bridge + net>0). (2) Added 3 per-iteration counters to `hot_gap_debug`: `matched_bridge_then_registry_rejected`, `matched_bridge_then_gas_rejected`, `matched_bridge_then_scored_positive`.
- `tests/unit/test_e1_base_chain_aware.py` — Fixed conflated E1.2 test (split into 2 tests for registry vs gas). Added Section 12: `TestE1_3_ChainPurityInvariant` (4 tests — Arbitrum contamination addresses, family_unresolved detection, source-level hardcoded pool check). Added Section 13: `TestE1_3_RegistryVsGasSeparation` (6 tests — bridge_registry_rejected, bridge_gas_rejected, bridge_scored_positive, not_in_bridge_ignored, sum invariant).

CI: 3728 passed, 6 skipped (3718 + 10 new E1.3 tests).

**Evidence (10-min nonstop, 07:10-07:21Z)**:

| Metric | E1.2 (conflated) | E1.3 (separated) |
|--------|-------------------|-------------------|
| `matched_then_registry_rejected_total` | N/A (was lumped in gas) | **0** |
| `matched_then_gas_rejected_total` | 12 (conflated) | **44** |
| `matched_then_scored_positive_total` | 0 | **6** |
| `events_in_bridge_total` | 12 | **50** |
| `blocker_class` | `gas_economics_only` | **`selection_or_scoring`** |
| `families_with_any_hot_events` | 9/17 | **19/27** |
| `cold_executable_count` | 0 | **3** (W/WETH +92.63, CRV/WETH +59.08, doginme/WETH +24.08 bps) |
| `hot viable_count` (final iteration) | 0 | **1** |
| `near_executable_count` | 5 | **5** (best -2.20 bps) |
| supervisor restarts | 0 | **0** (3/3 alive, clean shutdown) |

**Findings**:
1. **Registry rejection is definitively NOT a blocker**: 0/50 bridge events are registry-rejected. All events that reach bridge pools pass the hot registry check.
2. **Gas is the majority blocker but NOT the only one**: 44/50 (88%) bridge events are gas-rejected. But 6/50 (12%) score positive, proving some events have viable economics.
3. **Viable signal exists on Base**: Cold lane found 3 executable candidates with strong positive bps (<92.63 bps). Hot lane achieved viable_count=1 in the final iteration. This was hidden by E1.2's conflated counter.
4. **blocker_class correctly upgraded**: `selection_or_scoring` (was `gas_economics_only`) because `matched_then_scored_positive_total > 0`. The three-way classifier works as designed.
5. **E1.2 narrative was incomplete**: E1.2 said "gas_economics_only" based on 3-min run where 12/12 bridge events were gas-killed. The 10-min E1.3 run with 50 bridge events reveals a more nuanced picture — most are gas-blocked but some break through.
6. **Counter sum invariant holds**: 0 + 44 + 6 = 50 = `events_in_bridge_total` ✓

### M7.E1.4: Convergence Fields + Viable Funnel Counter + Repeatability Proof (April 8, 08:07-08:40Z)

**Goal**: Convert Base scored-positive events into repeatable submit-ready candidates. Add cold-hot convergence fields to hot intents for cross-referencing. Add viable_total funnel counter to rollup. Prove repeatability across 3 consecutive 10-min runs.

**Code changes (2 files)**:
- `scripts/m7a_orderflow_loop.py` — (1) Hot intents convergence: build 3 lookup structures from bridge (cold_exec_pool_set, selected_pool_info from bridge_selected_pools_top, pool_token_transport for family fallback). Added 4 new fields per intent row: `pool_address`, `family`, `selected_bucket`, `same_pool_as_cold_exec`. (2) Rollup: added `viable_total` counter (sum of route_viable=True per window, cumulative) between fast_path_positive_total and profit_guard_passed_total.
- `tests/unit/test_e1_base_chain_aware.py` — Section 14: `TestE1_4_IntentConvergenceFields` (8 tests — pool_address present/none, family from selected_pools, family fallback to PTT, same_pool_as_cold_exec true/false/empty, selected_bucket none). Section 15: `TestE1_4_FunnelCounters` (5 tests — viable_total accumulates, funnel ordering, zero when no viable, counts only viable, schema key).

CI: 3741 passed, 6 skipped (3728 + 13 new E1.4 tests).

**Evidence (3x 10-min nonstop, 08:07-08:40Z)**:

| Metric | Run #1 (0-10min) | Run #2 (Δ 10-20min) | Run #3 (Δ 20-30min) | Cumulative |
|--------|-------------------|---------------------|---------------------|------------|
| `windows_seen` | 227 | +21 | +21 | 269 |
| `events_seen_total` | 326 | +100 | +100 | 526 |
| `fast_path_scored_total` | 143 | +71 | +64 | 278 |
| `fast_path_positive_total` | 24 | +3 | +4 | **31** |
| `viable_total` | 12 | +3 | +4 | **19** |
| `profit_guard_passed_total` | 24 | +3 | +4 | **31** |
| `matched_then_scored_positive_total` | 11 | +2 | +1 | **14** |
| `matched_then_gas_rejected_total` | 79 | +53 | +42 | 174 |
| `matched_then_registry_rejected_total` | 0 | 0 | 0 | **0** |
| supervisor restarts | 0 | 0 | 0 | **0** |

**Convergence fields in hot intents (sample)**:
- BRETT/WETH: pool_address=0x4e82..., family=WETH/BRETT (PTT), selected_bucket=null, same_pool_as_cold_exec=false, net_bps=+40.16, profit_guard_passed=true
- token1_in/USDC: pool_address=0x6524..., family=USDC/token1 (PTT), selected_bucket=A_cold_exec, same_pool_as_cold_exec=false
- cold_executable_count=0 (cold lane produced no executables in short runs)

**Findings**:
1. **Repeatability confirmed**: All 3 runs produced positive events (24, +3, +4). No run dropped to zero. Pattern is consistent: ~10% of scored events are positive.
2. **viable_total tracks the economics funnel**: 19 viable out of 31 positive. The gap (31 positive − 19 viable) represents events with net_bps>0 but failing route-level economics (gas_exceeds_gross or fee decomposition).
3. **Convergence fields functional**: pool_address, family, selected_bucket all populated. `selected_bucket=A_cold_exec` appears for bridge-matched intents. `same_pool_as_cold_exec=false` for all hot intents (cold lane found 0 executables in short runs — longer cold runs may improve).
4. **Cold-hot convergence gap persists**: Hot winners (BRETT/WETH +40 bps) don't match cold winners from E1.3 (W/WETH, CRV/WETH, doginme/WETH). This is expected — cold and hot windows sample different market states.
5. **Registry rejection remains zero**: 0/188 bridge events registry-rejected across all 3 runs. The hot pool registry is not a bottleneck.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.

---

## Canonical Commands

```
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/ci_full_pipeline.py --mode ci
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5
```

## Known Blockers

1. **EVENT-SOURCE CEILING — FROZEN (Arbitrum only)** — 3 consecutive proof runs (47q, 47r, 47s) confirm `architecture_blocker_trace.blocker_class=event_source_absence` on Arbitrum One. **Does NOT apply to Base** — E1.4 confirms 14 bridge-scored-positive events across 3 consecutive runs.
2. **GAS_EXCEEDS_GROSS — MAJORITY BLOCKER (Base, both lanes)** — E1.4: 174/188 (93%) bridge events gas-rejected across 3 runs. But 14/188 (7%) score positive, proving viable economics exist for a subset.
3. **COLD-HOT CONVERGENCE GAP** — Hot winners (BRETT/WETH +40 bps) don't match E1.3 cold winners (W/WETH, CRV/WETH, doginme/WETH). Short cold runs produce 0 executables. Longer cold runs or targeted cold contour may improve overlap.
4. **Flashblocks WS DNS unreachable** — `base.flashblocks.base.org` does not resolve from local machine. Sub-block delivery untested. Alchemy WS fallback works.
5. **Subgraph 403** — enrichment breadth limited to V3 local adapter only.

## Next steps

1. **M7 Arbitrum mainline FROZEN.** No further Arbitrum M7 scoring/bridge changes.
2. **Submit-stage simulation (E1.5)**: E1.4 proved repeatability of positive events. Next: Tenderly simulation for top positive-scored hot intents to validate submit-readiness. Requires: (a) select top intent with pool_address + family + profit_guard_passed. (b) build calldata. (c) simulate via Tenderly fork.
3. **Cold-hot convergence improvement**: Run longer cold lanes (30-60 min) to populate cold_executable. Then cross-reference same_pool_as_cold_exec=true intents.
4. **Gas economics optimization**: 174/188 bridge events gas-rejected. Priorities: (a) L1 data cost reduction. (b) gas_floor_bps tuning for Base. (c) Flashblocks WS for sub-block delivery.
5. **Family symbol resolution**: Hot intents show raw address families (0x4200.../0x5326...) instead of human-readable symbols. Add token symbol lookup to convergence fields.
