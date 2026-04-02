# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: m7a_534_session
mode: ONLINE (code changes + unit tests + CI pipeline + online hot/cold runs)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.34 — hot-lane no-fallback, PRICING_ANOMALY exclusion, execution-readiness timing
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z

## Session Completion
session_goal: M7.A.5.34 — first profit_guard-passed hot candidate on a tiny prewarmed watchlist under 250ms budget
goal_status: BLOCKED (hot lane architecture correct — events not in watchlist correctly skipped via hot_skip ~0ms — but no events matched HOT_WATCHLIST_PAIRS during 30-iteration online run, so profit_guard_passed_count remains 0)
close_allowed: true
remaining_blockers: (1) HOT_WATCHLIST_PAIRS (3 pairs) did not match any mempool events during 30-iteration hot run — need either longer run window or expanded watchlist; (2) Cold lane resolve_ms=643ms dominates latency — needs caching or parallel resolve
evidence_session_run_dirs: [tests/unit (3179 passed, 6 skipped), scripts/ci_full_pipeline.py --mode ci (ALL REQUIRED GATES PASSED), scripts/check_repo_safety.py (PASS 0 warnings), online hot 30 iterations, online cold 3 iterations, dashboard /api/hot + /api/rolling verified]
primary_blocker_of_session: (1) Hot lane fell back to ~1330ms parallel pipeline for non-watchlist events; (2) PRICING_ANOMALY contaminated hot candidates; (3) No execution-readiness timing breakdown; (4) DEV_REPORT blocker-tag count drift (8 vs 9)
blocker_status_before: ACTIVE (hot lane fell back to slow parallel pipeline; PRICING_ANOMALY not excluded; only 5 stage timing keys; blocker-tag count wrong)
blocker_status_after: RESOLVED (hot lane creates hot_skip ~0ms for non-registry events; PRICING_ANOMALY hard-excluded; 7 stage timing keys; blocker-tag count fixed to 9; 3179/3179 tests pass; online hot/cold runs completed)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.34 — hot-lane no-fallback + PRICING_ANOMALY exclusion + execution-readiness timing
change_summary:
  - m7/orderflow/mode_ws_live.py (MODIFIED): Hot mode no longer falls back to score_backrun_live_parallel(); creates lightweight BackrunResult(scoring_path="hot_skip", reject_reason="REJECT_NOT_IN_HOT_REGISTRY") for non-registry events (~0ms vs ~1330ms); cold lane moved to else branch; added artifact["_raw_results"] for downstream BackrunResult access
  - m7/orderflow/scoring_parallel.py (MODIFIED): Added PRICING_ANOMALY hard-exclude (abs(net_bps) > 10000 → REJECT_PRICING_ANOMALY, route_viable=False); profit guard gated by route_viable; Stage 5 split into 3 sub-stages: tx_build_ms, calldata_ms, sign_or_bundle_prep_ms (7 total timing keys)
  - scripts/m7a_orderflow_loop.py (MODIFIED): PRICING_ANOMALY exclusion in profit guard + hot headline selection; removed redundant second fast-path re-scoring (now extracts from _raw_results); updated stage_keys to 7
  - m7/shared/constants.py (MODIFIED): Added HOT_BUDGET_CALLDATA_MS=20, HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS=30
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): Added 7 tests in 4 classes for hot_skip, PRICING_ANOMALY exclusion, 7 timing keys, raw_results pipeline
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.34 section, updated header (3179 tests, 9 blocker tags)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.34)
touched_files:
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - m7/orderflow/scoring_parallel.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/shared/constants.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3179 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest OK, docs_consistency OK, status_m4_check OK, m5_0_offline OK, m4_smoke OK, m4_profit OK — ALL REQUIRED GATES PASSED)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 errors, 0 warnings)
python scripts/m7a_orderflow_loop.py --lane hot --iterations 30 --pause 1: COMPLETED (30 iterations, events_count=2, viable=0, profit_guard_passed=0)
python scripts/m7a_orderflow_loop.py --lane cold --iterations 3 --pause 5: COMPLETED (3 iterations, events=22, scored=21, viable=0, best_clean=46.20bps, positive_clean=2)
python scripts/m7a_orderflow_loop.py --dashboard --port 8099: RUNNING (/api/hot + /api/rolling verified)

## 3) Artifacts Attached

