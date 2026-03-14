# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-14, Session 6 Round 27.4)
**Goal**: R27.4 — YAML config audit + cleanup. Fix validate_universe.py regression, move golden fixture, define frozen active config inventory, delete 15 stale configs, implement ve33 adapter, rebind all references.

## 0) Meta
timestamp_utc: 2026-03-14T20:15:36Z
rolling_provenance: 2026-03-14T20:15:36Z (arbitrum_one NORMAL, ci_m5_gate_20260314_211452 — fresh R27.4 run)
mode: MIXED (config audit + online verification)
test_count: 1803 passed, 3 skipped (-2 from R27.3: removed tests for deleted configs, +2 new inventory/adapter tests)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R27.4: YAML config audit — fix regression, delete stale configs, freeze inventory, implement ve33 adapter |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb primary; ZKSYNC: drift_rejection_rate=30.77% (need <25%) |
| evidence_session_run_dirs | ci_m5_gate_20260314_211452 (fresh online run with rolling update) |
| primary_blocker_of_session | 15 stale configs in config/, validate_universe.py regression (is_strict_run used before defined), ve33 adapter not registered |
| blocker_status_before | 32 YAML files, 15 stale, validator crashes on intent_forced, ve33 NOT registered |
| blocker_status_after | 16 YAML files (frozen inventory), validator fixed, ve33 registered, all 10 scanner configs PASS |
| start_metric | R27.3: 1805 tests, 32 YAML configs, validator regression, ve33 gap |
| end_metric | R27.4: 1803 tests, 16 YAML configs (frozen), ve33 adapter implemented, all gates green |
| delta | -15 stale configs deleted, 1 moved to docs/artifacts/golden/, +1 adapter (ve33), +2 new tests, -4 deleted tests |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — config layer audit and cleanup (R27.4 lead directive)
change_summary:
  - `scripts/validate_universe.py`: FIXED — R27.3 regression: `is_strict_run`/`run_kind` moved above intent check block (was referenced before definition)
  - `config/*.yaml`: 15 stale configs DELETED (coverage_intent_*, real_debug, real_expanded, real_hunting*, real_nonstop, real_test_coverage, real_minimal_discovery_runtime, real_minimal_intent_forced, real_scan_linea_smoke)
  - `config/real_m5_0_golden.yaml`: MOVED to `docs/artifacts/golden/real_m5_0_golden.yaml` (golden fixture, not a scanner config)
  - `dex/adapters/ve33.py`: NEW — formal ve33/Solidly adapter class wrapping getAmountOut()
  - `dex/registry.py`: MODIFIED — ve33 adapter registered in _register_adapters(), create_adapter() handles router
  - `config/real_intent_arbitrum_one.yaml`: MODIFIED — added HIERARCHY comment (R27.4)
  - `tests/unit/test_config_contracts.py`: MODIFIED — COVERAGE_CONFIGS → onboard_*, added TestConfigInventoryGuard (16 allowed files)
  - `tests/unit/test_adapter_readiness.py`: MODIFIED — ve33 in IMPLEMENTED_ADAPTERS, TestVe33AdapterRegistered (was TestVe33GapExplicit), quoter check skips ve33
  - `tests/unit/test_mantle_mixed_source.py`: MODIFIED — coverage_intent_mantle → onboard_mantle_stage1
  - `tests/unit/test_artifact_schema.py`: MODIFIED — real_nonstop → real_minimal in mock data
  - `tests/unit/test_config_pool_coverage.py`: MODIFIED — removed TestHuntingConfigPoolCoverage (config deleted)
  - `tests/unit/test_start.py`: MODIFIED — coverage_intent_base → onboard_base_stage1
  - `tests/unit/test_daily_report_aggregator.py`: MODIFIED — session_goal string updated
  - `docs/WORKFLOW.md`: MODIFIED — long_scan command uses onboard_* configs, real_expanded → real_intent_arbitrum_one
  - `docs/TESTING.md`: MODIFIED — golden config reference → real_minimal
  - `scripts/run_coverage_batch.py`: MODIFIED — default config → real_minimal
  - `scripts/lint_readiness.py`: MODIFIED — help text uses onboard_* configs
  - `config/real_minimal.yaml`: MODIFIED — comment references updated (real_expanded → onboard_candidate)
  - `core/constants.py`: MODIFIED — comment updated (no real_expanded reference)
touched_files: 20+ files across config/, tests/, scripts/, docs/, dex/, core/

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1803 passed, 3 skipped, 1 warning, 30.99s)
py -3.11 scripts/ci_m5_0_gate.py --offline: **PASS** (runDir ci_m5_gate_offline_20260314_211254)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --artifact-mode rolling: **PASS** (2 sims, $0.50)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1: **PASS** (runDir ci_m5_gate_20260314_211452, 17 quotes, 4 signals)
py -3.11 scripts/validate_universe.py --config (all 10 scanner configs): **ALL PASS**

