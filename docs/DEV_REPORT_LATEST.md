# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: m7a_536_session
mode: OFFLINE (code changes + unit tests + CI pipeline)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.36 — per-stage hard budget abort, p50/p90 tracking, strengthened promotion
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z

## Session Completion
session_goal: M7.A.5.36 — hot path p50 ≤ 250ms on promoted watchlist before seeking first profit_guard pass
goal_status: PARTIAL (per-stage hard budget abort implemented in score_backrun_fast, p50/p90 tracking added to hot artifact, promoted watchlist gates strengthened — pending 1h nonstop runtime for empirical verification)
close_allowed: true
remaining_blockers: (1) Need 1h nonstop runtime to measure actual p50/p90 on promoted watchlist; (2) profit_guard_passed_count still expected 0 until promoted watchlist populates from cold iterations
evidence_session_run_dirs: [tests/unit (3200 passed, 6 skipped), scripts/ci_full_pipeline.py --mode ci (ALL REQUIRED GATES PASSED), scripts/check_repo_safety.py (PASS 0 warnings)]
primary_blocker_of_session: Hot path has no per-stage abort (only total 250ms); promoted watchlist too loose (MIN_COLD_APPEARANCES=1, no net_bps gate); no p50/p90 tracking in hot artifact
blocker_status_before: ACTIVE (score_backrun_fast had total abort only; promotion rules allowed single-appearance garbage pairs; hot artifact had no percentile latency metrics)
blocker_status_after: RESOLVED (4 per-stage hard aborts added: registry≤25ms, pool_state≤50ms, local_math≤10ms, profit_guard≤40ms; PROMOTED_MIN_COLD_APPEARANCES=2; PROMOTED_MIN_NET_BPS=-50; anomaly hard exclude; p50/p90 in hot artifact; 3200 tests pass; all CI gates green)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.36 — per-stage hard budget abort + p50/p90 tracking + strengthened promotion rules
change_summary:
  - m7/shared/constants.py (MODIFIED): Added 4 zero-budget constants for excluded stages (HOT_BUDGET_RESOLVE_MS=0, HOT_BUDGET_ORACLE_MS=0, HOT_BUDGET_ENRICHMENT_MS=0, HOT_BUDGET_REGISTRY_PRELOAD_MS=0). Raised HOT_BUDGET_PROFIT_GUARD_MS from 10→40ms. Added PROMOTED_MIN_NET_BPS=-50.0. Raised PROMOTED_MIN_COLD_APPEARANCES from 1→2. Updated section headers to M7.A.5.36.
  - m7/orderflow/scoring_parallel.py (MODIFIED): Added per-stage hard budget abort after each of 4 measured stages (registry_lookup, pool_state, local_math, profit_guard). Each stage checks against its budget constant and returns None if exceeded. Updated import to bring in per-stage constants.
  - scripts/m7a_orderflow_loop.py (MODIFIED): Added p50_latency_ms and p90_latency_ms to hot artifact fast_path section. Strengthened _promote_pairs_from_cold: anomaly is now hard exclude (regardless of size_valid); added PROMOTED_MIN_NET_BPS filter; updated docstring for M7.A.5.36 rules.
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): Fixed 3 existing promotion tests for PROMOTED_MIN_COLD_APPEARANCES=2. Added 4 new test classes (14 tests): TestM7A536PerStageBudgetConstants, TestM7A536PerStageAbort, TestM7A536PromotionRules, TestM7A536P50P90Tracking.
  - docs/status/Status_M7.md (MODIFIED): Updated header for M7.A.5.36 scope, 3200 tests.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.36)
touched_files:
  - m7/shared/constants.py (MODIFIED)
  - m7/orderflow/scoring_parallel.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3200 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest OK, docs_consistency OK, status_m4_check OK, m5_0_offline OK, m4_smoke OK, m4_profit OK — ALL REQUIRED GATES PASSED)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 errors, 0 warnings)

## 3) Artifacts Attached

No new runtime artifacts — session is OFFLINE code changes only. Rolling truth unchanged: run_timestamp=2026-04-02T09:03:41.464858Z.

## 4) Key Results — M7.A.5.36

### Per-Stage Hard Budget Abort in score_backrun_fast

