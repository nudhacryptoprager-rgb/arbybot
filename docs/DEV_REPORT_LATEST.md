# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: data/runs/_rolling/ (M7 artifacts: m7_orderflow_latest.json, m7_hot_rollup_latest.json)
mode: ONLINE (M7.E1.6 + E1.6.1 strict exec semantics, chain-aware gas, heartbeat, signal_counts. 3x 10-min Base nonstop April 9 08:56-09:29Z. M4/M5 rolling unchanged — M7-only session with --no-m4)
artifact_mode: rolling
config: config/onboard_base_profit.yaml (base, narrow contour)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.E1.6+E1.6.1 - strict exec, chain-aware gas, heartbeat, signal_counts

## Session Completion
session_goal: M7.E1.6.1 - fresh non-empty Base runtime validation of E1.6 artifact semantics (strict exec, chain-aware gas, gate_trace, heartbeat timestamps, signal_counts)
goal_status: BLOCKED (3x 10-min Base runs all produce empty cold windows — no scored events in cold lane. Heartbeat fields proved working but signal_counts=null and gate_trace not exercised in runtime. Hot lane stale — not writing fresh artifacts.)
close_allowed: true
remaining_blockers: (1) No non-empty cold window in 3x 10-min runs — signal_counts null, gate_trace exercised only in unit tests. (2) Hot lane m7_hot_latest.json stuck at 07:05:12Z — not updated by runs.
evidence_session_run_dirs: [data/runs/_rolling/ (m7_orderflow_latest.json current_window_timestamp=2026-04-09T09:29:26Z, m7_cold_hot_bridge.json)]
primary_blocker_of_session: fresh_non_empty_evidence — E1.6 strict exec/gate_trace/signal_counts cannot be validated in runtime without scored events
blocker_status_before: ACTIVE — E1.6 code changes deployed but no runtime evidence
blocker_status_after: BLOCKED — cold heartbeat proves runtime alive, but empty windows prevent E1.6 evidence extraction. Hot lane stale.
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.6 + E1.6.1 = strict executable semantics, chain-aware gas floor, per-candidate gate_trace, heartbeat timestamps, signal_counts funnel dict
change_summary:
  - m7/orderflow/artifacts.py: Strict exec (route_viable AND size_valid_for_token). top_route_viable_candidates. Per-candidate gate_trace (8 fields). signal_counts 9-key funnel dict.
  - m7/orderflow/profit_guard.py: Chain-aware gas floor (chain param, get_gas_floor_bps). Base 0.5 bps vs Arbitrum 2.0 bps.
  - m7/orderflow/scoring_parallel.py: chain param in score_backrun_fast(), get_gas_floor_bps(chain).
  - m7/orderflow/mode_ws_live.py: Chain param to build_replay_summary. Cold heartbeat: current_window_timestamp, snapshot_preserved, snapshot_run_timestamp.
  - scripts/m7a_orderflow_loop.py: Chain param to profit guard. Bridge family_unresolved_pool_count as int. Hot heartbeat in hot/rollup/intents.
  - tests/unit/test_e1_base_chain_aware.py: 24 new tests (sections 18-24). Total 96 E1 tests.
  - tests/unit/test_orderflow_artifacts.py: Updated keys for gate_trace and size_valid_for_token.
touched_files:
  - m7/orderflow/artifacts.py
  - m7/orderflow/profit_guard.py
  - m7/orderflow/scoring_parallel.py
  - m7/orderflow/mode_ws_live.py
  - scripts/m7a_orderflow_loop.py
  - tests/unit/test_e1_base_chain_aware.py
  - tests/unit/test_orderflow_artifacts.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3770 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (2 warnings: Status_M7 bloat fixed to 295 lines, DEV_REPORT alignment)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --chain base --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS x3 (08:56-09:06, 09:06-09:17, 09:19-09:29, all 3/3 alive, 0 restarts)

## 3) Artifacts Attached

