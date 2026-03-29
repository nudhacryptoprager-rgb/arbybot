# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a5_3_ws_live_infrastructure
mode: OFFLINE (infrastructure build + contract tests; ws-live evidence pending)
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow_7 universe, ws-triggered block-event backrun replay
code_identity:
  primary: ts:2026-03-27T21:30:14.342304Z
  dirty: false
  desc: M7.A.5.3 WebSocket-triggered same-block/next-block replay

## Session Completion
session_goal: Build ws-live streaming replay infrastructure for M7.A.5.3 hypothesis — websocket-triggered same-block/next-block backrun with parallel scoring and multicall-assisted venue pruning.
goal_status: REACHED (infrastructure built, 15 new tests pass, 2836 total)
close_allowed: true
remaining_blockers: none (infrastructure goal complete; live evidence is a separate session goal)
evidence_session_run_dirs:
  - ci_m5_gate_arbitrum_one_20260327_222948_123275 (rolling baseline, unchanged)
primary_blocker_of_session: M7.A.5.2 closed only the HTTP polling architecture, not the streaming low-latency architecture
blocker_status_before: ACTIVE (ws-live infrastructure not built)
blocker_status_after: RESOLVED (ws-live infrastructure built, tests pass, ready for evidence run)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.3 — WebSocket-triggered same-block/next-block replay on arbitrum_one.
change_summary:
  - Added --ws-live CLI mode with --ws-blocks N and --ws-timeout S controls
  - WebSocket newHeads subscription via resolve_rpc_ws() (Alchemy WSS)
  - Single-block log fetch per newHead (not historical window)
  - score_backrun_live_parallel(): ThreadPoolExecutor for parallel buy/sell fanout
  - Multicall-assisted venue pruning via prefetch_slot0_multicall()
  - 6 new BackrunResult fields: ws_provider, event_detected_at_block, quote_started_block, quote_finished_block, quote_pipeline_latency_ms, venues_pruned_by_multicall
  - Artifact ws-specific fields: ws_live_config, ws_live_stats, ws_provider, ws_source, resolved_ws_host, events_scored_low_lag_ws
  - 15 new contract tests (100 total in test_orderflow_contracts.py)
  - Status_M7.md trimmed from 332 to 93 lines (consolidated M7.A-M7.A.3 evidence)
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: --ws-live mode, score_backrun_live_parallel, new BackrunResult fields)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +15 tests, 100 total)
  - docs/status/Status_M7.md (MODIFIED: trimmed from 332 to 93 lines, M7.A.5.3 section added)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (100 passed in 6.15s)
py -3.11 -m pytest tests/unit -q: PASS (2836 passed, 6 skipped in 56.70s)

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - (none yet — infrastructure build session, ws-live evidence run pending)

prior session artifacts (still valid, for comparison):
  - data/tmp/m7a_live_alchemy_narrow.json (M7.A.5.2, Alchemy: 100 blocks, 20 events, best_net=-19.49 bps)
  - data/tmp/m7a_live_blocks.json (M7.A.5.1, public RPC: 100 blocks, 5 events)
  - data/tmp/m7a_live_wider.json (M7.A.5.1, public RPC: 500 blocks, 10 events)

rolling (unchanged):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.5.3 Infrastructure

### New Infrastructure

| Component | Description |
|-----------|-------------|
| `--ws-live` CLI | WebSocket-triggered replay mode with `--ws-blocks N` and `--ws-timeout S` |
| `score_backrun_live_parallel()` | ThreadPoolExecutor-based parallel buy/sell fanout across venues |
| Multicall prefetch | `prefetch_slot0_multicall()` for venue pruning (zero-liquidity removal) |
| BackrunResult +6 fields | ws_provider, event_detected_at_block, quote_started/finished_block, pipeline_latency_ms, venues_pruned |
| newHeads subscription | WebSocket `eth_subscribe("newHeads")` → single-block log fetch → parallel scoring |

### Architecture Comparison

| Aspect | M7.A.5/5.2 (polling) | M7.A.5.3 (ws-live) |
|--------|----------------------|---------------------|
| Event source | Historical block window | newHeads subscription |
| Quote execution | Sequential per-venue | Parallel ThreadPoolExecutor |
| Venue pruning | None | Multicall prefetch → zero-liquidity removal |
| Latency tracking | block_lag only | pipeline_latency_ms + started/finished block |
| Expected lag | 60-218 blocks (stale) | 0-2 blocks (same/next) |

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestWsLiveFields | 5 | PASS |
| TestWsProvenance | 3 | PASS |
| TestScoreBackrunLiveParallel | 3 | PASS |
| TestWsLiveArtifactSchema | 2 | PASS |
| TestM7A53BackwardCompat | 2 | PASS |
| **Total new** | **15** | **PASS** |
| **Total orderflow tests** | **100** | **PASS** |
| **Total all tests** | **2836** | **PASS (6 skipped)** |

## 5) Strategic Reading

M7.A.5.3 infrastructure is ready for live evidence:

1. **Streaming vs polling**: The `--ws-live` mode subscribes to `newHeads` and processes each block as it arrives, fetching logs only for the current block. This eliminates the historical-window fetch-lag that made M7.A.5/5.2 evidence structurally stale.

2. **Parallel scoring**: `score_backrun_live_parallel()` fans out buy/sell quotes across all venues simultaneously using ThreadPoolExecutor, reducing per-event scoring latency.

3. **Multicall venue pruning**: Before quoting, multicall prefetch can identify and remove venues with zero liquidity, reducing wasted RPC calls.

4. **Machine-readable latency tracking**: `quote_pipeline_latency_ms` and `quote_started_block`/`quote_finished_block` provide sub-block latency measurement that M7.A.5/5.2 lacked.

5. **Evidence run needed**: Run `--ws-live --ws-blocks 10 --output data/tmp/m7a_ws_live.json` with ALCHEMY_API_KEY loaded to generate first ws-live evidence. The key measurement is `events_scored_low_lag_ws` — if >0, the streaming architecture achieves what polling could not.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY — NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY — NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC) |
| M7.A.5.2 | **LIVE EVIDENCE: NOT VIABLE** (Alchemy RPC — stale lag unchanged) |
| M7.A.5.3 | **INFRASTRUCTURE READY** (ws-live + parallel scoring, evidence pending) |
| M7.B | NOT STARTED (closed by M7.A verdicts) |
