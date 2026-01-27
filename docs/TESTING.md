# ARBY3 Testing Guide

_Last updated: 2026-01-27_

## Python Version (STEP 1 - MANDATORY)

**ARBY requires Python 3.11.x**

```powershell
# Check version
python --version
# Must show: Python 3.11.x

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

```powershell
# M3 gate (basic sanity)
python scripts/ci_m3_gate.py

# M4 gate - offline (default, no network)
python scripts/ci_m4_gate.py --offline

# M4 gate - online (requires network)
python scripts/ci_m4_gate.py --online
```

## What "Green" Means

A change is acceptable only if:

1. `python --version` shows 3.11.x
2. `python -c "from monitoring.truth_report import calculate_confidence; print('ok')"` works
3. `python -m pytest -q` is green
4. `python scripts/ci_m4_gate.py --offline` passes with 4/4 artifacts

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
