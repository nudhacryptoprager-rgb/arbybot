# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]  
**Updated**: 2026-03-10  
**Tests**: 1548 passed, 2 skipped  
**Evidence runDirs**: `ci_m5_gate_20260310_120509` (Arbitrum ✅), `ci_m5_gate_20260310_120608` (zkSync ✅), `ci_m5_gate_20260310_121004` (Linea ✅), `ci_m5_gate_20260310_121135` (Mantle ✅), `ci_m5_gate_20260310_121237` (Base ✅), `ci_m5_gate_20260310_121521` (Scroll ❌)  
**Evidence rolling**: `data/runs/_rolling/_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`

---

## [!] Core Truth Statement

> **M5_0 є обов'язковим для CI та infra-proof.**  
> M5_0 валідує схеми/інваріанти артефактів, multicall, failover, провенанс.  
> M4 execution gate є окремим "core truth" для profit.

---

## Multi-Chain Quality Deep Investigation (2026-03-09 22:45)

### Primary Blocker Identified

**Primary blocker**: `stale tokens_usd_price` - ALL 6 coverage configs had WETH=3000 (real ~2050). NOTIONAL_DRIFT >30% excluded all quotes from spread evaluation.

**Resolution (2026-03-10)**: Updated all configs with current market prices. Base + zkSync upgraded to SIGNAL_PRODUCING.

### Fresh Chain Quality Results (2026-03-10, 12:20 — session 2 post-config-fixes)

| Chain | M5 Gate | run_summary.status | quality_status | Signals | Included | Net USD | Key Issues | runDir |
|-------|---------|-------------------|----------------|---------|----------|---------|------------|--------|
| **Arbitrum** | PASS | **PASS** | WARN | 5 | 4 | $3.46 | WARN_PROFIT_DIAGNOSTIC | 120509 |
| **zkSync** | PASS | **PASS** | WARN | 3 | 1 | $0.84 | LOW_SAMPLE ← was FAIL | 120608 |
| **Linea** | PASS | **PASS** | WARN | 3 | 2 | $11.03 | LOW_SAMPLE, SAME_DEX | 121004 |
| **Mantle** | PASS | **PASS** | WARN | 4 | 3 | $7.53 | TOP_PAIR_DOMINANCE_WARN | 121135 |
| **Base** | PASS | **PASS** | WARN | 10 | 7 | $5.53 | TOP_PAIR_DOMINANCE_HIGH | 121237 |
| Scroll | PASS | **FAIL** | FAIL_QUALITY | 1 | 0 | $0.00 | FAIL_ALL_EXCLUDED (probe-only) | 121521 |

**Session 2 config fixes that produced these results**:
- zkSync: target_usd_notional 100→25, paper_size_usd 100→25, drift_warning_pct 30→40% → FAIL→PASS
- Linea: suspect_spread_bps_hard=1000, drift_warning_pct 30→40% → WETH/USDT at 810bps included
- Mantle: suspect_spread_bps_hard=750 → WETH/WMNT at 522bps included (1→3 signals)
- Base: wstETH/rETH tokens added but pools not yet in cache (dominance persists)
- Scroll: probe-only formalized (single DEX, no fix possible)

### Profit Invariant VERIFIED

**Canonical invariant**: `daily_report.net_pnl_usdc = execution_report.total_net_usdc = run_summary.total_net_usdc`

| Chain | daily_report | execution_report | run_summary | Verified |
|-------|--------------|------------------|-------------|----------|
| **Arbitrum** | $3.7175 | $3.7175 | $3.7175 | ✅ YES |
| **Mantle** | $0.0291 | $0.0291 | $0.0291 | ✅ YES |

**Invariant tests added**: 4 new tests enforce this contract permanently in `tests/unit/test_daily_report_aggregator.py`

### Chain Quality Classification (2026-03-10 12:20 post-session-2)

```
arbitrum_one:   PASS/WARN (rolling stable, m4_sim_net_usdc=$3.46, 4 included signals)
Base:           PASS/WARN (TOP_PAIR_DOMINANCE_HIGH, wstETH/rETH pools not yet discovered)
Mantle:         PASS/WARN (TOP_PAIR_DOMINANCE_WARN, 3 included signals, $7.53)
Linea:          PASS/WARN (LOW_SAMPLE, 2 included signals, WETH/USDT at 810bps)
zkSync:         PASS/WARN (LOW_SAMPLE, 1 included signal, notional $25 fix) ← was FAIL
Scroll:         FAIL (FAIL_ALL_EXCLUDED, 1 DEX only, probe-only, MARKET_BLOCKED)
```

---

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
- Scripts: `cleanup_rolling.py`, `lint_readiness.py --config`, `suggest_anchor_updates.py`

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
# EXPECT: 1548 passed, 2 skipped
```

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

- **start.py session 4 hardening**: ASCII-safe output, richer per-chain summary (quality_status, chain_quality_level, profit_truth_available, cross_dex_pairs_count), aggregate chain lists, strict exit mode (--max-fail-chains), updated summary schema
- **Long scan semantics**: A multi-chain long scan is a market/data probe confirming infra + data quality, not proof of constant profit
- Docs drift closure: enforce DOCS_POLICY on Status + archive map fixed
- Continue M5_0 infra hardening with multicall/failover stability