Online hot artifact (final iteration 30): events_count=2, viable_count=0, profit_guard_passed_count=0, has_positive=false — events correctly skipped via hot_skip (not in registry)
Online cold artifact (final iteration 3): events=22, scored=21, viable=0, best_clean_net_bps=46.20, positive_clean=2, stale_positive=2, latency_mean=1381ms
Cold latency breakdown: resolve_ms_mean=643, registry_preload_ms_mean=484, oracle_ms_mean=111, total_mean=1331
Rolling truth unchanged: run_timestamp=2026-04-02T09:03:41.464858Z

## 4) Key Results — M7.A.5.34

### Architectural Change: Hot Lane No Parallel Fallback

Hot mode in mode_ws_live.py no longer calls score_backrun_live_parallel() when score_backrun_fast() returns None. Instead creates a lightweight BackrunResult with scoring_path="hot_skip" and reject_reason="REJECT_NOT_IN_HOT_REGISTRY" (~0ms). Cold lane handles full pipeline in separate else branch. This eliminates the ~1330ms parallel fallback that defeated hot lane purpose.

### PRICING_ANOMALY Hard-Exclude

score_backrun_fast() now checks abs(net_bps) > 10000 → sets REJECT_PRICING_ANOMALY, route_viable=False. Profit guard only runs if route_viable=True. Downstream: m7a_orderflow_loop skips PRICING_ANOMALY results in profit guard evaluation and hot headline selection.

### Execution-Readiness Timing (7 Stage Keys)

Stage 5 split into 3 sub-stages: tx_build_ms, calldata_ms, sign_or_bundle_prep_ms. Total pipeline_stage_latency_ms now has 7 keys (was 5). New budget constants: HOT_BUDGET_CALLDATA_MS=20, HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS=30.

### Redundant Re-Scoring Removed

m7a_orderflow_loop.py no longer calls score_backrun_fast() a second time for hot artifact writing. Instead extracts fast-path results from artifact["_raw_results"] by filtering scoring_path=="registry_fast".

### Online Evidence

Hot 30 iterations: events not in HOT_WATCHLIST_PAIRS correctly skipped via hot_skip (~0ms per event). No watchlist-matching events observed during window — profit_guard_passed remains 0.

Cold 3 iterations: 21/21 scored via registry_direct. Latency dominated by resolve_ms (643ms, 48%) and registry_preload (484ms, 36%). Best candidate 46.20 bps net but viable=0 (gas/slippage exceeds spread).

## 5) Strategic Reading

1. **Hot/cold lane separation is now clean**: hot lane never touches parallel pipeline; latency for non-registry events is ~0ms (hot_skip). First genuine hot-path measurement requires watchlist-matching mempool events.
2. **Cold lane bottleneck identified**: resolve_ms (643ms) + registry_preload (484ms) = 84% of 1331ms total. These are the targets for M7.A.5.35 optimization.
3. **PRICING_ANOMALY exclusion protects metrics**: anomalous spreads (>100x expected) can no longer contaminate profit guard counts or hot headlines.
4. **Execution-readiness timing framework ready**: 7-stage decomposition enables budget monitoring for tx_build + calldata + sign_or_bundle_prep as these move from placeholder to implementation.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files in _rolling)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (scoring_parallel.py ≤ 1300 lines)
test file size constraint: OK (test_orderflow_artifacts.py — approaching limit)
Status_M7.md size constraint: OK (241 lines ≤ 300)

## 5.2) Blockers / Risks
- PRIMARY: HOT_WATCHLIST_PAIRS (3 pairs) did not match any mempool events during 30-iteration hot run — need longer window or expanded watchlist to prove first profit_guard pass
- PRIMARY: Cold lane resolve_ms=643ms (48% of total) — needs caching/parallel resolve for latency target
- SECONDARY: test_orderflow_artifacts.py approaching size limit — may need split
- RESOLVED (this session): Hot lane parallel fallback removed (~1330ms → ~0ms for non-registry events)
- RESOLVED (this session): PRICING_ANOMALY contamination (hard-excluded from fast path + profit guard + headlines)
- RESOLVED (this session): Only 5 stage timing keys (now 7 with calldata_ms + sign_or_bundle_prep_ms)
- RESOLVED (this session): Redundant second score_backrun_fast() call removed (extracts from _raw_results)
- RESOLVED (this session): DEV_REPORT blocker-tag count drift (8→9 corrected)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Longer hot run or expand watchlist to catch matching events, (b) Cache/parallel resolve_ms to reduce cold lane latency, (c) First profit_guard_passed_count > 0 is M7.A.5.35 target
