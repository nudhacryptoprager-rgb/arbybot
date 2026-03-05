# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## SESSION GOAL + DONE CRITERIA (v3.2.28)
**Goal**: M4 online-profit quality - reduce SUSPECT_LIQUIDITY/PRICE_SANITY_FAILED rejections, disable dead pairs.

### M4.2 TRUTH-PROGRESS CRITERIA (primary - must pass)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 1 | `roundtrip_lp_filter.passed_to_roundtrip` | >= 1 | 2 | + |
| 2 | `roundtrip.evaluated_count` | >= 1 | 2 | + |

### QUALITY/STRETCH CRITERIA (secondary - nice to have)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 3 | `window_chain_key` | != MIXED | arbitrum_one | + |
| 4 | `agg_status` | PASS | PASS | + |
| 5 | `unique_pairs` | >= 8 | 13 | + |

### v3.2.28 CHANGES SUMMARY

**Rejection Quality Improvements:**
1. **config/intent.txt** - Disabled dead pairs: RDNT/WETH, RDNT/USDC, MAGIC/WETH, MAGIC/USDC, GRAIL/WETH (collapsed tokens)
2. **config/real_intent_arbitrum_one.yaml** - Evidence-based anchor updates from ci_m5_gate_20260305_151229

**Rejection Analysis (ci_m5_gate_20260305_153431):**
| Reason | Count | Change | Notes |
|--------|-------|--------|-------|
| SUSPECT_LIQUIDITY | 32 | -11 (-26%) | Dead pairs removed |
| PRICE_SANITY_FAILED | 22 | -11 (-33%) | Anchors updated |
| NOTIONAL_DRIFT_EXCLUDED | 1 | -1 | Expected |
| NO_USD_PRICE | 0 | - | Clean |
| Total | 55 | -23 (-30%) | Significant improvement |

**Tests**: 1385 passed, CI pipeline PASS

## 0) Meta
timestamp_utc: 2026-03-05T14:35:30Z
run_id: data/runs/ci_m5_gate_20260305_153431
mode: ONLINE (v3.2.28: rejection quality improvements)
artifact_mode: rolling
config: config/real_intent_arbitrum_one.yaml (arbitrum_one, run_kind=NORMAL)
code_identity:
  primary: ts:2026-03-05T14:35:30Z
  dirty: false
  desc: v3.2.28 rejection quality improvements

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
touched_files (v3.2.28):
  - config/intent.txt (disabled dead pairs: RDNT, MAGIC, GRAIL)
  - config/real_intent_arbitrum_one.yaml (evidence-based anchor updates)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: 1385 passed, 1 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --offline: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_intent_arbitrum_one.yaml --refresh-rolling: PASS
py -3.11 scripts/lint_readiness.py --config config/coverage_intent_scroll.yaml: [N/A] (0 pairs)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json
capstone_run_dir:
  - data/runs/ci_m5_gate_20260305_153431/reports (arbitrum_one, run_kind=NORMAL)
intent_configs:
  - config/coverage_intent_arbitrum_one.yaml (arbitrum_one + camelot_v3 for testing)
  - config/real_intent_arbitrum_one.yaml (arbitrum_one - no duplicate case variants)
  - config/coverage_intent_linea.yaml (Linea rollout)
  - config/coverage_intent_mantle.yaml (Mantle rollout)
  - config/coverage_intent_scroll.yaml (Scroll rollout)
  - config/coverage_intent_zksync.yaml (zkSync rollout)
evidence (NORMAL rolling run):
  - run_dir_name: ci_m5_gate_20260305_153431
  - run_timestamp: 2026-03-05T14:35:30Z
  - spread_signals: 17
  - quotes_fetched: 49
  - unique_pairs: 13
  - runs_in_window: 57
  - agg_status: PASS
  - quality_warnings: [EXCLUDED_PRESENT, CRITICAL_REJECT, PROFIT_DIAGNOSTIC]

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  run_dir_name: ci_m5_gate_20260305_153431
  run_timestamp: 2026-03-05T14:35:30Z
  run_quality_status: WARN
  run_quality_warnings:
    - EXCLUDED_PRESENT(2)
    - CRITICAL_REJECT(PRICE_SANITY_FAILED:22)
    - PROFIT_DIAGNOSTIC
  metrics:
    signals_count: 17
    signals_included: 15
    signals_excluded: 2
    total_net_usdc: ~50
  run_context:
    chain_key: arbitrum_one
    config_path: config/real_intent_arbitrum_one.yaml
  rolling:
    runs_in_window: 57
    quality_warnings: []

