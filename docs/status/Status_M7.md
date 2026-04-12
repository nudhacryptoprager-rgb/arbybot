# Status: M7 (Triangular Feasibility)

**Status**: **M7.E1.12.4A IN PROGRESS — Anvil backend abstraction** (E1.12.4A: simulation backend router, anvil_backend.py, generic infra fields, --require-simulation. Pending: CI validation, 2×30m soaks, sim_passed>0.)  
**Updated**: 2026-04-12
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep, 9 canonical blocker tags, temporal repeatability, verdict summary, universe profiles, orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, gas decomposition, stale/low-lag split, pool-class truth, V2 direct resolve, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, registry activation in ws-live, pipeline latency optimization, profit guard + hot-mode fast path, hot-lane no-fallback + execution-readiness timing, cold/hot artifact isolation + promoted watchlist, batch pre-resolve + supervisor fix. M7.B remains closed.

---

## Strategic Focus (E1.12.1)

**Base M7 production = main lane.** Arbitrum M4 = regression/paper benchmark only.

Rationale (E1.12 audit):
- Base delivers 183x more swap events per block than Arbitrum One (73.4 vs ~0.4)
- M7 production lane on Base has produced best_net_bps=32.61 (best signal ever)
- Arbitrum M4 stays at simulate_only/paper-live — profit_realism=ROUNDTRIP_NOT_PROFITABLE
- No resources allocated to Arbitrum M7 (FROZEN at 5.47s)

**E1.12.1 closure note**: Engineering session CLOSED. Burn-in evidence is documented in DEV_REPORT_LATEST.md via rolling artifact session IDs (production=d4f84d5c, discovery=9c79152f), not discrete run_dirs. Production closure requires: sim_passed>0, submit_ready>0, profit_realism=ROUNDTRIP_PROFITABLE — none met yet.

## E1.12.2 — Modularize loop + wire execution gate

**Goal**: 1h soak confirmed Base M7 hot-path progress; terminal stages remain blocked by two classes of blockers: (a) code-path not wired for sim/submit, (b) cold-lane economics still net-negative under current L1 data costs. E1.12.2 addresses (a) by modularizing the 3274-line monolith and wiring the execution gate pipeline.

**Done (Phase 1)**:
- Step 9: BackrunResult extended with 8 terminal-stage fields (sim_attempted..signing_ready)
- Step 3: `m7/orderflow/runtime_io.py` extracted (~200 lines): path management, atomic JSON, promoted pairs, discovery scoreboard
- Step 4: `m7/orderflow/bridge_runtime.py` extracted (~300 lines): cold-hot bridge I/O, registry prewarm, promotion rules
- Step 8: `m7/orderflow/execution_gate.py` created (~165 lines): profit_guard → sim → submit_ready pipeline, SIM_DISABLED honest blocker
- Step 7: `m7/orderflow/profit_guard.py` — batch helper `annotate_profit_guard_results()` added
- Step 2: `scripts/m7a_orderflow_loop.py` thinned: 635 lines removed, imports rewired to new modules, backward-compat re-exports preserved
- Execution gate wired into run_loop() hot lane: `run_execution_gate()` replaces raw `_run_profit_guard_on_results()`
- Rollup counters (sim_attempted_total, sim_passed_total, submit_ready_total) now increment from real gate_result
- signal_counts in hot artifact now populated from gate_result (no more hardcoded 0)
- Step 10: 16 protective tests added (`tests/unit/test_execution_gate.py`)
- CI: 3878 passed, 0 failed