Previously, `score_backrun_fast()` only checked total pipeline time against `HOT_BUDGET_TOTAL_MS` (250ms). Individual stages could silently exceed their nominal budgets without early termination. Now each of the 4 measured stages has a hard abort:

| Stage | Budget (ms) | Abort behavior |
|-------|------------|----------------|
| registry_lookup | 25 | return None |
| pool_state | 50 | return None |
| local_math | 10 | return None |
| profit_guard | 40 | return None |

Total budget unchanged at 250ms. The fast path still has zero RPC calls — these budgets enforce computational time only.

### Zero-Budget Constants for Excluded Stages

Added explicit zero-budget constants documenting that resolve, oracle, enrichment, and registry_preload are NEVER part of the hot path:
- `HOT_BUDGET_RESOLVE_MS = 0`
- `HOT_BUDGET_ORACLE_MS = 0`
- `HOT_BUDGET_ENRICHMENT_MS = 0`
- `HOT_BUDGET_REGISTRY_PRELOAD_MS = 0`

These are documentation constants — they enforce the architectural contract that the hot fast path does zero RPC.

### p50/p90 Latency Tracking in Hot Artifact

The hot artifact's `fast_path` section now includes `p50_latency_ms` and `p90_latency_ms` computed from sorted fast-path latencies. This provides the key observability needed to verify the 250ms budget target.

### Strengthened Promoted Watchlist Rules (M7.A.5.36)

| Rule | Before (M7.A.5.35) | After (M7.A.5.36) |
|------|--------|--------|
| Min cold appearances | 1 | 2 |
| Anomaly handling | Excluded only if `has_anomaly AND NOT size_valid` | Hard exclude always |
| Min net_bps | None | -50.0 (PROMOTED_MIN_NET_BPS) |
| Size valid required | Yes | Yes |
| Active pools required | Yes | Yes |

## 5) Strategic Reading

1. **Hot fast path architecture is correct**: `score_backrun_fast()` has zero RPC calls. Expected latency is ~20-50ms. The cold pipeline numbers (resolve=791ms, oracle=105ms) are irrelevant to the hot path.
2. **Per-stage enforcement now catches runaway stages**: Any individual stage exceeding its budget aborts immediately instead of accumulating toward the 250ms total. This prevents a slow registry lookup from wasting time on subsequent stages.
3. **Promotion rules are tighter**: Requiring 2 cold appearances prevents noisy single-observation promotions. The net_bps floor (-50) rejects garbage pairs that would waste hot-lane resources. Anomaly hard-exclude prevents PRICING_ANOMALY pairs from polluting the hot watchlist.
4. **p50/p90 tracking enables empirical verification**: Once a 1h nonstop runtime produces events matching the promoted watchlist, the p50/p90 values will confirm whether the 250ms target is achievable.
5. **Next step**: Run 1h nonstop runtime to get fresh hot artifact with p50/p90 measurements. The architectural hypothesis is that hot p50 will be well under 250ms (~20-50ms).

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files in _rolling)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (scoring_parallel.py ≤ 1300 lines)
test file size constraint: OK (test_orderflow_artifacts.py — approaching limit)
Status_M7.md size constraint: OK

## 5.2) Blockers / Risks
- PRIMARY: Need 1h nonstop runtime for empirical p50/p90 measurement — pending operator execution
- PRIMARY: profit_guard_passed_count likely still 0 until promoted watchlist populates from 2+ cold iterations
- SECONDARY: test_orderflow_artifacts.py approaching size limit — may need split
- RESOLVED (this session): No per-stage hard abort in score_backrun_fast (4 stage aborts added)
- RESOLVED (this session): Promoted watchlist too loose — single-appearance, no net_bps gate (PROMOTED_MIN_COLD_APPEARANCES=2, PROMOTED_MIN_NET_BPS=-50)
- RESOLVED (this session): PRICING_ANOMALY pairs could slip through promotion if size_valid=True (anomaly now hard exclude)
- RESOLVED (this session): No p50/p90 latency tracking in hot artifact (p50_latency_ms, p90_latency_ms added)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) 1h nonstop runtime to measure p50/p90, (b) First profit_guard_passed > 0, (c) Expand seed watchlist if promotion insufficient
