# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_520_300b / m7a_520_300b_b / m7a_520_1000b / m7a_520_triangular
mode: ONLINE (evidence runs + unit tests)
artifact_mode: local evidence (data/tmp/m7a_520_*.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-04-01T16:46:00Z
  dirty: true
  desc: M7.A.5.20 — local-state-first V3/V2 pricing, 3 new BackrunResult fields (59 total)
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275
rolling_run_timestamp: 2026-03-27T21:30:14Z
note: rolling artifacts predate this session; not regenerated; session evidence is in data/tmp/m7a_520_*

## Session Completion
session_goal: M7.A.5.20 -- local-state-first pricing via V3/V2 swap math; bypass remote quoter when local pricing succeeds; fresh evidence runs
goal_status: REACHED (v3_math.py created; 3 new fields; scoring_parallel conditional Stage B; 29 new tests; 3212 pass; 4 evidence runs; first positive net bps observed)
close_allowed: true
remaining_blockers: low-lag events blocked at coverage stage BEFORE reaching local pricing; NO_COUNTER_POOL + ALL_CANDIDATE_POOLS_TRULY_INACTIVE dominate low-lag; viable_count=0
evidence_session_run_dirs: [data/tmp/m7a_520_300b.json, data/tmp/m7a_520_300b_b.json, data/tmp/m7a_520_1000b.json, data/tmp/m7a_520_triangular.json]
primary_blocker_of_session: stale events scored locally with positive bps but all stale; low-lag events rejected before reaching local pricing
blocker_status_before: all scoring required remote quoter (~3500ms latency); no positive net bps ever observed; low-lag events rejected at coverage
blocker_status_after: local V3/V2 pricing bypasses remote quoter; pipeline latency halved (1402ms); positive net bps observed (+18.20, +13.45, +7.77); low-lag still blocked at coverage
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.20 -- local-state-first pricing using captured pool state to bypass remote quoter
change_summary:
  - `m7/orderflow/v3_math.py` (NEW, ~260 lines): `compute_v3_swap_amount_out()` (single-tick V3 Q96 math), `compute_v2_swap_amount_out()` (constant-product), `attempt_local_pricing()` orchestrator
  - `m7/orderflow/contracts.py`: 3 new BackrunResult fields (56→59): `local_pricing_attempted`, `local_pricing_used`, `local_pricing_failure_reason`
  - `m7/orderflow/scoring_parallel.py`: Local pricing attempt between Stage A (venue pruning) and Stage B (remote quoter); Stage B conditional — skipped when local pricing succeeds
  - `m7/orderflow/artifacts.py`: `low_lag_local_pricing` block (6 metrics)
  - `scripts/m7a_orderflow_replay.py`: Added re-exports for v3_math functions
  - `tests/unit/test_orderflow_m7a520.py` (NEW, ~380 lines): 29 tests (V3/V2 math, local pricing, fields, artifacts)
  - 6 existing test files: Updated field count assertions 56→59
touched_files:
  - m7/orderflow/v3_math.py (NEW: ~260 lines)
  - m7/orderflow/contracts.py (MODIFIED: +3 fields, 59 total)
  - m7/orderflow/scoring_parallel.py (MODIFIED: local pricing + conditional Stage B)
  - m7/orderflow/artifacts.py (MODIFIED: low_lag_local_pricing block)
  - scripts/m7a_orderflow_replay.py (MODIFIED: v3_math re-exports)
  - tests/unit/test_orderflow_m7a520.py (NEW: 29 tests)
  - tests/unit/test_orderflow_m7a513_515.py (MODIFIED: 56→59)
  - tests/unit/test_orderflow_m7a511_512.py (MODIFIED: 56→59)
  - tests/unit/test_orderflow_m7a516_517.py (MODIFIED: 56→59)
  - tests/unit/test_orderflow_m7a55_56.py (MODIFIED: 56→59)
  - tests/unit/test_orderflow_m7a59_510.py (MODIFIED: 56→59)
  - tests/unit/test_orderflow_m7a518_519.py (MODIFIED: 56→59)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.20 section added)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3212 passed, 6 skipped)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_520_300b.json: PASS
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_520_300b_b.json: PASS
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 1000 --ws-timeout 600 --max-events 100 --output data/tmp/m7a_520_1000b.json: PASS
py -3.11 scripts/m7a_enumerate_cycles.py --chain arbitrum_one --source runtime --score measured --max-cycles 500 --max-scored 100 --sweep-top 10 --output data/tmp/m7a_520_triangular.json: PASS

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_520_300b.json (300-block ws-live, 30 events, best_net=+18.20 bps, 29/30 local pricing used)
  - data/tmp/m7a_520_300b_b.json (300-block ws-live, 30 events, best_net=+13.45 bps)
  - data/tmp/m7a_520_1000b.json (1000-block ws-live, 82 events, best_net=+7.77 bps, 6 low-lag 0 scored)
  - data/tmp/m7a_520_triangular.json (500 cycles, 67 measured, best_net=-16.22 bps)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results -- M7.A.5.20

