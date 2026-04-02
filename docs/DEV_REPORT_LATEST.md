# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: ONLINE (M5 gate + M7 ws-live evidence runs + unit tests)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.26 — fix coverage UnboundLocalError in zero-active-pools fast reject; fresh April 2 verification runs; +1 regression test
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z

## Session Completion
session_goal: M7.A.5.26 — fix ws-live coverage unbound bug; refresh online evidence and docs against fresh April 2 rolling artifacts; verify M7 detection+scoring state with fresh runs
goal_status: REACHED (coverage bug fixed with test; DEV_REPORT and Status_M7 updated to fresh rolling; M5 gate PASS; 3 fresh M7 ws-live runs confirm same-block detection + registry_direct + local_pricing; viable_count still 0)
close_allowed: true
remaining_blockers: viable_count=0 (all positives STALE_POSITIVE — detected same-block, stale by scoring completion); scoring pipeline latency ~1.5-1.7s exceeds block_time_ms (250ms); best_net_bps_executable=null; M4 ROUNDTRIP_NOT_PROFITABLE (best=-28.77 bps)
evidence_session_run_dirs: [data/runs/ci_m5_gate_arbitrum_one_20260402_110313_968343, data/tmp/m7a_525_300b_fresh_20260402.json, data/tmp/m7a_525_300b_b_fresh_20260402.json, data/tmp/m7a_525_1000b_fresh_20260402.json]
primary_blocker_of_session: (1) coverage UnboundLocalError in scoring_parallel.py zero-active-pools fast reject path; (2) DEV_REPORT stale against fresh rolling artifacts after user ran online M5 gate
blocker_status_before: ACTIVE (bug surfaced during 1000b long scan; docs stale since M7.T1 structural session)
blocker_status_after: RESOLVED (bug fixed with cov=None; +1 regression test; docs refreshed to rolling run_timestamp 2026-04-02T09:03:41Z)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.26 — coverage bug fix + fresh evidence refresh + docs governance restore
change_summary:
  - m7/orderflow/scoring_parallel.py (MODIFIED): Fixed UnboundLocalError — `cov=coverage` → `cov=None` in zero-active-pools fast reject (line ~463). Coverage scan has not run at that point; variable was unbound.
  - tests/unit/test_orderflow_scoring_latency.py (MODIFIED): +1 test (test_zero_active_pools_reject_has_no_coverage) locking the fix.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.26 fresh verification summary.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten to fresh rolling provenance).
touched_files:
  - m7/orderflow/scoring_parallel.py (MODIFIED: coverage bug fix)
  - tests/unit/test_orderflow_scoring_latency.py (MODIFIED: +1 regression test)
  - docs/status/Status_M7.md (MODIFIED: +M7.A.5.26 section)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3105 passed, 6 skipped, 54.79s)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest + docs_consistency + status_m4_check + m5_0_offline + m4_smoke + m4_profit: ALL REQUIRED GATES PASSED, 58.0s)
user-run: py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: PASS (run_dir: ci_m5_gate_arbitrum_one_20260402_110313_968343)
user-run: py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 (x2) + --ws-blocks 1000 (x1): 3 fresh evidence runs

## 3) Artifacts Attached

