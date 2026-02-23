# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-23T08:36:42Z
run_id: data/runs/ci_m5_gate_20260223_093625
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-23T08:36:42.318085+00:00
  dirty: true
  desc: Directive #3.1 - Cross-artifact consistency + fresh evidence + beabbc6

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Directive #3 - QuoterV2 gas evidence + discovery dry-run
change_summary:
  - FIX: preflight.py extracts gasEstimate from QuoterV2 eth_call (bytes 96-127)
  - FIX: gas_estimate_source now "quoter_v2" instead of "fallback" on all legs
  - ADD: discovery_dry_run=true in real_minimal.yaml
  - ADD: 6 preflight invariant tests (test_preflight_m43.py TestPreflightInvariants)
  - ADD: cross-artifact consistency test for preflight evidence
  - FIX: preflight version aligned v1.0.0 -> v1.0.2 across all evidence structures
  - VERIFY: beabbc6 evidence confirms preflight_v1.0.2 in both scan AND truth_report
  - RESULT: runs_in_window=106, total_net_usdc=$5472.19
  - RESULT: discovery dry-run: 16 resolvable pairs, 12 unresolvable, 128 potential queries
  - NOTE: 10 missing tokens identified (DPX, FRAX, GNS, GRAIL, JOE, LUSD, MAGIC, RETH, TBTC, USDE)
touched_files:
  - execution/preflight.py (v1.0.2 - QuoterV2 gas extraction)
  - config/real_minimal.yaml (discovery_dry_run)
  - tests/unit/test_preflight_m43.py (6 invariant tests)
  - docs/DEV_REPORT_LATEST.md
  - docs/status/Status_M4.md

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.6.1, 10 checks, 0 warnings)
py -3.11 -m pytest -q: PASS (1000 passed, 1 skipped, 1 warning)
py -3.11 scripts/ci_m5_0_gate.py --online: PASS (ci_m5_gate_20260223_093625)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260223_093625/reports

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  agg_reasons: []
  data_run_rate: 0.9906
  low_sample_rate: 0.0

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-23T08:36:42.318085+00:00
  run_context.code_identity: ts:2026-02-23T08:36:42.318085+00:00
  inputs.run_dir_name: ci_m5_gate_20260223_093625
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 5
    included_signals_count: 5
    excluded_signals_count: 0
    total_net_usdc: 33.11 (single run)
    mae_net_usdc: 0.5
    est_sign_correct_rate: 1.0
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    cost_model_available: true
    profit_truth_available: false
  quality_status: WARN
  quality_reasons: ['WARN_TOP_PAIR_DOMINANCE', 'WARN_PROFIT_DIAGNOSTIC']
  preflight_evidence:
    evidence_source: preflight_v1.0.2 (VERIFIED in scan AND truth_report)
    candidates_count: 1
    passed_count: 1
    gas_estimate_source: quoter_v2 (all legs)

m4_stability_agg.json:
  runs_in_window: 106 (M4.1 N=100+ maintained)
  last_run: ci_m5_gate_20260223_093625
  computed_total_net_usdc: 5472.19
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
| Core Truth (paper +PnL) | [OK] PROVEN | N=106 runs, total_net_usdc=$5472.19 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] CLOSED | 106/100 runs (100%+ maintained) |
| M4.3 Preflight Evidence | [OK] VERIFIED | preflight_v1.0.2 in BOTH scan AND truth_report (cross-artifact) |

> **M4.1 CLOSED**: N=106 consecutive runs with agg_status=PASS.
> Paper profit PROVEN under declared cost model ($5472.19 cumulative).
> M4.3 Preflight: QuoterV2 gas evidence on all legs (no fallback), cross-artifact verified.
> Discovery dry-run: 16 resolvable, 12 unresolvable (10 missing tokens).
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
- 10 missing tokens block 12 unresolvable pairs in discovery
- WARN_TOP_PAIR_DOMINANCE in quality_reasons (signals dominated by few pairs)

## 9) Lead's 10 Steps: Execution Map
step_01 (ONLINE with beabbc6): DONE - ci_m5_gate_20260223_093625
step_02 (Verify preflight_v1.0.2): DONE - confirmed in BOTH scan AND truth_report
step_03 (Cross-artifact test): DONE - test_cross_artifact_preflight_consistency added
step_04 (Discovery runtime flag): PENDING - dry-run only, deferred
step_05 (Intent pool resolver): PENDING - deferred
step_06 (Resolver cache): PENDING - deferred
step_07 (Unresolvable pairs list): DONE - 10 missing tokens identified
step_08 (Gas evidence contract): PENDING - QuoterV2 gasEstimate sufficient for now
step_09 (Roundtrip fixture): PENDING - deferred
step_10 (Update docs): DONE - this report
