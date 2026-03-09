# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]  
**Updated**: 2026-03-09 12:00  
**Tests**: 1465 passed, 1 skipped  
**Evidence runDirs**: `ci_m5_gate_20260309_112122` (zkSync), `ci_m5_gate_20260309_112235` (Linea)  
**Evidence rolling**: `data/runs/_rolling/_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`

---

## [!] Core Truth Statement

> **M5_0 є обов'язковим для CI та infra-proof.**  
> M5_0 валідує схеми/інваріанти артефактів, multicall, failover, провенанс.  
> M4 execution gate є окремим "core truth" для profit.

---

## Multi-Chain Bring-up (2026-03-09)

### Session Fixes Applied (2026-03-09 12:00)

1. **WebSocket endpoint resolution fixed**: Chain-correct WS hosts now resolved per-config (was inheriting Arbitrum)
2. **zkSync quoter_v2 enabled**: Added `use_quoter_v2: true` to config (was rejecting all as SLOT0_DIAGNOSTIC)
3. **Linea/Scroll same-DEX fallback**: `require_cross_dex: false` (MIXED_SOURCE due to algebra↔uniswap incompatibility)
4. **ALL_OPPORTUNITIES_REJECTED reason**: Added to `core/no_data.py` for accurate NO_DATA classification
5. **Version strings removed**: From Status_M5_0.md per DOCS_POLICY.md

### Operational Directive (2026-03-09)

> **Next frontier**: Data collection quality + network stabilization, not raw infra PASS.  
> Code blocker is LOW; the real work is raising quote success rate and making chains repeatably non-NO_DATA.

### Mantle/Linea/Scroll Routing Directive (2026-03-09)

> **Status**: Same-DEX fallback mode on all three chains due to MIXED_SOURCE.
> - **Mantle**: stratum (ve33) ↔ agni_v3 (uniswap_v3) = MIXED_SOURCE
> - **Linea**: lynex_v3 (algebra) ↔ pancakeswap_v3 (uniswap_v3) = MIXED_SOURCE
> - **Scroll**: nuri_v3 (algebra) ↔ sushiswap_v3 (uniswap_v3) = MIXED_SOURCE
> 
> **Current routing**: Same-DEX fee-tier arbitrage where supported.
> **Upgrade criterion**: Add DEXes with compatible quoter interfaces for source-safe cross-DEX routing.

### Practical Bring-up Progress

**2026-03-09**: Mantle MIXED_SOURCE fix + artifact enhancements:
- **Mantle**: Set `require_cross_dex=false` to allow single-DEX fee-tier arbitrage. **NOW PASSING** (same-DEX fallback)
  - Root cause: ALL cross-dex routes are stratum (ve33) ↔ agni_v3 (uniswap_v3) = MIXED_SOURCE
  - Solution: `agni_v3→agni_v3` routes use consistent quoter_v2 source
  - **Note**: This is NOT cross-DEX readiness; Mantle is SIGNAL_PRODUCING via same-DEX fallback only
- **Artifacts**: Added `chain_quality_level` and `consecutive_non_nodata_cycles` to run_summary.metrics
- **Rolling**: Added `consecutive_non_nodata_cycles` to m4_stability_agg.quick_stats
- **Tests**: Added 6 new tests in `test_mantle_mixed_source.py`

**2026-03-08 (session 2)**: Config optimization for all chains:
- **All chains**: `min_spread_bps` lowered from 5 to 3 (still profitable with low L2 gas)
- **Base**: AERO token price corrected ($1.5→$0.35 market correction). **PASS with 1 signal**
- **Mantle**: Added PUFF/AUSD token prices. FAIL (signal excluded)
- **Linea/zkSync/Scroll**: NO_DATA (infra PASS but no cross-DEX spread > 3bps)
- **ChainQualityLevel**: New policy contract (INFRA_READY → SIGNAL_PRODUCING → QUALITY_RAISED)

**2026-03-08 (session 1)**: Base and Scroll upgraded with additional DEXes:
- **Base**: Added SushiSwap V3 (3 DEXes total). Fresh PASS with 1 roundtrip profitable signal
- **Scroll**: Added SushiSwap V3 (2 DEXes total) + quarantined 2 low-liquidity pools. **NOW PASSING**

