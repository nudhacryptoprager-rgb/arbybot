# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-24T13:16:57Z
run_id: data/runs/ci_m5_gate_20260224_141638
mode: ONLINE (M4.1 CAPSTONE - N>=100 achieved)
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile, fee_tiers expanded)
code_identity:
  primary: ts:2026-02-24T13:16:57+00:00
  dirty: true
  desc: M4.1 CAPSTONE - runs_in_window=184 >= 100, agg_status=PASS

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M4.1 Time-Bound Window - achieve N>=100 with agg_status=PASS
change_summary:
  - MILESTONE: M4.1 achieved - runs_in_window=184 >= 100
  - CHG: config/real_minimal.yaml WBTC/WETH fee_tiers: [500, 3000] (was [3000])
  - CHG: config/real_minimal.yaml ARB/WETH fee_tiers: [500, 3000] (was [3000])
  - FIX: strategy/spreads.py v2.5.2 - dual cross-DEX routes
  - RESULT: agg_status=PASS, unique_pairs=8, unique_routes_cross_dex=2, excluded=0
touched_files:
  - config/real_minimal.yaml (fee_tiers expansion)
  - strategy/spreads.py (v2.5.2 dual cross-dex routes)
  - tests/unit/test_same_dex_policy.py (dual-route test)

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS
py -3.11 -m pytest -q: PASS (1068 passed, 12 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)
py -3.11 scripts/verify_v3_pools.py --pairs WBTC/WETH ARB/WETH --verbose: 13 active pools verified
py -3.11 start.py --minutes 60 --max-runs 80: 184 runs accumulated
py -3.11 scripts/ci_m5_0_gate.py --online (capstone): PASS, runDir=ci_m5_gate_20260224_141638
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json (184 runs)
capstone_run_dir:
  - data/runs/ci_m5_gate_20260224_141638/reports
preflight_evidence:
  - enabled: true
  - candidates_count: 2
  - passed_count: 2 (100%)
  - evidence_source: preflight_v1.0.3
  - leg1.gas_estimate_source: quoter_v2
  - leg2.gas_estimate_source: quoter_v2

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS (M4.1 ACHIEVED!)
  agg_reasons: []
  quality_warnings: []
  data_run_rate: 1.0
  low_sample_rate: 0.0
  runs_in_window: 184 (>= 100 REQUIRED)
  in_warmup: false

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-24T13:16:57+00:00
  inputs.run_dir_name: ci_m5_gate_20260224_141638
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 8 per run
    included_signals_count: 8 (all included)
    excluded_signals_count: 0 (no exclusions!)
    total_net_usdc: $960.78 (184 runs)
    profit_is_diagnostic: true

m4_stability_agg.json:
  runs_in_window: 184 (M4.1 ACHIEVED!)
  pass_count: 184 (100%)
  data_run_rate: 1.0 (PERFECT)

  total_net_usdc: $960.78 (184 runs aggregated)
  unique_pairs: 8 (FIXED! was 6, now 8)
  unique_routes: 3
  unique_routes_cross_dex: 2
  agg_status: PASS (M4.1 ACHIEVED!)
  agg_reasons: []

## 5) Pair Diversity Expansion (v2.5.2)

fee_tiers_expansion:
  - WBTC/WETH: fee_tiers [3000] -> [500, 3000] (Uniswap fee-tier arb enabled)
  - ARB/WETH: fee_tiers [3000] -> [500, 3000] (Uniswap fee-tier arb enabled)
  - Pool verification: uniswap_v3_WBTC_WETH_500 liq=428657338564977205
  - Pool verification: uniswap_v3_ARB_WETH_500 liq=684124252408873178675578

log_evidence:
  - "unique_pairs: ['ARB/USDC', 'ARB/WETH', 'LINK/WETH', 'WBTC/USDC', 'WBTC/WETH', 'WETH/USDC', 'WETH/USDT', 'wstETH/WETH']"
  - "unique_routes: ['sushiswap_v3->uniswap_v3', 'uniswap_v3->sushiswap_v3', 'uniswap_v3->uniswap_v3']"

