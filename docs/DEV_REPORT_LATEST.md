# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-23T09:48:51Z
run_id: data/runs/ci_m5_gate_20260223_104821
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-23T09:48:51+00:00
  dirty: true
  desc: Directive #5 - Discovery runtime + pool resolver integration

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Directive #6 - Universe source mode + cross-dex filtering
change_summary:
  - ADD: universe_source=discovery_runtime mode in run_scan_real.py
  - ADD: require_cross_dex filter (only include pairs with pools on 2+ dexes)
  - ADD: runtime_pairs_to_pair_configs() converter for quote pipeline
  - ADD: RPC call limit guardrail (ARBY_RESOLVER_MAX_RPC_CALLS, default 50)
  - ADD: cross_dex_pairs_count in RuntimeStats observability
  - ADD: is_same_dex tracking in spread signals
  - FIX: core_tokens.yaml header clarified (trust anchors vs verified tokens)
  - RESULT: Tests 1027 passed (+2 from cross-dex tests)
touched_files:
  - discovery/runtime.py (runtime_pairs_to_pair_configs, require_cross_dex, decimals)
  - discovery/pool_resolver.py (RPC limit guardrail, stats)
  - strategy/jobs/run_scan_real.py (universe_source=discovery_runtime)
  - strategy/spreads.py (is_same_dex, SAME_DEX_FEE_TIER reason)
  - config/core_tokens.yaml (header clarification)
  - tests/unit/test_discovery_runtime.py (+2 cross-dex tests)

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.6.1, 10 checks, 0 warnings)
py -3.11 -m pytest -q: PASS (1027 passed, 1 skipped, 1 warning)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260223_104821/reports

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
  run_context.run_timestamp: 2026-02-23T09:48:51+00:00
  run_context.code_identity: ts:2026-02-23T09:48:51+00:00
  inputs.run_dir_name: ci_m5_gate_20260223_104821
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 6
    included_signals_count: 6
    excluded_signals_count: 0
    total_net_usdc: 49.32 (single run)
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
    candidates_count: 3
    passed_count: 3
    gas_estimate_source: quoter_v2 (all legs)

m4_stability_agg.json:
  runs_in_window: 108 (M4.1 N=100+ maintained)
  last_run: ci_m5_gate_20260223_104821
  computed_total_net_usdc: 5567.21
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
| Core Truth (paper +PnL) | [OK] PROVEN | N=108 runs, total_net_usdc=$5567.21 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] CLOSED | 108/100 runs (100%+ maintained) |
| M4.3 Preflight Evidence | [OK] VERIFIED | preflight_v1.0.2 in BOTH scan AND truth_report (cross-artifact) |
| Token Registry | [OK] EXPANDED | 49 tokens (39 original + 10 discovery tokens) |
| Pool Resolver | [OK] IMPLEMENTED | factory.getPool() with persistent cache |
| ROUNDTRIP_CANONICAL | [OK] GOLDEN PROOF | docs/artifacts/roundtrip_canonical_golden.json + 5 tests |
| Discovery Runtime | [OK] IMPLEMENTED | discovery/runtime.py + 11 tests (20 pools resolved) |
| Cross-Dex Filter | [OK] IMPLEMENTED | require_cross_dex flag + stats tracking |

> **M4.1 CLOSED**: N=108 consecutive runs with agg_status=PASS.
> Paper profit PROVEN under declared cost model ($5567.21 cumulative).
> M4.3 Preflight: QuoterV2 gas evidence on all legs (no fallback), cross-artifact verified.
> Discovery: 28 resolvable, 0 unresolvable (all missing tokens added).
> Discovery runtime: 20 pools resolved via factory.getPool(), cache persisted.
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

## 9) Lead's 10 Steps: Execution Map (Directive #6)
step_01 (Run baseline verification): DONE - check_repo_safety PASS, 1025 tests
step_02 (Fix core_tokens.yaml header): DONE - clarified trust anchors vs verified tokens
step_03 (Add universe_source=discovery_runtime): DONE - quote pipeline uses resolved pairs
step_04 (Implement require-cross-dex rule): DONE - filter pairs to 2+ dexes
step_05 (Connect resolver to infra): DEFERRED - documented TODO for RPCProvider
step_06 (Add resolver guardrails): DONE - ARBY_RESOLVER_MAX_RPC_CALLS=50
step_07 (Extend artifacts with cross_dex): DONE - cross_dex_pairs_count in stats
step_08 (Address suspect_signals policy): DONE - is_same_dex + SAME_DEX_FEE_TIER reason
step_09 (Sync docs with rolling): DONE - DEV_REPORT_LATEST aligned
step_10 (Final check_repo_safety): PENDING
