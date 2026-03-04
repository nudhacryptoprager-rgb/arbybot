# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## SESSION GOAL + DONE CRITERIA (v3.2.19)
**Goal**: Complete GPT reviewer steps: per-DEX promotion metrics, multi-chain configs, evidence discipline.

### M4.2 TRUTH-PROGRESS CRITERIA (primary - must pass)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 1 | `roundtrip_lp_filter.passed_to_roundtrip` | >= 1 | 4 | ✅ |
| 2 | `roundtrip.evaluated_count` | >= 1 | 4 | ✅ |

### QUALITY/STRETCH CRITERIA (secondary - nice to have)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 3 | `window_chain_key` | != MIXED | MIXED | ❌ |
| 4 | `agg_status` | PASS | PASS | ✅ |
| 5 | `unique_pairs` | >= 8 | 7 | ❌ |

### v3.2.19 CHANGES SUMMARY

**Per-DEX Promotion Metrics (NEW):**
1. **`per_dex_stats` in scan/reject artifacts** - Per-DEX breakdown: quotes_fetched, quotes_rejected, quote_success_rate, top_reject_reasons, health_status (HEALTHY/WARNING/CRITICAL)
2. **Schema tests** - Validates per_dex_stats structure in test_artifact_schema.py

**Multi-Chain Rollout:**
3. **coverage_intent_linea.yaml** - Linea chain with lynex_v3 (Algebra adapter)
4. **coverage_intent_mantle.yaml** - Mantle chain with agni_v3 (Uniswap V3 adapter)

**Evidence Discipline:**
5. **Always generate run_summary for ONLINE PASS** - M4 gate runs for every PASS
6. **Anchor validation per adapter_type** - validate_universe checks quoter/quoter_v2/router per DEX type

**Evidence runs:**
- NORMAL: `ci_m5_gate_20260304_200205` (PASS, signals=2, rolling updated)

**Tests**: 1341 passed, CI pipeline PASS

## 0) Meta
timestamp_utc: 2026-03-04T19:03:41.870653Z
run_id: data/runs/ci_m5_gate_20260304_200205
mode: ONLINE (v3.2.19: per_dex_stats + multi-chain configs)
artifact_mode: rolling
config: config/real_intent_arbitrum_one.yaml (arbitrum_one, run_kind=NORMAL)
code_identity:
  primary: ts:2026-03-04T19:03:41.870653Z
  dirty: false
  desc: v3.2.19 per_dex_stats + multi-chain rollout + evidence discipline

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5 Evidence discipline + per-DEX promotion metrics + multi-chain rollout
change_summary (v3.2.19):
  - ADD: strategy/artifacts.py (_compute_per_dex_stats + per_dex_stats in scan/reject)
  - ADD: config/coverage_intent_linea.yaml (Linea multi-chain)
  - ADD: config/coverage_intent_mantle.yaml (Mantle multi-chain)
  - UPD: scripts/ci_m5_0_gate.py (per_dex_stats in fixture generator)
  - UPD: tests/unit/test_artifact_schema.py (per_dex_stats schema validation)
  - UPD: scripts/validate_universe.py (anchor validation per adapter_type)
  - UPD: scripts/check_repo_safety.py (data_run_rate + agg_status checks)
  - TESTS: 1341 passed
touched_files (v3.2.19):
  - strategy/artifacts.py (per_dex_stats)
  - strategy/jobs/run_scan_real.py (pass quotes to artifact builders)
  - scripts/ci_m5_0_gate.py (fixture per_dex_stats)
  - tests/unit/test_artifact_schema.py (per_dex_stats tests)
  - scripts/validate_universe.py (anchor validation)
  - scripts/check_repo_safety.py (evidence discipline)
  - config/coverage_intent_linea.yaml (NEW)
  - config/coverage_intent_mantle.yaml (NEW)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: 1341 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_intent_arbitrum_one.yaml --refresh-rolling: PASS
py -3.11 scripts/validate_universe.py --config config/coverage_intent_linea.yaml: PASS
py -3.11 scripts/validate_universe.py --config config/coverage_intent_mantle.yaml: PASS
py -3.11 scripts/inspect_rolling.py --json: runs_in_window=42, agg_status=PASS, unique_pairs=7

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json
capstone_run_dir:
  - data/runs/ci_m5_gate_20260304_200205/reports (arbitrum_one, run_kind=NORMAL, v3.2.19)
