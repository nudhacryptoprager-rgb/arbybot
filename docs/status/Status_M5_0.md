# Status: M5_0 (Infrastructure Hardening)

**Status**: ✅ **DONE** (frozen)  
**Updated**: 2026-02-09  
**Closure SHA**: `93c08b0`  
**Gate Version**: `ci_m5_0_gate.py` v2.1.0  
**Tests**: 553 passed

---

## ⚠️ Core Truth Statement

> **M5_0 не блокує M4-profit, але є обов'язковим для CI.**  
> M5_0 валідує схеми/інваріанти артефактів.  
> M4 execution gate є "core truth" для релізу.

---

## Closure Summary

M5_0 is **frozen**. Any future changes require a separate PR with clear ROI justification.

---

## Canonical Commands

```bash
# 1 COMMAND = 1 GATE = PASS/FAIL

# Offline gate (0 WARN, no secrets required)
python scripts/ci_m5_0_gate.py --offline --strict
# EXPECT: PASS
# Example output:
#   RESULT: PASS
#   Run directory: data/runs/ci_m5_0_gate_offline_<timestamp>
#   Exit code: 0

# Online gate (requires RPC, real scan)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
# EXPECT: PASS (if RPC available)
# Example output:
#   RESULT: PASS
#   quotes_fetched: 6
#   dexes_active: 2
#   Exit code: 0

# M4 execution gate (offline)
python scripts/ci_m4_execution_gate.py --offline --profile smoke
# EXPECT: PASS
# Example output:
#   RESULT: PASS (profile=smoke)
#   simulations_passed: 1
#   total_net_usdc: -0.29

python scripts/ci_m4_execution_gate.py --offline --profile profit
# EXPECT: PASS
# Example output:
#   RESULT: PASS (profile=profit)
#   simulations_passed: 2
#   total_net_usdc: 0.5

# Unit tests
python -m pytest tests/unit -q
# EXPECT: 553 passed, 1 skipped
```

---

## Example RunDir

```
data/runs/ci_m5_0_gate_offline_20260209_105430/
├── reports/
│   ├── scan_20260209_105430.json
│   ├── truth_report_20260209_105430.json
│   └── reject_histogram_20260209_105430.json
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
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PUBLIC SYMBOLS ONLY GROW, NEVER DISAPPEAR.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If renamed → MUST provide alias: OldName = NewName
If deprecated → MUST keep alias for 2 milestones minimum
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
| `scripts/ci_m5_0_gate.py` | M5_0 acceptance gate v2.1.0 |
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

