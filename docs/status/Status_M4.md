# Status: Milestone 4 (M4) — Execution Layer (Phase 1: REAL Pipeline)

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-24  
**Branch:** `split/code`  
**Depends On:** M3 ✅ DONE

## REAL Mode Safety Contract

**REAL mode requires explicit enable** to prevent accidental live RPC calls:

```
--mode real WITHOUT explicit enable → RuntimeError
--mode real WITH explicit enable   → runs live RPC pipeline
```

Explicit enable options:
- `--allow-real` flag
- `--config <file>` argument

## Definition of Done (M4 Phase 1)

```
✅ python -m pytest -q                     → PASS
⬜ python scripts/ci_m4_gate.py            → PASS
   M4 Invariants:
   ├── run_mode == "REGISTRY_REAL"
   ├── schema_version == "3.0.0"
   ├── quotes_fetched >= 1
   ├── current_block > 0 (pinned)
   ├── execution_ready_count == 0
   └── 4/4 artifacts generated
```

## How to Run

### 1. SMOKE mode (always works, no network)

```powershell
# Activate venv
.\venv\Scripts\Activate.ps1

# Run SMOKE (no explicit enable needed)
python -m strategy.jobs.run_scan --mode smoke --cycles 1

# Or just
python scripts/ci_m3_gate.py
```

### 2. REAL mode (requires explicit enable)

```powershell
# Option 1: --allow-real flag
python -m strategy.jobs.run_scan --mode real --allow-real --cycles 1

# Option 2: --config file (also acts as explicit enable)
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 1

# Option 3: Both (recommended for CI)
python -m strategy.jobs.run_scan --mode real --allow-real --config config/real_minimal.yaml
```

### 3. M4 Gate (single button truth)

```powershell
# Runs pytest + REAL scan with explicit enable + artifact check
python scripts/ci_m4_gate.py
```

## What Happens Without Explicit Enable

```python
from strategy.jobs.run_scan import run_scanner, ScannerMode

# This RAISES RuntimeError:
run_scanner(mode=ScannerMode.REAL, cycles=1)

# Error message:
# RuntimeError: REAL mode requires explicit enable.
# To run REAL mode (live RPC), you must explicitly enable it:
#   Option 1: --allow-real flag
#   Option 2: --config <config_file>
```

## Expected Output (M4 Gate Pass)

```
============================================================
  ARBY M4 CI GATE (REAL Pipeline)
============================================================
✅ Unit Tests (pytest -q) PASSED
✅ REAL Scan (1 cycle) with explicit enable PASSED
✓ Found: scan_*.json
✓ Found: reject_histogram_*.json
✓ Found: truth_report_*.json
✓ Found: scan.log
✅ All 4 artifacts present and valid
✓ run_mode: REGISTRY_REAL
✓ schema_version: 3.0.0
✓ current_block: 150000XXX (pinned)
✓ quotes_fetched: 4 (>= 1 required)
✓ execution_ready_count: 0 (M4: execution disabled)
✅ M4 invariants satisfied
============================================================
  ✅ M4 CI GATE PASSED
============================================================
```

## Troubleshooting

### quotes_fetched = 0

If M4 gate fails with `quotes_fetched must be >= 1`:

1. **Check RPC connectivity**: Can you reach `arb1.arbitrum.io/rpc`?
2. **Check quoter addresses**: Are they correct in `config/dexes.yaml`?
3. **Check ALCHEMY_API_KEY**: If using Alchemy, set in `.env`
4. **Check reject reasons**: Look at `reject_histogram` in artifacts

### RuntimeError about explicit enable

This is EXPECTED behavior when calling REAL without:
- `--allow-real` flag, OR
- `--config <file>`

Use one of these options to explicitly enable REAL mode.

## M4 Contracts

### Artifact Contract (Same 4/4 as M3)

```
output_dir/
├── snapshots/scan_*.json
├── reports/
│   ├── reject_histogram_*.json
│   └── truth_report_*.json
└── scan.log
```

### M4 Gate Invariants

```python
# ci_m4_gate.py checks:
assert truth_report["run_mode"] == "REGISTRY_REAL"
assert truth_report["schema_version"] == "3.0.0"
assert scan["current_block"] > 0  # pinned
assert scan["stats"]["quotes_fetched"] >= 1
assert truth_report["stats"]["execution_ready_count"] == 0
```

### Public API Contract

```python
from strategy.jobs.run_scan import run_scanner, ScannerMode

# SMOKE: always works
run_scanner(mode=ScannerMode.SMOKE, cycles=1)

# REAL: requires explicit enable
run_scanner(mode=ScannerMode.REAL, cycles=1)  # RuntimeError!
run_scanner(mode=ScannerMode.REAL, cycles=1, allow_real=True)  # OK
run_scanner(mode=ScannerMode.REAL, cycles=1, config_path=Path("..."))  # OK
```

## Files

| File | Purpose |
|------|---------|
| `strategy/jobs/run_scan.py` | Entry point, enforces explicit enable |
| `strategy/jobs/run_scan_real.py` | REAL pipeline (only called with explicit enable) |
| `config/real_minimal.yaml` | Minimal config for REAL mode |
| `scripts/ci_m4_gate.py` | M4 gate (uses explicit enable) |
| `tests/integration/test_smoke_run.py` | Tests explicit enable requirement |

## M3 Baseline Preserved

- ✅ `python scripts/ci_m3_gate.py` must still pass
- ✅ SMOKE mode works unchanged
- ✅ `TestRealModeRaises` expects RuntimeError without explicit enable

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