intent_configs:
  - config/coverage_intent_arbitrum_one.yaml (arbitrum_one + camelot_v3 for testing)
  - config/real_intent_arbitrum_one.yaml (arbitrum_one - no camelot_v3)
  - config/coverage_intent_linea.yaml (NEW - Linea rollout)
  - config/coverage_intent_mantle.yaml (NEW - Mantle rollout)
evidence (NORMAL rolling run v3.2.19):
  - run_dir_name: ci_m5_gate_20260304_200205
  - run_timestamp: 2026-03-04T19:03:41.870653Z
  - spread_signals: 2
  - quotes_fetched: 47
  - unique_pairs: 7
  - runs_in_window: 42
  - agg_status: PASS
  - data_run_rate: 0.7619

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  run_dir_name: ci_m5_gate_20260304_200205
  run_timestamp: 2026-03-04T19:03:41.870653Z
  metrics:
    signals_count: 2
    signals_included: 1
    signals_excluded: 1
    total_net_usdc: 0.9402
  run_context:
    chain_key: arbitrum_one
    config_path: config/real_intent_arbitrum_one.yaml

run_summary_latest.json:
  status: PASS
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  reasons: [WARN_LOW_SAMPLE]
  roundtrip:
    evaluated_count: 4
    profitable_count: 0
    best_net_pnl_bps: -23.04
  per_dex_stats (NEW v3.2.19):
    uniswap_v3: WARNING (30.6% success)
    sushiswap_v3: CRITICAL (15.6% success)
    pancakeswap_v3: WARNING (27.0% success)

m4_stability_agg.json:
  agg_status: PASS
  runs_in_window: 42
  unique_pairs: 7
  unique_routes_cross_dex: 3
  data_run_rate: 0.7619
  total_net_usdc: 113.1414
  window_chain_key: MIXED (arbitrum_one + linea)

## 5) Per-DEX Health (NEW v3.2.19)

| DEX | Fetched | Rejected | Success Rate | Health | Top Reasons |
|-----|---------|----------|--------------|--------|-------------|
| uniswap_v3 | 30 | 68 | 30.6% | WARNING | NOTIONAL_DRIFT, PRICE_SANITY, SUSPECT_LIQUIDITY |
| sushiswap_v3 | 7 | 38 | 15.6% | CRITICAL | SUSPECT_LIQUIDITY, PRICE_SANITY, LIQUIDITY_ZERO |
| pancakeswap_v3 | 10 | 27 | 27.0% | WARNING | PRICE_SANITY, SUSPECT_LIQUIDITY, NOTIONAL_DRIFT |

**Interpretation**: sushiswap_v3 has CRITICAL health (15.6% success). Consider monitoring or removal.

## 6) Roundtrip Analysis

evaluated_count: 4
profitable_count: 0
best_net_pnl_bps: -23.04 (negative = not profitable after gas)

**Interpretation**: No roundtrip opportunities profitable at current gas prices.

## 7) GPT Reviewer Steps (v3.2.19)

| Step | Task | Status |
|------|------|--------|
| 1 | Generate run_summary for ONLINE PASS | ✅ |
| 2 | Add unit tests for run_summary contract | ✅ |
| 3 | Strengthen evidence discipline | ✅ |
| 4 | Remove camelot_v3 from NORMAL config | ✅ |
| 5 | Implement Algebra executable quoting | ❌ Deferred |
| 6 | Extend validate_universe strict anchors | ✅ |
| 7 | Add promotion metrics to artifacts | ✅ |
| 8 | Multi-chain rollout anchors | ✅ |
| 9 | Control run and verify | ✅ |
| 10 | Update docs from actual artifacts | ✅ |

**Completed: 9/10** (Step 5 deferred - multi-day task)

## 8) Multi-Chain Configs (NEW v3.2.19)

| Config | Chain | DEXes | Adapter Type |
|--------|-------|-------|--------------|
| coverage_intent_linea.yaml | Linea (59144) | lynex_v3 | algebra |
| coverage_intent_mantle.yaml | Mantle (5000) | agni_v3 | uniswap_v3 |

## 9) CI Pipeline Status

pytest: 1341 passed, 1 skipped
ci_full_pipeline: ALL REQUIRED GATES PASSED

## 10) Next Steps

1. **Monitor sushiswap_v3** - Consider removal from NORMAL if CRITICAL persists
2. **Algebra quoting (Step 5)** - Implement quoter-based amountOut for camelot_v3
3. **Multi-chain testing** - Run Linea/Mantle configs when RPC available
4. **Roundtrip profitability** - Wait for lower gas or find better spreads

---
*Generated: 2026-03-04T20:02:05Z*
*Evidence: ci_m5_gate_20260304_200205 (arbitrum_one, NORMAL)*

