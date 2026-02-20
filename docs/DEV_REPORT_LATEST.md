# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-19T20:04:47Z
run_id: data/runs/ci_m5_gate_20260219_210425
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-19T20:04:47.148356+00:00
  dirty: false
  desc: v2.3.4 Version consistency + guardrails + M4-close plan

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M4 simulate-only, v2.3.4 version consistency and guardrails
change_summary:
  - FIX: Status_M5_0.md version contract (ci_m5_0_gate.py v2.3.2, not v2.3.4)
  - ADD: check_repo_safety.py v1.3.0 - Status version consistency check
  - ADD: check_repo_safety.py v1.3.0 - DEV_REPORT freshness check
  - CLARIFY: Version semantics (Contract Version vs Script Version)
  - ADD: M4-close plan (deterministic criteria, not luck-based)
  - ADD: WARN_EXCLUDED_SIGNALS root cause (WBTC/WETH, ARB/WETH = MIXED_SOURCE)
  - ADD: Diversity restore contract with verify_v3_pools.py --require-cross-dex
  - ADD: UTF-8 viewing commands in DEV_REPORT_CANONICAL_UA.md
touched_files:
  - docs/status/Status_M4.md (version semantics, M4-close plan, WARN root cause)
  - docs/status/Status_M5_0.md (version contract fix)
  - scripts/check_repo_safety.py (v1.3.0: version + freshness checks)
  - tests/unit/test_check_repo_safety.py (v1.3.0 tests)
  - docs/DEV_REPORT_CANONICAL_UA.md (UTF-8 viewing)
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

python -m pytest tests/unit/test_check_repo_safety.py -v: PASS (11 passed, 0.15s)
python scripts/check_repo_safety.py: PASS (v1.3.0, 7 checks, 0 warnings)
  - [6] Status version consistency: OK
  - [7] DEV_REPORT freshness: OK

## 3) Artifacts Attached (шляхи)
rolling (unchanged from previous session):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle:
  - data/runs/ci_m5_gate_20260219_210425/reports

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  agg_reasons: []

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  run_id: ci_m5_gate_20260219_210425
  run_timestamp: 2026-02-19T21:04:25+00:00
  status: PASS
  metrics:
    signals_count: 8
    included_signals_count: 6
    excluded_signals_count: 2
    total_net_usdc: 58.06 (single run)
    mae_net_usdc: 0.5
    est_sign_correct_rate: 1.0
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    cost_model_available: true
    profit_truth_available: false
  quality_status: WARN
  quality_reasons: ['WARN_EXCLUDED_SIGNALS', 'WARN_CRITICAL_REJECTS', 'WARN_PROFIT_DIAGNOSTIC']

m4_stability_agg.json:
  runs_in_window: 79
  last_run: ci_m5_gate_20260219_210425
  computed_total_net_usdc: 4322.08
  agg_status: PASS
  agg_reasons: []

truth_report_20260219_203119.json:
  roundtrip_summary:
    real_quote_count: 4
    profitable_count: 0
    best_net_pnl_bps: -17.1
  profit_realism_status: ROUNDTRIP_NOT_PROFITABLE
  profit_is_diagnostic: true

## 5) Diversity Analysis (v2.3.4)

unique_pairs: 8 (target=8) -> OK
  - ARB/USDC, ARB/WETH, LINK/WETH, WBTC/USDC, WBTC/WETH, WETH/USDC, WETH/USDT, wstETH/WETH

unique_routes_cross_dex: 2 (target=2) -> OK
  - sushiswap_v3->uniswap_v3
  - uniswap_v3->uniswap_v3

excluded_from_signals (slot0 fallback):
  - PENDLE/WETH (quoter_v2 returning 0)
  - RDNT/WETH (quoter_v2 returning 0)

## 6) M4 DoD Status

| DoD | Status | Evidence |
|-----|--------|----------|
| Core Truth (paper +PnL) | [OK] PROVEN | N=78 runs, total_net_usdc=$4264.02 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |

> **M4 NOT CLOSED**: profit_truth_available=false (no roundtrip opportunities).
> Paper profit PROVEN under declared cost model, but requires profitable roundtrip for M4 close.

## 7) Per-Run Quality Warnings (informational)

Per-run quality_status=WARN with:
- WARN_EXCLUDED_SIGNALS: 2 signals excluded (PENDLE/WETH, RDNT/WETH slot0)
- WARN_CRITICAL_REJECTS: PRICE_SANITY_FAILED/SUSPECT_LIQUIDITY present
- WARN_PROFIT_DIAGNOSTIC: profit_is_diagnostic=true

These do NOT affect rolling agg_status (which is PASS with no diversity warnings).

## 8) Blockers

- roundtrip.profitable_count=0 (market has no arb opportunity currently)
- profit_truth_available=false (requires profitable roundtrip)
- PENDLE/RDNT quoter_v2 failures (slot0 fallback - pending investigation)

## 9) Next Steps

1. Monitor for market conditions with arb opportunity (roundtrip.profitable_count > 0)
2. Investigate PENDLE/RDNT quoter failures (low liquidity or wrong quoter path)
3. When profitable roundtrip appears, profit_truth_available becomes true -> M4 can close
4. Consider 3rd DEX (camelot_v3) for route diversity when Algebra quoter integrated
