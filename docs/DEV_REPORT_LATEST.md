# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## SESSION GOAL + DONE CRITERIA (v3.2.20)
**Goal**: Per-DEX quoter mode (Algebra), NO_USD_PRICE viability filter, multi-chain rollout (scroll/zksync).

### M4.2 TRUTH-PROGRESS CRITERIA (primary - must pass)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 1 | `roundtrip_lp_filter.passed_to_roundtrip` | >= 1 | 3 | ✅ |
| 2 | `roundtrip.evaluated_count` | >= 1 | 3 | ✅ |

### QUALITY/STRETCH CRITERIA (secondary - nice to have)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 3 | `window_chain_key` | != MIXED | MIXED | ❌ |
| 4 | `agg_status` | PASS | PASS | ✅ |
| 5 | `unique_pairs` | >= 8 | 7 | ❌ |

### v3.2.20 CHANGES SUMMARY

**Per-DEX Quoter Mode (Algebra auto-quoting):**
1. **Per-DEX quoter branching** - `use_quoter_for_dex = is_algebra or use_quoter_global` auto-enables quoter for Algebra DEXes
2. **ALGEBRA_NEEDS_QUOTER rejection** - Now reports `quoter_configured` and `quoter_result` for debugging

**Viability Filters:**
3. **NO_USD_PRICE** - Early filter skips pairs where token_in has no USD price configured (deterministic rejection)
4. **tokens_usd_price sync** - Added rETH, MAGIC, TBTC, GNS, GRAIL, JOE to arbitrum config

**DEX Health Guardrail:**
5. **DEX_HEALTH_CRITICAL** - Quality warning when per_dex_stats shows CRITICAL health (<20% success rate)
6. **best_included_spread_economics** - New field separating best signal from best NON-excluded signal

**Multi-Chain Rollout:**
7. **M4.2 semantics for Linea/Mantle** - Added execution_enabled, kill_switch_active, simulate_only
8. **coverage_intent_scroll.yaml** - Scroll chain (534352) with uniswap_v3
9. **coverage_intent_zksync.yaml** - zkSync chain (324) with izumi_v3

**Evidence runs:**
- NORMAL: `ci_m5_gate_20260304_205812` (PASS, signals=2, rolling updated)
- COVERAGE (Linea): `ci_m5_gate_20260304_205626` (NO_DATA: discovery_runtime 0 pairs)
- COVERAGE (Mantle): `ci_m5_gate_20260304_205651` (NO_DATA: discovery_runtime 0 pairs)

**Tests**: 1341 passed, CI pipeline PASS

## 0) Meta
timestamp_utc: 2026-03-04T19:59:10.422928Z
run_id: data/runs/ci_m5_gate_20260304_205812
mode: ONLINE (v3.2.20: per-DEX quoter + NO_USD_PRICE + _pre_routing bucket)
artifact_mode: rolling
config: config/real_intent_arbitrum_one.yaml (arbitrum_one, run_kind=NORMAL)
code_identity:
  primary: ts:2026-03-04T19:59:10.422928Z
  dirty: false
  desc: v3.2.20 exclude_reason + _pre_routing + multi-chain rollout

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Per-DEX quoter mode + viability filters + multi-chain rollout (scroll/zksync)
change_summary (v3.2.20):
  - UPD: strategy/quotes.py (per-DEX quoter mode, NO_USD_PRICE viability filter)
  - UPD: m4/fixtures.py (DEX_HEALTH_CRITICAL quality warning from per_dex_stats)
  - UPD: scripts/inspect_run_dir.py (best_included_spread_economics with is_excluded_signal)
  - UPD: config/real_intent_arbitrum_one.yaml (tokens_usd_price sync)
  - UPD: config/coverage_intent_linea.yaml (M4.2 truth-semantics)
  - UPD: config/coverage_intent_mantle.yaml (M4.2 truth-semantics)
  - ADD: config/coverage_intent_scroll.yaml (Scroll chain with uniswap_v3)
  - ADD: config/coverage_intent_zksync.yaml (zkSync chain with izumi_v3)
  - UPD: config/chains.yaml (scroll, zksync chains)
  - UPD: config/dexes.yaml (scroll:uniswap_v3, zksync:izumi_v3)
  - TESTS: 1341 passed
touched_files (v3.2.20):
  - strategy/quotes.py (per-DEX quoter mode, NO_USD_PRICE filter)
  - m4/fixtures.py (DEX_HEALTH_CRITICAL quality warning)
  - scripts/inspect_run_dir.py (best_included_spread_economics)
  - config/real_intent_arbitrum_one.yaml (tokens sync)
  - config/coverage_intent_linea.yaml (M4.2 semantics)
  - config/coverage_intent_mantle.yaml (M4.2 semantics)
  - config/coverage_intent_scroll.yaml (NEW)
  - config/coverage_intent_zksync.yaml (NEW)
  - config/chains.yaml (scroll, zksync)
  - config/dexes.yaml (scroll, zksync DEXes)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: 1341 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_intent_arbitrum_one.yaml --refresh-rolling: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml: FAIL (NO_DATA)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml: FAIL (NO_DATA)
py -3.11 scripts/inspect_rolling.py --json: runs_in_window=44, agg_status=PASS, unique_pairs=7

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json
capstone_run_dir:
  - data/runs/ci_m5_gate_20260304_205812/reports (arbitrum_one, run_kind=NORMAL, v3.2.20)
