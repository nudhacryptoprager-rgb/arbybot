# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-29T11:20:20Z
run_id: M7.E1.38 20m control soak after reviewer fix-list iteration
mode: ONLINE (20m Base control, rpc_fork, paper/sim-only)
artifact_mode: rolling
config: ProdSimBackend=rpc_fork, DiscSimBackend=rpc_fork, ARBY_MAX_TRADE_USD=50, ARBY_PRE_SIM_BISECT=1, ARBY_HOT_SWEEP_ENABLE=1, ARBY_SCORER_SIM_DIVERGENCE_BPS=500
code_identity:
  primary: ts:2026-04-29T11:20:20Z
  dirty: false
  desc: no code changes in this control session; 20m soak validates process stability but not economic path

## 1) Scope
goal (Roadmap): M7.E1 Base orderflow stabilization. Current control goal: confirm or refute the post-fix-list iteration with a fresh 20m online soak, without claiming production readiness from offline tests alone.

change_summary:
  - No runtime code changes in this session.
  - Re-read AGENTS.md, Roadmap.md, Status_M7.md, DOCS_POLICY.md, WORKFLOW.md, DEV_REPORT_CANONICAL_UA.md.
  - Verified unit suite and repo safety before soak.
  - Ran a first heartbeat-aware bootstrap attempt; it aborted because rollup did not advance within the probe window.
  - Ran a second 20m control with -NoRollupProbe; supervisor completed cleanly.
  - Verified reviewer, economics analyzer, dashboard live_deltas API, and replay-divergence tool behavior after the run.

touched_files:
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings, 20 gates)
py -3.11 scripts/check_rpc_endpoints.py --chain base --ws-timeout 15: PASS (Base chain_id/archive/newHeads OK; Flashblocks health emitted non-fatal 405 warning)
py -3.11 -m pytest tests/unit -q: PASS (4348 passed, 6 skipped, 1 warning; 115.70s)
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_system.ps1 -Hours 0.34 -ProdSimBackend rpc_fork -DiscSimBackend rpc_fork -RollupProbeHeartbeatSeconds 30: BOOTSTRAP_ABORTED (heartbeat extension fired, but rollup still did not advance before timeout)
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_system.ps1 -Hours 0.34 -ProdSimBackend rpc_fork -DiscSimBackend rpc_fork -NoRollupProbe: PASS process-wise, reviewer/economics FAIL by fresh deltas
py -3.11 scripts/reviewer_soak_summary.py --baseline data/runs/_rolling/reviewer_soak_baseline_latest.json --current data/runs/_rolling/m7_hot_rollup_latest.json --staleness-anchor-utc 2026-04-29T11:28:06Z: FAIL
py -3.11 scripts/reviewer_soak_summary.py --baseline data/runs/_rolling/reviewer_soak_baseline_latest_discovery.json --current data/runs/_rolling/m7_hot_rollup_latest_discovery.json --staleness-anchor-utc 2026-04-29T11:28:06Z: FAIL
py -3.11 scripts/analyze_roundtrip_profitability.py --baseline data/runs/_rolling/reviewer_soak_baseline_latest.json: FAIL (NO_ROUNDTRIP_ATTEMPTED)
py -3.11 scripts/replay_divergence_samples.py --rollup data/runs/_rolling/m7_hot_rollup_latest.json: NO_SAMPLES

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/m7_hot_rollup_latest.json
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json
  - data/runs/_rolling/m7_hot_latest.json
  - data/runs/_rolling/m7_hot_latest_discovery.json
  - data/runs/_rolling/reviewer_soak_baseline_latest.json
  - data/runs/_rolling/reviewer_soak_baseline_latest_discovery.json
session_logs:
  - data/runs/_sessions/m7_bootstrap_20260429_130350.out.log
  - data/runs/_sessions/m7_bootstrap_20260429_130732.out.log

## 4) Key Results
process health:
  supervisor_session_id: 998f31d3
  supervisor_started_utc: 2026-04-29T11:07:33Z
  supervisor_finished_utc: 2026-04-29T11:28:06Z
  children_alive_until_shutdown: 5/5
  crash_restarts: 0
  clean_restarts: 8
  external_provider_blocker_total: 0
  simulation_backend: rpc_fork

production lane delta vs baseline:
  baseline_session_id: 37e452d6
  current_session_id: 998f31d3
  events_seen_total: +100
  windows_seen: +1
  fast_path_scored_total: +0
  fast_path_positive_total: +0
  profit_guard_passed_total: +0
  sim_attempted_total: +0
  sim_passed_total: +0
  roundtrip_attempted_total: +0
  submit_ready_total: +0
  roundtrip_profitable_total: +0
  scorer_sim_divergence_samples_total: +0
  pre_sim_skip_samples_total: +0

