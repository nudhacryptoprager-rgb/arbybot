# Status: M7 (Triangular Feasibility)

**Status**: **M7.E1.10 OPEN -- discovery contour cleanup + 20m A/B cadence** (E1.10: AMONGUS dead slot removed, structurally stronger pairs prioritized, hot fallback profile-aware, config contract + cross_dex policy tests. 3838 tests pass.)  
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
4. **MARKET-WINDOW SCARCITY — CONFIRMED AT 1H SCALE (Base)** — E1.10: 1h production (16:05-17:05Z) + 1h discovery (17:05-18:05Z) at peak hours, 1953 windows total, 0 events. Prior short runs (E1.9.2: 9 runs, E1.9.3: 2 runs) also 0 events. Historical data confirms engine capability (290 events in prior sessions). Scarcity is market-driven, not code-driven. Pair 1 of 3 toward reviewer expansion threshold.
5. **Flashblocks WS DNS unreachable** — `base.flashblocks.base.org` does not resolve. Sub-block delivery untested.
6. **Submit-stage sim = 0** — sim_attempted/sim_passed/submit_ready all zero. Scaffolded, not wired.
7. ~~**Dashboard dead appearance**~~ — **RESOLVED in E1.8**: M7 freshness banner separates M7 vs PRIMARY rolling.
8. ~~**Chain provenance incomplete in run_context**~~ — **RESOLVED in E1.8.1**: rollup + intents now have `run_context.chain` + `run_context.run_timestamp`.

## Next steps

1. **M7 Arbitrum mainline FROZEN.** No further Arbitrum M7 changes.
2. **20m A/B proof cadence**: One 20-minute production + one 20-minute discovery, then immediate analysis. No further runs if both empty without contour/code changes.
3. **Non-empty window capture**: Run during peak Base activity hours (14:00-22:00 UTC) to populate signal_counts with scored events.
4. **Discovery expansion decision**: If 2-3 dev sessions with 20m A/B runs + contour cleanup all zero, modest discovery expansion or OP Mainnet comparative pilot (not longer Base runs).
5. **Scoreboard graduation**: Once discovery families accumulate `scored_positive >= 3` across `>= 2` sessions, evaluate for production promotion.
6. **Submit-stage simulation**: Wire Tenderly fork simulation. Only after fresh non-empty hot evidence.
7. **Gas economics optimization**: L1 data cost reduction, gas_floor_bps tuning, Flashblocks WS for sub-block delivery.
