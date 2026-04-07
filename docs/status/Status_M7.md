# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.47e. M7.A.5.47e fixes hot-rollup semantics: disentangled counters, per-window miss classification, atomic writes, first_window_at, bridge_hit_deficit adaptive logic. 3344 tests pass, all CI gates green. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B closed.)  
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

`funnel_by_pair_top` (5 funnel counts per pair family), `pair_family_concentration` KPI, `best_net_bps_any_anomaly` flag. Diversity-aware bridge fill with `_FAMILY_CAP=8`. Evidence: concentration is FILTER-INDUCED — gas kills major pairs, RAIN/WETH stale. CI: 3360 passed.

---

## M7.A.5.47g: 3-Bucket Bridge + Stale-Pin TTL + Gas-Near Sizing + Adaptive Intake

3-bucket bridge ranking (C1=stale_recovery, C2=gas_near_survivor, C3=activity fill). Stale-pin TTL lifecycle. Severe deficit escalation. 3-tier broad fallback interval. 25 tests. CI: 3385 passed.

### M7.A.5.47h–47n (bridge truth convergence, compressed)

**47h** (exact-pool stale-recovery + hot-seen promotion): C1 tightened to recoverable_stale only, C2 gross-positive filter, hot-seen pin promotion.
**47i** (anomaly-clean + bridge hit isolation): Fixed PRICING_ANOMALY leak in C1, 3 independent try/except for bridge hit detection, C2 gas tolerance `-10 bps`. CI: 3437.
**47j** (bridge minimum floor + focused pool count): `_BRIDGE_MIN_FLOOR=20`, `bridge_focused_pool_count` metric, C2 tolerance `-5 bps`. CI: 3461.
**47k** (session-scoped rollup + auto-pin ALL bridge-miss): `_SESSION_ID` restart detection, `stale_sub_reason` classification, bridge-miss auto-pin, `bridge_excluded_top`. CI: 3487.
**47l** (cold-exec hard-pin + cold_exec_pool_trace): Cold-exec hard-pin into bridge, `cold_exec_pool_trace` diagnostic, C1 block_lag filter, `cut_stage_top`. CI: 3508.
**47m** (truthful bridge diagnostics + run_context): Fixed `list(set)[:30]` truncation bug. A-bucket priority ordering. `bridge_hit_trace_top` with full `_bridge_pool_addrs_set` for truthful `in_bridge`. `run_context` in all M7 artifacts. Session rollup flattened. CI: 3529.
**47n** (cross-artifact truth + exact-pool session trace): Fixed cold/hot race condition — cold preserve of hot-merged keys. Hot merge writes trace to bridge file. `exact_pool_trace` per-window tracking. Evidence: `in_bridge_every_window=true`, `session_hot_events_seen=0`. CI: 3551.

### M7.A.5.47o (overlap trace + gas-hopeless C3 tightening + session reset)

