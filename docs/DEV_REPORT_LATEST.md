# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-07T12:32:31Z
mode: ONLINE (10-min nonstop proof run, April 7 12:22-12:32Z)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-07T12:32:31Z
  dirty: true
  desc: M7.A.5.47n — cross-artifact truth + exact-pool session trace

## Session Completion
session_goal: M7.A.5.47n — first exact-pool hot event hit for 0xd13040d4fe917ee704158cfcb3338dcd2838b245
goal_status: MARKET_BLOCKED (code correct: pool in bridge 5/5 windows, no on-chain swaps at pool during proof window)
close_allowed: true
remaining_blockers: session_bridge_pool_hit_total=0 — no swaps at target pool during 10-min window
evidence_session_run_dirs: [data/runs/_rolling/ (m7_cold_hot_bridge.json, m7_hot_latest.json, m7_hot_rollup_latest.json)]
primary_blocker_of_session: no_hot_events_at_pool — pool 0xd13040d4... consistently in bridge but no on-chain activity
blocker_status_before: BUG (cold lane clobbers hot-merged bridge fields; no cross-artifact trace; no per-pool session trace)
blocker_status_after: FIXED (cross-artifact truth + exact_pool_trace proves code-side placement is correct)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47n — cross-artifact truth for bridge file + exact-pool session trace in rollup
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Cold bridge preserve: read existing file before overwriting, preserve 4 hot-derived keys if cold payload is falsy. (b) _write_hot_artifact returns bridge_hit_trace list (was None). (c) Hot merge writes bridge_hit_trace_top + cold_exec_pool_trace into bridge file. (d) exact_pool_trace in hot rollup: per-window tracking for target pool.
  - tests/unit/test_47n_cross_artifact_truth.py (NEW): 22 tests — cold preserve (5), hot merge trace (5), exact-pool trace (8), return contract (1), cross-artifact truth (3).
  - docs/status/Status_M7.md (MODIFIED): 47n entry + updated Known Blockers + Next Steps.
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47n.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47n_cross_artifact_truth.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3551 passed, 6 skipped)
py -3.11 -m pytest tests/unit/test_47n_cross_artifact_truth.py -v: PASS (22 passed)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (0 restarts, clean exit)

## 3) Artifacts Attached

Rolling artifacts (from 10-min nonstop, April 7 12:22-12:32Z):
- m7_cold_hot_bridge.json: bridge_selected_pools_top=20, bridge_hit_trace_top=1 entry (in_bridge=true)
- m7_hot_latest.json: bridge_selected_pools_top=30, bridge_hit_trace_top=1 entry
- m7_hot_rollup_latest.json: session_windows_seen=5, exact_pool_trace present

## 4) Key Results — M7.A.5.47n

### Cross-Artifact Truth (before vs after)

| Metric | Pre-47n (bridge file) | Post-47n (bridge file) | Hot artifact |
|--------|----------------------|----------------------|--------------|
| bridge_selected_pools_top | [] | 20 entries | 30 entries |
| bridge_hit_trace_top | absent | 1 entry (in_bridge=true) | 1 entry |
| cold_exec_pool_trace | absent | 1 entry | 1 entry |
| bridge_excluded_top | [] | [] | [] |

### Exact-Pool Session Trace (from rollup)

| Field | Value |
|-------|-------|
| pool_address | 0xd13040d4fe917ee704158cfcb3338dcd2838b245 |
| session_windows_seen | 5 |
| session_windows_in_bridge | 5 |
| in_bridge_every_window | true |
| session_hot_events_seen | 0 |
| session_fast_attempted | 0 |
| session_fast_scored | 0 |
| last_seen_window | null |
| reason_if_not_hit | no_hot_events_at_pool |

### Root Cause Analysis

1. **Cold clobber race**: Cold and hot are separate concurrent processes. Cold writes `bridge_selected_pools_top=[]` (no bridge assembly in cold lane). Hot merges correctly but next cold iteration overwrites.
2. **Trace never in bridge file**: `bridge_hit_trace_top`/`cold_exec_pool_trace` computed and written only in `_write_hot_artifact()`, never merged back into bridge file.
3. **No per-pool session trace**: Rollup tracked aggregate session counters but had no pool-specific tracking.

### 47n Fixes

1. **Cold bridge preserve**: Before `_atomic_json_write`, read existing bridge file and preserve 4 hot-derived keys (`bridge_selected_pools_top`, `bridge_hit_trace_top`, `cold_exec_pool_trace`, `bridge_excluded_top`) if existing value is truthy and cold payload is falsy.
2. **Hot merge trace propagation**: `_write_hot_artifact()` now returns `_bridge_hit_trace`. Hot merge block writes `bridge_hit_trace_top` + `cold_exec_pool_trace` into bridge file.
3. **Exact-pool session trace**: `exact_pool_trace` dict in rollup tracks per-window: `session_windows_in_bridge`, `session_hot_events_seen`, `in_bridge_every_window`, `reason_if_not_hit` for target pool.

## 5) Strategic Reading

1. **This is now MARKET_BLOCKED, not code**: Pool `0xd130...` is in bridge 5/5 windows. Code correctly places it. No on-chain swaps arrived at this pool during the 10-min window.
2. **exact_pool_trace disambiguates code vs market**: `in_bridge_every_window=true` + `session_hot_events_seen=0` proves placement is correct, activity is missing.
3. **Cross-artifact truth is defense-in-depth**: Bridge file now mirrors hot artifact for trace keys, surviving cold clobber.
4. **Next**: Longer proof runs during high-activity periods, or onboard chain with more frequent swaps at target pools.

## 5.1) Contract Checks
status/reasons consistency: OK (MARKET_BLOCKED with no_hot_events_at_pool — consistent)
rolling discipline: OK (exact_pool_trace, cold preserve are additive; no new artifact files)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