M7 cold artifact (from 3x Base 10-min nonstop, April 9 08:56-09:29Z):
- m7_orderflow_latest.json: current_window_timestamp=2026-04-09T09:29:26Z, snapshot_preserved=true, snapshot_run_timestamp=2026-04-08T09:54:01Z, signal_counts=null, loop_context.window_empty=true
- m7_cold_hot_bridge.json: Last modified 09:29:26Z (fresh)

M7 hot artifacts (STALE — not updated by nonstop runs):
- m7_hot_latest.json: timestamp=2026-04-09T07:05:12Z (before runs)
- m7_hot_rollup_latest.json: last_updated=2026-04-09T07:05:12Z

M4/M5 rolling (unchanged — M7-only session):
- _latest.json: run_status=PASS, agg_status=PASS, data_run_rate=1.0
- run_summary_latest.json: status=PASS, signals_count=31, total_net_usdc=40.0986

## 4) Key Results - M7.E1.6 + E1.6.1

### Cold Artifact Evidence

| Field | Value | Assessment |
|-------|-------|------------|
| `current_window_timestamp` | 2026-04-09T09:29:26Z | FRESH — heartbeat working |
| `snapshot_preserved` | true | Empty window, old data carried forward |
| `snapshot_run_timestamp` | 2026-04-08T09:54:01Z | Origin of preserved snapshot |
| `signal_counts` | null | BLOCKED — window empty, no scoring |
| `top_executable_candidates` | 2 (DEGEN/WETH, size_valid=false) | STALE — pre-E1.6 data |

### Hot Artifact Status

| Field | Value | Assessment |
|-------|-------|------------|
| `timestamp` | 2026-04-09T07:05:12Z | STALE — hot lane not writing |
| `current_window_timestamp` | null | Hot heartbeat NOT exercised |

### CI Evidence

| Command | Result |
|---------|--------|
| pytest | 3770 passed, 6 skipped |
| ci_full_pipeline | ALL REQUIRED GATES PASSED |
| nonstop x3 | 3/3 alive, 0 restarts each |

latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 1.0
  low_sample_rate: 0.0
run_summary_latest:
  status: PASS
  metrics.signals_count: 31
  metrics.total_net_usdc: 40.0986
  run_timestamp: 2026-04-02T09:03:41.464858Z
  code_identity: ts:2026-04-02T09:03:41.464858Z
  inputs.run_mode: REGISTRY_REAL

## 5) Strategic Reading

1. **Cold heartbeat WORKS**: `current_window_timestamp=09:29:26Z` with `snapshot_preserved=true` makes stale-data carry-forward explicit.
2. **Fresh non-empty evidence NOT OBTAINED**: 3x 10-min Base runs had empty cold windows. Market/timing dependent.
3. **Hot lane is a known gap**: Hot artifacts not updated. WS subscription or iteration exception on Base.
4. **E1.6 strict exec semantics proven in unit tests**: exec ⊂ route_viable, gate_trace 8-field, signal_counts 9-key — all locked by 24 new tests.
5. **Code quality high**: 3770 tests, CI green, repo safety PASS.

## 5.1) Contract Checks
status/reasons consistency: OK (BLOCKED — evidence gap is honest, not contradictory)
rolling discipline: OK (canonical M7 artifacts only)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true

## 6) Blocker Classification

code_blocker: LOW (pytest PASS, CI green)
data_collection_blocker: HIGH (3x runs all empty windows)
market_window_blocker: MEDIUM (seed watchlist pools inactive during run times)

## 6.1) Blockers / Risks
- Hot lane not writing artifacts during nonstop runs
- Cold empty windows prevent signal_counts/gate_trace runtime validation
- Flashblocks WS DNS unreachable
- Submit sim = 0 (scaffold only)

## 8) What I need from Lead now
question_1: Run longer sessions (30-60min) or target peak hours for non-empty cold windows?
request_1: Confirm E1.6.1 heartbeat contract is sufficient to close, or specify additional runtime evidence required.
