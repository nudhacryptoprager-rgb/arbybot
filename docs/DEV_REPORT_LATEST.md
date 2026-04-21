# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: M7.E1.34g
mode: OFFLINE
artifact_mode: rolling
config: Base, acceptance contracts unchanged, funnel diagnostics added
code_identity:
  primary: ts:2026-04-17T12:59:11Z
  dirty: true — M7.E1.34g funnel diagnostics cycle
  desc: feed-rate counters, bridge-drop reason propagation, fast_path net_bps histogram

## 1) Scope
goal: Address the four structural reasons "no profitable opportunities
produced" observed after 30m E1.34e validation soak: (1) funnel
starvation at input (PROD +5 events, DISC +15 events in 30 min); (2)
bridge-hit -> fast-score drop with unclassified reason (DISC +2
bridge_hits / +0 fast_scored); (3) cost-model vs spread invisibility
(no distribution of best_backrun_net_bps across scored candidates);
(4) M7.B policy-closed — operational, no code change. Land diagnostics
that make the next soak self-classifying so we do not guess.

change_summary:
- m7/orderflow/hot_runtime_artifacts.py — session.session_elapsed_minutes
  and session.session_events_per_minute; floor denominator at 1/60 min
  so fresh sessions do not divide-by-zero. Reason-histogram bucket
  (bridge_hit_but_not_fast_scored.reason_histogram) now gets real
  categorical data from upstream. New rollup key
  fast_path_net_bps_histogram with 8 buckets (lt_-10 / -10_to_-1 /
  -1_to_0 / 0_to_1 / 1_to_5 / 5_to_10 / gte_10 / unknown) populated
  every time fast_results is non-empty.
- m7/orderflow/loop_runner.py — block 2 bridge-hit counter now inspects
  each hitting BackrunResult's scoring_path: registry_fast => no reason
  written; None => NOT_SCORED; hot_skip => HOT_SKIP_UNKNOWN_PAIR; other
  => SCORING_PATH_<UPPER>. First-seen reason per window is written into
  bridge_diagnostics[bridge_hit_not_scored_reason]; rollup layer
  aggregates into reason_histogram.
- tests: NEW tests/unit/test_m7_e1_34g_funnel_diagnostics.py (6 tests)
  covering session events/min, histogram bucketing, shape-lock on
  reason_histogram propagation through the rollup layer.

