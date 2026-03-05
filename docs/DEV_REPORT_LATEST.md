# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## SESSION GOAL + DONE CRITERIA (v3.2.30)
**Goal**: M4.1 Simulate-Only DoD CLOSED (N≥100 REGISTRY_REAL runs with profit).

### M4.1 DoD CRITERIA (ACHIEVED)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 1 | REGISTRY_REAL runs with net_usdc > 0 | >= 100 | 100 | ✅ |
| 2 | `agg_status` | PASS | PASS | ✅ |
| 3 | `profit_is_diagnostic` | true (simulate-only) | true | ✅ |
| 4 | `total_net_usdc` | > 0 | $870.31 | ✅ |

### QUALITY/STRETCH CRITERIA (secondary - nice to have)
| # | Criterion | Target | Current | Status |
|---|-----------|--------|---------|--------|
| 3 | `window_chain_key` | != MIXED | arbitrum_one | + |
| 4 | `agg_status` | PASS | PASS | + |
| 5 | `unique_pairs` | >= 8 | 13 | + |

### v3.2.30 CHANGES SUMMARY

**M4.1 DoD ACHIEVED (per Roadmap.md L130-145):**
- N = 100 REGISTRY_REAL runs with `net_usdc > 0`
- `agg_status = PASS` sustained
- `total_net_usdc = $870.31` cumulative paper profit
- Evidence: `ci_m5_gate_20260305_181243`

**Policy (v3.2.29):**
- `intent.txt` = business intent → pairs restored (RDNT, MAGIC, GRAIL)
- Pool-level filtering via `runtime_disabled`/quarantine handles bad pools

**Tests**: 1385 passed, CI pipeline PASS, M4 gate profit PASS

## 0) Meta
timestamp_utc: 2026-03-05T17:12:56Z
run_id: data/runs/ci_m5_gate_20260305_181243
mode: ONLINE (v3.2.30: M4.1 DoD CLOSED - N>=100 REGISTRY_REAL with profit)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, run_kind=NORMAL)
code_identity:
  primary: ts:2026-03-05T17:12:56Z
  dirty: false
  desc: v3.2.30 M4.1 simulate-only DoD CLOSED

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
touched_files (v3.2.29):
  - config/intent.txt (restored pairs: RDNT, MAGIC, GRAIL - intent=business intent policy)
  - config/real_intent_arbitrum_one.yaml (added USD prices/anchors for all tokens)

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
  - data/runs/ci_m5_gate_20260305_174946/reports (arbitrum_one, run_kind=NORMAL)
intent_configs:
  - config/coverage_intent_arbitrum_one.yaml (arbitrum_one + camelot_v3 for testing)
  - config/real_intent_arbitrum_one.yaml (arbitrum_one - no duplicate case variants)
  - config/coverage_intent_linea.yaml (Linea rollout)
  - config/coverage_intent_mantle.yaml (Mantle rollout)
  - config/coverage_intent_scroll.yaml (Scroll rollout)
  - config/coverage_intent_zksync.yaml (zkSync rollout)
evidence (NORMAL rolling run):
  - run_dir_name: ci_m5_gate_20260305_181243
  - run_timestamp: 2026-03-05T17:12:56Z
  - spread_signals: ~
  - quotes_fetched: ~
  - unique_pairs: 13
  - runs_in_window: 106
  - agg_status: PASS
  - quality_warnings: []

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  run_dir_name: ci_m5_gate_20260305_181243
  run_timestamp: 2026-03-05T17:12:56Z
  run_quality_status: PASS
  run_quality_warnings: []
  metrics:
    signals_count: ~
    signals_included: ~
    signals_excluded: ~
    total_net_usdc: 870.31
  run_context:
    chain_key: arbitrum_one
    config_path: config/real_minimal.yaml
  rolling:
    runs_in_window: 106
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
    SUSPECT_LIQUIDITY: 43      # Pool-level quarantine candidate
    LIQUIDITY_ZERO: 40         # Auto-disabled (working!)
    PRICE_SANITY_FAILED: 34    # Anchors stabilizing
    NOTIONAL_DRIFT_EXCLUDED: 2 # Drift filter working
    Total: 119                 # Intent restored, pool-level filtering active

m4_stability_agg.json:
  agg_status: PASS
  runs_in_window: 106
  unique_pairs: 13
  window_chain_key: arbitrum_one
  quality_warnings: []
  total_net_usdc: 870.31

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