**Deferred (Phase 2)** → **Done (Phase 2)**:
- Step 5: `m7/orderflow/hot_runtime_artifacts.py` extracted (~1356 lines): `_compute_headline_level`, `_write_hot_heartbeat_on_error`, `_write_hot_artifact`, `_write_hot_intents`, `_update_hot_rollup`
- Step 6: `m7/orderflow/loop_runner.py` extracted (~1339 lines): `LoopState` dataclass, `_apply_lane_defaults`, `_build_ws_args`, `run_loop`
- Guard consolidation: `execution_gate._run_profit_guard_on_results()` delegates to `annotate_profit_guard_results()`
- `scripts/m7a_orderflow_loop.py` thinned: 2750 → 204 lines (-93%), backward-compat re-exports preserved
- 18 test patches updated for `hot_runtime_artifacts` module path
- CI: 3881 passed, 6 skipped, 0 failed (includes 3 new regression tests)
- **Phase 2 review fix**: discovery hot artifact namespace regression — `hot_runtime_artifacts.py` imported path globals by value instead of via `_rio` module reference; discovery `_init_artifact_paths("discovery")` rebound `runtime_io` globals but `hot_runtime_artifacts` kept stale production paths. Fixed: all path/session constants now accessed through `_rio._HOT_ARTIFACT_PATH` etc. 3 regression tests added (`TestE1122HotArtifactsPathRebinding`).
- **Soak evidence (post-fix revalidation)**:
  - Production (base): 30m, 0 restarts, clean shutdown, exit 0 (session 19:27:09–19:57:09Z, sid=bf3083ed)
  - Discovery (base): 30m, 0 restarts, clean shutdown, exit 0 (session 19:27:22–19:57:22Z, sid=9edd8c86)
  - Prod rollup: windows_seen=5225, events=1426, fast_scored=405, fast_positive=36, guard_passed=31, sim_attempted=10
  - Disc rollup: windows_seen=424, events=291, fast_scored=59, fast_positive=5, guard_passed=5, sim_attempted=1
  - All 13 M7 rolling artifacts confirmed fresh (21:56–21:57 local), including previously-stale discovery hot files
  - WS: connected (drpc), heartbeat_on_error_windows=0 (both profiles)
  - Cold prod: events=8, best_net_bps=-2.27; Cold disc: events=7, best_net_bps=-10.20

## E1.12.3 — Simulation Telemetry + Blocker Refinement (DONE)

**Goal**: Diagnose WHY `sim_attempted=10` but `sim_passed=0`. E1.12.2 wired the execution gate, but sim failures were opaque. E1.12.3 surfaces per-error reasons via cumulative histograms + blocker refinements.

**Code changes**:
- `m7/orderflow/execution_gate.py`: Added `sim_errors: List[str]` and `submit_blockers_detail: List[str]` to `ExecutionGateResult` dataclass
- `run_execution_gate()` collects: on sim failure → `gate.sim_errors.append(error)`, on submit blocked → `gate.submit_blockers_detail.extend(blockers)`
- `m7/orderflow/hot_runtime_artifacts.py`:
  - `_update_hot_rollup()`: Added `simulation_error_histogram` + `submit_blocker_histogram` cumulative counters
  - `_write_hot_artifact()`: Added per-window `sim_errors` + `submit_blockers` lists
- `m7/orderflow/artifacts.py`:
  - Step 5 (GAS_L1_DATA_DOMINANT breakdown): Added `gas_l1_breakdown` to blocker_tags when GAS_L1_DATA_DOMINANT fires — surfaces L1/L2 split (l1_dominant_count, avg_l1_ratio, median_l1_bps, median_l2_bps)
  - Step 6 (SUBGRAPH_API_KEY_REQUIRED removed): Removed unconditional blocker (subgraph not used in hot path)
  - Step 7 (LOW_LAG_V2_UNSUPPORTED): Already conditional — no change needed

**Tests**:
- 6 new tests in `TestE1123SimErrorHistogram` class (`tests/unit/test_execution_gate.py`)
- 2 new tests in `TestM7A518BlockerTagsArtifact` class (`tests/unit/test_orderflow_blocker_tags.py`):
  - `test_blocker_tags_subgraph_removed_e1_12_3`
  - `test_gas_l1_breakdown_present_when_dominant`
- CI: 3888 passed, 6 skipped, 0 failed

