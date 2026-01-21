# Status: 10-Step Fix v3 (Backward Compatible)

**Date**: 2026-01-21
**Branch**: chore/claude-megapack
**Base SHA**: 9909290073be0979b879b5e838e7f0395ce54dfb
**Source of truth**: docs/Status_M3_P3_10step_fix.md (this file updates it)

## Summary

Fixes breaking changes from v2 to restore test compatibility while keeping new features.

## Critical Fixes

### 1. Restore `TruthReport(mode=...)` API ✅

**Problem**: Tests use `TruthReport(mode="DISCOVERY")` but v2 renamed to `run_mode`.

**Solution**: Keep BOTH fields:
- `mode`: Legacy TruthReport mode ("REGISTRY", "DISCOVERY") - default "REGISTRY"
- `run_mode`: Scanner runtime mode ("SMOKE_SIMULATOR", "REGISTRY_REAL") - new field

```python
@dataclass
class TruthReport:
    mode: str = "REGISTRY"  # Legacy
    run_mode: str = "SMOKE_SIMULATOR"  # New
```

**Verify**:
```powershell
python -m pytest -q tests\unit\test_truth_report.py -k "to_dict or create_truth_report"
```

### 2. Restore `report.mode` Attribute ✅

**Problem**: `TruthReport object has no attribute 'mode'`.

**Solution**: `mode` is now a dataclass field, accessible as `report.mode`.

**Verify**:
```powershell
python -c "from monitoring.truth_report import TruthReport; r = TruthReport(); print(r.mode)"
# Should print: REGISTRY
```

### 3. Keep `schema_version = "3.0.0"` ✅

**Problem**: v2 bumped to 3.1.0, tests expect 3.0.0.

**Solution**: Reverted to 3.0.0. Schema bumps need migration PR.

**Verify**:
```powershell
python -m pytest -q tests\unit\test_truth_report.py::TestTruthReport::test_save_report
```

### 4. `to_dict()` Includes Both `mode` AND `run_mode` ✅

**Problem**: v2 only had `run_mode`, breaking old consumers.

**Solution**: JSON now includes:
```json
{
  "schema_version": "3.0.0",
  "mode": "REGISTRY",
  "run_mode": "SMOKE_SIMULATOR",
  ...
}
```

**Verify**:
```powershell
python -m pytest -q tests\unit\test_truth_report.py::TestTruthReport::test_to_dict
```

### 5. `build_truth_report()` Accepts Both Parameters ✅

**Problem**: Caller code used `mode=`, not `run_mode=`.

**Solution**: Function signature:
```python
def build_truth_report(
    ...,
    mode: str = "REGISTRY",      # Legacy
    run_mode: str = "SMOKE_SIMULATOR",  # New
) -> TruthReport:
```

### 6. Semantic Clarification ✅

- `mode`: TruthReport mode (REGISTRY/DISCOVERY) - data source semantic
- `run_mode`: Scanner runtime mode (SMOKE_SIMULATOR/REGISTRY_REAL) - execution semantic

### 7. All Previous v2 Fixes Preserved ✅

- Real block numbers (timestamp-based, ~150M)
- `null` instead of `0` for unknown values
- Standardized `dex_id` naming
- `opportunity_id` linking in paper trades
- `error_class`/`error_message` in QUOTE_REVERT

## Files Changed

| File | Changes |
|------|---------|
| `monitoring/truth_report.py` | Restore `mode`, keep `run_mode`, schema 3.0.0 |
| `strategy/jobs/run_scan_smoke.py` | Pass `mode="REGISTRY"` + `run_mode` |
| `strategy/jobs/run_scan.py` | Import RunMode |
| `strategy/paper_trading.py` | opportunity_id field |

## Verification Commands

```powershell
# Full test suite
python -m pytest -q

# Specific contract tests
python -m pytest -q tests\unit\test_truth_report.py

# Smoke run
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\verify_v3

# Check outputs
Get-Content data\runs\verify_v3\reports\truth_report_*.json | Select-String '"mode"'
Get-Content data\runs\verify_v3\reports\truth_report_*.json | Select-String '"run_mode"'
Get-Content data\runs\verify_v3\reports\truth_report_*.json | Select-String '"schema_version"'
# Expected:
#   "mode": "REGISTRY",
#   "run_mode": "SMOKE_SIMULATOR",
#   "schema_version": "3.0.0",
```

## Apply Instructions

```powershell
# Copy patched files
Copy-Item outputs/monitoring/truth_report.py monitoring/
Copy-Item outputs/strategy/jobs/run_scan_smoke.py strategy/jobs/
Copy-Item outputs/strategy/jobs/run_scan.py strategy/jobs/
Copy-Item outputs/strategy/paper_trading.py strategy/

# Verify tests pass
python -m pytest -q

# Commit
git add -A
git commit -m "fix: restore TruthReport backward compat (mode + schema 3.0.0)"
```

## Contract Summary

| Field | Location | Value | Purpose |
|-------|----------|-------|---------|
| `schema_version` | JSON | "3.0.0" | Format version |
| `mode` | TruthReport + JSON | "REGISTRY" | Legacy TruthReport mode |
| `run_mode` | TruthReport + JSON + snapshot | "SMOKE_SIMULATOR" | Scanner runtime mode |