discovery lane delta vs baseline:
  baseline_session_id: 37e452d6
  current_session_id: 998f31d3
  events_seen_total: +100
  windows_seen: +1
  fast_path_scored_total: +0
  sim_attempted_total: +0
  sim_passed_total: +0
  roundtrip_attempted_total: +0
  submit_ready_total: +0
  roundtrip_profitable_total: +0

dashboard live_deltas check:
  schema_version: summary_v2
  current_scan.live_deltas: present
  live_deltas.session_id: 998f31d3
  live_deltas.is_fresh: false
  live_deltas.fresh_funnel.events_seen: 100
  live_deltas.fresh_funnel.fast_path_scored: 0
  live_deltas.fresh_funnel.sim_attempted: 0
  live_deltas.fresh_funnel.roundtrip_attempted: 0

reviewer verdict:
  production_lane_ok: false
  reasons:
    - NO_FRESH_SIM_PASSED
    - NO_FRESH_ROUNDTRIP_ATTEMPTED
    - FAST_PATH_SCORED_TOO_LOW=0<20
    - STALE_ROLLUP[production] age=466s>120s
  discovery_lane_equivalent: false, same zero-fresh-sim shape

economics verdict:
  mode: DELTA_VS_BASELINE
  sim_attempted: 0
  roundtrip_attempted: 0
  roundtrip_profitable: 0
  verdict: NO_ROUNDTRIP_ATTEMPTED

## 4.1) Theoretical Net Profit
not_applicable: no fresh sim, no fresh roundtrip, no fresh profitable opportunity. No real or simulated net-profit claim is valid from this 20m run.

## 5) Contract Checks
status/reasons consistency: OK for failure state; reviewer FAIL matches artifact deltas.
rolling discipline: OK; canonical rolling artifacts overwritten, runtime logs remain under data/runs.
v2.x provenance contract: OK; evidence based on timestamps and rolling artifacts.
runtime artifacts not committed: OK.
dashboard live_deltas contract: PRESENT but marked stale because rollup age exceeded freshness threshold by analysis time.
bootstrap heartbeat contract: PARTIAL; heartbeat extension happened, but did not prevent abort in first attempt.

## 6) Blocker Classification
| Blocker Type | Level | Meaning |
|--------------|-------|---------|
| CODE | LOW-MEDIUM | Unit/safety green; no crash in 20m, but bootstrap probe logic is still too aggressive for slow hot rollup startup. |
| DATA_COLLECTION | HIGH | 20m produced +100 events per lane but 0 fast_path_scored, so signal funnel did not advance. |
| MARKET_WINDOW | HIGH | Control window did not produce executable candidates. |
| ECONOMICS | HIGH | No fresh sim, no roundtrip, no profitable path; production readiness remains blocked. |
| OBSERVABILITY | MEDIUM | live_deltas exists and correctly shows stale/zero-funnel state, but replay tool had NO_SAMPLES because no divergence sample fired. |

## 7) Production Readiness
Production criteria: fresh sim_passed > 0 AND fresh submit_ready > 0 AND fresh roundtrip_profitable > 0, with non-stale rollup.
Current 20m delta: sim_passed=0, submit_ready=0, roundtrip_profitable=0, rollup stale by reviewer anchor.
Verdict: NOT PRODUCTION-READY.

## 8) Reviewer Item Status After This Control
- #1 input-mismatch observability: NOT EXERCISED at runtime (no fresh divergence sample).
- #2 offline replay tool: TOOL RUN, returned NO_SAMPLES as expected from empty recent divergence ring.
- #3 eth_simulateV1 pending-state: still DEFERRED.
- #4 pre-sim size bisection: ENV enabled, but NOT EXERCISED because no fresh scored candidate reached pre-sim.
- #5 bootstrap heartbeat: PARTIAL; extension triggered, but first attempt still aborted.
- #6 factory enumeration scaffold: inert at runtime, no regression observed.
- #7 tier classifier scaffold: inert at runtime, no regression observed.
- #8 dashboard live_deltas: API PRESENT and truthful; it reports stale/zero fresh funnel.

## Session Completion
session_goal: Run a fresh 20m control soak to confirm or refute the post-fix-list iteration under online runtime conditions.
goal_status: BLOCKED
close_allowed: true
remaining_blockers: no fresh fast scoring, no fresh sim, no fresh roundtrip, reviewer FAIL, economics FAIL, bootstrap probe still aborts before hot rollup warmup in first attempt.
evidence_session_run_dirs:
  - data/runs/_rolling/m7_hot_rollup_latest.json (session_id=998f31d3, last_updated=2026-04-29T11:20:20Z)
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json (session_id=998f31d3, last_updated=2026-04-29T11:19:16Z)
  - data/runs/_sessions/m7_bootstrap_20260429_130350.out.log
  - data/runs/_sessions/m7_bootstrap_20260429_130732.out.log
primary_blocker_of_session: NO_FRESH_SIGNAL_PATH
blocker_status_before: UNRESOLVED
blocker_status_after: BLOCKED
docs_reread_confirmed: true