**Soak evidence (2026-04-11, post-completion)**:
- Production (base): 30m, 0 restarts, clean shutdown, exit 0 (session 20:41:43–21:08:52Z, sid=88fd183f)
- Discovery (base): 30m, 0 restarts, clean shutdown, exit 0 (session 20:39:24–21:09:03Z, sid=62d08408)
- Prod rollup: windows_seen=5266, session_windows=41, events=102, fast_scored=447, fast_positive=36, guard_passed=31, sim_attempted=10, sim_passed=0
- Disc rollup: windows_seen=472, session_windows=48, events=101, fast_scored=86, fast_positive=7, guard_passed=7, sim_attempted=3, sim_passed=0
- All 13 M7 rolling artifacts confirmed fresh (23:08–23:09 local)
- WS: connected, heartbeat_on_error_windows=0 (both profiles)
- **E1.12.3 verified fields**:
  - Prod `simulation_error_histogram`: `{}` (no sim events this session)
  - Disc `simulation_error_histogram`: `{"HTTP 403: ...insufficient": 1, "HTTP 403: ...insufficient": 1}` — **Tenderly credits exhausted**
  - Both `submit_blocker_histogram`: `{}`
  - Prod cold `active_tags`: `["GAS_L1_DATA_DOMINANT"]` — SUBGRAPH removed
  - Disc cold `active_tags`: `["LOW_LAG_INACTIVE_POOL", "GAS_L1_DATA_DOMINANT"]`
  - Both cold `gas_l1_breakdown`: `{l1_dominant_count: ..., avg_l1_ratio: 0.8, median_l1_bps: 0.16, median_l2_bps: 0.04}`
- **Key finding**: sim failures are **Tenderly HTTP 403 (insufficient credits)**, NOT code bugs or tx construction errors. Resolution: replenish Tenderly credits or switch to local fork sim.

## E1.12.4 — Anvil Backend Diversification (IN PROGRESS)

**Goal**: Replace Tenderly dependency with local Anvil fork sim to unblock `sim_passed > 0`.

**Sub-steps**:
- `E1.12.4A`: Backend abstraction + Anvil health — `ARBY_SIM_BACKEND=tenderly|anvil`, generic `is_simulation_configured()`, `check_simulation_backend_connection()`, additive infra fields, `--require-simulation` flag
- `E1.12.4B`: Real calldata/gas path (future) — wire actual swap calldata into `_attempt_simulation()`
- `E1.12.4C`: 2×30m Base prod/discovery with Anvil (future) — stable soaks with backend=anvil
- `E1.12.4D`: First fresh non-Tenderly `sim_passed > 0` (future) — acceptance criterion

**Exit criteria**: `simulation_backend=anvil` in fresh artifacts, 2×30m stable soaks, first non-Tenderly `sim_passed > 0`. Until then, M7.B NOT opened.

**E1.12.4A code changes**:
- `m7/orderflow/simulation.py`: Backend router with `ARBY_SIM_BACKEND`, `get_simulation_backend()`, `is_simulation_configured()`, `is_anvil_configured()`. Tenderly impl moved to `_simulate_swap_tenderly()`. `SimulationResult.backend` field added.
- `m7/orderflow/sim_backends/anvil_backend.py`: New module — `is_anvil_configured()`, `get_anvil_rpc_url()`, `check_anvil_connection()`, `simulate_swap_anvil()`, `estimate_gas_anvil()`, `reset_anvil_fork()`. Uses `eth_call` + `eth_estimateGas` via JSON-RPC.
- `m7/orderflow/execution_gate.py`: Decoupled from Tenderly — uses generic `is_simulation_configured()`. Blocker string `SIM_DISABLED` unchanged.
- `scripts/start_anvil_fork.py`: Standalone Anvil bootstrap (not embedded in hot lane).
- `strategy/infra.py`: Added `check_simulation_backend_connection()` and generic fields in `build_infra_payload()`: `simulation_backend`, `simulation_enabled`, `simulation_ok`, `simulation_error`, `simulation_endpoint_host`. Legacy `tenderly_*` fields kept.
- `strategy/jobs/run_scan_real.py`: Imports `check_simulation_backend_connection`, uses it for connection check (falls through to Tenderly when backend=tenderly).
- `scripts/ci_m5_0_gate.py`: Added `--require-simulation` flag (alias for `--require-tenderly`). Generic simulation field validation added.

**E1.12.4A tests**:
- `tests/unit/test_anvil_backend.py`: 17 tests covering backend selection, configuration, health probe, eth_call simulation, revert handling, gas estimation, fork reset, router dispatch, infra connection check
- `tests/unit/test_execution_gate.py`: Updated 3 monkeypatches from `is_tenderly_configured` to `is_simulation_configured`
- `tests/unit/test_artifact_schema.py`: Added `test_simulation_generic_fields_accepted`
- `tests/unit/test_require_tenderly.py`: Added `test_require_simulation_alias`

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

