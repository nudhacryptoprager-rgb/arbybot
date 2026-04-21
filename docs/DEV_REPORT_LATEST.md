# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: M7.E1.34e
mode: OFFLINE
artifact_mode: rolling
config: Base, M7.E1.34d acceptance contracts retained
code_identity:
  primary: ts:2026-04-17T12:59:11Z
  dirty: true — M7.E1.34e reviewer-fix cycle
  desc: supervisor clean-vs-crash restart accounting, fast_path_scored gate, stale-rollup gate, session-delta invariant, sim_failed_samples session provenance

## 1) Scope
goal: Land reviewer fix steps from 2026-04-21 17:58–18:28Z STF soak FAIL.
Strict-provider regression delta is fixed (+0) and Anvil drift remains
fixed (+0 BlockOutOfRangeError). Defect was operational: supervisor
default --max-restarts=10 plus --m7-hot-blocks=20 exhausted budget
after ~4 min, leaving ~17 min idle and +0 fast_path_scored /
+0 sim_passed / +0 roundtrip_attempted.

change_summary:
- scripts/start_nonstop_runtime.py — ManagedProcess gains
  cycles_completed, crash_restarts, max_crash_restarts_hit;
  check_and_restart treats rc==0 as clean cycle exit (always relaunch,
  never consume --max-restarts); rc!=0 consumes budget. Defaults
  bumped: --m7-hot-blocks 20 -> 900, --m7-cold-blocks 300 -> 900,
  --max-restarts 10 -> 100. Per-process supervisor summary at shutdown.
- scripts/reviewer_soak_summary.py — new fast_path_scored gate
  (delta >= ARBY_REVIEWER_MIN_FAST_PATH_SCORED, default 20; opt-in
  override via ARBY_REVIEWER_QUIET_OK=1); new
  --max-rollup-staleness-s (default 120) fails when production
  rollup did not refresh near supervisor end.
- m7/orderflow/hot_runtime_artifacts.py —
  invariant_violations.profit_guard_exceeds_route_viable now carries
  session_profit_guard_passed_delta, session_route_viable_delta,
  session_delta, is_session_regression. sim_failed_samples_recent
  entries stamped with session_id and sample_updated_at.
- tests: NEW tests/unit/test_m7_e1_34e_reviewer_fixes.py (7 tests);
  tests/unit/test_reviewer_soak_summary.py PASS fixture updated.

scope_NOT_done: corrected 30m soak with new defaults (deferred per
reviewer fix #10 — do not open M7.B before fresh submit_ready>0 and
roundtrip_profitable_delta>0); bridge coverage debug.

## 2) Commands Executed
- py -3.11 -m pytest tests/unit -q -> 4229 passed, 6 skipped, 0 failed (114.22s).
- py -3.11 scripts/check_repo_safety.py -> PASS.

## 3) Artifacts
no new runtime artifacts produced this cycle (code + tests only).
canonical run_dir reference (unchanged from rolling pointer):
ci_m5_gate_arbitrum_one_20260417_145636_478653.
canonical operational artifacts unchanged from M7.E1.34d soak end:
- data/runs/_rolling/m7_hot_rollup_latest.json last_updated 2026-04-21T18:09:01Z (PROD)
- data/runs/_rolling/m7_hot_rollup_latest_discovery.json last_updated 2026-04-21T18:10:23Z (DISC)
- data/runs/_rolling/reviewer_soak_baseline_latest{,_discovery}.json
- data/runs/_rolling/_latest.json, run_summary_latest.json, m4_stability_agg.json

## 4) Key Results — 30m STF validation soak 2026-04-21 17:58–18:28Z (M7.E1.34d code)
PRODUCTION lane:
- last_updated 2026-04-21T18:09:01Z (~19 min before supervisor end)
- delta sim_passed=+0, roundtrip_attempted=+0, fast_path_scored=+0
- delta BlockOutOfRangeError=+0 (Step 9 confirmed)
- delta strict_provider_breaches=+0 (M7.E1.34d hardening confirmed)
- windows ~+6, events ~+15