**Diagnosis**: Fresh review of 47n artifacts reveals: (a) Session-rollup inconsistency — `session.session_windows_seen=2` vs `exact_pool_trace.session_windows_seen=7` (exact_pool_trace did not reset on supervisor restart). (b) `bridge_focused_pool_count` and `bridge_loaded_candidate_count` are None at hot artifact top level (only in `hot_gap_debug`). (c) No trace for non-cold-exec pools that have hot events (why other pools don't convert). (d) C3 bridge fill admits deep-negative GAS_EXCEEDS_GROSS families (wasting attention slots).

**Fixes**: (1) `exact_pool_trace` now resets on session change (`_prev_sid != _SESSION_ID`), consistent with session counters. (2) `bridge_focused_pool_count`/`bridge_loaded_candidate_count` surfaced to hot artifact top level (integers, not None). (3) `other_live_pool_trace_top`: new diagnostic showing top 10 non-cold-exec pools with hot events, family, bridge membership, bucket, and reason_if_not_hit. (4) Gas-hopeless C3 tightening: families where ALL candidates are GAS_EXCEEDS_GROSS with worst gap < -5 bps are excluded from C3 fill. `c3_gas_hopeless_skipped`/`c3_gas_hopeless_families` at hot artifact top level. (5) DEV_REPORT `timestamp_utc` fixed to match `run_summary_latest.run_context.run_timestamp`. (6) 31 new tests.

**Evidence** (10-min nonstop, April 7, 13:26-13:36Z): Session consistency fixed: `session.session_windows_seen=2` = `exact_pool_trace.session_windows_seen=2`. Bridge counts at top level: `bridge_focused_pool_count=37`, `bridge_loaded_candidate_count=5`. Target pool RAIN/WETH at 47.41 bps in bridge (bucket A_cold_exec, `in_bridge_every_window=true`, 2/2), `session_hot_events_seen=0`, `reason_if_not_hit=no_hot_events_at_pool`. `other_live_pool_trace_top`: 1 non-bridge pool with hot events. Session goal MARKET_BLOCKED: same market overlap — no on-chain swaps at `0xd130...` during proof window.

CI: 3582 passed, 6 skipped. check_repo_safety PASS (1 warning). ci_full_pipeline ALL REQUIRED GATES PASSED.

### M7.A.5.47p (truthful cross-artifact trace + bridge_selection_diff)

**Diagnosis**: Fresh review of 47o artifacts reveals: (a) `bridge_hit_trace_top` stale — unconditionally preserved from previous cold window even when `cold_executable=[]`. (b) Cross-artifact mismatch: `m7_hot_latest.json` has `bridge_hit_trace_top=[]` but bridge file shows populated trace (stale). (c) `other_live_pool_trace_top.family=""` empty string (should be `"family_unresolved"` when PTT absent). (d) `c3_gas_hopeless_skipped=None` and `c3_gas_hopeless_families=None` in hot artifact (explicit None from `_bd`, not caught by `.get(key, default)`). (e) No `bridge_selection_diff_top` — no diagnostic showing whether bridge pools are starved of events or hot events are at non-bridge pools. (f) No live-miss auto-pin: pools seen with hot events but not in bridge are not auto-promoted.

**Fixes**: (1) Conditional cold bridge preserve: split `_HOT_PRESERVE_KEYS` into `_HOT_PRESERVE_ALWAYS` (bridge_selected_pools_top, bridge_excluded_top) and `_HOT_PRESERVE_IF_COLD_EXEC` (bridge_hit_trace_top, cold_exec_pool_trace). When `cold_executable=[]`, trace keys explicitly cleared to `[]`. (2) c3_gas_hopeless: `_bd.get(key) or fallback` pattern handles both absent key and explicit None. (3) `family_unresolved` sentinel replaces empty string `""`. (4) `bridge_selection_diff_top`: new bidirectional diagnostic — `hot_seen_not_in_bridge` + `bridge_selected_but_no_hot_events` (top 10 each). (5) Live-miss auto-pin: pools from `other_live_pool_trace` with `reason_if_not_hit=="not_in_bridge"` auto-pinned to `_hot_seen_pin`. (6) Hot merge unconditional trace write — always clears stale. (7) 27 new tests in `test_47p_cross_artifact_truth.py`.

**Evidence** (10-min nonstop, April 7, 14:19-14:30Z): Cross-artifact truth CONSISTENT — both `m7_hot_latest.json` and `m7_cold_hot_bridge.json` have `bridge_hit_trace_top=[]`. `c3_gas_hopeless_skipped=0` (integer, not None). `bridge_selection_diff_top` present: 10 `bridge_selected_but_no_hot_events` entries showing pools selected for bridge but receiving no hot events (key finding: bridge starvation is at the event layer, not the selection layer). `session_bridge_pool_hit_total=0`, `session_events_seen_total=8`. Session goal MARKET_BLOCKED: bridge pools correctly selected but on-chain swap events land at non-bridge pools.

CI: 3609 passed, 6 skipped. check_repo_safety PASS (1 warning). ci_full_pipeline ALL REQUIRED GATES PASSED.

### M7.A.5.47q (family-level event trace + sibling-pool pinning + stale separation)

**Diagnosis**: Fresh review of 47p artifacts reveals: (a) `bridge_selected_but_no_hot_events=10` — all bridge-selected pools starved. (b) `hot_seen_not_in_bridge=[]` — bridge selection truthful, no missing pools. (c) Starvation could be pool-specific or family-wide — no diagnostic to distinguish. (d) `stale_pipeline_abort` mixed with generic stale — cannot assess if locally fixable. (e) `family_unresolved` pools occupy A_cold_exec bucket — wasting high-priority slots. (f) `c3_gas_hopeless_*` only in hot artifact, not visible in bridge file.

**Fixes**: (1) `bridge_selected_family_diff_top`: family-level aggregation — groups bridge-selected pools by token-pair family, counts selected, events at any pool, exact hit count, reason_if_zero per family. (2) `exact_family_trace` in hot rollup: session-level family trace — resolves target family via PTT, discovers sibling pools, tracks `session_family_events_seen` vs `session_exact_pool_events_seen`, determines `reason_if_no_exact_hit`. Resets on session change. (3) Sibling-pool auto-pin: for each cold-exec family, pins up to 3 sibling pools of the same family from PTT not already in bridge/pin. Source `"family_sibling_pin"`. (4) `stale_sub_reason` surfaced in `bridge_hit_trace_top` entries: differentiates `pipeline_abort`, `block_lag`, `state_recheck`. (5) `family_unresolved` downgrade: pools with unresolved family demoted from A_cold_exec to C3_activity_fill. `_bsa_fam=""` replaced with `"family_unresolved"`. (6) `c3_gas_hopeless_skipped` / `c3_gas_hopeless_families` merged into bridge file with `or` fallback. (7) 36 new tests in `test_47q_family_trace.py`.

**Evidence** (10-min nonstop, April 7, 16:57-17:07Z): `exact_family_trace` confirms family-wide starvation: `session_family_events_seen=0`, `session_exact_pool_events_seen=0`, `reason_if_no_exact_hit="no_events_at_any_family_pool"`. Only 1 pool of target family in bridge — no siblings discovered. `bridge_selected_family_diff_top` shows ALL 10 families with `reason_if_zero="no_events_at_any_family_pool"` — starvation is systemic across all families, not pool-specific. Family_unresolved pool `0xe879...` correctly downgraded to C3_activity_fill. 3/3 processes alive for 10 min, 0 restarts. Session: `session_windows_seen=3`, `session_events_seen_total=2`, `session_bridge_pool_hit_total=0`. Escalation applies: family starvation confirmed — blocker is event-source/architecture, not selection.

CI: 3645 passed, 6 skipped. ci_full_pipeline ALL REQUIRED GATES PASSED.

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

1. **session_bridge_pool_hit_total=0 — CONFIRMED EVENT-SOURCE/ARCHITECTURE blocker** — 47q proves starvation is family-wide and systemic: ALL 10 bridge families show `no_events_at_any_family_pool`. `exact_family_trace` for target RAIN/WETH family shows 0 family events across entire session. Not pool-specific, not selection-related — the bridge simply does not receive on-chain swaps during proof windows. Per 47q escalation rule: blocker officially moves from "selection" to "event-source/architecture".
2. **cold_executable_positive fluctuates** — last proof window: `cold_executable=0`. Bridge retains pools from prior cold window but no fresh executables.
3. **Subgraph 403** — enrichment breadth limited to V3 local adapter only.

## Next steps

1. Escalation path (47q conclusion): bridge selection is truthful and family-wide — no swaps at ANY family pool. Next investigation should focus on event-source architecture (ws-live subscription filter, block range, event type whitelist) or different chain/market (Base, higher-volume pairs).
2. If choosing to stay on Arbitrum One, run nonstop during peak activity (UTC 14:00-18:00) with wider pair surface — current bridge families may be low-volume tail pairs.
3. Alternative: onboard Base (higher event rate, lower gas) — `config/onboard_base_stage2.yaml` already prepared.
4. The `bridge_selected_family_diff_top` diagnostic is now the canonical tool for assessing family-level starvation on any chain.
