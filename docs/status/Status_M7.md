# Status: M7 (Triangular Feasibility)

**Status**: **M7.E1.8.1 OPEN — provenance completion + zero-state uniformity** (E1.8.1: run_context.chain populated in rollup + intents. Heartbeat signal_counts = 9-key zero dict (was {}). 8 new invariant tests. 3-min Base nonstop: all 3 artifacts chain=base, run_context.chain=base. CI: 3797 passed, 6 skipped.)  
**Updated**: 2026-04-10
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

### M7.E1.1–E1.4: Nonstop → Contamination Fix → Separation → Convergence (CLOSED, compressed)

**E1.1** (April 7): Hot+cold nonstop — 30 events, GAS_EXCEEDS_GROSS 86.7%, best -2.20 bps, gas breakdown: L1 0.16 / L2 0.04 / total 0.20 bps. CI: 3702.
**E1.2** (April 7): Arbitrum contamination fix — hardcoded `_TARGET_POOL` → dynamic. `blocker_class` corrected `event_source_absence`→`gas_economics_only`. Fixed `KeyError: stage_a_ms` (hot lane silently crashing). 9/17 families have hot events. CI: 3718.
**E1.3** (April 8): Registry vs gas separation — `registry_rejected=0`, `gas_rejected=44`, `scored_positive=6`. Registry NOT a blocker. 3 cold executables (W/WETH +92.63 bps). `blocker_class=selection_or_scoring`. CI: 3728.
**E1.4** (April 8): Convergence fields in intents. 3x repeatability: positive 24/+3/+4, viable 12/+3/+4. Funnel inversion bug found (guard=31 > viable=19) → fixed in E1.5. CI: 3741.

### M7.E1.5: Funnel Semantics Fix + Submit-Stage Scaffold (April 8, 09:10-09:57Z)

**Goal**: Fix funnel semantics (profit_guard_passed_total > viable_total). Add sim/submit placeholders. Filter family_unresolved.

**Code changes**: Renamed `viable_total`→`route_viable_total`. Changed `profit_guard_passed_total` from batch to inline attribute (gated on route_viable). Added sim_attempted/sim_passed/submit_ready_total. Filtered family_unresolved from bridge summary. 10 new tests. CI: 3746 passed, 6 skipped.

**Evidence (3x 10-min nonstop, 09:25-09:57Z)**: scored=196, positive=17, route_viable=14, guard=14. Funnel invariant `scored >= positive >= route_viable >= guard` — **PASS** (was violated in E1.4: guard=31 > viable=19). sim/submit all zero (placeholder). family_unresolved_pool_count=3-8 per window.

---

### M7.E1.6 + E1.6.1: Strict Exec + Chain-Aware Gas + Heartbeat (CLOSED, compressed)

**E1.6**: Strict exec = route_viable AND size_valid_for_token. Chain-aware gas floor (Base 0.5 vs Arb 2.0 bps). Per-candidate gate_trace (8 fields). signal_counts 9-key funnel. **E1.6.1**: Cold/hot heartbeat (current_window_timestamp, snapshot_preserved, snapshot_run_timestamp). Runtime invariant tests. 7 files changed. CI: 3770 passed.

**Evidence**: 3x 10-min Base nonstop (April 9): cold heartbeat fresh (09:29:26Z), hot stale (07:05:12Z). Empty windows — signal_counts=null, gate_trace unit-tested only.

**Findings**: Cold heartbeat works; hot lane NOT writing (→ fixed in E1.7). signal_counts/gate_trace need non-empty windows.

---

### M7.E1.7: Hot Lane Write Fix + Heartbeat-on-Error (CLOSED, compressed)

Root cause: `UnboundLocalError: _rollup_wwe` — variable scoping bug crashed every hot iteration before `run_ws_live()`. Fix: initialize `_rollup_wwe=0`, `_rollup_wwbh=0` before bridge try block. Added `_write_hot_heartbeat_on_error()` for exception-path writes. 3x Base nonstop: all hot artifacts FRESH at 07:12:27Z, zero code errors. 7 new tests (103 E1 total). CI: 3775 passed.

---

### M7.E1.8: Dashboard M7 Freshness + Chain Provenance + Zero-State (April 10, 09:37-09:40Z)

**Goal**: Fix dashboard UX (M7-only runs appear dead because primary panels read stale non-M7 artifacts). Add chain provenance to all M7 artifacts. Ensure zero-state surfaces use honest 0/{}, never null.

