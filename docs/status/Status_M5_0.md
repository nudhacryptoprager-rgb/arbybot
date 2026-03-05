# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]  
**Updated**: 2026-03-05  
**Tests**: 1385 passed (including lint_readiness, cleanup_rolling, suggest_anchor_updates tests)  
**Evidence runDir**: `ci_m5_gate_20260305_123559`  
**Evidence rolling**: `data/runs/_rolling/_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`

---

## [!] Core Truth Statement

> **M5_0 є обов'язковим для CI та infra-proof.**  
> M5_0 валідує схеми/інваріанти артефактів, multicall, failover, провенанс.  
> M4 execution gate є окремим "core truth" для profit.

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
- Latest runDir: `data/runs/ci_m5_gate_20260305_123559/reports/`
- run_timestamp: `2026-03-05T11:37:00.563309Z`
- Scripts: `cleanup_rolling.py`, `lint_readiness.py --config`, `suggest_anchor_updates.py`

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

