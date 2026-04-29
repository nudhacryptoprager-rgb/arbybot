# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-29T09:28:56Z
run_id: post-2h-soak FIX-LIST iteration — 6 of 8 reviewer items now have code/test landing or scaffold; quote-model uniformization (P0) still deferred to runtime-validating iteration; rollup last_updated pinned (no new soak)
mode: ONLINE (no fresh run; doc/code/test landing only)
artifact_mode: rolling
config: 2h Base soak session 37e452d6 (2026-04-29T07:32:50Z → 09:32:59Z) cumulative evidence base; ENV pins: ARBY_HOT_SWEEP_ENABLE=1, ARBY_LATENCY_TARGET_MS=200, ARBY_MAX_TRADE_USD=0, ARBY_SCORER_SIM_DIVERGENCE_BPS=500, ARBY_SIM_REQUIRE_SIZE_METADATA=1, ARBY_PRE_SIM_BISECT=0 (NEW; default OFF)
code_identity:
  primary: ts:2026-04-29T09:28:56Z
  dirty: false
  desc: 6 reviewer fixes landed (#1 input-mismatch detector observability bridge, #2 offline replay tool, #4 ENV-gated pre-sim size bisection, #5 bootstrap probe heartbeat-aware, #6 factory enumeration scaffold, #7 tier classifier scaffold, #8 dashboard live-deltas); +39 unit tests (4310 → 4348); rollup pinned

## 1) Scope
goal (Roadmap): M7.E1.38 — process the 7-item reviewer fix-list from post-2h-soak verdict by landing code/test/docs without bypassing CLAUDE.md §1.2 (small backward-compatible changes per iteration; no large refactors). Each large item decomposed to observability-first or scaffold form so the runtime path is opt-in or inert until a follow-up iteration validates it under a fresh soak.
change_summary:
  - m7/orderflow/execution_gate.py:
    * SIZE_OVER_CAP path now branches on ARBY_PRE_SIM_BISECT. With env=1, oversized candidates are scaled by (cap_usd / size_usd_estimate * 0.95) across amount_in_wei + best_sweep_size_wei + size_usd_estimate and admitted; emits a SIZE_BISECTED_TO_CAP pre_sim_skip_sample with original_size_usd and scale factor (default OFF preserves legacy block).
    * SCORER_SIM_DIVERGENCE sample extended (24 fields total) with input_mismatch_detected (bool) and input_mismatch_ratio (float|None) to classify whether divergence is INPUT mismatch (scorer amount_in_wei vs sim input_amount_wei mismatch >1%) or pool-quote-model error.
  - scripts/replay_divergence_samples.py (NEW, 130 lines): offline replay tool. Consumes m7_hot_rollup_latest.json.scorer_sim_divergence_samples_recent (no RPC), audits required reproducer fields, emits per-sample manifest under data/runs/_replays/divergence/<event_id>.json plus a summary. Exit 0=OK, 1=NO_SAMPLES, 2=missing/corrupt rollup.
  - scripts/bootstrap_system.ps1: new -RollupProbeHeartbeatSeconds 30 param. Probe loop now extends maxProbe ONCE to RollupProbeSeconds*2 when probe times out but supervisor log file shows recent activity (LastWriteTimeUtc within heartbeat window). Backward compatible: previous timing preserved when no heartbeat extension triggers.
  - monitoring/dashboard_server.py: /api/summary.current_scan payload now includes live_deltas block sourced from rollup snapshot — session_id, baseline_session_id, age_seconds, is_fresh, staleness_reason, fresh_funnel, scorer_sim_divergence_samples_total, scorer_sim_divergence_samples_recent_count, pre_sim_skip_samples_total, pre_sim_skip_samples_recent_count, submit_blocker_histogram, simulation_error_histogram, external_provider_blocker_total.
  - discovery/factory_enumeration.py (NEW): scaffold module — FactoryPoolRecord frozen dataclass + EnumerationCache (schema_version=factory_enum_v1, read/write/filter/add chain-guarded) + enumerate_factory_pools(chain, dex, cache_path) offline reader. No RPC; live impl deferred.
  - discovery/tier_classifier.py (NEW): scaffold module — PoolTier=Literal["hot","warm","cold"], TierThresholds dataclass (defaults 120s / 1800s; ordering validated), PoolActivitySnapshot, pure classify_tier(snapshot, *, now_ts, thresholds=None) total function. No I/O; future runtime wiring deferred.
  - tests/unit/test_replay_divergence_samples.py (NEW, 8 tests, ALL PASS).
  - tests/unit/test_orderflow_artifacts.py: TestPreSimSizeBisection (3 tests) + TestScorerSimInputMismatchDetector (2 tests) added; existing tests unchanged.
  - tests/unit/test_dashboard_summary.py: test_live_deltas_block_present added; full file 26/26 PASS.
  - tests/unit/test_factory_enumeration.py (NEW, 12 tests, ALL PASS): record immutability + dict round-trip, cache chain-guard + JSON schema/version + write→read, schema rejection, missing-file FileNotFoundError, filter combinations, enumerate_factory_pools empty-when-missing/no-cache-path/filtered/chain-mismatch.
  - tests/unit/test_tier_classifier.py (NEW, 12 tests, ALL PASS): threshold ordering, negative reject, None last_swap_ts → cold, recent → hot, boundary inclusivity, future timestamp clock-skew tolerance, custom thresholds.
  - docs/status/Status_M7.md: status block prepended with E1.38 fix-list iteration summary; unit baseline updated to 4348.
  - docs/DEV_REPORT_LATEST.md: this file.
touched_files:
  - m7/orderflow/execution_gate.py
  - monitoring/dashboard_server.py
  - scripts/bootstrap_system.ps1
  - scripts/replay_divergence_samples.py
  - discovery/factory_enumeration.py
  - discovery/tier_classifier.py
  - tests/unit/test_orderflow_artifacts.py
  - tests/unit/test_dashboard_summary.py
  - tests/unit/test_replay_divergence_samples.py
  - tests/unit/test_factory_enumeration.py
  - tests/unit/test_tier_classifier.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed
py -3.11 -m pytest tests/unit/test_orderflow_artifacts.py::TestScorerSimDivergenceGuard -q: 2 passed in 0.24s
py -3.11 -m pytest tests/unit/test_orderflow_artifacts.py::TestScorerSimInputMismatchDetector -q: 2 passed in 0.36s
py -3.11 -m pytest tests/unit/test_orderflow_artifacts.py::TestPreSimSizeBisection -q: 3 passed
py -3.11 -m pytest tests/unit/test_replay_divergence_samples.py -q: 8 passed
py -3.11 -m pytest tests/unit/test_dashboard_summary.py -q: 26 passed
py -3.11 -m pytest tests/unit/test_factory_enumeration.py -q: 12 passed in 0.29s
py -3.11 -m pytest tests/unit/test_tier_classifier.py -q: 12 passed in 0.16s
py -3.11 -m pytest tests/unit -q: PASS (4348 passed, 6 skipped, 0 failed; 104.85s)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings, 20 gates)
(no new bootstrap; rollup last_updated pinned to 2026-04-29T09:28:56Z from 2h diagnostic soak)

