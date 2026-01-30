# ARBY3 Testing Guide

_Last updated: 2026-01-30_

## Python Version (STEP 1 - MANDATORY)

**ARBY requires Python 3.11.x**

```powershell
# Check version
python --version  # Must show: Python 3.11.x

# If wrong version, install 3.11
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

## Environment Setup (STEP 2 - Unified .venv)

```powershell
# 1. Create venv (use .venv, NOT venv)
py -3.11 -m venv .venv

# 2. Activate
.venv\Scripts\Activate.ps1

# 3. Verify
python --version  # Must be 3.11.x

# 4. Install deps
pip install -e ".[dev]"
```

## Quick Commands

Run all unit tests:
```powershell
python -m pytest -q --ignore=tests/integration
```

Run all tests (offline mode - default):
```powershell
python -m pytest -q
```

Run smoke scan (writes artifacts):
```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$out = "data\runs\session_$ts"
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir $out
```

## CI Gates

### M3 Gate (basic sanity)
```powershell
python scripts/ci_m3_gate.py
```

### M4 Gate (REAL pipeline)
```powershell
# Offline (default, no network)
python scripts/ci_m4_gate.py --offline

# Online (requires network)
python scripts/ci_m4_gate.py --online
```

### M5_0 Gate (Infrastructure Hardening)

**Recommended: Explicit --run-dir**
```powershell
# Validate a specific run directory
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456
```

**Offline fixture mode**
```powershell
# Create fixture in data/runs/ (default location)
python scripts/ci_m5_0_gate.py --offline

# Create fixture in custom directory
python scripts/ci_m5_0_gate.py --offline --out-dir data/runs/my_test_fixture
```

**Auto-select latest**
```powershell
# Auto-select latest valid runDir (when no --run-dir and no --offline)
python scripts/ci_m5_0_gate.py

# Print latest valid runDir without running gate
python scripts/ci_m5_0_gate.py --print-latest
```

**Run-Dir Selection Priority:**
| Priority | Flag | Behavior |
|----------|------|----------|
| 1 | `--run-dir PATH` | Uses explicit path (highest priority) |
| 2 | `--offline` | Creates fixture in `--out-dir` or `data/runs/ci_m5_0_gate_<ts>` |
| 3 | (default) | Auto-selects latest valid runDir in `data/runs/` |

**Latest RunDir Selection Logic:**
- Must contain all 3 artifacts (scan, truth_report, reject_histogram)
- Priority: `ci_m5_0_gate_*` > `run_scan_*` > `real_*` > other
- Within same priority: sorted by modification time (newest first)

**M5_0 Gate validates:**
- schema_version exists (X.Y.Z format)
- run_mode exists (REGISTRY_REAL or SMOKE_SIMULATOR)
- current_block > 0 (for REAL mode)
- quotes_total >= 1, quotes_fetched >= 1
- dexes_active >= 1
- price_sanity_passed/failed metrics exist
- 3 core artifacts: scan_*.json, truth_report_*.json, reject_histogram_*.json

## What "Green" Means

A change is acceptable only if:

1. `python --version` shows 3.11.x
2. `python -c "from monitoring.truth_report import calculate_confidence; print('ok')"` works
3. `python -m pytest -q` is green
4. `python scripts/ci_m4_gate.py --offline` passes with 4/4 artifacts
5. `python scripts/ci_m5_0_gate.py --offline` passes (for M5_0+ branches)

## PR Checklist

Before creating a PR:

```powershell
# 1. Python version
python --version

# 2. Import check
python -c "from monitoring.truth_report import calculate_confidence; print('OK')"
python -c "from core.constants import DexType, SCHEMA_VERSION; print(SCHEMA_VERSION)"

# 3. Unit tests
python -m pytest -q

# 4. M4 gate (if applicable)
python scripts/ci_m4_gate.py --offline

# 5. M5_0 gate (RECOMMENDED: use explicit --run-dir)
python scripts/ci_m5_0_gate.py --offline
# or with specific runDir:
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456
```

## Offline vs Online Testing (STEP 8)

- **Offline** (default): Uses fixtures, no network required
- **Online**: Hits real RPC endpoints

Environment variables:
```powershell
# Force offline
$env:ARBY_OFFLINE = "1"

# Force online (clears offline)
Remove-Item Env:\ARBY_OFFLINE
```

## CI Note

If CI fails but local is green, treat CI as source of truth and fix CI first.

## Artifact Locations

| Artifact | Layout | Path |
|----------|--------|------|
| scan | nested | `data/runs/{session}/snapshots/scan_*.json` |
| truth_report | nested | `data/runs/{session}/reports/truth_report_*.json` |
| reject_histogram | nested | `data/runs/{session}/reports/reject_histogram_*.json` |
| scan.log | flat | `data/runs/{session}/scan.log` |

## Testing Specific Components

### ErrorCode Contract
```powershell
python -m pytest tests/unit/test_error_codes.py -v
```

### Truth Report
```powershell
python -m pytest tests/unit/test_truth_report.py -v
```

### M5_0 Gate
```powershell
python -m pytest tests/unit/test_ci_m5_0_gate.py -v
```

### Core Models
```powershell
python -m pytest tests/unit/test_core_models.py -v
```

## Help Commands

```powershell
# M5_0 gate help
python scripts/ci_m5_0_gate.py --help

# M4 gate help
python scripts/ci_m4_gate.py --help
```
