# Status: M5_0 (Infrastructure Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-30

## Goal

Consolidate infrastructure, unify contracts, and prepare for M5 multi-chain execution.

---

## 10 Критичних Зауважень (Що Було Не Так)

| # | Issue | Impact | Status |
|---|-------|--------|--------|
| 1 | Price sanity дублюється в gates.py і run_scan_real.py | Contract drift | Fixed |
| 2 | ErrorCode contract drift (INFRA_BAD_ABI missing) | Runtime crash | Fixed |
| 3 | Anchor = "first success" → можна отруїти | Security | Fixed |
| 4 | Недостатня діагностика sanity-fail | Debug hard | Fixed |
| 5 | SCHEMA_VERSION локально в truth_report | Drift risk | Fixed |
| 6 | Execution blocker strings scattered | Inconsistency | Fixed |
| 7 | REAL pipeline окремо від run_scan | M5 risk | Documented |
| 8 | Provider policy incomplete | No rate-limit | TODO M5 |
| 9 | Concurrency control weak | RPC storm | TODO M5 |
| 10 | No offline golden fixture | CI fragile | Fixed |

---

## 10 Кроків Виправлень

### КРОК 1: Уніфікований Price Sanity ✅

**File**: `core/validators.py`

```python
from core.validators import normalize_price, check_price_sanity

# Unified API for both SMOKE and REAL pipelines
price, was_inverted, diag = normalize_price(
    amount_in_wei, amount_out_wei, decimals_in, decimals_out, token_in, token_out
)

passed, dev_bps, error, diagnostics = check_price_sanity(
    token_in, token_out, price, config,
    dynamic_anchor=None,  # BACKWARD COMPATIBLE
    dex_id="uniswap_v3",
    pool_address="0x...",
)
```

### КРОК 2: ErrorCode Contract ✅

**File**: `core/exceptions.py`, `tests/unit/test_error_codes.py`

- Added `INFRA_BAD_ABI` to ErrorCode enum
- Test that all `ErrorCode.XXXX` usages exist in enum
- Test no duplicate values
- Test ERROR_TO_GATE_CATEGORY maps valid codes

### КРОК 3: Anchor Selection ✅

**File**: `core/validators.py`, `core/constants.py`

Priority:
1. Quote from `anchor_dex` (uniswap_v3 > pancakeswap_v3 > sushiswap_v3)
2. Median of valid quotes
3. Hardcoded bounds (fallback)

```python
ANCHOR_DEX_PRIORITY = ("uniswap_v3", "pancakeswap_v3", "sushiswap_v3")
```

### КРОК 4: Extended Diagnostics ✅

Sanity-fail diagnostics now include:

| Field | Description |
|-------|-------------|
| `implied_price` | Normalized price |
| `anchor_price` | Anchor used |
| `amount_in_wei` | Raw input |
| `amount_out_wei` | Raw output |
| `decimals_in` | Input decimals |
| `decimals_out` | Output decimals |
| `raw_price` | Before normalization |
| `inversion_applied` | Was price inverted |
| `pool_fee` | Fee tier |
| `pool_address` | Pool address |
| `dex_id` | DEX identifier |
| `anchor_source_info` | Anchor selection details |

### КРОК 5: Централізовані Константи ✅

**File**: `core/constants.py`

```python
from core.constants import (
    SCHEMA_VERSION,        # "3.2.0" (frozen)
    ExecutionBlocker,      # Enum of canonical blockers
    RunMode,               # SMOKE_SIMULATOR, REGISTRY_REAL, etc.
    ANCHOR_DEX_PRIORITY,   # ("uniswap_v3", ...)
    PRICE_SANITY_BOUNDS,   # Hardcoded fallbacks
    DexType,               # UNISWAP_V2, UNISWAP_V3, etc. (RESTORED)
    TokenStatus,           # VERIFIED, UNVERIFIED, etc. (RESTORED)
    PoolStatus,            # ACTIVE, DISABLED, etc. (RESTORED)
)
```

### КРОК 6: Canonical Blocker Strings ✅

**File**: `core/constants.py`

```python
class ExecutionBlocker(str, Enum):
    EXECUTION_DISABLED_M4 = "EXECUTION_DISABLED_M4"
    SMOKE_MODE_NO_EXECUTION = "SMOKE_MODE_NO_EXECUTION"
    NOT_PROFITABLE = "NOT_PROFITABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    NO_COST_MODEL = "NO_COST_MODEL"
    INVALID_SIZE = "INVALID_SIZE"
    # ... etc
```

### КРОК 7-9: Provider/Concurrency (TODO M5)

Not in M5_0 scope. Will be addressed in M5 multi-chain.

### КРОК 10: M5_0 CI Gate ✅