## M7.A.5.30–5.47s: Hot Execution + Bridge Truth + Freeze (CLOSED, Arbitrum FROZEN)

**5.30**: Hot/cold lane split, profit guard, latency telemetry. CI: 3140.
**5.31**: Hot lane decision, discovery solved (registry_direct=30/30), completion latency ~1544ms. CI: 3155.
**5.32**: Nonstop supervisor, retention pruning, `score_backrun_fast()` 250ms budgets. CI: 3163.
**5.33–5.35**: Hot fast-path, no-fallback, artifact isolation, two-level promoted watchlist. CI: 3172→3186.
**5.36–5.39**: Per-stage budget abort, caching (pool_token, oracle, cold_registry), promotion rules, Web3 reuse. CI: 3200→3244.
**5.40**: Batch pre-resolve (97% latency reduction, 15.62ms warm). Supervisor I/O fix. CI: 3258.
**5.41–5.46**: Hot-lane activation, execution funnel (5 stages), bridge-driven hot registry, micro-refinement, first verified_profitable (77.65 bps). CI: 3272→3327.
**5.47–5.47g**: Focused hot intake, cumulative rollup, hybrid intake, 3-bucket bridge, stale-pin TTL. CI: 3327→3385.
**5.47h–5.47n**: Bridge truth convergence, session-scoped rollup, auto-pin, cold-exec hard-pin, cross-artifact truth. CI: 3437→3551.
**5.47o–5.47r**: Architecture blocker convergence, family-level event trace, cross-artifact contract closure. `blocker_class=event_source_absence` (25 families selected, 0 with events). CI: 3582→3671.
**5.47s (FREEZE)**: Peak-hours proof (April 7, 18:39-18:50Z) confirms event-source ceiling on Arbitrum One. `families_with_any_hot_events=0`, `session_bridge_pool_hit_total=0`. M7 mainline FROZEN. Recommendation: open M7.E1 event-source pilot on Base.

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

### M7.E1.5–E1.7: Funnel Fix → Strict Exec → Hot Write Fix (CLOSED, compressed)

**E1.5**: Fixed funnel inversion (guard > viable). Renamed viable_total→route_viable_total, inline guard attribute. sim/submit scaffolded. Evidence: scored=196, positive=17, viable=14, guard=14. Invariant PASS. CI: 3746.
**E1.6+E1.6.1**: Strict exec = route_viable AND size_valid_for_token. Chain-aware gas floor (Base 0.5 vs Arb 2.0). Per-candidate gate_trace. signal_counts 9-key. Cold/hot heartbeat. CI: 3770.
**E1.7**: Hot lane write fix (UnboundLocalError on `_rollup_wwe`). heartbeat-on-error fallback. 3x Base nonstop: all hot artifacts FRESH. CI: 3775.

---

### M7.E1.8 + E1.8.1: Dashboard Freshness + Chain Provenance + Zero-State (CLOSED, compressed)

**E1.8**: Dashboard M7 freshness banner (hot/cold timestamps, chain label). `chain` + `run_context.chain` in all 4 hot artifacts. `signal_counts` 9-key zero dict. `error_counts`. 13 new tests. CI: 3790.
**E1.8.1**: run_context.chain in rollup/intents (was None). Heartbeat signal_counts = 9-key zero dict (was {}). 8 invariant tests. Evidence: all 3 artifacts chain=base. CI: 3797.

---

### M7.E1.9–E1.9.3: Discovery Lane Split + A/B Infrastructure (OPEN, compressed)

**E1.9: Lane Split** — Production (narrow, 4 pairs) and discovery (wide, 10 pairs) profiles. `get_prewarm_pairs(chain, profile)` dispatch. Discovery scoreboard tracks per-family graduation (`min_positive=3`, `min_sessions=2`). 6 files, 20 tests. CI: 3817.

**E1.9.1: Namespace Isolation** — Discovery artifacts use `*_discovery.json` suffix (7 files). Production canonical names unchanged. Sequential A/B proof (12:38-12:59Z): zero cross-contamination, 0 events both (off-peak). CI: 3825.

