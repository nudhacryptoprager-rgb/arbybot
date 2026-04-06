# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-06T12:00:00Z
mode: OFFLINE (CI verification, nonstop pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-06T12:00:00Z
  dirty: true
  desc: M7.A.5.47b — hybrid intake, activity ranking, temporal rollup, queue ordering

## Session Completion
session_goal: M7.A.5.47b — fix 0 hot events from focused-only intake via hybrid broad/focused + activity ranking
goal_status: IN_PROGRESS (code changes complete, CI green, nonstop verification pending)
close_allowed: false
remaining_blockers: Nonstop verification needed to confirm hybrid intake produces events_seen > 0 and windows_with_events > 0
evidence_session_run_dirs: [tests/unit (3327 passed, 6 skipped)]
primary_blocker_of_session: Focused-only intake produced 0 events across 33 windows (bridge pools not actively traded)
blocker_status_before: ACTIVE (events=0, fast_path.scored=0, bridge_pool_hit=0, dominant_miss=bridge_pool_not_hit)
blocker_status_after: PENDING_VERIFICATION (hybrid intake + activity ranking + temporal counters implemented)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47b — hybrid hot intake + pool activity ranking + temporal rollup counters + submit-size queue ordering
change_summary:
  - m7/orderflow/mode_ws_live.py (MODIFIED): Hybrid intake — every 3rd block does broad scan (no address filter), rest do focused. 4 diagnostic counters (broad_blocks, focused_blocks, broad_logs, focused_logs) surfaced in ws_live_stats.
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Pool activity ranking — _cold_active_pools dict tracks pool addresses from cold events; hot bridge set ranked by activity. (b) 4 new rollup counters: windows_with_events, windows_with_bridge_hits, windows_with_fast_scores, broad_fallback_events_total. (c) Split miss reason: bridge_pool_not_hit → no_events_in_filtered_window + events_seen_but_not_bridge_pool. (d) micro_refinement transported in cold→hot bridge. (e) Hot intents sorted by cold_verified_net_bps; rows carry cold_verified_net_bps, cold_best_submit_size, cold_gas_floor_gap_bps.
  - tests/unit/test_nonstop_loop_artifacts.py (MODIFIED): m7_hot_rollup_latest.json added to canonical rolling set.
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): m7_hot_rollup_latest.json added to canonical rolling set.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.47b section, updated header.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.47b)
touched_files:
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_nonstop_loop_artifacts.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3327 passed, 6 skipped)

## 3) Artifacts Attached

rolling: pending nonstop verification to populate:
  - data/runs/_rolling/m7_hot_rollup_latest.json (now with windows_with_events, windows_with_bridge_hits, windows_with_fast_scores, broad_fallback_events_total)
  - data/runs/_rolling/m7_hot_intents_latest.json (now with cold_verified_net_bps ordering)
  - data/runs/_rolling/m7_cold_hot_bridge.json (now with micro_refinement transport)

## 4) Key Results — M7.A.5.47b

### Problem: Focused-Only Intake Produced 0 Events

Fresh 10-min nonstop evidence showed:
- Cold: events=30, viable=3, cold_executable_positive=3, best_net_bps_executable=108.6898
- Hot: events=0, fast_path.scored=0, profit_guard_passed=0
- Rollup: windows_seen=33, bridge_loaded=177, bridge_pool_hit=0, dominant_miss=bridge_pool_not_hit

Root cause: 51 bridge pool addresses filtered, but across 33 windows ZERO had swap events. These pools are simply not actively traded during short windows.

### Fix 1: Hybrid Intake (Focused + Broad Fallback)

Every 3rd block does broad scan (no address filter), rest do focused with bridge pool addresses. This ensures hot lane sees SOME events even when bridge pools are quiet.

Diagnostic counters: `broad_blocks`, `focused_blocks`, `broad_logs`, `focused_logs` — reveals whether problem is "no events at all" vs "events at non-bridge pools."

### Fix 2: Pool Activity Ranking

Cross-iteration `_cold_active_pools` dict tracks pool addresses seen in cold events (address → event_count + last_iter). When building bridge pool set for hot, all candidates are ranked by cold activity (most-active first), top 50 selected. Cold_exec pools always included regardless of ranking.

### Fix 3: Temporal Rollup Counters

4 new counters in `m7_hot_rollup_latest.json`:
- `windows_with_events`: windows where events_count > 0
- `windows_with_bridge_hits`: windows where bridge_pool_address_hit_count > 0
- `windows_with_fast_scores`: windows where fast-path scored > 0
- `broad_fallback_events_total`: cumulative events from broad (unfocused) blocks

### Fix 4: Split Miss Reason

`bridge_pool_not_hit` replaced by two sub-reasons:
- `no_events_in_filtered_window`: windows with 0 events (filter too tight or pools inactive)
- `events_seen_but_not_bridge_pool`: events exist but none match bridge pool set

### Fix 5: Submit-Size Queue Ordering

`micro_refinement` data now transported via cold→hot bridge. Hot intents sorted by `cold_verified_net_bps` (cold-verified candidates first), then `net_bps`.

Each intent row carries:
- `cold_verified_net_bps`: verified net_bps from cold micro_refinement
- `cold_best_submit_size`: the wei amount that produced best net_bps in cold
- `cold_gas_floor_gap_bps`: how close to gas floor across tested sizes

## 5) Strategic Reading

1. **Hybrid intake is the minimal viable fix**: Focused-only was correct in theory but assumed bridge pools are actively traded. Hybrid (2/3 focused, 1/3 broad) provides both targeted scoring AND diagnostic visibility.
2. **Activity ranking prevents stale pool selection**: Cold lane events reveal which pools actually receive swaps. Using this to rank bridge pools means hot lane focuses on the most-active pools, not just any pool in the bridge.
3. **Temporal rollup counters enable root-cause diagnosis**: `windows_with_events` vs `windows_with_bridge_hits` vs `windows_with_fast_scores` reveals exactly where the conversion funnel breaks.
4. **Split miss reasons prevent misdiagnosis**: "bridge_pool_not_hit" was ambiguous — could mean "no events" or "events but at wrong pools." The split enables correct diagnosis.
5. **Cold-verified submit-size ordering ensures best candidates are prioritized**: When hot lane finally scores events, the queue is ordered by cold-verified profitability, not just raw hot net_bps.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (canonical files + m7_hot_rollup_latest.json added to canonical set)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
