# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: ONLINE (10-min nonstop proof run, April 7 12:22-12:32Z)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.47o — overlap trace + gas-hopeless C3 tightening + session reset

## Session Completion
session_goal: M7.A.5.47o — overlap trace + gas-hopeless C3 tightening + session reset for first exact-pool hot event hit
goal_status: MARKET_BLOCKED (code correct: pool in bridge 2/2 windows, session-consistent; no on-chain swaps at pool during proof window)
close_allowed: true
remaining_blockers: session_bridge_pool_hit_total=0 — no swaps at target pool during 10-min window
evidence_session_run_dirs: [data/runs/_rolling/ (m7_cold_hot_bridge.json, m7_hot_latest.json, m7_hot_rollup_latest.json)]
primary_blocker_of_session: no_hot_events_at_pool — pool 0xd13040d4... consistently in bridge but no on-chain activity
blocker_status_before: BUG (session-rollup inconsistency; bridge counts None at top level; no other-pool trace; C3 admits gas-hopeless families)
blocker_status_after: FIXED (session reset + bridge counts + other_live_pool_trace + gas-hopeless C3 filter)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47o — overlap trace + gas-hopeless C3 tightening + session reset
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) exact_pool_trace resets on session change. (b) bridge_focused_pool_count/bridge_loaded_candidate_count at hot artifact top level. (c) other_live_pool_trace_top — non-cold-exec pools with hot events. (d) Gas-hopeless C3 fill filter — families where ALL candidates are GAS_EXCEEDS_GROSS with gap < -5 bps excluded. (e) c3_gas_hopeless_skipped/c3_gas_hopeless_families at top level.
  - tests/unit/test_47o_overlap_trace.py (NEW): 31 tests — session reset (7), bridge counts (4), other_live_pool_trace (10), gas-hopeless detection (5), diverse fill filter (5).
  - docs/status/Status_M7.md (MODIFIED): 47o entry + updated Known Blockers + Next Steps.
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47o.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47o_overlap_trace.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3582 passed, 6 skipped)
py -3.11 -m pytest tests/unit/test_47o_overlap_trace.py -v: PASS (31 passed)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (1 warning: DEV_REPORT_ALIGNMENT)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED, 61.5s)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (0 restarts, clean exit, 13:26-13:36Z)

## 3) Artifacts Attached

Rolling artifacts (from 10-min nonstop, April 7 13:26-13:36Z):
- m7_cold_hot_bridge.json: bridge_selected_pools_top=20, bridge_hit_trace_top=1 entry (in_bridge=true, bucket=A_cold_exec)
- m7_hot_latest.json: bridge_focused_pool_count=37, bridge_loaded_candidate_count=5, other_live_pool_trace_top=1, c3_gas_hopeless_skipped=0, c3_gas_hopeless_families=[]
- m7_hot_rollup_latest.json: session_windows_seen=2, exact_pool_trace.session_windows_seen=2 (consistent)

## 4) Key Results — M7.A.5.47o

### Session Consistency Fix (before vs after)

| Metric | Pre-47o | Post-47o |
|--------|---------|----------|
| session.session_windows_seen | 2 | 2 |
| exact_pool_trace.session_windows_seen | 7 (stale from prior session) | 2 (reset on session change) |
| Consistent | NO | YES |

### Bridge Counts at Top Level (before vs after)

| Field | Pre-47o | Post-47o |
|-------|---------|----------|
| bridge_focused_pool_count | None (only in hot_gap_debug) | 37 |
| bridge_loaded_candidate_count | None (only in hot_gap_debug) | 5 |

### Exact-Pool Session Trace (from rollup)

| Field | Value |
|-------|-------|
| pool_address | 0xd13040d4fe917ee704158cfcb3338dcd2838b245 |
| session_windows_seen | 2 |
| session_windows_in_bridge | 2 |
| in_bridge_every_window | true |
| session_hot_events_seen | 0 |
| session_fast_attempted | 0 |
| session_fast_scored | 0 |
| reason_if_not_hit | no_hot_events_at_pool |

### Bridge Hit Trace (from bridge file)

| Field | Value |
|-------|-------|
| pool_address | 0xd13040d4fe917ee704158cfcb3338dcd2838b245 |
| actual_pair | RAIN/WETH |
| cold_net_bps | 47.4128 |
| in_bridge | true |
| selected_bucket | A_cold_exec |
| hot_events_seen | 0 |
| reason_if_not_hit | no_hot_events_at_pool |

### Window Miss Classification

| Class | Windows |
|-------|---------|
| no_events_in_window | 31 |
| events_but_no_bridge_hit | 19 |

### other_live_pool_trace_top

1 pool with hot events not in bridge: `0x467f4b89...` — `not_in_bridge`, 1 event, not scored.

### 47o Fixes Summary

1. **Session reset**: `exact_pool_trace` resets when `_prev_sid != _SESSION_ID` (supervisor restart detection).
2. **Bridge counts at top level**: `bridge_focused_pool_count`/`bridge_loaded_candidate_count` surfaced from `_hot_bridge_diag` to `hot[...]`.
3. **other_live_pool_trace_top**: Top 10 non-cold-exec pools by event count with family, bridge membership, bucket, and miss reason.
4. **Gas-hopeless C3 filter**: Families where ALL candidates are GAS_EXCEEDS_GROSS with worst gap < -5 bps excluded from C3 fill.
5. **DEV_REPORT timestamp**: Fixed to match `run_summary_latest.run_context.run_timestamp`.

## 5) Strategic Reading

1. **MARKET_BLOCKED persists**: Pool `0xd130...` in bridge every window, code correct. No on-chain swap activity at this pool during proof window.
2. **Session consistency now proven**: `session.session_windows_seen` = `exact_pool_trace.session_windows_seen` — no stale accumulation across supervisor restarts.
3. **Observability improved**: Bridge counts, other-pool trace, and gas-hopeless diagnostics all at hot artifact top level.
4. **dominant_hot_miss_reason=no_events_in_window** (31/50): Most windows have zero events. 19/50 had events but at non-bridge pools.
5. **Next**: Longer nonstop during high-activity, or chain expansion to increase swap probability at bridge pools.

## 5.1) Contract Checks
status/reasons consistency: OK (MARKET_BLOCKED with no_hot_events_at_pool — consistent)
rolling discipline: OK (session reset, bridge counts, other_live_pool_trace, gas-hopeless filter are additive; no new artifact files)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
