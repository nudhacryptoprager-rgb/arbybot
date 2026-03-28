# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14.342304Z
run_id: ci_m5_gate_arbitrum_one_20260327_222948_123275
mode: ONLINE
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow universe, runtime source, measured scoring
code_identity:
  primary: ts:2026-03-27T21:30:14.342304Z
  dirty: false
  desc: M7.A bounded-scope verdict formalization

## Session Completion
session_goal: formalize bounded-scope no-graduate verdict for M7.A on arbitrum_one narrow universe
goal_status: REACHED
close_allowed: true
remaining_blockers: none
evidence_session_run_dirs:
  - data/tmp/m7a_blockers_run4.json (fresh, block 446661451)
  - data/tmp/m7a_verdict.json (formal verdict artifact)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260327_222948_123275
primary_blocker_of_session: M7.A verdict not yet formalized as machine-readable artifact
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A step 8 - decide whether M7 stops or graduates to M7.B
change_summary:
  - Added build_verdict_summary() to scripts/m7a_enumerate_cycles.py
  - Added --verdict CLI arg (builds repeatability internally, then produces verdict)
  - Verdict fields: verdict_scope, beats_two_leg_baseline, all_sizes_negative, gross_sometimes_positive, stable/flapping_blockers_count, recommend_open_m7b, recommend_freeze_current_m7a_scope, best_net_bps_range, dominant_triple, route_failure_rate
  - TWO_LEG_BASELINE_NET_BPS = -3.5062 from rolling long_scan_latest.json
  - Fixed docs wording: gross can be transiently positive; binding blocker is multi-cost, not reserve-only
  - Added 10 verdict contract tests (TestVerdictSummary)
  - Total test count: 2704 passed, 0 failures
touched_files:
  - scripts/m7a_enumerate_cycles.py
  - tests/unit/test_triangular_contracts.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest -q: PASS (2704 passed, 17 skipped, 51.75s)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (1 warning: docs line count)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all gates OK)
py -3.11 scripts/m7a_enumerate_cycles.py --verdict (4 artifacts): PASS

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_blockers_run1.json (block 446652757)
  - data/tmp/m7a_blockers_run2.json (block 446653838)
  - data/tmp/m7a_blockers_run3.json (block 446654943)
  - data/tmp/m7a_blockers_run4.json (block 446661451, fresh this session)
  - data/tmp/m7a_blocker_repeatability.json (3-block aggregation)
  - data/tmp/m7a_verdict.json (4-block formal verdict)

rolling (unchanged from prior session):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results - M7.A Verdict

### Verdict Summary (from m7a_verdict.json)

| Field | Value |
|-------|-------|
| beats_two_leg_baseline | **false** |
| all_sizes_negative | **true** |
| gross_sometimes_positive | **true** |
| stable_blockers_count | **6** |
| flapping_blockers_count | **0** |
| best_net_bps_range | -23.52 to -9.56 (mean -16.60) |
| two_leg_baseline_net_bps | -3.5062 |
| dominant_triple | **true** (ARB/USDC/WETH, concentration 1.0) |
| route_failure_rate | 0.33 (stable across all runs) |
| recommend_open_m7b | **false** |
| recommend_freeze_current_m7a_scope | **true** |

### Multi-cost Blocker Structure

The binding constraint is NOT a single factor. Temporal evidence across 4 independent blocks:

- **Gross bps** ranges -14.29 to +2.25 (mean -6.21) - sometimes positive
- **Gas bps** ranges 9.23 to 11.81 (mean 10.09) - always dominant cost
- **Fee bps** ranges 1.00 to 6.00 (mean 4.33) - third-leg fee compounds loss
- **Net bps** ranges -23.52 to -9.56 (mean -16.60) - always negative

Even when gross is transiently positive, gas + fees push net below zero.

### Blocker Class Stability (6/6 stable, 0/6 flapping)

| Tag | Status | Interpretation |
|-----|--------|----------------|
| GROSS_NEGATIVE_CORE | STABLE | Gross negative in majority of cycles (can be transiently positive) |
| GAS_DOMINANT_SMALL | STABLE | Gas dominates at small notionals |
| SLIPPAGE_DOMINANT_LARGE | STABLE | Slippage dominates at large notionals |
| THIRD_LEG_FEE_BINDING | STABLE | Third leg protocol fee >= 5 bps |
| SINGLE_TRIPLE_CONCENTRATION | STABLE | Zero token-path diversity |
| QUOTE_FAILURE_BREADTH_LIMIT | STABLE | VE33 adapter failures limit route breadth |

### Rolling Two-Leg Baseline (unchanged)

| Metric | Value |
|--------|-------|
| best_roundtrip_net_bps | -3.5062 |
| total_profitable_roundtrips | 0 |

### Evidence Tiers Supporting Verdict

1. **Temporal repeatability** - 5 runs across blocks 446589515-446622133, all negative
2. **Size sweep** - 10 cycles x 19 sizes at block 446635245, all negative, U-shaped curves
3. **Blocker RCA** - 6 canonical tags with normalized count semantics
4. **Blocker repeatability** - 4 blocks (446652757-446661451), all 6 tags stable, 0 flapping
5. **Formal verdict** - machine-readable recommend_open_m7b: false

## 5) Strategic Reading

For the current bounded M7.A scope on arbitrum_one narrow-universe (7 tokens, 4 DEX families), temporal repeatability, size sweep, and blocker repeatability jointly support a **no-graduate verdict**.

M7.B remains closed. The current M7.A scope should be frozen unless a new explicit hypothesis changes the search surface (different chain, expanded universe, new adapter types).

This is a **valid negative outcome** per docs/step_M7.md stop condition:
> If bounded read-only triangular work does not produce repeatable, provenance-aware, measured economics that clearly outperform the closed public two-leg thesis, then M7.A is considered a valid negative outcome, M7.B does not open, M7 is frozen as an R&D branch.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY - NO-GRADUATE** |
| M7.B | NOT STARTED (closed by M7.A verdict) |