**Code changes (session 2)**:
- `m4/policy.py`: Added `ChainQualityLevel` (INFRA_READY/SIGNAL_PRODUCING/QUALITY_RAISED)
- `m4/policy.py`: Added `classify_chain_quality()` function
- `m4/policy.py`: Added `MIN_CYCLES_FOR_QUALITY_RAISED = 3` threshold
- `tests/unit/test_chain_quality_level.py`: 14 tests for ChainQualityLevel
- `config/coverage_intent_*.yaml`: min_spread_bps 5→3, token price fixes

### Terminology Contract

| Metric | Source | Meaning |
|--------|--------|---------|
| `quotes_total` | `scan.json stats.quotes_total` | All quote requests attempted |
| `quotes_fetched` | `scan.json stats.quotes_fetched` | Quotes successfully received |
| `infra_gate` | `gate_result.json status` | Artifacts valid, schema OK, quotes_fetched > 0 |
| `run_summary.status` | `run_summary.json status` | Signal flow: NO_DATA/FAIL/PASS |
| `signals_count` | `run_summary.json metrics.signals_count` | Raw spread signals detected |
| `ChainQualityLevel` | `m4/policy.py` | Chain maturity: INFRA_READY/SIGNAL_PRODUCING/QUALITY_RAISED |
| `chain_quality_level` | `run_summary.metrics` | Runtime chain quality level |
| `consecutive_non_nodata_cycles` | `run_summary.metrics` / `quick_stats` | Count for QUALITY_RAISED proof |
| `ws_connected` | `truth_report.infra` | WebSocket connection status |
| `ws_fallback_to_http` | `truth_report.infra` | True if WS failed, fell back to HTTP |
| `ws_lag_ms` | `truth_report.infra` | WebSocket handshake latency |
| `multicall.success_rate` | `truth_report.infra.multicall` | Multicall batching success rate |

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. Infra gate validates infrastructure; run_summary shows actual opportunity flow.

### Transport Health Contract (2026-03-09 11:00)

**Thresholds for satisfactory transport health**:
- `ws_connected`: **true** (WebSocket active)
- `ws_fallback_to_http`: **false** (no fallback)
- `ws_lag_ms`: **< 300ms** (acceptable latency)
- `multicall.success_rate`: **1.0** (all batched calls succeed)

| Chain | ws_connected | ws_fallback | ws_lag_ms | mc_success | mc_rpc | Transport |
|-------|--------------|-------------|-----------|------------|--------|-----------|
| Arbitrum | ✅ true | ✅ false | 172 | 1.0 | 4 | **HEALTHY** |
| Base | ✅ true | ✅ false | 140 | 1.0 | 4 | **HEALTHY** |
| Mantle | ✅ true | ✅ false | 170 | 1.0 | 4 | **HEALTHY** |
| Linea | ✅ true | ✅ false | 140 | 1.0 | 4 | **HEALTHY** |
| zkSync | ✅ true | ✅ false | 155 | 1.0 | 4 | **HEALTHY** |
| Scroll | ✅ true | ✅ false | 125 | 1.0 | 4 | **HEALTHY** |

**Audit conclusion (2026-03-09 12:00)**: Multicall and WebSocket transport are chain-correct and healthy on all 6 chains. **Main blocker is NOT transport code**, but DEX ecosystem compatibility (MIXED_SOURCE on 3 chains due to algebra↔uniswap quoter mismatch).

### Data Collection Quality Contract (2026-03-09 12:00)

| Chain | quotes | fetch% | signals | no_data_reason | Status |
|-------|--------|--------|---------|----------------|--------|
| Base | 29/42 | 69% | 2 | — | SIGNAL_PRODUCING |
| zkSync | 49/49 | 100% | 0 | NO_SPREAD_SIGNALS | INFRA_READY (quoter_v2 FIX applied) |
| Linea | 30/30 | 100% | 0 | MIXED_SOURCE | same-DEX fallback |
| Mantle | 24/50 | 48% | 3 | — | same-DEX fallback |
| Arbitrum | 42/101 | 42% | 9 | — | SIGNAL_PRODUCING |
| Scroll | 21/21 | 100% | 0 | MIXED_SOURCE | same-DEX fallback |

