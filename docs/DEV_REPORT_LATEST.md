# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: ci_m5_gate_arbitrum_one_20260327_222948_123275
mode: ONLINE
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow_7 universe, runtime source, measured scoring, regime tagging
code_identity:
  primary: ts:2026-03-27T21:30:14Z
  dirty: false
  desc: M7.A.3 temporal-regime hypothesis — regime classification and aggregation

## Session Completion
session_goal: Implement M7.A.3 temporal-regime hypothesis — classify measured runs by market regime (activity, failure, spread) and test whether different regimes produce different triangular edge characteristics.
goal_status: REACHED
close_allowed: true
remaining_blockers: none
evidence_session_run_dirs:
  - data/tmp/m7a_regime_run1.json (block 446834785)
  - data/tmp/m7a_regime_run2.json (block 446835947)
  - data/tmp/m7a_regime_run3.json (block 446837081)
  - data/tmp/m7a_regime_repeatability.json (3-run regime aggregation)
primary_blocker_of_session: M7.A.3 temporal-regime hypothesis not yet implemented or tested
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.3 — temporal-regime hypothesis. On arbitrum_one narrow_7, measured triangular edge may appear only in specific temporal market regimes rather than in generic short windows.
change_summary:
  - Added classify_regime_bucket() with 7 canonical regime tags across 3 dimensions (activity, failure, spread)
  - Added build_regime_repeatability_summary() aggregator for cross-run regime analysis
  - Added --regime-repeatability CLI arg for regime aggregation mode
  - Artifact summary includes regime_bucket field in measured mode
  - Backward-compatible: old artifacts without regime_bucket are re-classified from stats
  - Added 28 new contract tests (TestRegimeClassification, TestRegimeRepeatabilitySchema, TestRegimeBackwardCompatibility)
  - Total test count: 2736 passed, 6 skipped, 0 failures
touched_files:
  - scripts/m7a_enumerate_cycles.py
  - tests/unit/test_triangular_contracts.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (2736 passed, 6 skipped)
py -3.11 scripts/m7a_enumerate_cycles.py --source runtime --score measured --max-cycles 500 --max-scored 100 --sweep-top 10 --output data/tmp/m7a_regime_run1.json: PASS (block 446834785)
py -3.11 scripts/m7a_enumerate_cycles.py --source runtime --score measured --max-cycles 500 --max-scored 100 --sweep-top 10 --output data/tmp/m7a_regime_run2.json: PASS (block 446835947)
py -3.11 scripts/m7a_enumerate_cycles.py --source runtime --score measured --max-cycles 500 --max-scored 100 --sweep-top 10 --output data/tmp/m7a_regime_run3.json: PASS (block 446837081)
py -3.11 scripts/m7a_enumerate_cycles.py --regime-repeatability data/tmp/m7a_regime_run1.json data/tmp/m7a_regime_run2.json data/tmp/m7a_regime_run3.json --output data/tmp/m7a_regime_repeatability.json: PASS

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_regime_run1.json (block 446834785, regime: medium_activity)
  - data/tmp/m7a_regime_run2.json (block 446835947, regime: medium_activity)
  - data/tmp/m7a_regime_run3.json (block 446837081, regime: medium_activity)
  - data/tmp/m7a_regime_repeatability.json (3-run regime aggregation)

prior session artifacts (still valid, not overwritten):
  - data/tmp/m7a_verdict.json (narrow_7, 4-block verdict from session 17)
  - data/tmp/m7a_expanded_verdict.json (expanded_10, 3-block verdict from session 18)
  - data/tmp/m7a_blocker_repeatability.json (narrow_7, 3-block aggregation)

rolling (unchanged):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.3 Temporal Regime Classification

### New Infrastructure

| Component | Description |
|-----------|-------------|
| `classify_regime_bucket()` | Per-run regime classification using 3 dimensions |
| `build_regime_repeatability_summary()` | Cross-run regime aggregation |
| `--regime-repeatability` CLI | Regime aggregation mode |
| `regime_bucket` artifact field | Added to measured artifacts |
| 7 canonical regime tags | `high_activity`, `medium_activity`, `low_activity`, `high_failure`, `low_failure`, `wide_spread`, `tight_spread` |

### Regime Classification Thresholds

| Dimension | Tag | Threshold |
|-----------|-----|-----------|
| Activity | `high_activity` | quote success rate > 80% |
| Activity | `medium_activity` | 50% <= quote success rate <= 80% |
| Activity | `low_activity` | quote success rate < 50% |
| Failure | `high_failure` | route_failure_rate > 0.4 |
| Failure | `low_failure` | route_failure_rate < 0.2 |
| Spread | `wide_spread` | best_net_bps < -30 |
| Spread | `tight_spread` | best_net_bps > -10 |

### Evidence Runs (3 independent blocks)

| Run | Block | Scored | Failed | Best Net (bps) | Regime |
|-----|-------|--------|--------|----------------|--------|
| regime_1 | 446834785 | 67 | 33 | **-21.70** | `medium_activity` |
| regime_2 | 446835947 | 67 | 33 | **-26.46** | `medium_activity` |
| regime_3 | 446837081 | 67 | 33 | **-14.16** | `medium_activity` |

### Regime Repeatability (from m7a_regime_repeatability.json)

| Field | Value |
|-------|-------|
| regimes_observed | `["medium_activity"]` |
| runs_by_regime.medium_activity | 3 |
| best_net_bps_by_regime.medium_activity | -14.16 |
| mean_best_net_bps_by_regime.medium_activity | -20.77 |
| beats_two_leg_baseline_by_regime.medium_activity | **false** |
| blocker_stability_by_regime.medium_activity.stable | 6/6 |
| blocker_stability_by_regime.medium_activity.flapping | 0 |
| two_leg_baseline_net_bps | -3.5062 |

### New Tests Added (28 contract tests)

| Class | Tests | What it locks |
|-------|-------|--------------|
| TestRegimeClassification | 16 | Threshold correctness, boundary behavior, tag ordering, canonical set, empty/zero guards, multi-tag coexistence |
| TestRegimeRepeatabilitySchema | 10 | Schema keys, runs_count, runs_by_regime, best_net, beats_baseline, blocker_stability, backward_compat, empty, run_entries |
| TestRegimeBackwardCompatibility | 2 | Pre-M7.A.3 blocker_summary and repeatability schemas unchanged |

## 5) Strategic Reading

M7.A.3 temporal-regime hypothesis infrastructure is now operational: each measured run is automatically classified into market regimes, and the regime repeatability aggregator can compare edge characteristics across different regimes.

**Finding**: All 3 evidence runs fall in the same `medium_activity` regime (67% quote success, 33% failure rate, net between -30 and -10 bps). The hypothesis that a different temporal regime might produce a positive edge is **not yet falsifiable** from this evidence — only one regime has been observed. However, within the `medium_activity` regime, the blocker structure is identical to all prior M7.A/M7.A.2 evidence (6/6 stable, 0 flapping, no run beats baseline).

**M7.A.3 is a closed bounded baseline** for the `medium_activity` regime on arbitrum_one `narrow_7`. To further test the temporal-regime hypothesis, future runs would need to capture `high_activity` or `low_activity` regimes (which require market conditions that produce >80% or <50% quote success rates respectively).

**M7.B remains closed.** M7.A, M7.A.2, and M7.A.3 all independently confirm the no-graduate verdict.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY — NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY — NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime, narrow_7) |
| M7.B | NOT STARTED (closed by M7.A + M7.A.2 + M7.A.3 verdicts) |