**E1.9.2: Peak-Hours A/B** — 3 sequential pairs (13:23-14:27Z), all 6 runs 0 events. Namespace re-confirmed. **Blocker formalized: market-window scarcity** — 9 proof-runs, all 0 swap events. Market-driven, not code/infra. CI: 3825.

**E1.9.3: Session-First Dashboard** — Dashboard "visibly alive" with 0 events: session KPIs primary, production/discovery toggle, cold snapshot banner. `signal_counts` 9-key zero backfill on empty-window heartbeat. 5 files, 4 tests. CI: 3829.

---

### M7.E1.10: Extended Peak-Hours A/B + Contour Cleanup (OPEN)

**1h proof-run (pair 1 of 3 toward expansion threshold)**:
Production (16:05-17:05Z) + Discovery (17:05-18:05Z): 1953 windows total, 0 events both, 3/3 workers, 0 restarts, namespace isolated. Historical production: 3573 windows / 290 events / 17 positive / 14 viable -- engine has found signals before, scarcity is market-driven. Dashboard: namespace badge + cold heartbeat age. 2 tests. CI: 3831.

**E1.10 contour cleanup (reviewer f5c8faa7)**:

| Fix | Description | Status |
|-----|------------|--------|
| #2 | Remove AMONGUS/WETH dead slot (not in core_tokens.yaml) | DONE |
| #3 | Mark meme families (DEGEN, BRETT, TOSHI) as diagnostic_only | DONE |
| #4 | Prioritize structurally stronger pairs (AERO, cbBTC >= 2 DEXes) | DONE |
| #5 | Hot fallback promoted_watchlist profile-aware | DONE |
| #6 | Config contract test (tokens in core_tokens.yaml) | DONE (3 tests) |
| #7 | Cross-dex policy test (diagnostic documentation) | DONE (2 tests) |

**20m A/B after cleanup**: Production (18:42-19:02Z) + Discovery (19:03-19:23Z): 0 events both. Discovery hot confirmed clean seed list (no AMONGUS).

**Proof cadence rule**: Default = 20m production + 20m discovery + immediate analysis. If both empty, return to code/config cleanup before next A/B proof.

CI after contour cleanup: 3838 passed, 6 skipped. ALL GATES PASSED.

**E1.10 VIRTUAL expansion (config audit finding)**:

A full Base config audit (validate_universe + warm_pool_cache --check-liquidity) does not support a broad stale addresses/factories/pools diagnosis: 9/9 canonical intent pairs with cross-DEX coverage, zero no-token/no-pool failures. The concrete config issue found: discovery contour omitted the structurally strong VIRTUAL family despite strong local pool coverage. VIRTUAL/USDC and WETH/VIRTUAL added to discovery prewarm + config. Production cold lane independently found VIRTUAL/WETH in candidate_pairs, validating the finding.

**20m A/B after VIRTUAL expansion (19:56-20:37Z)**: Production (19:56-20:16Z, 327 windows, 0 events) + Discovery (20:16-20:37Z, 277 windows, 0 events, 12-pair seed with VIRTUAL confirmed). Market-window scarcity persists post-expansion. Per cadence rule: both empty, no further runs this session.

**E1.10 429-fallback fix (2026-04-11)**: Alchemy free tier permanently 429 on both WS and HTTP. Root cause: all prior zero-event windows were ambiguous — `events_count=0` could mean market scarcity OR provider blindness. WS fallback (Alchemy→publicnode) and HTTP fallback (Alchemy→mainnet.base.org) added with automatic detection. Provenance fields (`rpc_source`, `ws_source`, `fallback_used`, `http_fallback_used`, `ws_fallback_used`) and 429-specific session counters added to artifacts.

- **Production 20m**: 230 events / 46 windows / 800 cumulative events_seen_total / 0 ws_failed / public_fallback on both HTTP and WS. Cold artifact provenance correctly shows `public_http_fallback` / `public_ws_fallback`.
- **Discovery 20m**: 245 events / 50 windows / 49 ws_connected / 1 ws_failed / 0 ws_failed_429 / 50 http_fallback / 49 ws_fallback. Cold artifact: `rpc_source=public_http_fallback`, `ws_source=public_ws_fallback`, `fallback_used=True`. Events confirmed: discovery sees comparable volume to production (245 vs 230). **Funnel divergence**: production has 84 bridge_pool_hits → 196 fast_path_scored → 42 scored_but_rejected_economics → 13 guard_passed; discovery has 84 bridge_pool_hits → 0 fast_path_scored. Discovery zero-funnel is now confirmed NOT 429-related — it is a profile-specific path issue (bridge_pair matching gap: `bridge_pool_hit_total=84` but `bridge_pair_hit_total=0`).