| Metric | Target | Base | Mantle | Arbitrum | Notes |
|--------|--------|------|--------|----------|-------|
| `quotes_fetched/quotes_total` | ≥70% | 29/42 (69%) ⚠️ | 24/50 (48%) | 42/101 (42%) | zkSync/Linea 100% |
| `signals_count` | ≥1 | 2 ✅ | 3 ✅ | 9 ✅ | Base/Mantle/Arb SIGNAL_PRODUCING |
| `runtime_disabled_pools` | 0 | 0 | 0 | 0 | OK |
| `cross_dex_ready` | true | true | **false** | true | Mantle/Linea/Scroll = same-DEX fallback |

**Stabilization criterion**: Chain is stable when it repeatably produces non-NO_DATA across 3+ consecutive cycles, not just single-run PASS.

### Reject Surface Analysis (2026-03-09)

**Base** (`coverage_intent_base.yaml`, runDir `104548`):
- Quotes: 42 total → 29 fetched (69% fetch rate) ⚠️
- DEXes: uniswap_v3, aerodrome, sushiswap_v3
- Signals: 2 (ROUNDTRIP_PROFITABLE)
- **Status**: SIGNAL_PRODUCING

**Mantle** (`coverage_intent_mantle.yaml`, runDir `104720`):
- Quotes: 50 total → 24 fetched (48% fetch rate)
- DEXes: agni_v3 (13 pairs), stratum (5)
- Signals: 3 (same-DEX fee-tier arbitrage)
- **Blocker**: Only 5 true cross-DEX pairs; using same-DEX fallback (require_cross_dex=false)

**Arbitrum** (`coverage_intent_arbitrum_one.yaml`, runDir `104851`):
- Quotes: 101 total → 42 fetched (42% fetch rate)
- DEXes: 4 (uniswap_v3, sushiswap_v3, camelot, pancakeswap)
- Signals: 9 (highest count)
- **Status**: SIGNAL_PRODUCING

**zkSync** (`coverage_intent_zksync_era.yaml`, runDir `104838`):
- Quotes: 49/49 (100% fetch rate) ✅ **EXCELLENT**
- DEXes: syncswap_v2, pancakeswap_v3
- Signals: 0
- **Status**: INFRA_READY (NO_DATA - no arb market)

**Linea** (`coverage_intent_linea.yaml`, runDir `104751`):
- Quotes: 28 total → 27 fetched (96% fetch rate) ✅ **EXCELLENT**
- DEXes: lynex_v3
- Signals: 0
- **Status**: INFRA_READY (NO_DATA - no arb market)

**Scroll** (`coverage_intent_scroll.yaml`, runDir `104818`):
- Quotes: 21 total → 10 fetched (48% fetch rate) ⚠️
- DEXes: sushiswap_v3, nuri_v3
- Signals: 0
- **Status**: INFRA_READY (NO_DATA - no arb market)
- **Note**: Improved from 24% after PAPER/SYN removal (no token addresses)

**Action items** (updated 2026-03-09 12:00):
1. ✅ DONE: mUSD added to `core_tokens.yaml` for Mantle
2. ✅ DONE: AUSD removed from intent.txt (zero liquidity on DEXes)
3. ✅ DONE: PAPER/SYN removed from intent.txt Scroll (no token addresses)
4. ✅ DONE: zkSync quoter_v2 enabled (was SLOT0_DIAGNOSTIC)
5. ✅ DONE: WebSocket endpoint resolution fixed (chain-correct hosts)
6. TODO: Add FusionX V3 or another quoter_v2 DEX on Mantle for true cross-DEX
7. TODO: Add Algebra-compatible DEX on Linea/Scroll OR remove Algebra DEX

### Blocker Classification (2026-03-09 12:00)

