# Status: M5_0 Infrastructure Hardening

**Status**: IN PROGRESS  
**Last Updated**: 2026-02-01

## Overview

M5_0 focuses on API stability and import contract hardening after 4 waves of "Enum drift" broke core.models imports.

## API Stability Policy (GUARDRAIL)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PUBLIC SYMBOLS ONLY GROW, NEVER DISAPPEAR.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If renamed → MUST provide alias: OldName = NewName
If deprecated → MUST keep alias for 2 milestones minimum

Any rename/delete in core.constants without alias → M5_0 "not Done"
```

## Enum Drift History

| Wave | Symbol | Status |
|------|--------|--------|
| 1 | DexType | ✅ Fixed |
| 2 | TokenStatus | ✅ Fixed |
| 3 | PoolStatus | ✅ Fixed |
| 4 | TradeDirection | ✅ Fixed |

## Required Public Symbols (core.constants)

```python
# Enums - DO NOT REMOVE
DexType
TokenStatus
PoolStatus
TradeDirection   # ← Wave 4 fix
ExecutionBlocker

# Constants - DO NOT REMOVE
ANCHOR_DEX_PRIORITY
PRICE_SANITY_BOUNDS
PRICE_SANITY_MAX_DEVIATION_BPS
CURRENT_EXECUTION_BLOCKER
SCHEMA_VERSION
CHAIN_IDS
DEX_IDS
DEFAULT_QUOTE_AMOUNT_WEI
```

## CI Gate v2.0.0

### Canonical Commands

```bash
# Offline (ALWAYS works, IGNORES ALL ENV)
python scripts/ci_m5_0_gate.py --offline

# Online (runs real scan)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL validation |
| 2 | FAIL missing artifacts |
| 3 | FAIL scanner error |

## Test Import Contract

The "police" test catches Enum drift before suite fails:

```bash
# Run FIRST (< 0.2 seconds)
python -m pytest tests/unit/test_imports_contract.py -v

# If it fails → restore symbol in core/constants.py
# DO NOT weaken the test!
```

## Definition of Done

- [x] TradeDirection restored in core.constants
- [x] test_imports_contract.py covers all 5 Enums
- [x] "constants must not shrink" regression test
- [x] ci_m5_0_gate.py --offline works
- [x] API Stability Policy documented
- [ ] core.models imports without error (needs repo sync)
- [ ] Full test suite green (needs repo sync)

## Files Changed

| File | Change |
|------|--------|
| core/constants.py | +TradeDirection, API stability comment |
| core/validators.py | AnchorQuote.dex_id required |
| monitoring/__init__.py | Export all symbols |
| monitoring/truth_report.py | EXECUTION_DISABLED (not _M4) |
| scripts/ci_m5_0_gate.py | v2.0.0, --offline/--online |
| tests/unit/test_imports_contract.py | +TradeDirection, regression guard |
| tests/unit/test_ci_m5_0_gate.py | Mode tests |
| docs/status/Status_M5_0.md | API stability policy |

## Apply Commands

```powershell
# Copy files
Copy-Item outputs/core/constants.py core/
Copy-Item outputs/core/validators.py core/
Copy-Item outputs/monitoring/__init__.py monitoring/
Copy-Item outputs/monitoring/truth_report.py monitoring/
Copy-Item outputs/scripts/ci_m5_0_gate.py scripts/
Copy-Item outputs/tests/unit/test_imports_contract.py tests/unit/
Copy-Item outputs/tests/unit/test_ci_m5_0_gate.py tests/unit/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# Run import tests FIRST
python -m pytest tests/unit/test_imports_contract.py -v

# Verify core.models imports
python -c "import core.models; print('core.models ok')"

# Run gate
python scripts/ci_m5_0_gate.py --offline

# Commit
git add -A
git commit -m "fix(M5_0): TradeDirection (wave 4) + API stability policy"
```