### Local-State-First Pricing

Created `m7/orderflow/v3_math.py` with Uniswap V3 single-tick swap math (Q96 fixed-point, fee deduction, MIN/MAX_SQRT_RATIO bounds) and V2 constant-product math. `attempt_local_pricing()` orchestrator iterates candidate pools, determines zero_for_one from token ordering, picks best buy/sell amounts locally.

In `scoring_parallel.py`, local pricing attempt inserted between Stage A (venue pruning) and Stage B (remote quoter). If local pricing succeeds, Stage B (ThreadPoolExecutor remote quoter) is skipped entirely. 3 new BackrunResult fields track: `local_pricing_attempted`, `local_pricing_used`, `local_pricing_failure_reason`.

### Evidence: Orderflow (3 runs)

| Run | Events | Positive | best_net_bps | Low-lag | Low-lag Scored | Local Used |
|-----|--------|----------|-------------|---------|----------------|------------|
| 300b | 30 | 1 | +18.20 | 1 | 0 | 29/30 |
| 300b_b | 30 | 1 | +13.45 | 1 | 0 | — |
| 1000b | 82 | 2 | +7.77 | 6 | 0 | — |

Pipeline latency: mean=1402ms (was ~3500ms). Stage B=0ms when local pricing used. All positive-net events are stale (block_lag >> 2), rejected by STALE_POSITIVE gate. `low_lag_local_pricing` block: all zeros (low-lag events rejected at coverage before reaching pricing).

### Evidence: Triangular

67/100 measured, 0 promoted, best_net=-16.22 bps. Blockers: GROSS_NEGATIVE_CORE=10, GAS_DOMINANT_SMALL=10, SLIPPAGE_DOMINANT_LARGE=10. Same-state proven 100%. regime_bucket=medium_activity.

## 5) Strategic Reading

1. **First positive net bps observed**: +18.20, +13.45, +7.77 bps across 3 runs — local V3 math produces net-positive scoring for the first time. However all are stale events (block_lag >> 2), rejected by STALE_POSITIVE. viable_count=0, best_net_bps_executable=null.
2. **Pipeline latency halved**: From ~3500ms to ~1402ms mean. Stage B (remote quoter) is entirely skipped for 29/30 events. Infrastructure benefit is real.
3. **Low-lag blocker unchanged**: All low-lag events rejected at coverage stage (NO_COUNTER_POOL, ALL_CANDIDATE_POOLS_TRULY_INACTIVE) BEFORE reaching local pricing. The `low_lag_local_pricing` artifact correctly reports zeros.
4. **Honest assessment**: M7.A.5.20 is infrastructure progress, NOT profit progress. Local pricing works (proven by stale positive net bps), but it doesn't unlock the low-lag pathway because that's blocked earlier in the pipeline.
5. **Triangular still negative**: best_net=-16.22 bps, same structural blockers as prior runs.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 19, UNSCORED_REJECTS: 11, BackrunResult: 59 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (all m7/ modules ≤ 854 lines, v3_math.py at ~260 lines)
test file size constraint: OK (all M7 test files ≤ 995 lines, test_orderflow_m7a520.py at ~380 lines)

## 5.2) Blockers / Risks
- PRIMARY (unchanged): NO_COUNTER_POOL + ALL_CANDIDATE_POOLS_TRULY_INACTIVE dominate low-lag; events never reach local pricing
- SECONDARY (unchanged): temporal instability — LOW_LAG_NONE_THIS_WINDOW in longer windows
- NEW INSIGHT: stale events produce positive net bps (+18.20) via local pricing, but STALE_POSITIVE gate correctly rejects them
- UNCHANGED: Gas-exceeds-gross dominates stale subset for most events; M4 baseline still negative
- NEXT: To unlock low-lag scoring, need to address coverage-stage blockers (not pricing-stage)
