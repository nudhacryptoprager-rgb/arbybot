# DEV REPORT

## 0) Meta
timestamp_utc: 2026-02-19T18:04:16Z
run_id: data/runs/ci_m5_gate_20260219_190354
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-19T18:04:16.934105+00:00
  dirty: false
  desc: v2.3.2-fix profit_is_diagnostic + gross_pnl_usdc_est + ASCII

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M4 simulate-only, v2.3.2 Profit Truth Semantics
change_summary:
  - FIX: profit_is_diagnostic тепер false при roundtrip.profitable_count > 0 (навіть якщо truth_mode_m42=true)
  - FIX: _compute_execution_pnl використовує gross_pnl_usdc_est (не spread_usdc)
  - FIX: ASCII encoding в status файлах (em-dash, arrows)
  - ADD: 7 нових тестів для profit_is_diagnostic/execution_pnl
  - ADD: 5 нових sushi regression test cases (WBTC/USDC, inverted)
  - UPDATE: Status_M5_0.md test counts (933 passed)
  - UPDATE: Status_M4.md - прибрано M5_0 infra деталі, Clean PnL AVAILABLE
touched_files:
  - strategy/artifacts.py
  - tests/unit/test_truth_report.py
  - tests/unit/test_sushi_price_sanity_regression.py
  - docs/status/Status_M4.md
  - docs/status/Status_M5_0.md
  - docs/status/INDEX.md
  - Roadmap.md

## 2) Commands Executed (лише факти)

python -m pytest -q: PASS (933 passed, 1 skipped, 10.43s)
python scripts/ci_full_pipeline.py --mode ci: PASS (all gates passed, 11.9s)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1 --refresh-rolling: PASS
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling: PASS (via rolling refresh)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260219_190354/reports

## 4) Key Results (числа з артефактів)

latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY
  data_run_rate: 0.9865
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 8
  metrics.total_net_usdc: 43.7188
  metrics.profit_truth_available: false
  metrics.cost_model_available: true
  metrics.profit_is_diagnostic: true
  metrics.profit_truth_source: ONE_LEG_DIAGNOSTIC
  quality_reasons: ['WARN_EXCLUDED_SIGNALS', 'WARN_CRITICAL_REJECTS', 'WARN_PROFIT_DIAGNOSTIC']
m4_stability_agg:
  total_net_usdc: 4041.9231
  unique_pairs: 8
  unique_routes: 4
  unique_routes_cross_dex: 2
  low_sample_rate: 0.0

## 5) v2.3.2 Fields Evidence

truth_report (ci_m5_gate_20260219_190354):
  execution_pnl.cost_model_available: true
  execution_pnl.cost_model_version: paper_gas_slippage_v1
  execution_pnl.gross_pnl_usdc: 888.227900
  profit_is_diagnostic: true
  profit_truth_source: ONE_LEG_DIAGNOSTIC

## 6) Blockers

- roundtrip.profitable_count=0 (no arb opportunity in current market)
- profit_truth_available=false (diagnostic mode)
- unique_routes_cross_dex=2 < 4 (need 3rd DEX)
- unique_pairs=8 < 10 (diversity warning)

## 7) Next Steps

1. Add 3rd DEX (camelot_v3) for diversity_routes
2. Wait for market conditions with actual arb opportunity
3. When roundtrip.profitable_count > 0, profit_truth_available will become true
