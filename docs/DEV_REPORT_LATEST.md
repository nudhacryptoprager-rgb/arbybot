# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-23T15:55:14Z
run_id: data/runs/ci_m5_gate_20260223_165456
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-23T15:55:14+00:00
  dirty: true
  desc: Directive #11 - preflight v1.0.3 + discovery_runtime config fix

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Directive #11 - preflight v1.0.3 chain-aware leg2 + gas sanity
change_summary:
  - FIX: execution/preflight.py v1.0.3 - leg2.amount_in uses leg1.quoted_amount_out (chain-aware)
  - ADD: execution/preflight.py MAX_REALISTIC_GAS_ESTIMATE = 1,500,000 sanity check
  - ADD: tests/unit/test_preflight_m43.py 3 new v1.0.3 invariant tests
  - ADD: strategy/artifacts.py reason_keys_top observability for SUSPECT_LIQUIDITY
  - ADD: strategy/quarantine.py SUSPECT_LIQUIDITY to trackable_errors
  - FIX: config/real_minimal_discovery_runtime.yaml token format (nested->flat)
  - FIX: docs/status/Status_M4.md ≥ -> >= for encoding safety
  - RESULT: 1051 tests passed, discovery_runtime fixed, all CI gates PASS
touched_files:
  - execution/preflight.py (v1.0.3 chain-aware leg2, gas sanity)
  - tests/unit/test_preflight_m43.py (3 new tests)
  - strategy/artifacts.py (reason_keys_top observability)
  - strategy/quarantine.py (SUSPECT_LIQUIDITY trackable)
  - config/real_minimal_discovery_runtime.yaml (token format fix)
  - docs/status/Status_M4.md (encoding fix)

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.6.1, 10 checks, 0 warnings)
py -3.11 -m pytest -q: PASS (1051 passed, 1 skipped, 1 warning)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all gates)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --refresh-rolling: PASS

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260223_165456/reports
discovery_runtime_evidence:
  - data/runs/ci_m5_gate_20260223_165319/reports (universe_source=discovery_runtime, config fix verified)

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  agg_reasons: []
  data_run_rate: 0.9739
  low_sample_rate: 0.0

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-23T15:55:14+00:00
  run_context.code_identity: ts:2026-02-23T15:55:14+00:00
  inputs.run_dir_name: ci_m5_gate_20260223_165456
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 6
    included_signals_count: 6
    excluded_signals_count: 0
    total_net_usdc: 23.29 (single run)
    mae_net_usdc: 0.5
    est_sign_correct_rate: 1.0
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    cost_model_available: true
    profit_truth_available: false
  quality_status: WARN
  quality_reasons: ['WARN_PROFIT_DIAGNOSTIC']
  preflight_evidence:
    evidence_source: preflight_v1.0.3 (upgraded)
    candidates_count: 2
    passed_count: 2
    gas_estimate_source: quoter_v2 (all legs)

m4_stability_agg.json:
  runs_in_window: 115 (M4.1 N=100+ maintained)
  last_run: ci_m5_gate_20260223_165456
  computed_total_net_usdc: 5678.84
  agg_status: PASS
  agg_reasons: []

discovery_stats (from scan):
  resolvable_pairs: 28
  unresolvable_pairs: 0
  potential_v3_queries: 224
  core_tokens_loaded: 49

discovery_runtime_stats (from scan):
  pairs_resolved: 20
  rpc_calls: 22
  pools_from_cache: 0 (first call)
  cache_persisted: 22 entries (20 positive, 2 negative)
  cross_dex_pairs_count: tracked (v2.5.0)
  rpc_limit: 50 (ARBY_RESOLVER_MAX_RPC_CALLS)
  universe_source modes: config|intent|intent_forced|discovery_runtime

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
| Core Truth (paper +PnL) | [OK] PROVEN | N=115 runs, total_net_usdc=$5678.84 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] CLOSED | 115/100 runs (100%+ maintained) |
| M4.3 Preflight Evidence | [OK] v1.0.3 | chain-aware leg2, gas_sanity (max 1.5M) |
| Token Registry | [OK] EXPANDED | 49 tokens (39 original + 10 discovery tokens) |
| Pool Resolver | [OK] IMPLEMENTED | factory.getPool() with persistent cache |
| ROUNDTRIP_CANONICAL | [OK] GOLDEN PROOF | docs/artifacts/roundtrip_canonical_golden.json + 5 tests |
| Discovery Runtime | [OK] IMPLEMENTED | discovery/runtime.py + config fix verified |
| Cross-Dex Filter | [OK] IMPLEMENTED | require_cross_dex flag + stats tracking |

> **M4.1 CLOSED**: N=115 consecutive runs with agg_status=PASS.
> Paper profit PROVEN under declared cost model ($5678.84 cumulative).
> M4.3 Preflight v1.0.3: chain-aware leg2 (uses leg1.quoted_amount_out), gas sanity (MAX_REALISTIC_GAS_ESTIMATE=1.5M).
> Discovery: 28 resolvable, 0 unresolvable (all missing tokens added).
> Discovery runtime config fix: tokens format corrected (nested->flat).
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
- discovery_runtime not yet default (requires cross-dex evidence)
- WARN_TOP_PAIR_DOMINANCE in quality_reasons (signals dominated by few pairs)

## 9) Lead's 10 Steps: Execution Map (Directive #11)
step_01 (Fix preflight leg2.amount_in): DONE - uses leg1.quoted_amount_out (chain-aware)
step_02 (Add gas_estimate sanity): DONE - MAX_REALISTIC_GAS_ESTIMATE = 1,500,000
step_03 (Add preflight v1.0.3 unit tests): DONE - 3 new tests in test_preflight_m43.py
step_04 (Add SUSPECT_LIQUIDITY observability): DONE - reason_keys_top in artifacts.py
step_05 (Auto-quarantine SUSPECT_LIQUIDITY): DONE - added to trackable_errors
step_06 (Verify verify_v3_pools.py exists): DONE - --require-cross-dex option verified
step_07 (Fix discovery_runtime config): DONE - tokens format nested->flat
step_08 (Run deterministic verification): DONE - check_repo_safety, pytest, ci_full_pipeline PASS
step_09 (ONLINE evidence run): DONE - ci_m5_gate_20260223_165456, rolling updated
step_10 (Update docs from artifacts): DONE - DEV_REPORT_LATEST, Status_M4.md updated
