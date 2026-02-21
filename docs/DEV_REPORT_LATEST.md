# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-21T10:00:09Z
run_id: data/runs/ci_m5_gate_20260221_105949
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-21T10:00:09.828466+00:00
  dirty: true
  desc: M4 fee_tier fix + M4.1 deterministic close plan + status normalization

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M4 stability + MIXED_SOURCE elimination + deterministic close plan
change_summary:
  - FIX: WBTC/WETH fee_tiers changed to [3000] only (Sushi fee=500 has no liquidity)
  - FIX: ARB/WETH fee_tiers changed to [3000] only (Sushi fee=500 PRICE_SANITY_FAILED)
  - ADD: M4.1 deterministic close plan in Roadmap.md (N=100 time-bound window)
  - FIX: Status_M4.md data_run_rate corrected (0.9873 → 0.9875 with new run)
  - FIX: Status_M4.md provenance timestamp corrected
  - RESULT: excluded_signals_count dropped from 2 to 1 (MIXED_SOURCE partly fixed)
touched_files:
  - Roadmap.md
  - config/real_minimal.yaml
  - docs/status/Status_M4.md
  - docs/status/Status_M5_0.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.4.0, 8 checks, 0 warnings)
py -3.11 -m pytest -q: PASS (955 passed, 12 skipped, 1 warning, 11.03s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (12.3s, all required gates passed)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1 --refresh-rolling: PASS
py -3.11 scripts/verify_v3_pools.py --pairs WBTC/WETH ARB/WETH --require-cross-dex --verbose: PASS (13 active pools)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260221_105949/reports

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  agg_reasons: []
  data_run_rate: 0.9875
  low_sample_rate: 0.0

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-21T10:00:09.828466+00:00
  run_context.code_identity: ts:2026-02-21T10:00:09.828466+00:00
  inputs.run_dir_name: ci_m5_gate_20260221_105949
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 8
    included_signals_count: 7
    excluded_signals_count: 1
    total_net_usdc: 37.43 (single run)
    mae_net_usdc: 0.5
    est_sign_correct_rate: 1.0
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    cost_model_available: true
    profit_truth_available: false
  quality_status: WARN
  quality_reasons: ['WARN_EXCLUDED_SIGNALS', 'WARN_PROFIT_DIAGNOSTIC']

m4_stability_agg.json:
  runs_in_window: 80
  last_run: ci_m5_gate_20260221_105949
  computed_total_net_usdc: 4359.51
  agg_status: PASS
  agg_reasons: []

## 5) Diversity Analysis (from rolling artifacts)

unique_pairs: 8 (target=8) -> OK
  - ARB/USDC, ARB/WETH, LINK/WETH, WBTC/USDC, WBTC/WETH, WETH/USDC, WETH/USDT, wstETH/WETH

unique_routes_cross_dex: 2 (target=2) -> OK
  - sushiswap_v3->uniswap_v3
  - uniswap_v3->uniswap_v3

excluded_from_signals (MIXED_SOURCE/slot0 fallback):
  - 1 signal excluded in current run (down from 2 after fee_tier fix)

## 6) M4 DoD Status

| DoD | Status | Evidence |
|-----|--------|----------|
| Core Truth (paper +PnL) | [OK] PROVEN | N=79 runs, total_net_usdc=$4359.51 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [IN PROGRESS] | 80/100 runs (80% complete) |

> **M4 NOT CLOSED**: profit_truth_available=false (no roundtrip opportunities).
> Paper profit PROVEN under declared cost model.
> M4.1 deterministic close plan: N=100 runs with agg_status=PASS (currently at 80).

## 7) Contract Checks (коротко)
status/reasons consistency: OK (no FAIL_* with PASS status)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no SHA tracking)
runtime artifacts not committed: OK

## 8) Blockers / Risks (max 5)
- roundtrip.profitable_count=0 (market has no arb opportunity currently)
- profit_truth_available=false (requires profitable roundtrip for M4 full close)
- 1 signal still excluded (remaining MIXED_SOURCE) - needs further investigation
- PENDLE/RDNT quoter_v2 failures (slot0 fallback - pairs DISABLED)

## 9) Lead's 10 Steps: Execution Map
step_01 (Deterministic M4 close plan): DONE - added M4.1 section to Roadmap.md
step_02 (MIXED_SOURCE fix for WBTC/WETH, ARB/WETH): DONE - fee_tiers changed to [3000]
step_03 (intent→pool runtime contract): NO - deferred
step_04 (Discovery→runtime integration): NO - deferred
step_05 (3rd DEX track): NO - deferred (Algebra quoter needs integration)
step_06 (M4.3 preflight evidence): NO - deferred
step_07 (Execution plan dry-run): NO - deferred
step_08 (Clean PnL audit test): NO - deferred
step_09 (Normalize Status facts): DONE - Status_M4.md and Status_M5_0.md updated
step_10 (Canonical DEV REPORT): DONE - this report