DISCOVERY lane:
- last_updated 2026-04-21T18:10:23Z (~18 min before supervisor end)
- delta sim_passed=+0, roundtrip_attempted=+0, fast_path_scored=+0
- delta strict_provider_breaches=+0, BlockOutOfRangeError=+0
- windows ~+5, events ~+13

Supervisor end: 2026-04-21T18:28:21Z. Both hot lanes idle for final ~17 min.

Reviewer summary verdict: FAIL (supervisor restart-budget exhaustion).
M7.E1.34d code-side regressions confirmed not to recur.

## 5) Theoretical Net Profit
n/a (no new soak this cycle). M4 truth path unchanged:
profit_realism_status=ROUNDTRIP_NOT_PROFITABLE.

## 6) Contract Checks
- pytest: 4229 PASS, 6 skipped, 0 failed (+7 new in
  test_m7_e1_34e_reviewer_fixes.py).
- check_repo_safety: PASS.

## 7) Blocker Classification
- code_blocker: LOW — supervisor + acceptance contracts reviewer-proof.
- data_collection_blocker: HIGH — premium RPC/WS still required.
- market_window_blocker: HIGH until corrected long-block soak runs.

## 8) Risks
- new defaults extend cycle wallclock; if a worker truly wedges, restart
  cadence is slower (mitigated by per-process supervisor summary).
- ARBY_REVIEWER_QUIET_OK=1 is operator-only; if accidentally exported
  during a real soak it could mask a starved funnel.
- session-delta invariant flags only intra-session regressions;
  cumulative pollution surfaces but is explicitly tagged.

## 9) Execution Map
- step_11 — supervisor restart-budget split + reviewer acceptance
  hardened: DONE this cycle (M7.E1.34e).
- step_12 — corrected 30m STF soak with new defaults: NEXT (cmd in §11).
- step_13 — bridge coverage debug: NEXT after step_12 if
  fast_path_scored_delta>=20 but sim_passed_delta==0.

## 10) Requests to Lead
- approve corrected 30m STF soak with long-block defaults from §11.
- confirm ARBY_REVIEWER_QUIET_OK policy (opt-in only vs auto-set on
  MARKET_QUIET_BLOCKED).

## 11) Reviewer Runbook
RUNBOOK:
  $Env:ARBY_STRICT_PROVIDER_POLICY = "1"
  $Env:ARBY_RPC_PREMIUM_ONLY      = "1"
  $Env:ARBY_REQUIRE_PREMIUM       = "1"
  $Env:ARBY_REQUIRE_ARCHIVE       = "1"
  $Env:ARBY_SIM_BACKEND           = "anvil"
  $Env:ARBY_ANVIL_AUTO_REFRESH    = "1"
  $Env:ARBY_ANVIL_CLAMP_BLOCK     = "1"
  $Env:ARBY_SIM_ADMISSION_STRICT  = "1"
  $Env:ARBY_SIM_MIN_NET_BPS       = "1.0"
  $Env:ARBY_SIM_BYPASS_GUARD      = "0"

  py -3.11 scripts\reviewer_soak_summary.py --capture-baseline
  py -3.11 scripts\start_nonstop_runtime.py --chain base --hours 0.5 --with-discovery --no-m4 --with-anvil --anvil-port 8545 --m7-hot-blocks 900 --m7-cold-blocks 900 --max-restarts 100
  py -3.11 scripts\reviewer_soak_summary.py --max-rollup-staleness-s 120

exit 0 = PASS, 2 = FAIL acceptance, 1 = missing artifacts.

## 12) Session Completion
goal_status: BLOCKED
primary_blocker_of_session: M7.E1.34d acceptance validation soak FAIL
blocker_status_after: BLOCKED (corrected long-block soak required)
docs_reread_confirmed: true
next_session_entrypoint: corrected 30m STF soak with M7.E1.34e supervisor