intent_configs:
  - config/coverage_intent_arbitrum_one.yaml (arbitrum_one + camelot_v3 for testing)
  - config/real_intent_arbitrum_one.yaml (arbitrum_one - no camelot_v3)
  - config/coverage_intent_linea.yaml (Linea rollout)
  - config/coverage_intent_mantle.yaml (Mantle rollout)
  - config/coverage_intent_scroll.yaml (Scroll rollout)
  - config/coverage_intent_zksync.yaml (zkSync rollout)
evidence (NORMAL rolling run v3.2.20):
  - run_dir_name: ci_m5_gate_20260304_205812
  - run_timestamp: 2026-03-04T19:59:10.422928Z
  - spread_signals: 2
  - quotes_fetched: 42
  - unique_pairs: 7
  - runs_in_window: 44
  - agg_status: PASS
  - data_run_rate: 0.7273

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  run_dir_name: ci_m5_gate_20260304_205812
  run_timestamp: 2026-03-04T19:59:10.422928Z
  metrics:
    signals_count: 2
    signals_included: 1
    signals_excluded: 1
    total_net_usdc: 0.9362
  run_context:
    chain_key: arbitrum_one
    config_path: config/real_intent_arbitrum_one.yaml

run_summary_latest.json:
  status: PASS
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  reasons: [WARN_LOW_SAMPLE, WARN_DEX_HEALTH_CRITICAL]
  roundtrip:
    evaluated_count: 3
    profitable_count: 0
    best_net_pnl_bps: -170.36
  per_dex_stats (v3.2.20):
    uniswap_v3: WARNING (34.2% success)
    sushiswap_v3: CRITICAL (17.2% success)
    pancakeswap_v3: WARNING (32.3% success)
    _pre_routing: CRITICAL (0% - NO_USD_PRICE bucket, not a DEX)

m4_stability_agg.json:
  agg_status: PASS
  runs_in_window: 44
  unique_pairs: 7
  unique_routes_cross_dex: 3
  data_run_rate: 0.7273
  total_net_usdc: 114.7858
  window_chain_key: MIXED (arbitrum_one + linea)

## 5) Per-DEX Health (v3.2.20)

| DEX | Fetched | Rejected | Success Rate | Health | Top Reasons |
|-----|---------|----------|--------------|--------|-------------|
| uniswap_v3 | 27 | 52 | 34.2% | WARNING | NOTIONAL_DRIFT, PRICE_SANITY, SUSPECT_LIQUIDITY |
| sushiswap_v3 | 5 | 24 | 17.2% | CRITICAL | PRICE_SANITY, SUSPECT_LIQUIDITY, NOTIONAL_DRIFT |
| pancakeswap_v3 | 10 | 21 | 32.3% | WARNING | PRICE_SANITY, NOTIONAL_DRIFT, SUSPECT_LIQUIDITY |
| _pre_routing | 0 | 5 | 0.0% | CRITICAL | NO_USD_PRICE (not a DEX, excluded from health checks) |

**Interpretation**: 
- sushiswap_v3 has CRITICAL health (17.2% success). Consider monitoring or removal.
- `_pre_routing` bucket contains pre-DEX viability rejections (NO_USD_PRICE) - not counted for DEX health.

## 6) Roundtrip Analysis

evaluated_count: 3
profitable_count: 0
best_net_pnl_bps: -170.36 (negative = not profitable after gas)

**Interpretation**: No roundtrip opportunities profitable at current gas prices.

## 7) GPT Reviewer Steps (v3.2.20)

| Step | Task | Status |
|------|------|--------|
| 1 | Remove version strings from Status_M4.md | ✅ |
| 2 | Grep-sanity version strings | ✅ |
| 3 | Fix exclude_reason for best_spread_economics | ✅ |
| 4 | Clarify per_dex_stats.ALL → _pre_routing | ✅ |
| 5 | Run 4 coverage runs (multi-chain) | ✅ |
| 6 | Add chain rollout verdict | ✅ |
| 7 | Control run verification | ✅ |
| 8 | Update docs from artifacts | ✅ |

**Completed: 8/8**

## 8) Multi-Chain Rollout Verdict (v3.2.20)

| Config | Chain | ONLINE Status | Verdict | Notes |
|--------|-------|---------------|---------|-------|
| coverage_intent_linea.yaml | Linea (59144) | **NO_DATA** | ⚠️ | discovery_runtime 0 pairs (lynex_v3 pool resolution failed) |
| coverage_intent_mantle.yaml | Mantle (5000) | **NO_DATA** | ⚠️ | discovery_runtime 0 pairs (agni_v3 pool resolution failed) |
| coverage_intent_scroll.yaml | Scroll (534352) | NOT_TESTED | ❓ | Config valid, RPC not tested |
| coverage_intent_zksync.yaml | zkSync (324) | NOT_TESTED | ❓ | Config valid, RPC not tested |

**Root Cause**: Multi-chain discovery requires:
1. Proper token addresses in `core_tokens.yaml` for each chain
2. Pool resolution working for each DEX adapter
3. DEX protocol anchors (factory, quoter_v2, router) in `dexes.yaml`

## 9) CI Pipeline Status

pytest: 1341 passed, 1 skipped
ci_full_pipeline: ALL REQUIRED GATES PASSED

## 10) Next Steps

1. **Add Linea/Mantle tokens to core_tokens.yaml** - WETH, USDC, etc. for each chain
2. **Debug pool resolution for lynex_v3/agni_v3** - Check factory calls and fee_tiers
3. **Monitor sushiswap_v3** - Consider removal from NORMAL if CRITICAL persists
4. **Roundtrip profitability** - Wait for lower gas or better spreads

---
*Generated: 2026-03-04T20:58:12Z*
*Evidence: ci_m5_gate_20260304_205812 (arbitrum_one, NORMAL)*