run_summary_latest.json:
  status: PASS
  profit_status: PASS
  drift_status: PASS  
  quality_status: WARN
  reasons: [WARN_EXCLUDED_SIGNALS, WARN_CRITICAL_REJECTS, WARN_PROFIT_DIAGNOSTIC]
  roundtrip:
    evaluated_count: 2
    profitable_count: 0
  rejection_summary:
    SUSPECT_LIQUIDITY: 32      # -26% (dead pairs removed)
    PRICE_SANITY_FAILED: 22    # -33% (anchors updated)
    NOTIONAL_DRIFT_EXCLUDED: 1 # Expected
    NO_USD_PRICE: 0            # Clean
    Total: 55                  # -30% improvement

m4_stability_agg.json:
  agg_status: PASS
  runs_in_window: 57
  unique_pairs: 13
  window_chain_key: arbitrum_one
  quality_warnings: []

## 5) Per-DEX Health

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
| 1 | Remove version strings from Status_M4.md | + |
| 2 | Grep-sanity version strings | + |
| 3 | Fix exclude_reason for best_spread_economics | + |
| 4 | Clarify per_dex_stats.ALL -> _pre_routing | + |
| 5 | Run 4 coverage runs (multi-chain) | + |
| 6 | Add chain rollout verdict | + |
| 7 | Control run verification | + |
| 8 | Update docs from artifacts | + |

**Completed: 8/8**

## 8) Multi-Chain Rollout Verdict (v3.2.20)

| Config | Chain | ONLINE Status | Verdict | no_tokens | no_pool |
|--------|-------|---------------|---------|-----------|---------|
| coverage_intent_linea.yaml | Linea (59144) | **NO_DATA** | ! | 11 | 6 |
| coverage_intent_mantle.yaml | Mantle (5000) | **NO_DATA** | ! | 6 | 10 |
| coverage_intent_scroll.yaml | Scroll (534352) | **NO_DATA** | ! | 9 | 5 |
| coverage_intent_zksync.yaml | zkSync (324) | **NO_DATA** | ! | 10 | 5 |

**Root Cause**: Multi-chain discovery requires:
1. Proper token addresses in `core_tokens.yaml` for each chain
2. Pool resolution working for each DEX adapter
3. DEX protocol anchors (factory, quoter_v2, router) in `dexes.yaml`

## 9) CI Pipeline Status

pytest: 1341 passed, 1 skipped
ci_full_pipeline: ALL REQUIRED GATES PASSED

## 10) Next Steps

1. ~~**Fix MIXED_CHAIN_KEYS**~~ + Resolved via `scripts/cleanup_rolling.py` + chain guard in `ci_m5_0_gate.py`
2. **Add Linea/Mantle tokens to core_tokens.yaml** - Use `scripts/lint_readiness.py --chain <chain>` to identify gaps
3. **Debug pool resolution for lynex_v3/agni_v3** - Check factory calls and fee_tiers
4. **Monitor sushiswap_v3** - Consider removal from NORMAL if CRITICAL persists
5. **Roundtrip profitability** - Wait for lower gas or better spreads

## 11) Session Code Changes (v3.2.21)

| Change | File | Purpose |
|--------|------|---------|
| Rolling chain guard | `scripts/ci_m5_0_gate.py` | FAIL --refresh-rolling if chain != arbitrum_one |
| NO_DATA run_summary | `scripts/ci_m5_0_gate.py` | Generate minimal run_summary for NO_DATA/FAIL runs |
| Cleanup script | `scripts/cleanup_rolling.py` | Remove non-primary chain runs from rolling |
| Lint readiness | `scripts/lint_readiness.py` | Check token/DEX readiness before ONLINE run |
| inspect_run_dir fix | `scripts/inspect_run_dir.py` | Fallback run_timestamp from truth_report when run_summary missing |

---
*Generated: 2026-03-04T22:13:00Z*
*Evidence: ci_m5_gate_20260304_221101 (arbitrum_one, NORMAL)*
*MIXED_CHAIN_KEYS: RESOLVED via cleanup_rolling.py*

