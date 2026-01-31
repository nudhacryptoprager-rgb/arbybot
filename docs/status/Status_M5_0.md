# Status: M5_0 (Infrastructure Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-31

## Goal

Consolidate infrastructure, unify contracts, and prepare for M5 multi-chain execution.

---

## CI Gate v2.0.0

### Two Canonical Commands

```powershell
# 1. OFFLINE (always works, creates fixture)
python scripts/ci_m5_0_gate.py --offline

# 2. ONLINE (runs real scan, validates)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

### Mode Semantics

| Mode | Creates RunDir | Uses ENV | Validates |
|------|----------------|----------|-----------|
| `--offline` | `data/runs/ci_m5_0_gate_offline_<ts>/` | NO (ignores) | Fixture |
| `--online` | `data/runs/ci_m5_0_gate_<ts>/` | NO (ignores ARBY_RUN_DIR) | Real artifacts |
| Legacy | Uses `--run-dir` or `ARBY_RUN_DIR` | YES | Both |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL (validation) |
| 2 | FAIL (artifacts missing) |
| 3 | FAIL (mode error) |

---

## Known Issues

### ⚠️ P0: DexType ImportError (FIXED)

**Symptom**: `ImportError: cannot import name 'DexType' from 'core.constants'`

**Status**: FIXED - `DexType` restored to `core/constants.py`

**Fix**: DexType Enum added back for backward compatibility.

### ⚠️ P1: Sushi V3 fee=3000 Bad Quote

**Symptom**: sushiswap_v3 fee=3000 returns ~8.6 USDC for 1 WETH

**Status**: Gate correctly REJECTS. Root cause NOT fixed.

**Workaround**: Sanity gate rejects with clear diagnostics.

---

## Contracts

### 1. Price Orientation

Price is ALWAYS `quote_token per 1 base_token`.

### 2. NO INVERSION

`inversion_applied` is **ALWAYS** `False`.

### 3. Deviation Formula

```python
deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
MAX_DEVIATION_BPS_CAP = 10000
```

### 4. Execution Blocker

Use `EXECUTION_DISABLED` (not `_M4`).

---

## Definition of Done (M5_0)

```powershell
# 1. Import smoke test
python -m pytest tests/unit/test_imports_contract.py -v

# 2. Unit tests
python -m pytest tests/unit -q

# 3. Offline gate (always works)
python scripts/ci_m5_0_gate.py --offline

# 4. (Optional) Online gate
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

# 5. Verify artifacts
dir data\runs\ci_m5_0_gate_*
```

---

## Files Changed (M5_0)

| File | Change |
|------|--------|
| `core/constants.py` | DexType restored, EXECUTION_DISABLED |
| `scripts/ci_m5_0_gate.py` | v2.0.0: --offline / --online modes |
| `tests/unit/test_imports_contract.py` | NEW: import smoke tests |
| `tests/unit/test_ci_m5_0_gate.py` | Updated for new modes |
| `docs/TESTING.md` | Updated documentation |
| `docs/status/Status_M5_0.md` | This file |

---

## Apply Commands

```powershell
# Copy files
Copy-Item outputs/core/constants.py core/
Copy-Item outputs/scripts/ci_m5_0_gate.py scripts/
Copy-Item outputs/tests/unit/test_imports_contract.py tests/unit/
Copy-Item outputs/tests/unit/test_ci_m5_0_gate.py tests/unit/
Copy-Item outputs/docs/TESTING.md docs/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# Add new files
git add tests/unit/test_imports_contract.py

# Verify
python -m pytest tests/unit/test_imports_contract.py -v
python -m pytest tests/unit/test_ci_m5_0_gate.py -v
python scripts/ci_m5_0_gate.py --offline

# Commit
git add core/constants.py scripts/ci_m5_0_gate.py `
    tests/unit/test_imports_contract.py tests/unit/test_ci_m5_0_gate.py `
    docs/TESTING.md docs/status/Status_M5_0.md
git commit -m "fix(M5_0): DexType restored + gate v2.0.0 with --offline/--online modes"
```
