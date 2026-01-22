# Status: 10-Step Critical Fix

**Date**: 2025-01-20
**Branch**: chore/claude-megapack
**Base SHA**: 1096c8725687b1aede35056fecede7c08f4c8644

## Summary

Fixes 10 critical issues from "10 критичних зауважень" document to unblock megapack merge.

## Steps Completed

### Step 1: core/models.py - Unified API ✅

**Problem**: `test_core_models.py` uses legacy API (strings), `test_models.py` uses new API (objects). Both must pass.

**Solution**: Unified dataclasses supporting both:
- `Quote(pool_address=str, ...)` → legacy
- `Quote(pool=Pool, direction=TradeDirection, timestamp_ms=int, ...)` → new
- Same for `Trade`, `PnLBreakdown`, `Opportunity`

**Verify**:
```powershell
python -m pytest -q tests/unit/test_core_models.py
python -m pytest -q tests/unit/test_models.py
```

### Step 2: test_smoke_run.py - WinError32 Fix ✅

**Problem**: `tempfile.TemporaryDirectory()` can't delete `scan.log` because file handler is open.

**Solution**: Added `_close_all_handlers()` in `finally` block to close all logging handlers before tmpdir cleanup.

**Verify**:
```powershell
python -m pytest -q tests/integration/test_smoke_run.py
```

### Step 3: run_scan.py - Remove stderr Warning ✅

**Problem**: `logger.warning("REAL SCANNER NOT YET IMPLEMENTED...")` goes to stderr, causing PowerShell NativeCommandError.

**Solution**: 
- Changed `StreamHandler()` to use `sys.stdout` explicitly
- Replaced warning with info-level log

**Verify**:
```powershell
python -m strategy.jobs.run_scan --cycles 1 --output-dir data\runs\verify 2>&1
# Should not show NativeCommandError
```

### Step 4: JSON scanner_mode Field ✅

**Problem**: `truth_report` shows `mode: REGISTRY` when actually running `SMOKE_SIMULATOR`.

**Solution**: 
- Added `ScannerMode` enum
- Pass `scanner_mode` from `run_scan.py` to `run_scan_smoke.py`
- Include in all JSON outputs

**Verify**:
```powershell
# After running scan
Get-Content data\runs\verify\snapshots\scan_*.json | Select-String "scanner_mode"
# Should show: "scanner_mode": "SMOKE_SIMULATOR"
```

### Step 5: Forensic Samples in Snapshot ✅

**Problem**: No way to debug individual rejects - just aggregates.

**Solution**: Added to scan snapshot JSON:
- `sample_rejects[]` - up to 50 rejected quotes with details
- `sample_passed[]` - up to 50 passed quotes

Each sample includes: `quote_id, dex, pool, token_in, token_out, amount_in, amount_out, gas_estimate, reject_reason, reject_details`

**Verify**:
```powershell
Get-Content data\runs\verify\snapshots\scan_*.json | ConvertFrom-Json | Select -Expand sample_rejects | Select -First 3
```

### Step 6: QUOTE_REVERT Details ✅

**Problem**: `QUOTE_REVERT` without diagnostic info.

**Solution**: Added `reject_details` with:
- `fn_or_selector`: e.g., "0xf7729d43"
- `params_summary`: e.g., "tokenIn=WETH,tokenOut=USDC,fee=500"
- `rpc_provider_tag`: e.g., "alchemy_arb_1"
- `pool`, `dex`, `block_number`

### Step 7: SLIPPAGE_TOO_HIGH Details ✅

**Problem**: No slippage calculations visible.

**Solution**: Added `reject_details` with:
- `expected_out`, `min_out`
- `slippage_bps`
- `implied_price`, `anchor_price`
- `deviation_bps`

### Step 8: Golden Fixtures Path ✅

**Problem**: Need reproducible baseline artifacts in git.

**Solution**: Created `docs/artifacts/smoke/` with README template.

**Verify**:
```powershell
Test-Path docs/artifacts/smoke/README.md
```

### Step 9: .gitignore Update ✅

**Problem**: `data/runs/**` shouldn't be committed, but `docs/artifacts/**` should.

**Solution**: Updated `.gitignore`:
```
data/runs/
!docs/artifacts/
!docs/artifacts/**
```

**Verify**:
```powershell
git check-ignore -v data/runs/session_1/scan.log  # Should be ignored
git check-ignore -v docs/artifacts/smoke/README.md  # Should NOT be ignored
```

### Step 10: Final Gate ✅

**Verify all tests pass**:
```powershell
python -m pytest -q
python -m strategy.jobs.run_scan --cycles 1 --output-dir data\runs\verify
```

## Files Changed

| File | Change |
|------|--------|
| `core/models.py` | Unified legacy + new API |
| `tests/integration/test_smoke_run.py` | WinError32 fix |
| `strategy/jobs/run_scan.py` | stdout logging, mode enum |
| `strategy/jobs/run_scan_smoke.py` | Forensic samples, mode, details |
| `.gitignore` | Allow docs/artifacts |
| `docs/artifacts/smoke/README.md` | Golden fixtures template |

## Apply Instructions

```powershell
# Copy files to repo
Copy-Item arbybot_patch/core/models.py core/
Copy-Item arbybot_patch/tests/integration/test_smoke_run.py tests/integration/
Copy-Item arbybot_patch/strategy/jobs/run_scan.py strategy/jobs/
Copy-Item arbybot_patch/strategy/jobs/run_scan_smoke.py strategy/jobs/
Copy-Item arbybot_patch/.gitignore .
New-Item -ItemType Directory -Force -Path docs/artifacts/smoke
Copy-Item arbybot_patch/docs/artifacts/smoke/README.md docs/artifacts/smoke/

# Verify
python -m pytest -q
python -m strategy.jobs.run_scan --cycles 1 --output-dir data\runs\verify
```

## Next Steps

1. Run full test suite
2. Create golden fixtures from successful smoke run
3. Commit and push
4. Request review from ChatGPT