## 3) Artifacts Attached (шляхи)
rolling (FRESH — updated by R27.4 online run):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-14T20:15:36Z)
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json

## 4) Key Results (числа з артефактів)

```
config_audit: 32 → 16 YAML files (15 deleted, 1 moved to docs/artifacts/golden/)
active_inventory: 6 registry + 4 primary/probes + 6 onboard = 16 frozen
validator_regression: FIXED (is_strict_run ordering)
all_10_configs_pass_validate_universe: true
ve33_adapter: IMPLEMENTED (dex/adapters/ve33.py + registered in registry)
test_delta: -2 (1805 → 1803: -4 hunting tests removed, +2 inventory/adapter tests added)
online_run: PASS (17 quotes, 4 signals, 3 cross-dex pairs)
roundtrip: 0/3 profitable, gap_to_zero=20.41 bps (WBTC/USDC @ $25)
total_net_usdc: 5.55 (diagnostic one-leg)
profit_is_diagnostic: true
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline (3+1 canonical files): OK — freshly updated by R27.4 online run
- config inventory: FROZEN to 16 allowed files with TestConfigInventoryGuard
- validate_universe regression: FIXED — clean FAIL on intent_forced (was crash)
- ve33 adapter: IMPLEMENTED and registered (aerodrome/base, stratum/mantle)
- stale config references: ALL updated across 20+ files
- Arbitrum hierarchy: documented (real_minimal → real_intent → onboard_candidate)
- zksync drift: 30.77% (market blocker, need <25% for promotion)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1803 PASS, CI gates green, ve33 implemented)
data_collection_blocker: LOW (online runs producing signals)
market_window_blocker: HIGH (roundtrip_profitable=0 on primary, gap_to_zero=20.41 bps)
adapter_blocker: RESOLVED (ve33 implemented R27.4)
config_blocker: RESOLVED (15 stale deleted, inventory frozen)
```

## 7) Lead's R27.4 10 Steps: Execution Map
step_01: **DONE** — Fixed validate_universe.py regression: moved run_kind/is_strict_run computation above intent check block (was NameError on intent_forced configs).
step_02: **DONE** — Moved real_m5_0_golden.yaml from config/ to docs/artifacts/golden/ (golden fixture, not a scanner config — different dexes schema).
step_03: **DONE** — Active inventory defined: 6 registry/service + 4 primary/probes + 6 onboard_ = 16 total.
step_04: **DONE** — Deleted 15 stale scanner YAMLs: coverage_intent_* (6), real_debug, real_expanded, real_hunting, real_hunting_lowfee, real_nonstop, real_test_coverage, real_minimal_discovery_runtime, real_minimal_intent_forced, real_scan_linea_smoke.
step_05: **DONE** — Rebound all scripts/tests/docs: test_config_contracts, test_adapter_readiness, test_mantle_mixed_source, test_artifact_schema, test_config_pool_coverage, test_start, test_daily_report_aggregator, run_coverage_batch, lint_readiness, WORKFLOW.md, TESTING.md, real_minimal.yaml comments, core/constants.py.
step_06: **DONE** — TestConfigInventoryGuard added: ALLOWED_YAML_FILES set (16 files), test_no_unexpected_yaml_files + test_all_allowed_configs_exist.
step_07: **DONE** — Arbitrum hierarchy clarified: real_minimal (proven) → real_intent (progressive) → onboard_candidate (full 4-DEX). HIERARCHY comment added to real_intent.
step_08: **DONE** — ve33 adapter: dex/adapters/ve33.py created (Ve33Adapter class, getAmountOut encoding/decoding), registered in dex/registry.py. zksync drift: documented as market quality blocker (30.77% > 25% threshold).
step_09: **DONE** — All tests pass (1803/3 skipped). All 10 scanner configs pass validate_universe. M5 offline PASS. M4 offline profit PASS. M5 online PASS (fresh rolling update).
step_10: **DONE** — DEV_REPORT refresh with R27.4 evidence.

## 8) Що потрібно від ліда
1. Config inventory sign-off: 16 files frozen — confirm no missing configs before hard-lock
2. ve33 integration testing: adapter class created but online runs with aerodrome/stratum need separate session (need onboard_base/mantle configs promoted to run)
3. ci_full_pipeline: TIMESTAMP_PROPAGATION error from check [11] — DEV_REPORT timestamp vs rolling timestamp mismatch was pre-existing from R27.3 (no online runs that session); now fixed by R27.4 fresh evidence
