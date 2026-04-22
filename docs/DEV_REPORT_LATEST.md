# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: M7.E1.34h
mode: OFFLINE
artifact_mode: rolling
config: Base, acceptance contracts unchanged, reviewer 10-step batch
code_identity:
  primary: ts:2026-04-17T12:59:11Z
  dirty: true — M7.E1.34h reviewer batch cycle
  desc: enriched HOT_SKIP_UNKNOWN_PAIR samples, supervisor_window, shutdown flush, sim-failed ring session prune

## 1) Scope
goal: Address the reviewer 30-min E1.34g validation verdict (2026-04-21
T20:12:56Z–T20:42:59Z, acceptance FAIL, feed starvation +
HOT_SKIP_UNKNOWN_PAIR drop). Land the 4 code-addressable items from
reviewer 10-step fix batch and document the rest as policy/operational.

change_summary:
- m7/orderflow/loop_runner.py — bridge-hit block 2 now writes
  bridge_hit_not_scored_sample with raw pool_address, scoring_path,
  actual_pair, token_in, token_out, fee_tier, venue, adapter_type.
  Loop-exit path calls flush_rollup_shutdown(cli_args.chain) so every
  clean supervisor-managed exit stamps shutdown_flush_at and refreshes
  last_heartbeat_utc (fix #3, fix #6).
- m7/orderflow/hot_runtime_artifacts.py — supervisor_window block
  computed from rollup.first_window_at + events_seen_total; survives
  session_id changes across child restarts (fix #5). sim_failed_samples_recent
  ring is pruned to the current _SESSION_ID before each append, so no
  cross-session stale samples (fix #7). bridge_hit_but_not_fast_scored
  bucket now carries a bounded samples list (max 10) propagated from
  loop_runner (fix #3). New flush_rollup_shutdown(chain) helper (fix #6).
- tests: NEW tests/unit/test_m7_e1_34h_reviewer_fixes.py (7 tests):
  TestBridgeSampleEnrichment x2, TestSupervisorWindow x2,
  TestShutdownFlush x2, TestSimFailedSamplesSessionPrune x1.

scope_NOT_done (documented as policy/operational):
- #1/#10 accept = BLOCKED/goal_status BLOCKED: recorded in Status_M7.
- #2 feed coverage fix on Base (hot set, pair filter, WS coverage):
  operational; requires registry + intent changes beyond this surgical
  cycle.
- #4 bridge <-> canonical pair registry join: requires pair-registry
  audit; unblocked by #3 (enriched samples) which now supply the raw
  pair context.
- #8 cost gate untouched (ARBY_SIM_MIN_NET_BPS=1.0 stays).
- #9 repeat 30m strict Anvil soak: next step owned by reviewer/operator.

## 2) Commands Executed
- py -3.11 -m pytest tests/unit/test_m7_e1_34h_reviewer_fixes.py -q
  -> 7 passed in 0.65s.
- py -3.11 -m pytest tests/unit -q
  -> 4251 passed, 6 skipped, 1 warning in 124.72s.
- py -3.11 scripts/check_repo_safety.py
  -> PASS 0 warnings (expected after this report is written).

## 3) Artifacts
run_dir reference (unchanged rolling pointer):
ci_m5_gate_arbitrum_one_20260417_145636_478653.
no new runtime artifacts produced this cycle (code + tests + docs only).
canonical rolling artifacts from prior 30m E1.34g soak still in place:
- data/runs/_rolling/m7_hot_rollup_latest.json
- data/runs/_rolling/m7_hot_rollup_latest_discovery.json
- data/runs/_rolling/reviewer_soak_baseline_latest{,_discovery}.json
- data/runs/_rolling/_latest.json, run_summary_latest.json, m4_stability_agg.json

## 4) Key Results — shape-lock for new rollup keys
- rollup.supervisor_window: {first_window_at, events_total,
  elapsed_minutes, events_per_minute}; values accumulate across
  session_id changes (verified by
  test_supervisor_window_survives_session_id_change).
- rollup.bridge_hit_but_not_fast_scored.samples: bounded ring of 10
  dicts with pool_address + scoring_path + reason + actual_pair +
  token_in/out + fee_tier + venue + adapter_type + observed_at.
- rollup.sim_failed_samples_recent: filtered to current session_id
  before each append; sim_failed_samples_total still cumulative.
- rollup.shutdown_flush_at: stamped only by flush_rollup_shutdown();
  last_heartbeat_utc and last_updated match on shutdown.

## 5) Theoretical Net Profit
n/a (no new soak this cycle). M4 truth path unchanged:
profit_realism_status=ROUNDTRIP_NOT_PROFITABLE. analyze_roundtrip_profitability.py
exit=2 (NO_ROUNDTRIP_ATTEMPTED) — next 30m strict soak required.

## 6) Contract Checks
- pytest: 4251 PASS, 6 skipped, 0 failed (+7 new in
  test_m7_e1_34h_reviewer_fixes.py).
- check_repo_safety: PASS 0 warnings.

## 7) Blocker Classification
- code_blocker: LOW — all reviewer code-addressable asks landed;
  remaining gap is registry/feed-coverage operational work.
- data_collection_blocker: HIGH (unchanged) — E1.34g soak confirmed
  funnel starvation (0.467 / 0.8 events/min vs >= 5 threshold).
- market_window_blocker: HIGH — net_bps histogram is too sparse for
  cost-model conclusions; keep cost gate frozen until >= 20 fast scores
  (reviewer step #8).

## 8) Risks
- supervisor_window derives from rollup.first_window_at which is set
  by setdefault; if a reviewer deletes the rolling file mid-soak, the
  first_window_at resets and events_per_minute will under-report until
  enough time passes. This is already the reviewer runbook invariant
  (capture-baseline then soak).
- bridge_hit_not_scored_sample is first-seen per window; if multiple
  distinct (scoring_path, pair) combos hit, only the first is retained.
  Ring bounded to 10 across the session — sufficient for classification
  but not forensic.
- flush_rollup_shutdown only fires on clean loop exit; a hard kill
  (SIGKILL) still leaves the rollup stamped with the last mid-cycle ts.
  Mitigation: supervisor SIGTERM path executes the same loop-exit.
- sim_failed_samples_recent prune drops samples that were missing
  session_id (pre-E1.34e data); sim_failed_samples_total accumulator is
  preserved so no evidence is lost.

## 9) Execution Map
- step_15 — funnel diagnostics (feed-rate, bridge reason propagation,
  net_bps histogram) (M7.E1.34g): DONE.
- step_16 — reviewer 10-step batch, code-addressable subset
  (#3, #5, #6, #7) (M7.E1.34h): DONE this cycle.
- step_17 — operational: feed coverage fix on Base (#2) + bridge
  registry join (#4) + repeat 30m strict soak (#9): NEXT.
- step_18 — post-soak acceptance verdict using E1.34h
  supervisor_window.events_per_minute + enriched bridge samples.

## 10) Requests to Lead
- approve next 30m strict Base Anvil soak with E1.34h instrumentation
  visible; use the enriched bridge samples to drive registry join.
- keep ARBY_SIM_MIN_NET_BPS=1.0, ARBY_REVIEWER_QUIET_OK=0 (no cost-gate
  loosening, no silent quiet pass) until acceptance criterion holds.

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

  # Post-soak H-level inspection (no new script; standard JSON read):
  Get-Content data\runs\_rolling\m7_hot_rollup_latest.json | ConvertFrom-Json |
    Select-Object -ExpandProperty supervisor_window
  Get-Content data\runs\_rolling\m7_hot_rollup_latest.json | ConvertFrom-Json |
    Select-Object -ExpandProperty bridge_hit_but_not_fast_scored |
    Select-Object reason_histogram, samples

exit 0 = PASS, 2 = FAIL acceptance, 1 = missing artifacts.

## 12) Session Completion
goal_status: BLOCKED
primary_blocker_of_session: M7.E1.34g soak acceptance FAIL (feed starvation + HOT_SKIP_UNKNOWN_PAIR drop)
blocker_status_after: BLOCKED (code fixes landed; feed + registry work + next soak required)
docs_reread_confirmed: true
next_session_entrypoint: operational feed coverage + registry join + fresh 30m strict Base soak
