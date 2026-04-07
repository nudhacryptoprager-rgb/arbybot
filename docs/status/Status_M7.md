# Status: M7 (Triangular Feasibility)

**Status**: **M7.E1 OPEN — Base event-source pilot validates swap event availability** (M7 Arbitrum mainline FROZEN per 47s. M7.E1 Base pilot: 734 raw V3 Swap logs in 10 blocks (73.4/block avg), 10/10 same-block scored, sole blocker=GAS_EXCEEDS_GROSS at best -2.28 bps. Event source works — gas economics is new frontier.)  
**Updated**: 2026-04-07
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

**M7.A.5.46**: Strip 13 legacy hypothesis blocks from live-path, compact build_replay_summary, fix hot cold_executable_positive semantic (reads from bridge, not synthesized), bridge pair fallback counter, dashboard restructure. CI: 3327 passed.

CI: 3327 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

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

1. **EVENT-SOURCE CEILING — FROZEN (Arbitrum only)** — 3 consecutive proof runs (47q, 47r, 47s) confirm `architecture_blocker_trace.blocker_class=event_source_absence` on Arbitrum One. **Does NOT apply to Base** — M7.E1 pilot confirms 734 swap logs in 10 blocks (73.4/block avg).
2. **GAS_EXCEEDS_GROSS — ACTIVE (Base)** — All 10 Base events rejected by gas economics. best_net_bps=-2.28 (close to breakeven). New frontier: gas optimization, larger trade sizes, or L1 data cost reduction.
3. **Flashblocks WS DNS unreachable** — `base.flashblocks.base.org` does not resolve from local machine. Sub-block delivery untested. Alchemy WS fallback works.
4. **Subgraph 403** — enrichment breadth limited to V3 local adapter only.

## Next steps

1. **M7 Arbitrum mainline remains FROZEN.** No further changes to Arbitrum M7 scoring/bridge logic.
2. **M7.E1 Base pilot OPEN — event source validated.** Next priorities:
   - Priority 1: Resolve Flashblocks WS connectivity (alternative endpoints, HTTP polling, or WSS via different provider) for sub-block (<200ms) event delivery.
   - Priority 2: Gas economics optimization — larger trade sizes, L1 data cost analysis, gas_floor_bps tuning for Base.
   - Priority 3: Multi-iteration nonstop run on Base (10+ min) with full hot/cold bridge cycle to assess family-level bridge convergence.
   - Priority 4: If gas breakeven achieved → Tenderly simulation validation.
3. **Source plane validated — gas plane is new frontier**: Event-source absence blocker does NOT exist on Base. The bottleneck shifted to gas economics (GAS_EXCEEDS_GROSS at -2.28 bps best).
4. **Diagnostic toolkit proven on Base**: scoring pipeline works (100% same-block, 57-103ms latency), pool discovery healthy (35 known, 19 active), coverage complete (no_counter_pool_rate=0.0).