rolling (refreshed by user's M5 online run):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-04-02T09:03:41.464858Z)
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_arbitrum_one_20260402_110313_968343/reports/daily_report_2026-04-02.json
  - data/runs/ci_m5_gate_arbitrum_one_20260402_110313_968343/reports/gate_result.json
M7 live evidence (user-run):
  - data/tmp/m7a_525_300b_fresh_20260402.json (300-block ws-live, 30 events, best_net=+47322.92 bps [PRICING_ANOMALY outlier])
  - data/tmp/m7a_525_300b_b_fresh_20260402.json (300-block ws-live)
  - data/tmp/m7a_525_1000b_fresh_20260402.json (1000-block ws-live, 81 events, best_net=+408.52 bps, PRICING_ANOMALY:1)

## 4) Key Results — M7.A.5.26

### Bug Fix: coverage UnboundLocalError in Zero-Active-Pools Path

In `m7/orderflow/scoring_parallel.py`, the M7.A.5.24 fast-reject path for low-lag events with `_registry_pools_active == 0` passed `cov=coverage` to `_reject()`, but `coverage` is only assigned inside the `_registry_pools_active > 0` branch (registry_direct fast path) or later in the coverage scan fallback. When an event hit zero active pools, Python raised `UnboundLocalError: cannot access local variable 'coverage'`.

**Fix**: `cov=coverage` → `cov=None`. No coverage scan has been performed when registry reports zero active pools, so `None` is the correct value. Regression test added in `TestLowLagZeroActivePoolsReject`.

### Fresh M7 Evidence (April 2, User-Run)

| Metric | 300b_fresh | 1000b_fresh |
|--------|-----------|-------------|
| events_count | 30 | 81 |
| viable_count | 0 | 0 |
| events_detected_low_lag | 30 (100%) | 81 (100%) |
| positive_net_count | 4 | 8 |
| best_net_bps | +47322.92 (ANOMALY) | +408.52 |
| PRICING_ANOMALY | 1 | 1 |
| GAS_EXCEEDS_GROSS | 25 | 72 |
| STALE_POSITIVE | 3 | 8 |
| active_coverage_rate | 0.97 | 1.0 |
| scored_results_rate | 0.97 | 1.0 |
| valid_size_rate | 0.30 | 0.17 |

**Observations**:
1. **Same-block detection confirmed**: 100% of events detected at event block (events_detected_low_lag = events_count in all runs).
2. **registry_direct + local_pricing dominant**: active_coverage_rate near 1.0; discovery is solved.
3. **PRICING_ANOMALY gate catches 1/30 and 1/81** but the 300b outlier (+47322 bps) slipped through — suggests the `abs(net_bps) > 10000` threshold may need tightening, or there is a second anomaly path not covered by the current gate.
4. **valid_size_rate low** (17-30%): many results have `size_valid_for_token=false`, meaning their net_bps is unreliable as profit evidence.
5. **best_net_bps_executable = null**: no clean executable positive exists in any fresh run.

### Fresh M4 Online Evidence (April 2, User-Run)

| Metric | Value |
|--------|-------|
| M5 gate status | PASS |
| profit_realism_status | ROUNDTRIP_NOT_PROFITABLE |
| best_net_pnl_bps | -28.77 |
| signals_count | 31 |
| m4_sim_net_usdc | 40.10 |
| signal_win_rate | 0.1613 |
| quotes_fetched | 71 |
| cross_dex_pairs_count | 115 |

M4 roundtrip economics remain negative on real quotes. Paper sim shows +40 USDC but that is pre-cost modeled, not executable.

### Subgraph Seed Bug (Observed)

Fresh artifacts show subgraph seed errors: `uniswap_v3: name 'json' is not defined`, `sushiswap_v3: name 'json' is not defined`. This is a missing import in the subgraph seed path. Non-blocking (subgraph seed is optional) but should be fixed.

## 5) Strategic Reading

1. **Coverage bug was a real correctness blocker**: Long ws-live runs (1000b+) would crash on any event with zero active registry pools. Now fixed and tested.
2. **M7 detection is solved, scoring completion is the bottleneck**: 100% same-block detection, near-100% registry_direct coverage, but scoring still completes ~1.5-1.7s after detection. All positives are STALE_POSITIVE.
3. **No executable profit exists**: best_net_bps_executable is null in all fresh runs. Modeled positives (+408 bps in clean cases) are not executable at current pipeline latency.
4. **PRICING_ANOMALY gate has a gap**: one outlier (+47322 bps) was not caught. The anomaly gate threshold (10000 bps) may need refinement, or there is a secondary anomaly path (e.g., `size_valid_for_token=false` events producing extreme net_bps below 10000 threshold).
5. **M4 roundtrip is still negative**: best_net_pnl_bps=-28.77 on fresh real quotes. Paper sim positive (+40 USDC) is modeled, not real.
6. **Next justified work is execution-lane hardening**, not more discovery: fix subgraph import bug, tighten anomaly gate, isolate low-lag fast path, reduce scoring time toward block_time_ms. External references (Flashbots simple-blind-arbitrage, Arbitrum Timeboost) suggest the practical path is local/onchain decision with ordering advantage.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 66 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (all m7/ modules ≤ 1100 lines)
test file size constraint: OK (all M7 test files ≤ 600 lines)
Status_M7.md size constraint: OK (≤300 lines)

## 5.2) Blockers / Risks
- PRIMARY: Scoring pipeline latency (~1.5-1.7s) exceeds block_time_ms (250ms); viable_count=0; all positives STALE_POSITIVE; best_net_bps_executable=null
- SECONDARY: PRICING_ANOMALY gate has gap (47322 bps outlier not caught); valid_size_rate low (17-30%); subgraph seed has missing `json` import
- RESOLVED (this session): coverage UnboundLocalError in zero-active-pools fast reject
- RESOLVED (this session): DEV_REPORT stale against fresh rolling artifacts
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE (best=-28.77 bps); SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Tighten anomaly gate or add size_valid filter before counting positives, (b) Fix subgraph json import, (c) Isolate executable lane for low-lag events, (d) Reduce scoring path to minimum (registry hit → local state → single-size score → decision), (e) Investigate Timeboost ordering advantage for tiny prewarmed watchlist