**File**: `scripts/ci_m5_0_gate.py`

Offline artifact validation without heavy imports.

---

## M5_0 Gate Usage

### Commands

```powershell
# Offline with auto-generated fixture (default)
python scripts/ci_m5_0_gate.py --offline

# Validate specific run directory
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456

# Self-test mode
python scripts/ci_m5_0_gate.py --self-test

# Show version
python scripts/ci_m5_0_gate.py --version
```

### What It Validates

| Check | Description |
|-------|-------------|
| Artifacts present | scan_*.json, truth_report_*.json, reject_histogram_*.json |
| schema_version | Exists and matches X.Y.Z format |
| run_mode | Exists in both scan and truth_report |
| current_block | > 0 for REGISTRY_REAL mode |
| quotes_total | >= 1 |
| quotes_fetched | >= 1 and <= quotes_total |
| gates_passed | <= quotes_fetched |
| dexes_active | >= 1 |
| price_sanity_passed | Exists |
| price_sanity_failed | Exists |
| reject_histogram | Exists (can be empty) |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS - all checks passed |
| 1 | FAIL - one or more checks failed |
| 2 | FAIL - artifacts missing or unreadable |

---

## Files Changed

| File | Change |
|------|--------|
| `core/constants.py` | Centralized constants + restored DexType/TokenStatus/etc |
| `core/exceptions.py` | Added INFRA_BAD_ABI to ErrorCode |
| `core/validators.py` | NEW: Unified price sanity |
| `monitoring/truth_report.py` | Import SCHEMA_VERSION from constants |
| `tests/unit/test_error_codes.py` | NEW: ErrorCode contract test |
| `tests/unit/test_ci_m5_0_gate.py` | NEW: M5_0 gate unit tests |
| `scripts/ci_m5_0_gate.py` | NEW: M5_0 CI gate script |
| `docs/TESTING.md` | Added M5_0 gate instructions |

---

## Contracts (Frozen)

### Schema Version
```
SCHEMA_VERSION = "3.2.0" (in core/constants.py)
```

### ErrorCode (Partial)
```python
ErrorCode.INFRA_BAD_ABI = "INFRA_BAD_ABI"  # ABI encoding/decoding error
ErrorCode.INFRA_BLOCK_PIN_FAILED = "INFRA_BLOCK_PIN_FAILED"
ErrorCode.PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"
# ... see core/exceptions.py for full list
```

### ExecutionBlocker (Canonical)
```python
ExecutionBlocker.EXECUTION_DISABLED_M4
ExecutionBlocker.SMOKE_MODE_NO_EXECUTION
ExecutionBlocker.NOT_PROFITABLE
ExecutionBlocker.LOW_CONFIDENCE
ExecutionBlocker.NO_COST_MODEL
ExecutionBlocker.INVALID_SIZE
```

### Price Sanity API
```python
# BACKWARD COMPATIBLE
check_price_sanity(
    token_in, token_out, price, config,
    dynamic_anchor=None,  # Optional
    fee=0, decimals_in=18, decimals_out=6,
)
# Returns: (passed, deviation_bps, error, diagnostics)
# diagnostics ALWAYS includes: implied_price, anchor_price
```

---

## Definition of Done (M5_0)

```powershell
# 1. Python version
python --version  # Must be 3.11.x

# 2. Import contract
python -c "from core.constants import DexType, SCHEMA_VERSION; print(SCHEMA_VERSION)"
python -c "from core.exceptions import ErrorCode; print('INFRA_BAD_ABI' in [e.value for e in ErrorCode])"

# 3. Full pytest (NO --ignore)
python -m pytest -q

# 4. ErrorCode contract
python -m pytest tests/unit/test_error_codes.py -v

# 5. M5_0 gate (offline)
python scripts/ci_m5_0_gate.py --offline

# 6. M5_0 gate tests
python -m pytest tests/unit/test_ci_m5_0_gate.py -v
```

**All must be green for M5_0 to be considered complete.**

---

## Apply Commands

```powershell
# Copy new files
Copy-Item outputs/core/constants.py core/
Copy-Item outputs/core/exceptions.py core/
Copy-Item outputs/scripts/ci_m5_0_gate.py scripts/
Copy-Item outputs/tests/unit/test_ci_m5_0_gate.py tests/unit/
Copy-Item outputs/docs/TESTING.md docs/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# Run tests
python -m pytest -q

# Run M5_0 gate
python scripts/ci_m5_0_gate.py --offline

# Commit
git add core/constants.py core/exceptions.py scripts/ci_m5_0_gate.py \
        tests/unit/test_ci_m5_0_gate.py docs/TESTING.md docs/status/Status_M5_0.md
git commit -m "feat(M5_0): CI gate, centralized constants, ErrorCode fix"
```
