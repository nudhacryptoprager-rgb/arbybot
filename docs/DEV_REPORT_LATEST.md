# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: ONLINE (nonstop verification with fresh rolling artifacts)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.45 — bridge execution queue, hot intents artifact, headline_level enforcement
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z
m7_orderflow_timestamp: 2026-04-06T10:37:14Z
m7_hot_timestamp: 2026-04-06T10:34:43Z
m7_hot_intents_timestamp: 2026-04-06T10:34:43Z

## Session Completion
session_goal: M7.A.5.45 — bridge as scheduler input for hot lane, hot execution intents artifact, funnel headline_level enforcement
goal_status: REACHED (bridge-driven execution queue with priority_pools, m7_hot_intents_latest.json emitted, headline_level in cold/hot artifacts + dashboard badge, 10-min nonstop 3/3 alive 0 restarts)
close_allowed: true
remaining_blockers: hot_scored=0 (market timing — incoming hot events at different pools than cold_executable), profit_guard_passed=0 in hot lane (requires hot-scored event first)
evidence_session_run_dirs: [tests/unit (3327 passed, 6 skipped), nonstop 10-min (m7_orderflow_latest.json, m7_hot_latest.json, m7_hot_intents_latest.json, m7_cold_hot_bridge.json)]
primary_blocker_of_session: No machine-readable headline enforcement — cold/hot artifacts could claim progress beyond confirmed level; no priority prewarm for cold_executable pools; no separate hot intents artifact
blocker_status_before: ACTIVE (headline_level missing; prewarm treated all ptt entries equally; no hot intents artifact)
blocker_status_after: RESOLVED (headline_level in execution_funnel + hot artifact + hot intents + dashboard badge; priority prewarm from cold_executable pools; m7_hot_intents_latest.json with compact rows)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.45 — bridge-driven execution queue + hot intents + headline enforcement
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) _prewarm_registry_from_bridge() now accepts priority_pools param — cold_executable + near_executable pool addresses get priority prewarm via sorted iteration. (b) Hot lane extracts cold_exec_pools set from bridge cold_executable + near_executable, passes as priority_pools. (c) New _write_hot_intents() writes m7_hot_intents_latest.json with compact rows for hot-scored candidates only (capped at 20). (d) New _compute_headline_level() returns highest confirmed funnel stage with count > 0. (e) New _HOT_INTENTS_PATH constant. (f) headline_level added to hot artifact top-level.
  - m7/orderflow/artifacts.py (MODIFIED): execution_funnel now includes headline_level string field — highest confirmed stage.
  - monitoring/dashboard.html (MODIFIED): Headline level badge above funnel table (color-coded: red=none, yellow=diagnostic/cold, green=hot_scored+).
  - monitoring/dashboard_server.py (MODIFIED): New /api/intents endpoint. m7_hot_intents added to ARTIFACT_FILES.
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): +17 tests in 6 new classes. Updated 2 existing M7A544 tests for headline_level field.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.45 section. Updated header.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.45)
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/orderflow/artifacts.py (MODIFIED)
  - monitoring/dashboard.html (MODIFIED)
  - monitoring/dashboard_server.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3327 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all required gates)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (3/3 alive, 0 restarts)

## 3) Artifacts Attached

fresh rolling (from M7.A.5.45 nonstop):
  - data/runs/_rolling/m7_orderflow_latest.json (cold: events=30, positive_clean=7, best_clean=52.2 bps, execution_funnel={diagnostic_positive:7, cold_executable_positive:0, hot_scored:0, profit_guard_passed:0, realized_onchain_profit:0, headline_level:"diagnostic_positive"})
  - data/runs/_rolling/m7_hot_latest.json (hot: iterations=27, headline_level:"none", hot_scored=0, bridge diagnostics active)
  - data/runs/_rolling/m7_hot_intents_latest.json (NEW: hot_scored_count=0, cold_executable_pool_count=2, headline_level:"none", intents=[])
  - data/runs/_rolling/m7_cold_hot_bridge.json (cold_executable=0, near_executable=5, pool_token_transport=46)
  - data/runs/_rolling/m7_promoted_pairs.json

## 4) Key Results — M7.A.5.45

### Headline Level Enforcement (NEW)

headline_level is now emitted in 3 artifacts:
- Cold artifact `execution_funnel.headline_level`: "diagnostic_positive" (7 positives clean, 0 cold_executable)
- Hot artifact `headline_level`: "none" (0 hot-scored events)
- Hot intents artifact `headline_level`: "none" (0 hot-scored events)

Dashboard badge renders color-coded: red=none, yellow=diagnostic/cold, green=hot_scored+.
This prevents misinterpreting "9 diagnostic positives" as "9 execution-ready candidates."

### Bridge Execution Queue (NEW)

Priority prewarm: cold_executable + near_executable pool addresses extracted from bridge, passed as priority_pools to _prewarm_registry_from_bridge(). Priority pools sorted first in iteration order — ensures registry cache warm for cold-verified candidates before spending time on generic ptt entries.

This run: cold_executable_pool_count=2 (from prior bridge), near_executable=5, ptt=46. Priority pools = 7 out of 46 (15% of ptt) get first prewarm.

### Hot Execution Intents Artifact (NEW)

`m7_hot_intents_latest.json` schema:
```json
{
  "timestamp": "2026-04-06T10:34:43Z",
  "loop_iteration": 27,
  "headline_level": "none",
  "hot_scored_count": 0,
  "hot_positive_count": 0,
  "profit_guard_passed_count": 0,
  "cold_executable_pool_count": 2,
  "intents": []
}
```

When hot-scored events arrive, intents[] will contain compact rows with: event_id, actual_pair, net_bps, profit_guard_passed, guard_passed_in_hot, scoring_path, pipeline_latency_ms, route_viable. Capped at 20 rows.

### Comparison with M7.A.5.44

| Metric | M7.A.5.44 | M7.A.5.45 | Change |
|--------|-----------|-----------|--------|
| headline_level | Not implemented | 3 artifacts + dashboard | NEW |
| priority_prewarm | All ptt equal | cold_executable first | NEW |
| m7_hot_intents_latest.json | Not implemented | Schema defined, emitted | NEW |
| /api/intents | Not implemented | Endpoint operational | NEW |
| cold_executable_positive | 2 | 0 (this window) | Market-dependent |
| tests | 3310 | 3327 | +17 |

## 5) Strategic Reading

1. **headline_level prevents over-claiming**: With headline_level="diagnostic_positive" in cold and "none" in hot, no one can misread the funnel as "execution-ready." The dashboard badge makes the gap immediately visible.
2. **Priority prewarm targets gold candidates**: Instead of treating all 46 pool_token_transport entries equally, the 7 cold_executable + near_executable pools are prewarmed first. This maximizes the chance that if a hot event hits a verified profitable pool, the registry is already warm for it.
3. **Hot intents artifact creates the submission queue contract**: When hot_scored > 0, the intents array will contain the exact candidates ready for profit_guard check. This separates "what hot lane observed" from "what is submit-ready."
4. **The remaining gap is event arrival probability**: cold_executable pools are verified profitable but hot events arrive at different pools. The fix is not in scoring (already works) but in: (a) pool coverage, (b) event density, (c) market timing.
5. **Path to first hot_scored=1**: requires incoming mempool/block event whose pool_address is in the cold_executable transported set. Bridge now carries cold_executable pool addresses as priority prewarm, improving the chance that the registry/cache is warm when such an event arrives.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files + m7_promoted_pairs.json + m7_cold_hot_bridge.json + m7_hot_intents_latest.json)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