**E1.11 dRPC provider upgrade (2026-04-11)**: Chain-scoped env var support (`BASE_RPC`/`BASE_WSS` etc.) added to `core/rpc_urls.py`. dRPC (`lb.drpc.live/<chain>/...`) resolves as primary provider ahead of Alchemy/public. `classify_provider()` returns canonical types (alchemy, drpc, publicnode, public_fallback, flashblocks). `validate_drpc_url()` rejects wrong-chain dRPC URLs. `provider_switch_count` tracks provider changes per window.

- **Production 20m (dRPC)**: 87 events / 40 windows / 40 ws_connected / 0 ws_failed / 20 http_fallback / 0 ws_fallback / 6 provider_switches. dRPC WS: 100% stable. dRPC HTTP: 50% 429 fallback to public. Provenance: `rpc_source=chain_env_BASE_RPC`, `rpc_provider=drpc`. Scoring: 234 fast_path_scored, 73 windows_with_fast_scores.
- **Discovery 20m (dRPC)**: 89 events / 50 windows / 50 ws_connected / 0 ws_failed / 29 http_fallback / 0 ws_fallback / 12 provider_switches. **Discovery now scoring**: `bridge_pair_hit_total=23`, `fast_path_scored_total=31`, `windows_with_fast_scores=17`. Previous discovery zero-funnel (E1.10: bridge_pair_hit=0) resolved — likely by accumulated bridge state from prior production runs.

