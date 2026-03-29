# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.3 — all scopes produce no-graduate verdicts. M7.A.5.3 ws-live evidence: 0 low-lag events, pipeline latency 9× over budget. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B remains closed.)  
**Updated**: 2026-03-29  
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep ($1-$10K), 6 canonical blocker tags, temporal repeatability, verdict summary, universe profiles (`narrow_7|expanded_10`), orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay. M7.B remains closed.

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
- Tests: 152 in `test_triangular_contracts.py`, 100 in `test_orderflow_contracts.py`

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

## M7.A.5.3: WebSocket-Triggered Same-Block/Next-Block Replay

**Hypothesis**: `block_event_backrun` on arbitrum_one may only be fairly testable with websocket-triggered same-block/next-block replay, not historical block polling.

**Motivation**: M7.A.5.2 closes only the HTTP polling architecture. The repo has `resolve_rpc_ws()`, `check_ws_connection()`, `MulticallBatcher`, and `prefetch_slot0_multicall()` — all unused by the polling path. Streaming `newHeads` + parallel scoring is the correct architecture for low-lag replay.

**New infrastructure**:
- `--ws-live` CLI mode with `--ws-blocks N` and `--ws-timeout S` controls
- WebSocket `newHeads` subscription via `resolve_rpc_ws()` (Alchemy WSS)
- `score_backrun_live_parallel()`: ThreadPoolExecutor for parallel buy/sell fanout
- Multicall-assisted venue pruning, latency budget metrics (`latency_budget_ms`, `latency_budget_hit_rate`, `sub_block_capable`)
- `ws_low_lag_summary` / `ws_stale_summary` machine-readable artifact sections
- 7 new BackrunResult fields (incl. `latency_budget_ms`)
- 28 new contract tests (113 total in `test_orderflow_contracts.py`)

**Evidence — M7.A.5.3.1 (Alchemy WSS, narrow)**: 10 blocks, 6 events scored. Results:

| Metric | Value |
|--------|-------|
| events_scored_low_lag_ws | **0** |
| same_block_count | 0 |
| next_block_count | 0 |
| stale_count | 6 |
| mean_block_lag | 43.33 |
| mean_pipeline_latency_ms | **2258.17** |
| latency_budget_ms | 250 |
| latency_budget_hit_rate | **0.0** |
| sub_block_capable | **false** |
| best_net_bps | -20.49 |
| all reject | GAS_EXCEEDS_GROSS (6/6) |

**Verdict**: ws-live streaming architecture **NOT VIABLE**. WebSocket newHeads delivers blocks correctly but quote pipeline (~2.3s per event, 6 venues × 2 passes) is 9× over the 250ms block budget. All events stale regardless of delivery mechanism. This closes the streaming architecture path alongside the polling path.

**CI gates**: 2849 passed, 6 skipped. 113 tests in `test_orderflow_contracts.py`.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase, closed by default. Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.