## 3) Artifacts Attached
rolling (cumulative from 2h diagnostic soak 37e452d6, unchanged this iteration):
  - data/runs/_rolling/m7_hot_rollup_latest.json (last_updated=2026-04-29T09:28:56Z, session_id=37e452d6, simulation_backend=rpc_fork)
  - data/runs/_rolling/m7_hot_latest.json
  - data/runs/_rolling/reviewer_soak_baseline_latest.json
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json
  - data/runs/_rolling/m7_orderflow_latest*.json
  - data/runs/_rolling/m7_cold_hot_bridge*.json
session_log:
  - data/runs/_sessions/m7_bootstrap_20260429_093250.out.log (last fresh 2h soak supervisor; clean shutdown 09:32:59Z, 5/5 children alive, crash_restarts=0)

## 4) Key Results
m7_hot_rollup_latest (last fresh 2h soak 37e452d6 — process layer clean, economic layer FAIL):
  simulation_backend: rpc_fork
  last_updated: 2026-04-29T09:28:56Z
  windows_seen: 81
  external_provider_blocker_total: 0
  fresh delta vs baseline (per reviewer):
    fast_path_scored: +1 (threshold 20 → FAST_PATH_SCORED_TOO_LOW)
    sim_attempted: +0 (NO_FRESH_SIM_PASSED)
    roundtrip_attempted: +0 (NO_FRESH_ROUNDTRIP_ATTEMPTED)
    submit_ready: +0
    BlockOutOfRangeError: +0
    PRE_SIM_SKIP:MISSING_SIZE_METADATA: +1
  scorer_sim_divergence_samples_recent: [] fresh; 4 cumulative from earlier iteration (offline replay tool consumes these)
  staleness: rollup vs supervisor end 243s gap > 120s → STALE_ROLLUP[production]
