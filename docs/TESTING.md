# ARBY Testing Guide

## M5_0 CI Gate v2.0.0

### Two Canonical Commands

```powershell
# 1. OFFLINE (always works, ignores ALL ENV)
python scripts/ci_m5_0_gate.py --offline

# 2. ONLINE (runs real scan, ignores ARBY_RUN_DIR)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

### Mode Semantics

| Mode | Creates | Ignores | Validates |
|------|---------|---------|-----------|
| `--offline` | `ci_m5_0_gate_offline_<ts>/` | ALL ENV | Fixture |
| `--online` | `ci_m5_0_gate_<ts>/` | ARBY_RUN_DIR | Real |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL (validation) |
| 2 | FAIL (artifacts missing) |
| 3 | FAIL (scanner error) |

---

## Quick Start

```powershell
# 1. Import smoke tests (catch ImportError early)
python -m pytest tests/unit/test_imports_contract.py -v

# 2. All unit tests
python -m pytest tests/unit -q

# 3. Offline gate
python scripts/ci_m5_0_gate.py --offline

# 4. Online gate (requires RPC)
python scripts/ci_m5_0_gate.py --online --config config/real_m5_0_golden.yaml
```

---

## Unit Tests

```powershell
# Import contract tests
python -m pytest tests/unit/test_imports_contract.py -v

# Price sanity tests
python -m pytest tests/unit/test_price_sanity_inversion.py -v

# Gate tests
python -m pytest tests/unit/test_ci_m5_0_gate.py -v

# Adapter tests
python -m pytest tests/unit/test_algebra_adapter.py -v

# All unit tests
python -m pytest tests/unit -q
```

---

## Artifact Locations

| Mode | Location |
|------|----------|
| `--offline` | `data/runs/ci_m5_0_gate_offline_<ts>/` |
| `--online` | `data/runs/ci_m5_0_gate_<ts>/` |

---

## Advanced Mode (Deprecated)

For backward compatibility only:

```powershell
# Explicit run directory
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_xxx

# With ENV (deprecated)
$env:ARBY_RUN_DIR = "data\runs\real_xxx"
python scripts/ci_m5_0_gate.py
```

**Note**: Prefer `--offline` or `--online` for new workflows.