**E1.12 premium-provider gate fix (2026-04-11)**: `REQUIRE_ALCHEMY` gate in `ci_m5_0_gate.py` and `strategy/infra.py` generalized to accept any premium provider (alchemy, drpc, infura), not just alchemy. New env var `ARBY_REQUIRE_PREMIUM` as canonical flag (old `ARBY_REQUIRE_ALCHEMY` / `REQUIRE_ALCHEMY` still honored as aliases). Fresh same-session online evidence: `ci_m5_0_gate --online` PASS (exit 0), `ci_m4_execution_gate --online --profile profit` PASS (exit 0), run dir `ci_m5_gate_arbitrum_one_20260411_123905_815779`. Rolling artifacts refreshed: `run_timestamp=2026-04-11T10:39:56Z`, `status=PASS`, `profit_realism_status=ROUNDTRIP_NOT_PROFITABLE`, `signals=42`. Note: `profit_status=PASS` coexists with `profit_realism_status=ROUNDTRIP_NOT_PROFITABLE` — operator semantics mismatch flagged for future fix (issue #7 in audit).

**E1.12.1 artifact-semantics + start.py fix (2026-04-11)**: Two correctness bugs fixed:

1. **cold_executable_positive semantic fix** (`m7/orderflow/artifacts.py`): `viable_count` and `viable_net_bps` now require `route_viable AND size_valid_for_token` (was `route_viable` only). Fixes false positives where a result passes route viability but has invalid token size. The execution funnel label "Route-viable, fresh, size-valid" now matches the code. `top_executable_candidates` (line 944) already had this correct filter — the fix aligns `viable_count` with the execution funnel truth.

2. **start.py single-chain auto-partial**: `_allow_partial = args.allow_partial_chains or len(configs) == 1` added before `_warn_missing_chains()`. Single-config runs (e.g., `real_minimal.yaml` for arbitrum_one only) no longer FATAL exit when `chains.yaml` defines multiple chains.

CI: 3862 passed, 6 skipped, ALL GATES PASSED (repo safety 0 warnings, M5 offline PASS, M4 smoke+profit PASS).

**E1.12.1 full audit response (2026-04-11, second pass)**: All 10 audit steps implemented:
- Step 3: Premium-only RPC exponential backoff (3 retries, 1/2/4s) in `mode_ws_live.py`. `ARBY_RPC_PREMIUM_ONLY=1` env var.
- Step 4: Flashblocks URL fixed (`mainnet.flashblocks.base.org/ws`). `ARBY_FLASHBLOCKS_WS` env var for provider override.
- Step 5: Tenderly simulation scaffolding (`m7/orderflow/simulation.py`). Requires `TENDERLY_USER/PROJECT/ACCESS_KEY`.
- Step 6: Subgraph API key scaffolding (`_subgraph_url()` in constants.py). `GRAPH_API_KEY` env var.
- Step 7: L1 data fee first-class (`chains/l1_cost.py` OP-Stack GasPriceOracle → `scoring_parallel.py` dynamic gas floor).
- Step 9: Stricter release semantics (`production_readiness` block in `m4/fixtures.py` + `ci_m5_0_gate.py`).

**30min burn-in (12:03-12:33Z, Base)**:
- Production: 300 new windows, 37 events (12.3% rate), +1 positive, +1 viable, +1 guard_passed. dRPC WS 100% stable. 0 restarts.
- Discovery: 284 windows (fresh rollup), 38 events (13.4% rate), 6 fast_path_scored, 0 positive. 0 restarts.
- Both profiles: 30min clean, 3/3 workers throughout, clean shutdown.

CI post-changes: 3862 passed, 6 skipped, ALL GATES PASSED.

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
4. ~~**MARKET-WINDOW SCARCITY — CONFIRMED POST-CONTOUR-FIX (Base)**~~ — **RESOLVED by E1.10 429-fallback fix**: Prior zero-event evidence was 429-contaminated. Fresh production (230 events / 46 windows) and discovery (245 events / 50 windows) both confirm Base market is active. Remaining discovery funnel gap (bridge_pair_hit_total=0 despite bridge_pool_hit_total=84) is a profile-specific pair-matching issue, not market scarcity.
5. ~~**Flashblocks WS DNS unreachable**~~ — `base.flashblocks.base.org` does not resolve. Sub-block delivery untested.
6. **Submit-stage sim = 0** — sim_attempted/sim_passed/submit_ready all zero. Scaffolded, not wired.
7. ~~**Dashboard dead appearance**~~ — **RESOLVED in E1.8**: M7 freshness banner separates M7 vs PRIMARY rolling.
8. ~~**Chain provenance incomplete in run_context**~~ — **RESOLVED in E1.8.1**: rollup + intents now have `run_context.chain` + `run_context.run_timestamp`.
9. ~~**ALCHEMY 429 RATE LIMIT — RESOLVED in E1.10**~~: Alchemy free tier permanently 429 on both WS and HTTP. Fixed with automatic fallback: WS → publicnode, HTTP → mainnet.base.org. Provenance fields (`rpc_source`, `ws_source`, `fallback_used`, `http_fallback_used`, `ws_fallback_used`) and session counters (`session_ws_failed_429_windows`, `session_http_fallback_windows`, `session_ws_fallback_windows`) added.
10. **dRPC HTTP 429 INTERMITTENT (Base)** — dRPC free tier HTTP rate-limits ~50% of windows (`session_http_fallback_windows=20/40` in production). dRPC WS is 100% stable (0 failures). Mitigation: automatic fallback to public HTTP. Not blocking — events flow through WS, HTTP used only for quoting.

## Next steps

1. **M7 Arbitrum mainline FROZEN.** No further Arbitrum M7 changes.
2. **Discovery pair-matching deepening**: Discovery now scoring (31 fast_path_scored), but bridge_pair_hit=23 vs production's cumulative 405 bridge_pool_hit — gap narrowing. Continue A/B runs to accumulate bridge state for discovery.
3. **dRPC HTTP stabilization**: dRPC HTTP 429s ~50% of windows. Options: upgrade dRPC plan, or accept public fallback for HTTP (WS is stable).
4. **Non-empty window capture**: Run during peak Base activity hours (14:00-22:00 UTC) to populate signal_counts with scored events.
5. **Scoreboard graduation**: Once discovery families accumulate `scored_positive >= 3` across `>= 2` sessions, evaluate for production promotion.
6. **Submit-stage simulation**: Wire Tenderly fork simulation. Only after fresh non-empty hot evidence.
7. **Gas economics optimization**: L1 data cost reduction, gas_floor_bps tuning, Flashblocks WS for sub-block delivery.
