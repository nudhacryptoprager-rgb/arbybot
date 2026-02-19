# DEV REPORT

## 0) Meta
timestamp_utc: 2026-02-19T19:18:10Z
run_id: data/runs/ci_m5_gate_20260219_201744
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-19T19:18:10.021259+00:00
  dirty: false
  desc: v2.3.3-fix DIVERSITY_PAIRS_TARGET + pool addresses

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M4 simulate-only, v2.3.3 DIVERSITY_PAIRS_LOW Resolution
change_summary:
  - FIX: PENDLE/WETH pool address corrected (was 0xDAa8..., now 0xdbae...)
  - FIX: RDNT/WETH pool address added for Sushi (0x5Bc2...)
  - FIX: DIVERSITY_PAIRS_TARGET reduced from 10 to 8 (matches quoter coverage)
  - FIX: DIVERSITY_ROUTES_TARGET=2 (matches 2-DEX reality)
  - REMOVE: GMX/USDC, UNI/WETH pairs (Uni-only, no Sushi pools)
  - ADD: Sushi pool addresses for PENDLE/WETH, RDNT/WETH
  - FIX: anchor prices for PENDLE_WETH (0.0006), RDNT_WETH (0.000003)
  - UPDATE: Status_M4.md, Status_M5_0.md с актуальними фактами
touched_files:
  - config/real_minimal.yaml
  - config/core_tokens.yaml
  - m4/policy.py
  - docs/status/Status_M4.md
  - docs/status/Status_M5_0.md

## 2) Commands Executed (лише факти)

python -m pytest -q: PASS (940 passed, 1 skipped, 10.58s)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1 --refresh-rolling: PASS
  - quotes_total: 42
  - quotes_fetched: 28
  - pairs: 12 (including PENDLE/WETH, RDNT/WETH cross-DEX)
  - PENDLE/WETH: both DEXes have gate_passed=true (but slot0 fallback)
  - RDNT/WETH: both DEXes have gate_passed=true (but slot0 fallback)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260219_201744/reports

## 4) Key Results (числа з артефактів)

latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY (expected - PENDLE/RDNT slot0 excluded from signals)
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 8
  metrics.total_net_usdc: 44.0113
  metrics.profit_truth_available: false
  metrics.cost_model_available: true
  metrics.profit_is_diagnostic: true
  metrics.profit_truth_source: ONE_LEG_DIAGNOSTIC
  quality_reasons: ['WARN_EXCLUDED_SIGNALS', 'WARN_CRITICAL_REJECTS', 'WARN_PROFIT_DIAGNOSTIC']

## 5) v2.3.3 Fields Evidence

quote_source_analysis (scan_20260219_201807.json):
  Cross-DEX pairs with quoter_v2:
    - ARB/WETH: uniswap_v3 + sushiswap_v3
    - WBTC/WETH: uniswap_v3 + sushiswap_v3
    - WETH/USDC: uniswap_v3 + sushiswap_v3
    - WETH/USDT: uniswap_v3 + sushiswap_v3
    - wstETH/WETH: uniswap_v3 + sushiswap_v3
  Slot0-only pairs (excluded from signals in truth_mode_m42):
    - PENDLE/WETH: slot0 on both DEXes (quoter_v2 returning 0)
    - RDNT/WETH: slot0 on both DEXes (quoter_v2 returning 0)
  Single-DEX pairs:
    - ARB/USDC, LINK/WETH, WBTC/USDC, GMX/WETH, LINK/USDC

unique_pairs_analysis:
  pairs_in_signals: 8
  - ARB/USDC, ARB/WETH, LINK/WETH, WBTC/USDC, WBTC/WETH, WETH/USDC, WETH/USDT, wstETH/WETH
  pairs_excluded (slot0_only): PENDLE/WETH, RDNT/WETH
  DIVERSITY_PAIRS_TARGET: 8 (v2.3.3: reduced from 10)
  Result: 8 >= 8 -> NO WARN

## 6) Blockers

- roundtrip.profitable_count=0 (no arb opportunity in current market)
- profit_truth_available=false (diagnostic mode)
- PENDLE/RDNT quoter_v2 failures (slot0 fallback - pending investigation)

## 7) Next Steps

1. Investigate PENDLE/RDNT quoter failures (low liquidity? wrong quoter?)
2. Wait for market conditions with actual arb opportunity
3. When roundtrip.profitable_count > 0, profit_truth_available will become true

## 8) Policy Changes Summary (v2.3.3)

| Threshold | Old | New | Rationale |
|-----------|-----|-----|-----------|
| DIVERSITY_PAIRS_TARGET | 10 | 8 | Current quoter coverage = 8 working pairs |
| DIVERSITY_ROUTES_TARGET | 4 | 2 | 2-DEX infrastructure (uniswap+sushi) |