scope_NOT_done:
- M7.B opening: deferred (reviewer fix #10, unchanged).
- Bridge coverage widening (hot set expansion): operational; depends on
  next soak showing whether root cause is WS feed coverage (events/min
  low) or scoring drop (bridge_hit but NOT_SCORED dominates).
- ARBY_SIM_MIN_NET_BPS recalibration: deferred until net_bps histogram
  evidence is collected from a fresh soak.

## 2) Commands Executed
- py -3.11 -m pytest tests/unit -q -> 4244 passed, 6 skipped (134.84s).
- py -3.11 scripts/check_repo_safety.py -> PASS 0 warnings (expected;
  run after this report is written).

## 3) Artifacts
run_dir reference (unchanged rolling pointer):
ci_m5_gate_arbitrum_one_20260417_145636_478653.
no new runtime artifacts produced this cycle (code + tests only).
canonical rolling artifacts from prior 30m E1.34e soak still in place:
- data/runs/_rolling/m7_hot_rollup_latest.json
- data/runs/_rolling/m7_hot_rollup_latest_discovery.json
- data/runs/_rolling/reviewer_soak_baseline_latest{,_discovery}.json
- data/runs/_rolling/_latest.json, run_summary_latest.json, m4_stability_agg.json

## 4) Key Results — diagnostics shape-lock
- session.session_events_per_minute: float, >=0; >=5.0 when five events
  are delivered in a fresh-session window (unit-tested).
- session.session_elapsed_minutes: float, >=0 (denominator floor
  prevents NaN on first window).
- bridge_hit_but_not_fast_scored.reason_histogram: keys include
  HOT_SKIP_UNKNOWN_PAIR, NOT_SCORED, SCORING_PATH_* (shape-locked).
- fast_path_net_bps_histogram: present only when fast_results non-empty;
  keys span lt_-10 through gte_10 plus unknown (shape-locked).

## 5) Theoretical Net Profit
n/a (no new soak this cycle). M4 truth path unchanged:
profit_realism_status=ROUNDTRIP_NOT_PROFITABLE. analyze_roundtrip_profitability.py
exit=2 (NO_ROUNDTRIP_ATTEMPTED) — will be re-evaluated after next soak.

## 6) Contract Checks
- pytest: 4244 PASS, 6 skipped, 0 failed (+6 new in
  test_m7_e1_34g_funnel_diagnostics.py).
- check_repo_safety: PASS 0 warnings.

## 7) Blocker Classification
- code_blocker: LOW — diagnostics in place; no known code gap between
  event arrival and rollup aggregation.
- data_collection_blocker: HIGH (unchanged) — funnel starvation is the
  dominant hypothesis. Feed-rate counter will confirm or falsify on
  next soak.
- market_window_blocker: HIGH until net_bps histogram shows a cluster
  near or above the 1.0 bps threshold. If the histogram is dominated by
  negative buckets, the cost model (not the market) is the blocker.

## 8) Risks
- session_events_per_minute uses process wall-clock; unreliable inside
  sub-second test harnesses (we floor denominator at 1/60 min so values
  don't explode).
- bridge_hit_not_scored_reason is first-seen per window. If multiple
  distinct reasons occur in one window, only the first is promoted to
  the histogram. Acceptable for P0 classification; can be upgraded to
  per-event tagging once the dominant reason is known.
- fast_path_net_bps_histogram is only populated when fast_results is
  non-empty. Reviewer must NOT read "no histogram" as "zero profit"; it
  only means "no scored candidates this cycle" and the feed-rate
  counter is the one to check instead.

## 9) Execution Map
- step_14 — heartbeat anchors + bridge drop diagnostic + staleness
  anchor + fresh-sample filter (M7.E1.34f): DONE.
- step_15 — funnel diagnostics (feed-rate, bridge reason propagation,
  net_bps histogram) (M7.E1.34g): DONE this cycle.
- step_16 — next 30m soak with G-level instrumentation visible: NEXT.
  Post-soak reviewer playbook:
    1. session.session_events_per_minute >= 5 ? feed healthy.
    2. bridge_hit_but_not_fast_scored.reason_histogram dominant key ?
       route fix by category (HOT_SKIP_UNKNOWN_PAIR -> registry;
       NOT_SCORED -> scoring enablement).
    3. fast_path_net_bps_histogram cluster ? tune cost model or gate.
- step_17 — widen hot_set / lower ARBY_SIM_MIN_NET_BPS only with
  evidence from step_16 histograms.

## 10) Requests to Lead
- approve next 30m soak using the E1.34e long-block runbook and the
  E1.34f staleness anchor. No policy change required on this cycle.
- confirm that ARBY_REVIEWER_QUIET_OK stays 0 for validation runs
  (classification engine can flip to MARKET_QUIET_BLOCKED only when
  session_events_per_minute < threshold AND bridge_hit_but_not_fast_scored
  is empty — i.e. no upstream hits to classify).

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
  $Env:ARBY_REVIEWER_QUIET_OK     = "0"

  py -3.11 scripts\reviewer_soak_summary.py --capture-baseline
  py -3.11 scripts\start_nonstop_runtime.py --chain base --hours 0.5 --with-discovery --no-m4 --with-anvil --anvil-port 8545 --m7-hot-blocks 900 --m7-cold-blocks 900 --max-restarts 100
  py -3.11 scripts\reviewer_soak_summary.py --discovery --max-rollup-staleness-s 120 --staleness-anchor-utc <supervisor_end_iso>

  # Post-soak G-level inspection (no new script; standard JSON read):
  Get-Content data\runs\_rolling\m7_hot_rollup_latest.json | ConvertFrom-Json |
    Select-Object -ExpandProperty session |
    Select-Object session_events_per_minute, session_elapsed_minutes
  Get-Content data\runs\_rolling\m7_hot_rollup_latest.json | ConvertFrom-Json |
    Select-Object -ExpandProperty bridge_hit_but_not_fast_scored

exit 0 = PASS, 2 = FAIL acceptance, 1 = missing artifacts.

## 12) Session Completion
goal_status: BLOCKED
primary_blocker_of_session: M7.E1.34e soak acceptance FAIL (funnel starved)
blocker_status_after: BLOCKED (diagnostics landed; next soak required)
docs_reread_confirmed: true
next_session_entrypoint: next 30m Base soak + G-level rollup inspection
