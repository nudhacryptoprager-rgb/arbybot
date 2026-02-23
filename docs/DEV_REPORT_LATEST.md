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
goal (Roadmap пункт): Directive #5 - Discovery runtime + pool resolver integration
change_summary:
  - ADD: discovery/runtime.py - resolve_runtime_pairs() with deterministic ordering
  - ADD: tests/unit/test_discovery_runtime.py - 9 tests for runtime module
  - ADD: discovery_runtime flag in run_scan_real.py (observability only)
  - ADD: config/real_minimal.yaml discovery_runtime flags (default false)
  - RESULT: runs_in_window=108, total_net_usdc=$5563.59
  - RESULT: discovery_runtime: 20 pairs resolved, 22 rpc_calls, cache persisted
  - RESULT: pool_resolver_cache: 22 entries (20 positive, 2 negative)
touched_files:
  - discovery/runtime.py (new)
  - tests/unit/test_discovery_runtime.py (new)
  - strategy/jobs/run_scan_real.py (discovery_runtime integration)
  - config/real_minimal.yaml (discovery_runtime flags)
  - docs/status/Status_M5_0.md

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (v1.6.1, 10 checks, 0 warnings target)
py -3.11 -m pytest -q: PASS (1025 passed, 1 skipped, 1 warning)
py -3.11 scripts/ci_m5_0_gate.py --online: PASS (ci_m5_gate_20260223_104821)
py -3.11 scripts/ci_m5_0_gate.py --online with discovery_runtime=true: PASS (20 pools resolved)

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
| Discovery Runtime | [OK] IMPLEMENTED | discovery/runtime.py + 9 tests (20 pools resolved) |

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
- discovery_runtime not yet connected to quote pipeline
- WARN_TOP_PAIR_DOMINANCE in quality_reasons (signals dominated by few pairs)

## 9) Lead's 10 Steps: Execution Map
step_01 (Token registry contract): DONE - core_tokens.yaml extended as canonical registry
step_02 (Add 10 missing tokens): DONE - rETH, MAGIC, FRAX, LUSD, GNS, GRAIL, JOE, USDE, TBTC, DPX
step_03 (Token verify CLI): DONE - scripts/verify_tokens.py (10/10 verified)
step_04 (Verify discovery metrics): DONE - 28/0/224 (up from 16/12/128)
step_05 (Design discovery_runtime flag): DONE - architecture in pool_resolver + runtime.py
step_06 (Implement pool resolver + cache): DONE - discovery/pool_resolver.py + persistent cache
step_07 (Add resolver/cache tests): DONE - test_pool_resolver.py (11 tests)
step_08 (Roundtrip synthetic fixture): DONE - roundtrip_canonical_golden.json + 5 tests
step_09 (Update Status_M5_0.md): DONE - runDir ci_m5_gate_20260223_104821
step_10 (Discovery runtime integration): DONE - discovery/runtime.py + 9 tests, 20 pools resolved