diversity_resolution:
  - BEFORE v2.5.2: unique_pairs=6 < 8 (DIVERSITY_PAIRS_LOW)
  - AFTER v2.5.2: unique_pairs=8 >= 8 (RESOLVED!)
  - DIVERSITY_ROUTES_FAIL: RESOLVED (v2.5.2 Directive #14)
  - DIVERSITY_PAIRS_LOW: RESOLVED (v2.5.2 Directive #15)

## 6) M4 DoD Status

| DoD | Status | Evidence |
|-----|--------|----------|
| Core Truth (paper +PnL) | [OK] PROVEN | N=184 runs, total_net_usdc=$960.78 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, unique_pairs=8, routes=3 |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] ACHIEVED | runs_in_window=184 >= 100 |
| M4.3 Preflight Evidence | [OK] v1.0.3 | chain-aware leg2, gas_sanity, quoter_v2 |
| Cross-DEX Preference | [OK] v2.5.2 | dual routes, always prefer cross-DEX |
| Diversity Routes | [OK] PASS | unique_routes_cross_dex=2 >= 2 |
| Diversity Pairs | [OK] PASS | unique_pairs=8 >= 8 |

> **PAIR DIVERSITY v2.5.2**: Fee-tier expansion for WBTC/WETH and ARB/WETH enabled Uniswap fee-tier arbitrage.
> Evidence: Both pairs now generate signals, raising unique_pairs from 6 to 8.
> DIVERSITY_PAIRS_LOW RESOLVED. agg_status improved from WARN_QUALITY to PASS.

## 7) Contract Checks (коротко)
status/reasons consistency: OK (no FAIL_* with PASS status)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no SHA tracking)
runtime artifacts not committed: OK
dual cross-dex routes: IMPLEMENTED (_find_all_cross_dex_spreads)
pair diversity: RESOLVED (8 pairs >= 8 target)

## 8) Blockers / Risks (max 5)
- [RESOLVED] M4.1: runs_in_window=184 >= 100 ACHIEVED
- roundtrip.profitable_count=0 (market has no arb opportunity for M4.2)
- profit_is_diagnostic=true (M4.2 Full Close requires real roundtrip profit)
- paper_size_usd=250 conservative (may miss larger opportunities)
- kill_switch_active=true (no real execution until M4.2)

## 9) Lead's 10 Steps: Execution Map (M4.1 CAPSTONE)
step_01 (Add fee_tiers to WBTC/WETH & ARB/WETH): DONE - [500, 3000]
step_02 (Verify V3 pools): DONE - 13 active pools verified
step_03 (Run CI full pipeline): DONE - ALL GATES PASSED
step_04 (Generate ONLINE run): DONE - ci_m5_gate_20260224_141638
step_05 (Build N>=100 rolling): DONE - 184 runs (start.py completed)
step_06 (Verify M4.1 criteria): DONE - runs_in_window=184 >= 100, agg_status=PASS
step_07 (Check WBTC/WETH & ARB/WETH signals): DONE - both pairs in signals
step_08 (Check M4.3 preflight): DONE - preflight PASS, quoter_v2
step_09 (Run M4 offline profit gate): DONE - PASS (strict)
step_10 (Update docs): DONE - M4.1 ACHIEVED

## 10) M4.1 Time-Bound Window CLOSURE
M4.1_status: ACHIEVED
runs_in_window: 184 (>= 100 REQUIRED)
agg_status: PASS
data_run_rate: 1.0
capstone_run: ci_m5_gate_20260224_141638
total_net_usdc: $960.78 (paper profit, diagnostic)
unique_pairs: 8,  unique_routes_cross_dex: 2
excluded_signals_count: 0
preflight_evidence: v1.0.3, gas_estimate_source=quoter_v2

