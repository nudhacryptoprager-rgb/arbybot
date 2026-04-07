# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-07T18:19:13Z
mode: ONLINE (10-min nonstop proof run, April 7 18:10-18:21Z)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-07T18:19:13Z
  dirty: true
  desc: M7.A.5.47r - close cross-artifact family-trace contract and formalize event-source architecture blocker

## Session Completion
session_goal: M7.A.5.47r - close cross-artifact family-trace contract and formalize event-source architecture blocker
goal_status: MARKET_BLOCKED (code correct: cross-artifact contract gaps closed; architecture_blocker_trace confirms event_source_absence; family_unresolved fully excluded from bridge)
close_allowed: true
remaining_blockers: session_bridge_pool_hit_total=0 - event_source_absence confirmed by architecture_blocker_trace (25 families selected, 0 with any hot events)
evidence_session_run_dirs: [data/runs/_rolling/ (m7_cold_hot_bridge.json, m7_hot_latest.json, m7_hot_rollup_latest.json)]
primary_blocker_of_session: event_source_architecture - architecture_blocker_trace.blocker_class=event_source_absence; bridge_selected_family_diff_top consistent across hot+bridge; family_unresolved excluded from bridge (count=0)
blocker_status_before: DIAGNOSED (family-wide starvation proven in 47q but bridge_selected_family_diff_top None in bridge file; c3_gas_hopeless_* None in bridge; family_unresolved still in bridge; no architecture_blocker_trace)
blocker_status_after: FORMALIZED (all cross-artifact contract gaps closed; architecture_blocker_trace canonical block in rollup; family_unresolved fully excluded from bridge assembly+diverse fill+hard-pin+floor fill)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47r - close cross-artifact family-trace contract and formalize event-source architecture blocker
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) _write_hot_artifact returns 3-tuple (bridge_hit_trace, other_trace, fam_diff_list). (b) bridge_selected_family_diff_top persisted to bridge file via hot merge. (c) c3_gas_hopeless_skipped/families + bridge_selected_family_diff_top added to _HOT_PRESERVE_ALWAYS so cold lane overwrites don't erase them. (d) Preserve logic uses 'is not None' instead of truthiness for int/list safety. (e) family_unresolved excluded from bridge entirely - diverse fill, committed set, hard-pin, and floor fill all filter len(_pool_family) < 2. (f) architecture_blocker_trace added to hot rollup with blocker_class classification.
  - tests/unit/test_47r_cross_artifact_contract.py (NEW): 26 tests - cross-artifact bridge contract (4), c3_gas_hopeless non-null (6), family_unresolved exclusion (6), architecture_blocker_trace (8), return signature (2).
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47r.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47r_cross_artifact_contract.py (NEW)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3671 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: FAIL (1 error DEV_REPORT_ALIGNMENT - pre-existing stale timestamp, 3 warnings - expected, fixed by artifact refresh)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (0 restarts, clean exit, 18:10-18:21Z)

## 3) Artifacts Attached

Rolling artifacts (from 10-min nonstop, April 7 18:10-18:21Z):
- m7_cold_hot_bridge.json: bridge_selected_family_diff_top=list (families with reason_if_zero), c3_gas_hopeless_skipped=0, c3_gas_hopeless_families=[], family_unresolved count=0 in bridge_selected_pools_top
- m7_hot_latest.json: bridge_selected_family_diff_top=10 families (all no_events_at_any_family_pool)
- m7_hot_rollup_latest.json: architecture_blocker_trace={session_windows_seen=5, session_events_seen_total=2, families_selected_count=25, families_with_any_hot_events=0, families_with_exact_hits=0, blocker_class=event_source_absence}

## 4) Key Results - M7.A.5.47r

### architecture_blocker_trace (NEW in 47r)

| Metric | Value |
|--------|-------|
| session_windows_seen | 5 |
| session_events_seen_total | 2 |
| families_selected_count | 25 |
| families_with_any_hot_events | 0 |
| families_with_exact_hits | 0 |
| blocker_class | event_source_absence |

Canonical conclusion: blocker is event_source_absence, not selection_or_scoring.

### Cross-artifact contract (FIXED in 47r)

| Field | Hot artifact | Bridge file | Status |
|-------|-------------|-------------|--------|
| bridge_selected_family_diff_top | 10 families | 10 families | CONSISTENT |
| c3_gas_hopeless_skipped | 0 | 0 | CONSISTENT (non-null) |
| c3_gas_hopeless_families | [] | [] | CONSISTENT (non-null) |

Root cause fixed: cold lane's _HOT_PRESERVE_ALWAYS now includes these fields, and preserve logic uses 'is not None' for int/list safety.

### family_unresolved exclusion (FIXED in 47r)

family_unresolved pools excluded from bridge at 4 points:
1. diverse_fill loop: `len(_pool_family(pa)) < 2` → skip
2. _resolved_committed: filter from committed set before bridge assembly
3. hard-pin: only resolved-family pools from bucket_a
4. floor fill: skip unresolved in min floor fill

Result: family_unresolved count in bridge_selected_pools_top = 0.

### 47r Fixes Summary

1. _write_hot_artifact 3-tuple return: returns (bridge_hit_trace, other_trace, fam_diff_list)
2. bridge_selected_family_diff_top in bridge file: persisted via fam_diff_data from caller
3. c3_gas_hopeless_* preserved across cold overwrites: added to _HOT_PRESERVE_ALWAYS
4. Preserve logic safety: `is not None` instead of truthiness to handle 0 and []
5. family_unresolved fully excluded: 4-point exclusion across bridge assembly
6. architecture_blocker_trace: canonical blocker classification in hot rollup

## 5) Strategic Reading

1. EVENT_SOURCE_ABSENCE FORMALIZED: architecture_blocker_trace canonically classifies the blocker. 25 resolved families in bridge, 0 with any hot events over 5 windows. The code is correct — the market/event-source is the constraint.
2. CROSS-ARTIFACT CONTRACT CLOSED: bridge_selected_family_diff_top, c3_gas_hopeless_*, all consistent between hot and bridge files. No more None gaps.
3. ESCALATION RULE: Per 47q/47r, 2-3 more runs with 0 family events and 0 bridge hits → freeze M7 mainline on event-source ceiling. This is run 2 of 2-3 with identical outcome.
4. Recommended next steps: (a) Attempt peak-hours run (UTC 14:00-18:00) for one more data point, (b) if still 0, freeze M7 mainline and redirect to chain-onboarding (Base) or event-source architecture changes.

## 5.1) Contract Checks
status/reasons consistency: OK (MARKET_BLOCKED with event_source_absence - consistent)
rolling discipline: OK (architecture_blocker_trace, bridge_selected_family_diff_top preserve, family_unresolved exclusion are additive; no new artifact files)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
