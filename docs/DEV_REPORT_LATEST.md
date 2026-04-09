# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: ONLINE (M7.E1.5 funnel semantics fix + submit-stage scaffold, April 8 09:10-09:57Z 3x nonstop clean rollup. M4/M5 rolling unchanged — M7-only session with --no-m4)
artifact_mode: rolling
config: config/onboard_base_profit.yaml (base, narrow contour)
code_identity:
  primary: ts:2026-04-08T09:54:33Z
  dirty: true
  desc: M7.E1.5 - funnel semantics fix (route_viable_total, profit_guard from _fast), sim/submit scaffold, family_unresolved filtering

## Session Completion
session_goal: M7.E1.5 - fix funnel semantics (profit_guard_passed_total > viable_total inversion), add sim/submit placeholders, filter family_unresolved from bridge summary, prove invariant across 3 consecutive runs
goal_status: REACHED (Funnel invariant proven: scored(196) >= positive(17) >= route_viable(14) >= guard(14) across 3 clean runs. family_unresolved filtered. sim/submit scaffolded. Repeatability re-confirmed.)
close_allowed: true
remaining_blockers: sim_attempted/sim_passed/submit_ready all zero (placeholder only). Cold-hot convergence gap. Flashblocks WS untested. Family shows raw addresses.
evidence_session_run_dirs: [data/runs/_rolling/ (m7_hot_rollup_latest.json ts=2026-04-08T09:54:33Z, m7_hot_latest.json, m7_hot_intents_latest.json)]
primary_blocker_of_session: funnel_semantics — E1.4 profit_guard_passed_total=31 exceeded viable_total=19 due to batch rerun bypassing route_viable gate
blocker_status_before: M7.E1.4 OPEN — funnel inversion (guard > viable), family_unresolved in bridge summary, no sim/submit infrastructure
blocker_status_after: M7.E1.5 OPEN — funnel invariant holds (guard <= viable), family_unresolved filtered, sim/submit scaffolded (all zero — ready for E1.6 wiring)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.5 = fix funnel semantics and scaffold submit-stage
change_summary:
  - scripts/m7a_orderflow_loop.py: (1) Renamed viable_total → route_viable_total. (2) Changed profit_guard_passed_total from len(_guard) (batch) to sum from _fast inline attribute (gated on route_viable). (3) Added sim_attempted/sim_passed/submit_ready_total placeholders. (4) Filtered family_unresolved from bridge_selected_family_diff_top; added family_unresolved_pool_count. (5) Added sim_passed/submit_ready fields to hot intent rows.
  - tests/unit/test_e1_base_chain_aware.py: Replaced Section 15 with TestE1_5_FunnelSemantics (5 tests). Added Section 16: TestE1_5_IntentSubmitFields (2 tests). Added Section 17: TestE1_5_FamilyUnresolvedFiltering (3 tests).
  - docs/status/Status_M7.md: Updated status line, added E1.5 subsection, updated Known Blockers and Next Steps.
  - docs/DEV_REPORT_LATEST.md: This file.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED — funnel fix, sim scaffold, family filtering)
  - tests/unit/test_e1_base_chain_aware.py (MODIFIED — 10 new E1.5 tests, 5 old E1.4 funnel tests replaced)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3746 passed, 6 skipped — 3741 − 5 old + 10 new)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (1 warning — Status_M7.md bloat)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --chain base --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS x3 (clean rollup, 09:25-09:57Z)

## 3) Artifacts Attached

M7 rolling artifacts (from 3x Base 10-min nonstop, clean rollup, April 8 09:25-09:57Z):
- m7_hot_rollup_latest.json: last_updated=2026-04-08T09:54:33Z, windows_seen=59, events_seen_total=290, fast_path_scored_total=196, fast_path_positive_total=17, route_viable_total=14, profit_guard_passed_total=14, sim_attempted_total=0, sim_passed_total=0, submit_ready_total=0
- m7_hot_latest.json: final window viable_count=1, profit_guard_passed_count=1, best_net_bps_clean=68.254, family_unresolved_pool_count=3, bridge_selected_family_diff_top excludes family_unresolved
- m7_hot_intents_latest.json: intent rows include sim_passed=null, submit_ready=null

## 4) Key Results - M7.E1.5

### Funnel Invariant Evidence (3 clean runs)

| Metric | Run #1 | Run #2 (cumul.) | Run #3 (cumul.) |
|--------|--------|-----------------|-----------------|
| `fast_path_scored_total` | 61 | 134 | **196** |
| `fast_path_positive_total` | 10 | 11 | **17** |
| `route_viable_total` | 7 | 8 | **14** |
| `profit_guard_passed_total` | 7 | 8 | **14** |
| Invariant check | PASS | PASS | **PASS** |

### Bug Fix Detail

**Root cause**: `_update_hot_rollup()` used `len(_guard)` for `profit_guard_passed_total`. `_guard` came from `_run_profit_guard_on_results()` which runs on ALL positive results (no route_viable gate). The inline `profit_guard_passed` attribute in scoring_parallel.py is only set when `route_viable=True`. Fix: count from `_fast` inline attribute instead of batch.

**Before (E1.4)**: scored=278, positive=31, viable=19, guard=31 — guard > viable (INVARIANT VIOLATED)
**After (E1.5)**: scored=196, positive=17, viable=14, guard=14 — guard <= viable (INVARIANT PASS)

### New Artifact Fields

| Field | Location | Value |
|-------|----------|-------|
| `route_viable_total` | rollup | 14 (renamed from viable_total) |
| `sim_attempted_total` | rollup | 0 (placeholder) |
| `sim_passed_total` | rollup | 0 (placeholder) |
| `submit_ready_total` | rollup | 0 (placeholder) |
| `family_unresolved_pool_count` | hot artifact | 3-8 per window |
| `sim_passed` | intent row | null (placeholder) |
| `submit_ready` | intent row | null (placeholder) |

## 5) Strategic Reading

1. **E1.5 goal REACHED**: Funnel invariant proven correct across 3 clean runs. The E1.4 inversion was a measurement artifact (batch vs inline counting), not a scoring bug.
2. **Submit-stage is the next frontier**: sim infrastructure is scaffolded. E1.6 goal: wire Tenderly fork simulation for top guard-passed intents → `sim_passed_total > 0`.
3. **Viable rate stable**: 14/196 = 7.1% viable rate, consistent with E1.4's ~10%. Market-driven fluctuation is expected.
4. **family_unresolved filtering improves signal quality**: Bridge summary now shows only resolved families, while family_unresolved_pool_count provides diagnostics without polluting the ranking.

## 5.1) Contract Checks
status/reasons consistency: OK (REACHED — funnel invariant proven, sim scaffolded, family filtered)
rolling discipline: OK (m7_hot_rollup_latest.json updated at 09:54:33Z, no new artifact files)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