```
code_blocker:           LOW    (pytest 1465 passed, CI green, safety PASS)
multicall_blocker:      LOW    (success_rate=1.0 all chains, 4 RPC calls)
websocket_blocker:      LOW    (ws_connected=true, chain-correct hosts, lag <200ms)
dex_compatibility_blocker:
  - Mantle:     HIGH   (stratum ve33 ↔ agni_v3 uniswap = MIXED_SOURCE)
  - Linea:      HIGH   (lynex algebra ↔ pancakeswap uniswap = MIXED_SOURCE)
  - Scroll:     HIGH   (nuri algebra ↔ sushiswap uniswap = MIXED_SOURCE)
  - zkSync:     FIXED  (quoter_v2 enabled, was SLOT0_DIAGNOSTIC)
  - Base:       LOW    (uniswap↔aerodrome↔sushi all quoter_v2)
  - Arbitrum:   LOW    (all DEXes quoter_v2 compatible)
```

**Main blocker (2026-03-09 12:00)**: DEX ecosystem compatibility. Chains with mixed quoter interfaces (algebra + uniswap) cannot do cross-DEX arbitrage without MIXED_SOURCE rejection. Same-DEX fee-tier arb is the current workaround.

### Infra Gate Results (2026-03-09 10:35)

Note: M5_0 gate validates **infra** (artifacts, schemas, quotes). `run_summary.status` semantics:
- `NO_DATA`: signals_count == 0 (no raw signals at all)
- `FAIL`: signals_count > 0 but no profitable results (includes all-excluded case: FAIL_ALL_EXCLUDED)
- `PASS`: signals > 0 and profitable

| Chain | Infra Gate | run_summary | chain_quality_level | quotes | fetch% | signals | dexes | runDir | Notes |
|-------|------------|-------------|---------------------|--------|--------|---------|-------|--------|-------|
| Arbitrum | ✅ PASS | **PASS** | SIGNAL_PRODUCING | 51/122 | 42% | 11 | 4 | 102836 | Best signals |
| Base | ✅ PASS | **PASS** | SIGNAL_PRODUCING | 37/42 | 88% | 1 | 3 | 102444 | **IMPROVED** |
| Mantle | ✅ PASS | **PASS** | SIGNAL_PRODUCING | 24/47 | 51% | 3 | 2 | 102629 | same-DEX fallback |
| Linea | ✅ PASS | NO_DATA | INFRA_READY | 27/42 | 64% | 0 | 2 | 102739 | no spreads ≥3bps |
| zkSync | ✅ PASS | NO_DATA | INFRA_READY | 49/62 | 79% | 0 | 2 | 102825 | no spreads ≥3bps |
| Scroll | ✅ PASS | NO_DATA | INFRA_READY | 9/37 | 24% | 0 | 2 | 102807 | no spreads ≥3bps |

### Scroll Status Update

Scroll is **FULLY PASSING** (2026-03-08):
- SushiSwap V3 added with verified factory `0x46B3fDF7b5...` and quoter `0xe43ca1D...`
- Fresh run resolves 8 cross-dex pairs across 2 DEXes
- 2 low-liquidity pools quarantined via `disabled_pools` in coverage config:
  - `sushiswap_v3_WETH_USDC_10000` (price=50.3, expected 100-50000)
  - `sushiswap_v3_WETH_USDT_500` (price=7.65, expected 100-50000)

**Audit artifact**: [`docs/artifacts/scroll_dex_audit.json`](../artifacts/scroll_dex_audit.json) - updated 2026-03-08

### New Tools

- `scripts/warm_pool_cache.py` — Pre-populate pool resolver caches from intent.txt, diagnose missing tokens/pools/quoters, rank DEXes by coverage
  - `--check-liquidity`: Check pool liquidity via multicall (slower, requires RPC)
  - `--dex <name>`: Audit specific DEX candidates not yet in dexes.yaml
  - Uses `adapter_type` from dexes.yaml for fee tier detection (not name-based)