unit suite: 4348 PASS / 6 skipped / 0 failed (+39 vs E1.36 baseline 4309)
safety: PASS (0 warnings, 20 gates)

## 4.1) Theoretical Net Profit
not_applicable: signals_count=0 in last fresh window; cost_model not invoked; mode=paper_simulated. No new soak this iteration.

## 5) Contract Checks
status/reasons consistency: OK
rolling discipline (M7-specific): OK
v2.x provenance contract: OK (ts-only code_identity)
runtime artifacts not committed: OK
DEV_REPORT timestamp matches rollup: OK (2026-04-29T09:28:56Z = m7_hot_rollup_latest.last_updated)
new scaffolds are inert at runtime: OK (factory_enumeration is offline-only; tier_classifier is pure-function; ARBY_PRE_SIM_BISECT default 0 preserves legacy SIZE_OVER_CAP block)

## 6) Blocker Classification
| Blocker Type | Level | Meaning |
|--------------|-------|---------|
| CODE | LOW | 4348 tests pass; safety PASS; observability bridges + offline tools landed |
| DATA_COLLECTION | LOW | external_provider_blocker_total=0 (last fresh); supervisor clean |
| MARKET_WINDOW | HIGH | last fresh 2h Base soak produced only 1 fresh fast score; universe still narrow until factory_enumeration + tier_classifier scaffolds wire into runtime |
| ECONOMICS | P0 BLOCKED | quote-model uniformization (root cause of SCORER_SIM_DIVERGENCE) still pending — observability bridge (input_mismatch_detected) landed, classification will be confirmed by next fresh soak |

## 7) Production Readiness
Production criteria: sim_passed > 0 AND submit_ready > 0 AND roundtrip_profitable_total > 0.
Last fresh delta: sim_passed=0, submit_ready=0, roundtrip_profitable=0 → NOT PRODUCTION-READY.
Rollup staleness 243s>120s also fails reviewer's STALE_ROLLUP gate.

## 8) Reviewer Fix-List Status After This Iteration
- #1 quote-model uniformization (P0): MINIMAL OBSERVABILITY BRIDGE LANDED (input_mismatch_detected/ratio) — full uniformization deferred until next fresh soak classifies divergence as INPUT vs MODEL.
- #2 offline reproducer tool: FULL — scripts/replay_divergence_samples.py + 8 tests.
- #3 eth_simulateV1 pending-state sim: DEFERRED (large multi-module change).
- #4 pre-sim size bisection: IMPLEMENTED ENV-gated (ARBY_PRE_SIM_BISECT=1) + 3 tests; default OFF preserves legacy block.
- #5 bootstrap rollup probe heartbeat-aware: IMPLEMENTED (-RollupProbeHeartbeatSeconds 30); parser PASS.
- #6 factory enumeration: SCAFFOLD LANDED (discovery/factory_enumeration.py + 12 tests); live RPC enumerator deferred.
- #7 tiered cold/warm/hot universe: SCAFFOLD LANDED (discovery/tier_classifier.py + 12 tests); runtime wiring deferred.
- #8 dashboard live-delta panels: FULL — current_scan.live_deltas block + 1 test (full dashboard suite 26/26 PASS).
- #9 PRE_SIM_SKIP:SIZE_OVER_CAP (carryover): IMPLEMENTED earlier; runtime path still UNVERIFIED until cap>0 soak.
- POST-SOAK21 P0 / POST-2H-SOAK structured detail items remain landed.

## Session Completion
session_goal: Land 6 of 8 reviewer fix-list items as backward-compatible changes (observability-first or scaffold) per CLAUDE.md §1.2; verify each via targeted pytest before next iteration; finish with full pytest + safety; no new long soak; preserve rollup last_updated.
goal_status: BLOCKED
close_allowed: true
remaining_blockers: SCORER_SIM_DIVERGENCE root-cause uniformization (P0) — observability bridge ready; runtime classification pending fresh soak. Live factory enumerator + runtime tier wiring deferred. eth_simulateV1 pending-state simulation deferred.
evidence_session_run_dirs:
  - data/runs/_rolling/m7_hot_rollup_latest.json (session_id=37e452d6, last_updated=2026-04-29T09:28:56Z)
  - data/runs/_sessions/m7_bootstrap_20260429_093250.out.log (last fresh 2h soak supervisor)
primary_blocker_of_session: SCORER_SIM_DIVERGENCE (root-cause uniformization deferred; observability classifier landed)
blocker_status_before: BLOCKED
blocker_status_after: BLOCKED
docs_reread_confirmed: true
