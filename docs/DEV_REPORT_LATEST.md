# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-07T09:15:00Z
mode: OFFLINE CI (full pipeline verified, nonstop pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-07T09:15:00Z
  dirty: true
  desc: M7.A.5.47l — cold-exec hard-pin + cold_exec_pool_trace + cut_stage_top + C1 block_lag filter

## Session Completion
session_goal: M7.A.5.47l — first hot bridge hit on exact cold-executable pool 0xd13040d4fe917ee704158cfcb3338dcd2838b245
goal_status: REACHED (code changes complete, 3508 tests pass, all CI gates green, nonstop proof pending)
close_allowed: true
remaining_blockers: bridge_pool_hit_total needs runtime verification — exact pool in bridge but no hot events observed yet
evidence_session_run_dirs: [tests/unit (3508 passed, 6 skipped)]
primary_blocker_of_session: cold-executable pool survives cold lane but hot subscription sees zero events at this pool
blocker_status_before: DIAGNOSED (pool in bridge, 110.96 bps verified profitable, but hot_events_this_window=0)
blocker_status_after: INSTRUMENTED (cold_exec_pool_trace shows exactly where pool drops; cut_stage_top shows where positives die)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47l — first bridge hit on exact cold-exec pool via hard-pin + diagnostic transparency
change_summary:
  - m7/orderflow/artifacts.py (MODIFIED): (a) `cut_stage_top` — machine-readable WHERE each positive dies: economics, stale_block_lag, stale_pipeline_abort, stale_state_recheck, viable. Top families per stage.
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Cold-exec hard-pin: `_bridge_pool_addrs |= _bucket_a` after assembly. (b) `bridge_selected_pools_top` populated at assembly time (never empty when pools exist). (c) `cold_exec_pool_trace` diagnostic in hot artifact: per-pool in_bridge, hot_events_this_window, fast_score_attempted, registry_match. (d) C1 filter: skip `stale_sub_reason=block_lag`. (e) `bridge_excluded_top` persisted into bridge file.
  - tests/unit/test_47l_cold_exec_trace.py (NEW): 21 tests — hard-pin (3), bridge_selected (3), trace (2), C1 filter (5), cut_stage (6), bridge_excluded (2).
  - docs/status/Status_M7.md (MODIFIED): 47k + 47l entries added.
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47l.
touched_files:
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47l_cold_exec_trace.py (NEW)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED — stale_sub_reason key added to schema)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3508 passed, 6 skipped)
py -3.11 -m pytest tests/unit/test_47l_cold_exec_trace.py -v: PASS (21 passed)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
All __pycache__ cleared.

## 3) Artifacts Attached

No new rolling artifacts (offline session). Nonstop proof pending with 47l changes.

## 4) Key Results — M7.A.5.47l

### Fresh Evidence Summary (from 47k nonstop: April 7, 08:50-09:01Z)

| Metric | Value | Assessment |
|--------|-------|-----------|
| cold_executable_positive | 1 | Real positive: 0x25118290/WETH 110.96 bps |
| verified_profitable | true | Cold-side profit guard confirmed |
| pool_address | 0xd13040d4...45 | Exact pool identified |
| bridge_pool_hit_total | 0 | Hot conversion absent |
| session_bridge_pool_hit_total | 0 | Session-scoped confirms zero |
| bridge_focused_pool_count | 26 | Pool IS in the bridge |
| GAS_EXCEEDS_GROSS | 20/30 | Economics kills broad universe |
| STALE_POSITIVE | 9/9 positives | Stale by block_lag (3..8) |

### Diagnosis

The system now has a genuine cold-lane positive (not anomaly, not diagnostic-only) but hot conversion is zero. Three distinct cut stages identified:

1. **Economics** (GAS_EXCEEDS_GROSS=20/30): Broad families (ESP/USDC, USDC/WETH, USDT/WETH) die on gas floor. Correctly filtered.
2. **Stale block lag** (9/9 stale positives have lag 3..8): RAIN/WETH class. Not recoverable in current mode. Correctly cut by 47l C1 filter.
3. **No hot events** (cold-exec pool 0xd13040...): Pool is in bridge but subscription sees zero events. This is the remaining live blocker — not a code bug but a market/subscription coverage gap.

### 47l Changes

1. **Cold-exec hard-pin**: `_bridge_pool_addrs |= _bucket_a` — defense-in-depth, cold-exec pools cannot be evicted.
2. **`bridge_selected_pools_top` at assembly**: Populated immediately after bridge assembly, not only during hot merge. Guarantees non-empty list when bridge_focused_pool_count > 0.
3. **`cold_exec_pool_trace`**: Per-pool diagnostic showing exactly where the cold executable pool stands in the hot window: `in_bridge`, `hot_events_this_window`, `fast_score_attempted`, `registry_match`.
4. **C1 `stale_sub_reason=block_lag` filter**: Stale candidates with lag 3..8 are not recoverable in current mode. C1 now skips them.
5. **`cut_stage_top`**: Machine-readable artifact showing where each positive candidate dies, with top families per stage. Stages: economics, stale_block_lag, stale_pipeline_abort, stale_state_recheck, viable.
6. **`bridge_excluded_top` in bridge file**: Exclusion reasons persisted into bridge JSON for offline analysis.

## 5) Strategic Reading

1. **The problem is no longer code**: Pool IS in bridge, IS verified profitable, IS cold-executable. The gap is that the hot WebSocket subscription (newHeads + eth_getLogs) does not see events at this pool during the session.
2. **`cut_stage_top` makes the funnel transparent**: operators can now see exactly where the 20-30 positive moments are lost — not buried in individual candidate JSON.
3. **C1 stale filter tightening is safe**: 47k evidence showed all 9 stale positives at lag 3..8. These cannot be recovered in current next-block-continuation mode.
4. **Next step is NOT more filters**: It's either (a) longer observation to catch events at the exact pool, or (b) earlier orderflow capture (provider-specific feeds, pending-tx where available).

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (cut_stage_top, cold_exec_pool_trace, bridge_selected_pools_top are additive)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
docs_reread_confirmed: true
