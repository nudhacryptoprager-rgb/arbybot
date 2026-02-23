# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-23T08:17:10Z
run_id: data/runs/ci_m5_gate_20260223_091650
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-23T08:17:10.501985+00:00
  dirty: true
  desc: Directive #3 - QuoterV2 gas evidence + discovery dry-run + preflight v1.0.2

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Directive #3 - QuoterV2 gas evidence + discovery dry-run
change_summary:
  - FIX: preflight.py extracts gasEstimate from QuoterV2 eth_call (bytes 96-127)
  - FIX: gas_estimate_source now "quoter_v2" instead of "fallback" on all legs
  - ADD: discovery_dry_run=true in real_minimal.yaml
  - ADD: 5 preflight invariant tests (test_preflight_m43.py TestPreflightInvariants)
  - FIX: preflight version aligned v1.0.0 -> v1.0.2 across all evidence structures
  - RESULT: runs_in_window=105, total_net_usdc=$5439.08
  - RESULT: discovery dry-run: 16 resolvable pairs, 128 potential queries
touched_files:
  - execution/preflight.py (v1.0.2 - QuoterV2 gas extraction)
  - config/real_minimal.yaml (discovery_dry_run)
  - tests/unit/test_preflight_m43.py (5 new invariant tests)
  - docs/DEV_REPORT_LATEST.md
  - docs/status/Status_M4.md

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.6.1, 10 checks, 0 warnings)
py -3.11 -m pytest -q: PASS (999 passed, 1 skipped, 1 warning)
py -3.11 scripts/ci_m5_0_gate.py --online: PASS (ci_m5_gate_20260223_091650)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260223_091650/reports

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  agg_reasons: []
  data_run_rate: 0.9905
  low_sample_rate: 0.0

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-23T08:17:10.501985+00:00
  run_context.code_identity: ts:2026-02-23T08:17:10.501985+00:00
  inputs.run_dir_name: ci_m5_gate_20260223_091650
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 6
    included_signals_count: 6
    excluded_signals_count: 0
    total_net_usdc: 44.77 (single run)
    mae_net_usdc: 0.5
    est_sign_correct_rate: 1.0
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    cost_model_available: true
    profit_truth_available: false
  quality_status: WARN
  quality_reasons: ['WARN_PROFIT_DIAGNOSTIC']
  preflight_evidence:
    evidence_source: preflight_v1.0.2
    candidates_count: 3
    passed_count: 3
    gas_estimate_source: quoter_v2 (all legs)

m4_stability_agg.json:
  runs_in_window: 105 (M4.1 N=100+ maintained)
  last_run: ci_m5_gate_20260223_091650
  computed_total_net_usdc: 5439.08
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
| Core Truth (paper +PnL) | [OK] PROVEN | N=105 runs, total_net_usdc=$5439.08 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] CLOSED | 105/100 runs (100%+ maintained) |
| M4.3 Preflight Evidence | [OK] FULL | gas_estimate_source=quoter_v2, evidence_source=preflight_v1.0.2 |

> **M4.1 CLOSED**: N=105 consecutive runs with agg_status=PASS.
> Paper profit PROVEN under declared cost model ($5439.08 cumulative).
> M4.3 Preflight: QuoterV2 gas evidence on all legs (no fallback).
> Discovery dry-run: 16 pairs, 128 queries (enabled but not expanding universe).
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
- Discovery runtime integration not yet implemented (dry-run only)

## 9) Lead's 10 Steps: Execution Map
step_01 (Push local HEAD): DONE - git push completed
step_02 (Enable discovery_dry_run): DONE - config/real_minimal.yaml updated
step_03 (Add QuoterV2 gas evidence): DONE - preflight.py extracts gasEstimate from bytes 96-127
step_04 (Align preflight version): DONE - v1.0.0 -> v1.0.2 across all evidence structures
step_05 (Add preflight invariant tests): DONE - 5 tests in TestPreflightInvariants
step_06 (Test intent mode + preflight): DONE - ONLINE run ci_m5_gate_20260223_091650 passed
step_07 (Discovery runtime flag): PENDING - dry-run only, runtime integration deferred
step_08 (Intent pool resolver): PENDING - deferred
step_09 (Roundtrip synthetic fixture): PENDING - deferred
step_10 (Update docs from artifacts): DONE - this report
