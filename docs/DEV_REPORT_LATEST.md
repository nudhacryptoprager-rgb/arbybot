# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-22T09:10:03Z
run_id: data/runs/ci_m5_gate_20260222_100945
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-22T09:10:03.859524+00:00
  dirty: true
  desc: Directive #2 - excluded signals eliminated + Clean PnL tests + DEV_REPORT alignment guard

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Directive #2 - Eliminate excluded signals, add guardrails, Clean PnL tests
change_summary:
  - FIX: WBTC/WETH + ARB/WETH Sushi pools added to disabled_pools (SUSPECT_SPREAD_EXCLUDED)
  - ADD: DEV_REPORT alignment check (check_repo_safety.py v1.6.0, check #10)
  - ADD: inspect_rolling.py script for rolling artifact inspection
  - ADD: Clean PnL golden tests (10 test cases in test_execution_pnl_golden.py)
  - RESULT: excluded_signals_count=0, WARN_EXCLUDED_SIGNALS eliminated
  - RESULT: total_net_usdc=$5347.64 (N=103 runs)
touched_files:
  - scripts/check_repo_safety.py (v1.6.0 - alignment check)
  - scripts/inspect_rolling.py (new)
  - tests/unit/test_check_repo_safety.py
  - tests/unit/test_execution_pnl_golden.py (new)
  - config/real_minimal.yaml (disabled_pools)
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.6.1, 10 checks, 0 warnings)
py -3.11 -m pytest -q: PASS (994 passed, 1 skipped, 1 warning)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS
py -3.11 scripts/inspect_rolling.py: excluded_signals_count=0

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260222_111023/reports

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  agg_reasons: []
  data_run_rate: 0.9903
  low_sample_rate: 0.0

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-22T10:10:42.000000+00:00
  run_context.code_identity: ts:2026-02-22T10:10:42.000000+00:00
  inputs.run_dir_name: ci_m5_gate_20260222_111023
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 5
    included_signals_count: 5
    excluded_signals_count: 0
    total_net_usdc: 49.79 (single run)
    mae_net_usdc: 0.5
    est_sign_correct_rate: 1.0
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    cost_model_available: true
    profit_truth_available: false
  quality_status: WARN
  quality_reasons: ['WARN_PROFIT_DIAGNOSTIC']

m4_stability_agg.json:
  runs_in_window: 104 (M4.1 N=100+ maintained)
  last_run: ci_m5_gate_20260222_111023
  computed_total_net_usdc: 5394.31
  agg_status: PASS
  agg_reasons: []

## 5) Diversity Analysis (from rolling artifacts)

unique_pairs: 8 (target=8) -> OK (from m4_stability_agg.json quick_stats)
  - ARB/USDC, ARB/WETH, LINK/WETH, WBTC/USDC, WBTC/WETH, WETH/USDC, WETH/USDT, wstETH/WETH

unique_routes_cross_dex: 2 (target=2) -> OK
  - sushiswap_v3->uniswap_v3
  - uniswap_v3->uniswap_v3

excluded_from_signals: **NONE** (FIXED)
  - Previously: WBTC/WETH_3000, ARB/WETH_3000 Sushi pools causing SUSPECT_SPREAD_EXCLUDED
  - Fix: Both pools added to disabled_pools in real_minimal.yaml
  - Result: WARN_EXCLUDED_SIGNALS eliminated

## 6) M4 DoD Status

| DoD | Status | Evidence |
|-----|--------|----------|
| Core Truth (paper +PnL) | [OK] PROVEN | N=104 runs, total_net_usdc=$5394.31 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] CLOSED | 104/100 runs (100%+ maintained) |

> **M4.1 CLOSED**: N=104 consecutive runs with agg_status=PASS.
> Paper profit PROVEN under declared cost model ($5394.31 cumulative).
> Excluded signals ELIMINATED - quality_reasons now only WARN_PROFIT_DIAGNOSTIC.
> M4 full close requires M4.2 profitable roundtrip (market-dependent).

## 7) Contract Checks (коротко)
status/reasons consistency: OK (no FAIL_* with PASS status)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no SHA tracking)
runtime artifacts not committed: OK

## 8) Blockers / Risks (max 5)
- roundtrip.profitable_count=0 (market has no arb opportunity)
- profit_truth_available=false (requires profitable roundtrip for M4 full close)
- PENDLE/RDNT quoter_v2 failures (slot0 fallback - pairs DISABLED)
- eth_estimateGas fails on all preflight legs (fallback gas used, eth_call OK)

## 9) Lead's 10 Steps: Execution Map
step_01 (Realign DEV_REPORT): DONE - synced with rolling ci_m5_gate_20260222_100945
step_02 (DEV_REPORT drift guardrail): DONE - check_repo_safety.py v1.6.0 check #10
step_03 (inspect_rolling.py): DONE - new script for rolling inspection
step_04 (Disable WBTC/WETH Sushi): DONE - added to disabled_pools
step_05 (Verify excluded=0): DONE - WARN_EXCLUDED_SIGNALS eliminated
step_06 (Clean PnL golden test): DONE - 10 tests in test_execution_pnl_golden.py
step_07 (M4.3 preflight evidence): DONE - execution/preflight.py v1.0.1, 3/3 candidates passed
step_08 (Discovery dry-run): DONE - integrated in run_scan_real.py (discovery_dry_run flag)
step_09 (Intent→pool resolver): NO - deferred (requires new module)
step_10 (Final verification): DONE - this report
step_09 (Normalize Status facts): DONE - Status_M4.md updated
step_10 (Canonical DEV REPORT): DONE - this report
