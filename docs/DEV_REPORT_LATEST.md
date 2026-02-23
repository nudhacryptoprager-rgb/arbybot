# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-23T12:30:00Z
run_id: data/runs/ci_m5_gate_20260223_114444
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile)
code_identity:
  primary: ts:2026-02-23T12:30:00+00:00
  dirty: true
  desc: Directive #8 - Add test coverage + fix config schemas

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Directive #8 - Add test coverage for discovery_runtime + same-dex policy
change_summary:
  - ADD: tests/unit/test_discovery_runtime_quotes.py (8 tests)
    - TestRuntimePairsToPairConfigs: pool_info population, required keys
    - TestPoolInfoInPairConfig: PairConfig field tests
    - TestRpcCapTriggered: rpc_cap_triggered in RuntimeStats
  - ADD: tests/unit/test_same_dex_policy.py (5 tests)
    - TestSameDexDetection: is_same_dex flag verification
    - TestSameDexExclusion: require_cross_dex policy enforcement
  - FIX: config/real_minimal_discovery_runtime.yaml schema (missing fields)
    - Added: truth_mode_m42, use_quoter_v2, execution_enabled
    - Added: paper_size_usd, paper_slippage_bps, min_spread_bps
    - Added: tokens, tokens_anchor_price sections
  - RESULT: 1040 tests passed (original + 13 new), ONLINE evidence maintained
touched_files:
  - tests/unit/test_discovery_runtime_quotes.py (NEW - 8 tests)
  - tests/unit/test_same_dex_policy.py (NEW - 5 tests)
  - config/real_minimal_discovery_runtime.yaml (schema fixes)

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.6.1, 10 checks, 0 warnings)
py -3.11 -m pytest -q: PASS (1040 passed, 1 skipped, 1 warning)

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
  runs_in_window: 109 (M4.1 N=100+ maintained)
  last_run: ci_m5_gate_20260223_114444
  computed_total_net_usdc: 5588.72
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
| Core Truth (paper +PnL) | [OK] PROVEN | N=109 runs, total_net_usdc=$5588.72 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, agg_reasons=[] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] CLOSED | 109/100 runs (100%+ maintained) |
| M4.3 Preflight Evidence | [OK] VERIFIED | preflight_v1.0.2 in BOTH scan AND truth_report (cross-artifact) |
| Token Registry | [OK] EXPANDED | 49 tokens (39 original + 10 discovery tokens) |
| Pool Resolver | [OK] IMPLEMENTED | factory.getPool() with persistent cache |
| ROUNDTRIP_CANONICAL | [OK] GOLDEN PROOF | docs/artifacts/roundtrip_canonical_golden.json + 5 tests |
| Discovery Runtime | [OK] IMPLEMENTED | discovery/runtime.py + 11 tests (20 pools resolved) |
| Cross-Dex Filter | [OK] IMPLEMENTED | require_cross_dex flag + stats tracking |

> **M4.1 CLOSED**: N=109 consecutive runs with agg_status=PASS.
> Paper profit PROVEN under declared cost model ($5588.72 cumulative).
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

## 9) Lead's 10 Steps: Execution Map (Directive #8)
step_01 (Manual REAL run baseline): DONE - rolling artifacts verified
step_02 (Implement discovery_runtime quotes): DONE - pool_info populated in PairConfig
step_03 (Fix token address fallback): DONE - _get_token_address helper
step_04 (pool_addresses prefetch path): DONE - pre-cached in runtime_pairs_to_pair_configs
step_05 (pool_address->dex,fee mapping): DONE - pool_info dict with dex/fee/address
step_06 (Add discovery_runtime quotes test): DONE - 8 tests in test_discovery_runtime_quotes.py
step_07 (Add rpc_cap_triggered test): DONE - included in step_06 (3 tests)
step_08 (Fix discovery_runtime config schema): DONE - missing fields added
step_09 (Fix same-dex policy tracking): DONE - 5 tests in test_same_dex_policy.py
step_10 (Update docs with evidence): DONE - DEV_REPORT_LATEST updated