- `gate_result.json` — Each runDir now contains canonical gate result in `reports/`:
  - `schema_version: "m5_0:gate_result:v1.0"`
  - `run_context.run_timestamp`: ISO-8601 UTC timestamp (extracted from scan artifact's run_context)
  - `generated_at`: UTC ISO timestamp
  - `status`, `reasons`, `chain_key`, `quotes_fetched`, `cross_dex_pairs_count`

**2026-03-07 fix**: NO_DATA status contract aligned with Status_M4.md: `NO_DATA` only when `signals_count == 0`. All-excluded case now returns `FAIL` with `FAIL_ALL_EXCLUDED` reason.

### ve33 Adapter Fix

Stratum (Mantle) uses `getPair(tokenA, tokenB, stable)` instead of `getPool()`. Fixed `query_ve33_pool()` to try both methods.

---

## Rolling Discipline (2026-03-05)

### Chain Guard Policy

**PRIMARY_ROLLING_CHAIN**: `arbitrum_one`

| Rule | Behavior |
|------|----------|
| `--refresh-rolling` + `chain != arbitrum_one` | **FAIL** with error message |
| Auto-enable `refresh_rolling` + non-primary chain | **BLOCKED** by re-check after auto-enable |
| Unknown `chain_key` in cleanup | **REMOVED** (not kept as backdoor) |

### Minimal run_summary for NO_DATA/FAIL

All ONLINE runs generate `run_summary_*.json` for provenance:
- **Schema**: `m4:run_summary_min:v2.0` (separate from full `m4:run_summary:v2.0`)
- **Fields**: `run_timestamp`, `run_id`, `status`, `reasons`, `no_data_reason`, `chain_key`
- **Status mapping**: `NO_DATA` for zero signals, `FAIL` for validation failures
- **Atomic write**: Uses `core.json_io.atomic_write_json`

### Quality Warnings Propagation

`_latest.json` contains both aggregator-level and run-level quality fields:

**Aggregator-level (window-wide):**
- `quality_warnings`: Warnings affecting the entire rolling window (MIXED_CHAIN_KEYS, DATA_RUN_RATE_LOW, WARMUP_MIN_RUNS)
- `agg_status`, `agg_reasons`: Overall aggregator status

**Run-level (current run only):**
- `run_quality_status`: Quality status of the **current run** (PASS, WARN, FAIL)
- `run_quality_warnings`: Warnings for the **current run** (DEX_HEALTH_CRITICAL, CRITICAL_REJECT, WARN_LOW_SAMPLE)

These fields are documented in `docs/m4/ROLLING_CONTRACT.md` → "run_quality fields" section.

### Archive Policy

`cleanup_rolling.py` prunes archive files:
- Default: keep last 5 archives
- Archives created on cleanup: `m4_stability_agg_archive_*_cleanup.json`
- Prevents artifact explosion in `data/runs/_rolling/`

### Evidence Pointers

- Rolling triplet: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json}`
- Latest runDir: `data/runs/ci_m5_gate_20260305_142122/reports/`
- run_timestamp: `2026-03-05T12:22:17Z`
- Scripts: `cleanup_rolling.py`, `lint_readiness.py --config`, `suggest_anchor_updates.py`

### lint_readiness Note (2026-03-05)

`lint_readiness.py` text output now uses ASCII badges (`[READY]`, `[OK]`, `[FAIL]`) instead of emojis to avoid `UnicodeEncodeError` on Windows terminals with cp1251 encoding. Use `--json` for programmatic access.

### Latest Rolling Snapshot (2026-03-05)

| Metric | Value | Notes |
|--------|-------|-------|
| `runs_in_window` | 52 | Window full |
| `agg_status` | PASS | Aggregator healthy |
| `run_status` | PASS | Latest run passed |
| `run_quality_status` | WARN | Quality warnings present |
| `data_run_rate` | 0.64 | 64% data runs |
| `effective_pass_rate` | 0.64 | Same as data_run_rate |
| `unique_pairs` | 12 | Target: ≥8 ✅ |
| `low_sample_rate` | 0.26 | 26% low sample runs |

**run_quality_warnings** (current run):
- `CRITICAL_REJECT(PRICE_SANITY_FAILED:29)` — down from 63 (-54%), remaining are dead pools
- `EXCLUDED_PRESENT(3)` — same-DEX fee tiers excluded
- `PROFIT_DIAGNOSTIC: profit_is_diagnostic=True, profit_truth_available=False`

**Anchor fix evidence (2026-03-05)**: PRICE_SANITY_FAILED reduced 63→29 via evidence-based anchors from reject_histogram.

---

### Pool Coverage Fix (2026-03-01)
- `pool_missing_count=0` (was 4) - all pool addresses in registry
- `pool_disabled_count=1` (sushiswap_v3_WBTC_WETH_500 liq=0)
- `quarantined_count=3` (Sushi pools with persistent quote failures)
- `tokens_usd_price` section added for correct notional sizing
- `TestHuntingConfigPoolCoverage` added (3 tests)

### Signals Excluded Policy
- `signals_excluded` у rolling складається з `SAME_DEX_EXCLUDED` — це policy-семантика (fee-tier noise в межах одного DEX)
- Це НЕ quality issue, а очікувана поведінка з `require_cross_dex: true`
- Корисна метрика для крос-DEX прогресу: `signals_included` та `unique_routes_cross_dex`
- `WARN_SAME_DEX_PRESENT` — інформативний токен (не блокує PASS)

---

## Infra Changes (2026-02-21)

| Step | Change | File | Description |
|------|--------|------|-------------|
| 1 | **multicall field_success_rates** | `core/multicall.py` | Per-field `call_success/call_fail` tracking |
| 2 | **provenance unification** | `strategy/artifacts.py`, `run_scan_real.py` | `run_context.run_timestamp` unified |
| 3 | **PENDLE/WETH DISABLED** | `config/real_minimal.yaml` |: pair disabled (quoter_v2 returning 0) |
| 4 | **RDNT/WETH DISABLED** | `config/real_minimal.yaml` |: pair disabled (quoter_v2 returning 0) |
| 5 | **DIVERSITY_PAIRS_TARGET=6** | `m4/policy.py` |: reduced to match quoter coverage (was 8) |
| 6 | **check_repo_safety.py** | `scripts/check_repo_safety.py` | DEV_REPORT bloat guardrail added |
| 7 | **pool_missing_keys observability** | `strategy/quotes.py`, `run_scan_real.py` |: `pool_missing_keys` in scan.stats |
| 8 | **repo safety gate** | `scripts/check_repo_safety.py` |: check forbidden tracked files/keys |
| 9 | **Single DEV_REPORT policy** | `docs/DEV_REPORT_LATEST.md` |: only 1 DEV_REPORT tracked, versioned files forbidden |
| 10 | **WBTC/WETH fee=500 removed** | `config/real_minimal.yaml` | Cross-DEX only 3000 (MIXED_SOURCE fix) |
| 11 | **ARB/WETH fee=500 removed** | `config/real_minimal.yaml` | Cross-DEX only 3000 (MIXED_SOURCE fix) |
| 12 | **M4.1 deterministic close plan** | `Roadmap.md` | Time-bound window (N=100) for simulate-only |
| 13 | **Token registry expansion** | `config/core_tokens.yaml` | +10 discovery tokens (MAGIC, FRAX, etc.) |
| 14 | **Pool resolver + cache** | `discovery/pool_resolver.py` | factory.getPool() with persistent cache |
| 15 | **Token verify CLI** | `scripts/verify_tokens.py` | On-chain token verification |
| 16 | **Roundtrip golden fixture** | `docs/artifacts/roundtrip_canonical_golden.json` | ROUNDTRIP_CANONICAL proof |
| 17 | **Discovery runtime module** | `discovery/runtime.py` | factory.getPool() resolver at runtime |
| 18 | **Discovery runtime tests** | `tests/unit/test_discovery_runtime.py` | 9 tests for runtime module |

---

## Canonical Commands

```powershell
# 1 COMMAND = 1 GATE = PASS/FAIL
# MUST use py -3.11 (Python 3.11.x required)

