# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-10T12:00:00Z
run_id: N/A (offline code session — E1.9.1 namespace isolation)
mode: OFFLINE (M7.E1.9.1 artifact namespace isolation. Code + tests only. No new online runtime.)
artifact_mode: rolling
config: N/A (namespace isolation applies to all profiles)
code_identity:
  primary: ts:2026-04-10T12:00:00Z
  dirty: true
  desc: M7.E1.9.1 - artifact namespace isolation for discovery/production parallel safety

## Session Completion
session_goal: M7.E1.9.1 - fix reviewer issue #6 (artifact contamination). Discovery profile must write to separate rolling files so parallel production+discovery runs don't corrupt evidence. Also fix doc contract mismatch (DEV_REPORT goal_status vs Status_M7 OPEN).
goal_status: REACHED (code: namespace isolation implemented. Discovery artifacts use _discovery suffix. Production paths unchanged. Doc contract aligned.)
close_allowed: true
remaining_blockers: (1) Online A/B evidence pending — discovery vs production profiles need sequential or parallel nonstop run. (2) Scoreboard graduation untested in live runtime. (3) Flashblocks WS DNS unreachable. (4) Submit sim = 0.
evidence_session_run_dirs: [N/A — offline code session.]
primary_blocker_of_session: artifact_contamination_on_parallel_runs — RESOLVED (discovery writes to separate namespace)
blocker_status_before: ACTIVE — reviewer identified that both profiles write to same rolling files, contaminating evidence if run in parallel
blocker_status_after: RESOLVED — discovery profile redirects all 7 rolling artifacts to _discovery suffix filenames
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.9.1 = artifact namespace isolation per reviewer issue #6 + fix steps 3-4
change_summary:
  - scripts/m7a_orderflow_loop.py: _rolling_path(name, profile) helper, _init_artifact_paths(profile) to redirect all 6 module-level paths. Called at run_loop startup. Import _set_rolling_m7_profile from mode_ws_live.
  - m7/orderflow/mode_ws_live.py: _set_rolling_m7_profile(profile) to redirect cold lane rolling path.
  - docs/status/Status_M7.md: E1.9.1 section with policy statement.
  - docs/DEV_REPORT_LATEST.md: Aligned goal_status, fixed contract mismatch.
  - tests/unit/test_e1_9_discovery_lane.py: Added namespace isolation tests.
touched_files:
  - scripts/m7a_orderflow_loop.py
  - m7/orderflow/mode_ws_live.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md
  - tests/unit/test_e1_9_discovery_lane.py

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3825 passed, 6 skipped)

## 3) Artifacts Attached

No runtime artifacts — offline code session. Rolling artifacts unchanged.

## 4) Key Results - M7.E1.9.1

### Reviewer Issues Addressed

| Issue | Description | Status |
|-------|-------------|--------|
| #6 | Both profiles write same rolling files — evidence contamination | FIXED (discovery uses _discovery suffix) |
| #7 | Discovery scoreboard no live truth | ACKNOWLEDGED (needs online run) |
| #8 | DEV_REPORT goal_status vs Status_M7 OPEN mismatch | FIXED (aligned) |

### Reviewer Fix Steps Addressed

| Step | Description | Status |
|------|-------------|--------|
| 3 | Don't run production+discovery simultaneously without isolation | FIXED (namespace isolation) |
| 4 | Separate artifact namespace for discovery lane | DONE (7 files get _discovery suffix) |
| 8 | Document policy: narrow production intentional, wide discovery mandatory | DONE (Status_M7 E1.9.1 section) |

### Artifact Namespace Mapping

| Production path | Discovery path |
|----------------|---------------|
| m7_hot_latest.json | m7_hot_latest_discovery.json |
| m7_orderflow_latest.json | m7_orderflow_latest_discovery.json |
| m7_hot_rollup_latest.json | m7_hot_rollup_latest_discovery.json |
| m7_hot_intents_latest.json | m7_hot_intents_latest_discovery.json |
| m7_cold_hot_bridge.json | m7_cold_hot_bridge_discovery.json |
| m7_promoted_pairs.json | m7_promoted_pairs_discovery.json |
| m7_discovery_scoreboard.json | m7_discovery_scoreboard_discovery.json |

## 5) Strategic Reading

1. **Namespace isolation is a prerequisite for honest A/B evidence**: Without separate files, running discovery and production profiles concurrently or even alternately without cleanup would mix signals. The reviewer correctly identified this as the highest-priority code fix before any A/B evidence collection.
2. **Production paths unchanged (backward compatible)**: Dashboard, CI gates, and all existing commands read production paths. Discovery artifacts are diagnostic-only and intentionally excluded from the dashboard.
3. **Sequential A/B is now safe; parallel A/B is also safe**: With separate namespaces, either approach works without evidence contamination.
4. **Next action is A/B evidence**: Run `--profile discovery` and `--profile production` during peak Base hours. Compare funnel conversion (scored_positive, route_viable, guard_passed, gas reject rate) as reviewer requested in fix step 9.

## 5.1) Contract Checks
status/reasons consistency: OK (REACHED — namespace isolation implemented and tested)
rolling discipline: OK (production keeps canonical files, discovery uses separate namespace)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true

## 6) Blocker Classification

code_blocker: NONE (namespace isolation complete)
data_collection_blocker: HIGH (empty windows — signal_counts still zero without online run)
market_window_blocker: HIGH (Base swap events absent in off-peak windows)

## 6.1) Blockers / Risks
- No non-empty windows — signal_counts/gate_trace not exercised in runtime
- Flashblocks WS DNS unreachable
- Submit sim = 0 (scaffold only)
- Discovery scoreboard untested in live runtime

## 8) What I need from Lead now
question_1: Confirm E1.9.1 closure (namespace isolation). Schedule A/B evidence run?
request_1: Schedule 10-30min peak-hours Base nonstop for each profile (production first, then discovery) to collect independent evidence for funnel comparison.