**Code changes (3 files)**:
- `monitoring/dashboard.html`: M7 freshness banner (hot/cold timestamps, chain label, session events, hotness color-coding). Separates PRIMARY vs M7 rolling freshness.
- `scripts/m7a_orderflow_loop.py`: (1) `chain` param to `_write_hot_artifact`, `_write_hot_heartbeat_on_error`, `_update_hot_rollup`, `_write_hot_intents`. (2) `chain` field in all 4 artifact dicts + `run_context.chain`. (3) `signal_counts` 9-key dict (honest 0s, never null). (4) `error_counts` in hot artifact and rollup (heartbeat_on_error counter, normal_windows/heartbeat_on_error_windows).
- `tests/unit/test_e1_base_chain_aware.py`: 13 new tests (sections 27-29). Total: 116 E1 tests.

CI: 3790 passed, 6 skipped.

**Evidence (3-min Base nonstop, 09:37-09:40Z)**:

| Field | Before E1.8 | After E1.8 |
|-------|-------------|------------|
| `m7_hot_latest.chain` | absent | **base** |
| `m7_hot_latest.signal_counts` | absent | **{events_count:0, ...all 0}** |
| `m7_hot_latest.error_counts` | absent | **{heartbeat_on_error:0}** |
| `m7_hot_rollup.chain` | absent | **base** |
| `m7_hot_rollup.error_counts` | absent | **{normal:49, heartbeat:0}** |
| `m7_hot_intents.chain` | absent | **base** |
| Dashboard M7 banner | absent | **M7 ROLLING [base] Hot/Cold timestamps** |

**1.5h run evidence (07:49-09:19Z)**: `session_windows_seen=1251`, `session_events_seen_total=0`, `session_bridge_pool_hit_total=0`. Confirms: hot lane writes correctly, market currently empty. Dashboard correctly shows M7 freshness separate from stale PRIMARY rolling.

**E1.8.1 (reviewer fix, April 10 10:49-10:52Z)**: Reviewer found `run_context.chain=None` in rollup/intents and `signal_counts={}` in heartbeat from-scratch. Fixes: (1) Added `"chain": chain` to rollup `run_context` dict. (2) Added full `run_context` block to intents payload. (3) Heartbeat from-scratch: `signal_counts` = 9-key zero dict (was `{}`). 8 new invariant tests (section 30). 3-min nonstop evidence: rollup `run_context.chain=base`, intents `run_context.chain=base`, `run_context.run_timestamp` populated in all 3 artifacts. CI: 3797 passed, 6 skipped.

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

1. **EVENT-SOURCE CEILING — FROZEN (Arbitrum only)** — 47s proof confirms `event_source_absence`. Does NOT apply to Base.
2. **GAS_EXCEEDS_GROSS — MAJORITY BLOCKER (Base)** — E1.5: ~7% viable rate (14/196 scored). Near-exec frontier at -2.20 bps.
3. ~~**HOT LANE NOT WRITING (Base)**~~ — **RESOLVED in E1.7**.
4. **NO FRESH NON-EMPTY WINDOW** — 1.5h Base run (1251 windows, 0 events). Market-dependent, not code. Dashboard now correctly surfaces M7 freshness separately.
5. **Flashblocks WS DNS unreachable** — `base.flashblocks.base.org` does not resolve. Sub-block delivery untested.
6. **Submit-stage sim = 0** — sim_attempted/sim_passed/submit_ready all zero. Scaffolded, not wired.
7. ~~**Dashboard dead appearance**~~ — **RESOLVED in E1.8**: M7 freshness banner separates M7 vs PRIMARY rolling.
8. ~~**Chain provenance incomplete in run_context**~~ — **RESOLVED in E1.8.1**: rollup + intents now have `run_context.chain` + `run_context.run_timestamp`.

## Next steps

1. **M7 Arbitrum mainline FROZEN.** No further Arbitrum M7 changes.
2. **Non-empty window capture**: Run during peak Base activity hours (14:00-22:00 UTC) to populate signal_counts with scored events.
3. **E1.9: Submit-stage simulation**: Wire Tenderly fork simulation. Only after fresh non-empty hot evidence.
4. **Gas economics optimization**: L1 data cost reduction, gas_floor_bps tuning, Flashblocks WS for sub-block delivery.
