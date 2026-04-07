# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-07T17:04:16Z
mode: ONLINE (10-min nonstop proof run, April 7 16:57-17:07Z)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-07T17:04:16Z
  dirty: true
  desc: M7.A.5.47q - family-level event trace + sibling-pool pinning + stale separation

## Session Completion
session_goal: M7.A.5.47q - prove whether selected exact-family pools receive family-level events even when exact pool receives none
goal_status: MARKET_BLOCKED (code correct: family-wide starvation confirmed - ALL bridge families show no_events_at_any_family_pool; escalation applies)
close_allowed: true
remaining_blockers: session_bridge_pool_hit_total=0 - starvation is systemic across all bridge families, not pool-specific
evidence_session_run_dirs: [data/runs/_rolling/ (m7_cold_hot_bridge.json, m7_hot_latest.json, m7_hot_rollup_latest.json)]
primary_blocker_of_session: event_source_architecture - exact_family_trace and bridge_selected_family_diff_top prove no swaps at ANY family pool during proof window; blocker escalated from selection to event-source/architecture per 47q rule
blocker_status_before: UNKNOWN (no family-level diagnostic; stale_pipeline_abort mixed with generic stale; family_unresolved in A_cold_exec; c3_gas_hopeless not in bridge)
blocker_status_after: DIAGNOSED (family-wide starvation proven; stale_sub_reason visible; family_unresolved downgraded; c3_gas_hopeless in bridge file)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47q - family-level event trace + sibling-pool pinning
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) bridge_selected_family_diff_top - family-level aggregation of bridge-selected pools with per-family event counts, reason_if_zero. (b) exact_family_trace in hot rollup - session-level trace tracking sibling pools, family events vs exact pool events, reason_if_no_exact_hit. (c) Sibling-pool auto-pin - 3 siblings per cold-exec family from PTT, source=family_sibling_pin. (d) stale_sub_reason surfaced in bridge_hit_trace_top entries. (e) family_unresolved downgraded from A_cold_exec to C3_activity_fill. (f) c3_gas_hopeless merged into bridge file with or fallback for None.
  - tests/unit/test_47q_family_trace.py (NEW): 36 tests - family_diff (8), exact_family_trace (7), sibling_auto_pin (7), stale_sub_reason (4), family_unresolved_downgrade (6), c3_gas_hopeless_in_bridge (4).
  - docs/status/Status_M7.md (MODIFIED): 47q entry + updated Known Blockers + Next Steps.
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47q.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47q_family_trace.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3645 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED, 62.4s)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (0 restarts, clean exit, 16:57-17:07Z)

## 3) Artifacts Attached

Rolling artifacts (from 10-min nonstop, April 7 16:57-17:07Z):
- m7_cold_hot_bridge.json: cold_executable=0, bridge_selected_pools_top=20 entries, family_unresolved pool 0xe879 downgraded to C3_activity_fill
- m7_hot_latest.json: bridge_selected_family_diff_top=10 families (all no_events_at_any_family_pool)
- m7_hot_rollup_latest.json: exact_family_trace={family=0x2511.../0x82af..., session_family_events_seen=0, session_exact_pool_events_seen=0, reason_if_no_exact_hit=no_events_at_any_family_pool}

## 4) Key Results - M7.A.5.47q

### exact_family_trace (NEW in 47q)

| Metric | Value |
|--------|-------|
| family | 0x2511.../0x82af... (RAIN/WETH) |
| selected_pools | 1 (0xd130 only) |
| session_family_events_seen | 0 |
| session_exact_pool_events_seen | 0 |
| reason_if_no_exact_hit | no_events_at_any_family_pool |

Key finding: the target family has ZERO events at ANY pool. No siblings discovered in bridge - only 1 pool of that family exists in PTT.

### bridge_selected_family_diff_top (NEW in 47q)

| Families in bridge | Events at any pool | Families with events |
|-------------------|-------------------|---------------------|
| 10 | 0 | 0 |

ALL 10 bridge families show reason_if_zero=no_events_at_any_family_pool. Starvation is systemic across all families.

### Escalation Assessment

Per 47q escalation rule: if runs with family-cluster pinning still show 0 family events, blocker moves from selection to event-source/architecture.
- Result: session_family_events_seen=0 for target family AND 10/10 bridge families with 0 events.
- Conclusion: Blocker is event-source/architecture, not selection.

### family_unresolved downgrade (NEW in 47q)

Pool 0xe879 correctly downgraded from A_cold_exec to C3_activity_fill (family_unresolved should not occupy high-priority slot).

### 47q Fixes Summary

1. bridge_selected_family_diff_top: Family-level event diagnostic - per-family selected count, events, exact hit, reason.
2. exact_family_trace: Session-level family trace with sibling discovery and cumulative event counting.
3. Sibling-pool auto-pin: 3 PTT siblings per cold-exec family pinned to bridge (source: family_sibling_pin).
4. stale_sub_reason in bridge_hit_trace: pipeline_abort vs block_lag vs state_recheck visible per entry.
5. family_unresolved downgrade: Unresolved pools demoted from A_cold_exec to C3_activity_fill.
6. c3_gas_hopeless in bridge file: Merged with or fallback for None safety.

## 5) Strategic Reading

1. FAMILY-WIDE STARVATION CONFIRMED: This is the definitive finding of 47q. All 10 bridge families see zero events. The blocker is not pool selection, not family selection, but the event source itself (or market volume).
2. Escalation applies: Per 47q rule, blocker officially moves from selection to event-source/architecture. Next investigation should focus on ws-live subscription parameters or chain/market switching.
3. Sibling-pool pinning had no effect: Only 1 pool of the target family exists in PTT - there are no siblings to pin. This suggests the bridge families themselves are low-frequency pairs on Arbitrum One.
4. Low event volume persists: session_events_seen_total=2 over 3 hot windows. The few events that arrive land at non-bridge pools.
5. Recommended next steps: (a) Widen event subscription (all pools, not bridge-only), or (b) onboard Base chain with higher activity, or (c) run during Arbitrum peak hours (UTC 14:00-18:00).

## 5.1) Contract Checks
status/reasons consistency: OK (MARKET_BLOCKED with no_events_at_any_family_pool - consistent)
rolling discipline: OK (bridge_selected_family_diff_top, exact_family_trace, stale_sub_reason, c3_gas_hopeless merge are additive; no new artifact files)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