# Offline gate (0 WARN, no secrets required)
py -3.11 scripts/ci_m5_0_gate.py --offline --strict
# EXPECT: PASS

# Online gate (requires RPC, real scan)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1
# EXPECT: PASS (if RPC available)

# Online gate with rolling refresh
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3 --refresh-rolling --refresh-rolling-strict --prune-keep 50
# EXPECT: PASS

# Failover stress test (isolated)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --failover-stress 3
# EXPECT: PASS with endpoints_used_count >= 2

# Unit tests
py -3.11 -m pytest tests/unit -q
# EXPECT: 1183 passed, 1 skipped
```

---

## Evidence RunDirs

| Type | RunDir | Key Evidence |
|------|--------|--------------|
| ONLINE | `ci_m5_gate_20260223_134446` | discovery=28 pairs, 224 V3 queries, 49 tokens, preflight 3/3, runs_in_window=113 |
| discovery_runtime | `ci_m5_gate_20260223_133801` | universe_source=discovery_runtime, quotes_fetched=7, PASS |
| stress-test | `manual_run_20260223_133953` | rpc_cap_triggered=true, rpc_calls=5, pools_from_rpc=224 |
| Reference | `ci_m5_gate_20260223_132921` | discovery=28 pairs, runs_in_window=110 |

---

## Invariants Validated by Gate

| # | Invariant | Check |
|---|-----------|-------|
| 1 | `execution_enabled=false` | Always in M5_0/M5 |
| 2 | `current_block` consistent | scan == truth == histogram |
| 3 | `chain_id` consistent | All artifacts |
| 4 | `run_mode` consistent | All artifacts |
| 5 | `quotes_total` consistent | scan == truth |
| 6 | `schema_version` supported | Known version |
| 7 | No sentinel blocks (0,1,999999999) | Online mode only |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL validation |
| 2 | FAIL missing artifacts |
| 3 | FAIL scanner error |

---

## API Stability Policy

```
----------------------------------------------------------------
PUBLIC SYMBOLS ONLY GROW, NEVER DISAPPEAR.
----------------------------------------------------------------

