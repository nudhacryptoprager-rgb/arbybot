# Status: M5_0 (Infrastructure Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-31

## Goal

Consolidate infrastructure, unify contracts, prepare for M5 execution.

---

## CI Gate v2.0.0

### Two Canonical Commands

```powershell
# OFFLINE (always works)
python scripts/ci_m5_0_gate.py --offline

# ONLINE (runs real scan)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

### Mode Rules

| Mode | Creates | Ignores | Validates |
|------|---------|---------|-----------|
| `--offline` | `ci_m5_0_gate_offline_<ts>/` | ALL ENV | Fixture |
| `--online` | `ci_m5_0_gate_<ts>/` | ARBY_RUN_DIR | Real |

---

## Known Issues

### ⚠️ P1: Sushi V3 fee=3000 Bad Quote

**Symptom**: sushiswap_v3 fee=3000 returns ~8.6 USDC for 1 WETH

**Status**: Gate REJECTS correctly. Root cause NOT fixed.

**Workaround**: Excluded from `real_m5_0_golden.yaml`.

---

## Contracts

### 1. Backward Compatibility

```python
# These MUST exist in core.constants:
from core.constants import DexType      # REQUIRED
from core.constants import TokenStatus  # REQUIRED
from core.constants import ExecutionBlocker  # REQUIRED
```

### 2. Price Orientation

Price = `quote_token per 1 base_token`

### 3. NO INVERSION

`inversion_applied` is **ALWAYS** `False`

### 4. AnchorQuote.dex_id

`dex_id` is a **REQUIRED** field

### 5. Execution Blocker

Use `EXECUTION_DISABLED` (stage-agnostic, NOT `_M4`)

---

## Definition of Done

```powershell
# 1. Add untracked files
git add tests/unit/test_imports_contract.py
git add config/real_m5_0_golden.yaml

# 2. Import smoke tests
python -m pytest tests/unit/test_imports_contract.py -v

# 3. All unit tests
python -m pytest tests/unit -q

# 4. Offline gate
python scripts/ci_m5_0_gate.py --offline

# 5. Online gate (optional)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

# 6. Verify artifacts
dir data\runs\ci_m5_0_gate_*
```

---

## Files Changed

| File | Change |
|------|--------|
| `core/constants.py` | DexType, TokenStatus, EXECUTION_DISABLED |
| `core/validators.py` | AnchorQuote.dex_id required |
| `scripts/ci_m5_0_gate.py` | v2.0.0: --offline/--online |
| `monitoring/truth_report.py` | EXECUTION_DISABLED (not _M4) |
| `dex/adapters/algebra.py` | Real pool address in diagnostics |
| `tests/unit/test_imports_contract.py` | NEW: import smoke tests |
| `tests/unit/test_ci_m5_0_gate.py` | Mode tests |
| `tests/unit/test_algebra_adapter.py` | Stable field tests |
| `tests/unit/test_price_sanity_inversion.py` | Contract tests |
| `config/real_m5_0_golden.yaml` | NEW: stable golden config |
| `docs/TESTING.md` | Canonical commands |

---

## Apply Commands

```powershell
# 1. Copy files
Copy-Item outputs/core/constants.py core/
Copy-Item outputs/core/validators.py core/
Copy-Item outputs/scripts/ci_m5_0_gate.py scripts/
Copy-Item outputs/monitoring/truth_report.py monitoring/
Copy-Item outputs/dex/adapters/algebra.py dex/adapters/
Copy-Item outputs/tests/unit/test_imports_contract.py tests/unit/
Copy-Item outputs/tests/unit/test_ci_m5_0_gate.py tests/unit/
Copy-Item outputs/tests/unit/test_algebra_adapter.py tests/unit/
Copy-Item outputs/tests/unit/test_price_sanity_inversion.py tests/unit/
Copy-Item outputs/config/real_m5_0_golden.yaml config/
Copy-Item outputs/docs/TESTING.md docs/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# 2. Add NEW files to Git (CRITICAL for CI)
git add tests/unit/test_imports_contract.py
git add config/real_m5_0_golden.yaml

# 3. Verify imports
python -m pytest tests/unit/test_imports_contract.py -v

# 4. All unit tests
python -m pytest tests/unit -q

# 5. Offline gate
python scripts/ci_m5_0_gate.py --offline

# 6. Commit
git add -A
git commit -m "fix(M5_0): back-compat + gate v2.0.0 + untracked files"
```
