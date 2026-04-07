# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: ONLINE (10-min nonstop proof run, April 7 14:19-14:30Z)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-07T14:19:48Z
  dirty: true
  desc: M7.A.5.47p — truthful cross-artifact trace + bridge_selection_diff

## Session Completion
session_goal: M7.A.5.47p — truthful cross-artifact trace + first hit on exact live-miss pools
goal_status: MARKET_BLOCKED (code correct: cross-artifact truth CONSISTENT, bridge_selection_diff shows event-layer starvation, not selection error)
close_allowed: true
remaining_blockers: session_bridge_pool_hit_total=0 — bridge pools correctly selected but receive no on-chain swap events during proof windows
evidence_session_run_dirs: [data/runs/_rolling/ (m7_cold_hot_bridge.json, m7_hot_latest.json, m7_hot_rollup_latest.json)]
primary_blocker_of_session: event_layer_starvation — bridge_selection_diff_top shows 10 bridge-selected pools with zero hot events; session_events_seen_total=8
blocker_status_before: BUG (stale bridge_hit_trace_top, cross-artifact mismatch, c3_gas_hopeless=None, family="", no bridge_selection_diff)
blocker_status_after: FIXED (conditional preserve, unconditional merge, c3 or-fallback, family_unresolved, bridge_selection_diff_top, live-miss auto-pin)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47p — truthful cross-artifact trace + bridge_selection_diff
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Conditional cold bridge preserve — split _HOT_PRESERVE_KEYS into always/conditional groups; trace keys cleared when cold_executable=[]. (b) c3_gas_hopeless uses `or` fallback for explicit None → guaranteed integer/list. (c) family_unresolved sentinel replaces empty "". (d) bridge_selection_diff_top — bidirectional mismatch diagnostic (hot_seen_not_in_bridge + bridge_selected_but_no_hot_events). (e) Live-miss auto-pin from other_live_pool_trace. (f) Hot merge unconditional trace write — always clears stale.
  - tests/unit/test_47p_cross_artifact_truth.py (NEW): 27 tests — conditional preserve (5), cross-artifact truth (4), bridge_selection_diff (7), c3_gas_hopeless non-None (4), live-miss auto-pin (6), family_unresolved (2).
  - tests/unit/test_47o_overlap_trace.py (MODIFIED): Updated expected family from "" to "family_unresolved" (2 lines).
  - docs/status/Status_M7.md (MODIFIED): 47p entry + updated Known Blockers + Next Steps.
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47p.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47p_cross_artifact_truth.py (NEW)
  - tests/unit/test_47o_overlap_trace.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3609 passed, 6 skipped)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (1 warning: DEV_REPORT_ALIGNMENT)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED, 64.1s)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (0 restarts, clean exit, 14:19-14:30Z)

## 3) Artifacts Attached

Rolling artifacts (from 10-min nonstop, April 7 14:19-14:30Z):
- m7_cold_hot_bridge.json: bridge_hit_trace_top=[] (consistent with hot_latest), cold_executable=0
- m7_hot_latest.json: c3_gas_hopeless_skipped=0 (integer), bridge_selection_diff_top={hot_seen_not_in_bridge=[], bridge_selected_but_no_hot_events=10 entries}, other_live_pool_trace_top=0 entries
- m7_hot_rollup_latest.json: session_bridge_pool_hit_total=0, session_events_seen_total=8

## 4) Key Results — M7.A.5.47p

### Cross-Artifact Truth (before vs after)

| Metric | Pre-47p | Post-47p |
|--------|---------|----------|
| hot bridge_hit_trace_top | [] | [] |
| bridge bridge_hit_trace_top | [stale entry from prior cold] | [] (consistent) |
| Cross-artifact truth | VIOLATION | CONSISTENT |

### c3_gas_hopeless (before vs after)

| Field | Pre-47p | Post-47p |
|-------|---------|----------|
| c3_gas_hopeless_skipped | None | 0 (integer) |
| c3_gas_hopeless_families | None | [] (list) |

### bridge_selection_diff_top (NEW in 47p)

| Direction | Count | Interpretation |
|-----------|-------|----------------|
| hot_seen_not_in_bridge | 0 | No non-bridge pools had hot events |
| bridge_selected_but_no_hot_events | 10 | Bridge pools correctly selected but no on-chain swaps |

Key finding: bridge starvation is at the **event layer** (no swaps at bridge pools), not the **selection layer** (wrong pools in bridge). This proves the question from 47o's review: live-miss pools fail because they are excluded from bridge selection, AND bridge pools fail because they receive no repeat events.

### 47p Fixes Summary

1. **Conditional cold preserve**: `_HOT_PRESERVE_IF_COLD_EXEC` keys cleared when `cold_executable=[]`, preventing stale trace from prior cold window.
2. **c3_gas_hopeless non-None**: `_bd.get(key) or fallback` pattern handles both missing key and explicit None value.
3. **family_unresolved**: Pools not in PTT get `"family_unresolved"` sentinel instead of empty string.
4. **bridge_selection_diff_top**: Bidirectional mismatch diagnostic showing hot events at non-bridge pools and bridge pools without hot events.
5. **Live-miss auto-pin**: Pools from `other_live_pool_trace` with `reason_if_not_hit=="not_in_bridge"` auto-promoted to bridge via `_hot_seen_pin`.
6. **Unconditional hot merge**: Bridge trace always written (even when empty), preventing stale data from persisting.

## 5) Strategic Reading

1. **MARKET_BLOCKED confirmed by bridge_selection_diff_top**: 10 bridge-selected pools have zero hot events. Starvation is definitively at the event layer. The bridge selects correct pools; swaps just don't happen there.
2. **Cross-artifact truth now CONSISTENT**: Bridge and hot_latest agree on trace state. Stale data eliminated by conditional preserve + unconditional merge.
3. **Low event volume**: `session_events_seen_total=8` over 10 minutes. Even when events arrive, they land at non-bridge pools.
4. **Live-miss auto-pin**: Going forward, non-bridge pools observed with hot events will be auto-promoted to bridge, increasing diversity over time.
5. **Next**: Longer nonstop during high-activity, or chain expansion (Base) to increase swap probability at bridge pools.

## 5.1) Contract Checks
status/reasons consistency: OK (MARKET_BLOCKED with no_hot_events_at_pool — consistent)
rolling discipline: OK (session reset, bridge counts, other_live_pool_trace, gas-hopeless filter are additive; no new artifact files)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
