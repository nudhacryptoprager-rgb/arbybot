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

## M5_0 CI Gate Usage

### Commands

**Recommended: Explicit --run-dir (highest priority)**
```powershell
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456
```

**Offline fixture (saves to data/runs/)**
```powershell
# Default: data/runs/ci_m5_0_gate_<timestamp>
python scripts/ci_m5_0_gate.py --offline

# Custom output directory
python scripts/ci_m5_0_gate.py --offline --out-dir data/runs/my_fixture
```

**Auto-select latest**
```powershell
# Auto-select (when no --run-dir and no --offline)
python scripts/ci_m5_0_gate.py

# Print latest valid runDir
python scripts/ci_m5_0_gate.py --print-latest
```

### Run-Dir Selection Priority

| Priority | Condition | Behavior |
|----------|-----------|----------|
| 1 | `--run-dir PATH` | Uses explicit path |
| 2 | `--offline` | Creates fixture in `--out-dir` or `data/runs/ci_m5_0_gate_<ts>` |
| 3 | Default | Auto-select latest valid runDir in `data/runs/` |

### Latest RunDir Selection Logic

- **Must have**: all 3 artifacts (scan_*.json, truth_report_*.json, reject_histogram_*.json)
- **Priority prefixes**: `ci_m5_0_gate_*` > `run_scan_*` > `real_*` > `session_*` > other
- **Within same priority**: sorted by mtime (newest first)
- **Directories without 3 artifacts**: ignored

### What It Validates

| Check | Description |
|-------|-------------|
| Artifacts present | scan_*.json, truth_report_*.json, reject_histogram_*.json |
| schema_version | Exists and matches X.Y.Z format |
| run_mode | Exists in both scan and truth_report, consistent |
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

### Fixture Marker

Fixture data contains `_fixture: true` in JSON and uses `current_block: 275000000`.
Gate output shows `[FIXTURE]` marker for synthetic data.

---

## Files Changed

| File | Change |
|------|--------|
| `core/constants.py` | Centralized constants + restored DexType/TokenStatus/etc |
| `core/exceptions.py` | Added INFRA_BAD_ABI to ErrorCode |
| `scripts/ci_m5_0_gate.py` | NEW: M5_0 CI gate script |
| `tests/unit/test_ci_m5_0_gate.py` | NEW: M5_0 gate unit tests |
| `docs/TESTING.md` | Added M5_0 gate instructions |
| `docs/status/Status_M5_0.md` | This file |

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

# 4. M5_0 gate (offline or with explicit --run-dir)
python scripts/ci_m5_0_gate.py --offline
# or
python scripts/ci_m5_0_gate.py --run-dir data/runs/<valid_run>

# 5. M5_0 gate tests
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

# Add untracked files
git add scripts/ci_m5_0_gate.py tests/unit/test_ci_m5_0_gate.py

# Run tests
python -m pytest -q

# Run M5_0 gate
python scripts/ci_m5_0_gate.py --offline

# Commit all
git add core/constants.py core/exceptions.py scripts/ci_m5_0_gate.py \
        tests/unit/test_ci_m5_0_gate.py docs/TESTING.md docs/status/Status_M5_0.md
git commit -m "feat(M5_0): CI gate, centralized constants, ErrorCode fix"
```
