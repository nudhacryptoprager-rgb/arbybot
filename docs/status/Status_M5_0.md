# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]  
**Updated**: 2026-02-20  
**Tests**: 943 passed, 1 skipped  
**Evidence runDir**: `ci_m5_gate_20260219_210425`

---

## [!] Core Truth Statement

> **M5_0 є обов'язковим для CI та infra-proof.**  
> M5_0 валідує схеми/інваріанти артефактів, multicall, failover, провенанс.  
> M4 execution gate є окремим "core truth" для profit.

---

## v2.3.x Infra Changes (2026-02-19)

| Step | Change | File | Description |
|------|--------|------|-------------|
| 1 | **multicall field_success_rates** | `core/multicall.py` | Per-field `call_success/call_fail` tracking |
| 2 | **provenance unification** | `strategy/artifacts.py`, `run_scan_real.py` | `run_context.run_timestamp` unified |
| 3 | **PENDLE/WETH DISABLED** | `config/real_minimal.yaml` |: pair disabled (quoter_v2 returning 0) |
| 4 | **RDNT/WETH DISABLED** | `config/real_minimal.yaml` |: pair disabled (quoter_v2 returning 0) |
| 5 | **DIVERSITY_PAIRS_TARGET=8** | `m4/policy.py` |: reduced to match quoter coverage |
| 6 | **check_repo_safety.py** | `scripts/check_repo_safety.py` | DEV_REPORT bloat guardrail added |
| 7 | **pool_missing_keys observability** | `strategy/quotes.py`, `run_scan_real.py` |: `pool_missing_keys` in scan.stats |
| 8 | **repo safety gate** | `scripts/check_repo_safety.py` |: check forbidden tracked files/keys |
| 9 | **Single DEV_REPORT policy** | `docs/DEV_REPORT_LATEST.md` |: only 1 DEV_REPORT tracked, versioned files forbidden |

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
# EXPECT: 933 passed, 1 skipped
```

---

## Evidence RunDirs

| Type | RunDir | Key Evidence |
|------|--------|--------------|
| Normal | `ci_m5_gate_20260219_201744` | `field_success_rates~1.0`, unique_pairs=8 |
| Reference | `ci_m5_gate_20260219_190354` | `field_success_rates=1.0`, `endpoints_used=[alchemy]` |

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

## Next steps/focus

- Docs drift closure: enforce DOCS_POLICY on Status + archive map fixed (see `docs/DOCS_POLICY.md`, `docs/status/ARCHIVE_MAP.md`)
- Continue M5_0 infra hardening with multicall/failover stability