If renamed -> MUST provide alias: OldName = NewName
If deprecated -> MUST keep alias for 2 milestones minimum
```

---

## Required Public Symbols (core.constants)

```python
# Enums - DO NOT REMOVE
DexType, TokenStatus, PoolStatus, TradeDirection, ExecutionBlocker

# Constants - DO NOT REMOVE
ANCHOR_DEX_PRIORITY, PRICE_SANITY_BOUNDS, PRICE_SANITY_MAX_DEVIATION_BPS
CURRENT_EXECUTION_BLOCKER, SCHEMA_VERSION, CHAIN_IDS, DEX_IDS
```

---

## Schema Versions

| Artifact | Schema Family | Version | Notes |
|----------|---------------|---------|-------|
| scan | semver | `3.2.0` | M5 family |
| truth_report | semver | `3.2.0` | M5 family |
| reject_histogram | semver | `3.2.0` | M5 family, contains reject **samples** not aggregated counts |

**⚠️ reject_histogram Semantics:**
- `rejects` = list of individual reject samples (NOT aggregated histogram)
- `rejects_total` = count of samples in list
- `price_sanity_failed` = aggregate metric (may differ from rejects_total)

---

## Offline Mode Semantics

**Rationale**: Offline mode uses `run_mode=FIXTURE_OFFLINE` artifacts which deliberately omit infra fields. These fields are absent by design because offline mode generates deterministic fixtures for CI without network calls.

**Behavior**:
- Gate **skips infra validation entirely** in offline mode
- No WARN for missing infra fields
- Clean CI output with 0 WARN

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/ci_m5_0_gate.py` | M5_0 acceptance gate |
| `scripts/ci_full_pipeline.py` | Full CI pipeline |
| `core/artifact_invariants.py` | Cross-artifact validation |
| `tests/unit/test_imports_contract.py` | API stability test |

---

## Relationship to M5/M4

| Milestone | Focus | Gate |
|-----------|-------|------|
| M5_0 | Infrastructure hardening | `ci_m5_0_gate.py` |
| M5 | Production features | `ci_m5_gate.py` |
| M4 | Execution layer | `ci_m4_execution_gate.py` |

All gates use shared invariants from `core/artifact_invariants.py`.

---

## Risks

**Evidence (ci_m5_gate_20260224_141638 - capstone)**:
- M5_0 gate: PASS (offline and online)
- `runs_in_window=184`, `agg_status=PASS`
- `multicall field_success_rates` validated
- `preflight_evidence.enabled=true`, `gas_estimate_source=quoter_v2`

**Blockers**:
- None for M5_0 gate itself
- discovery_runtime mode requires anchor/quoter updates before production use

---

## Next steps/focus

- Docs drift closure: enforce DOCS_POLICY on Status + archive map fixed (see `docs/DOCS_POLICY.md`, `docs/status/ARCHIVE_MAP.md`)
- Continue M5_0 infra hardening with multicall/failover stability

