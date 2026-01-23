# Status: Milestone 3 (M3) — Opportunity Engine

**Status:** ✅ DONE  
**Last Updated:** 2026-01-23  
**Branch:** `split/code`

## M3 Gate Proof

```
Path:     data/runs/ci_m3_gate_20260123_110359
Result:   ✅ M3 CI GATE PASSED
SHA:      be85d14009ff1a15d9242618fdbf90c9bf7ae96d
```

This is the baseline truth for M3 closure. Any future changes must not break this gate.

## Done Criteria (M3) ✅

```
✅ python -m pytest -q                → PASS
✅ python scripts/ci_m3_gate.py       → PASS
✅ Smoke creates 4 artifacts:
   - snapshots/scan_*.json
   - reports/reject_histogram_*.json
   - reports/truth_report_*.json
   - scan.log
```

## Commands (Windows PowerShell + venv)

```powershell
# 1. Create and activate venv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements-dev.txt

# 3. Run tests
python -m pytest -q

# 4. Run CI gate (runs tests + smoke + artifact check)
python scripts/ci_m3_gate.py

# 5. Manual smoke run
python -m strategy.jobs.run_scan --mode smoke --cycles 1 --output-dir data/runs/manual_test
```

## Contracts (Frozen for M4)

### Public API CONTRACT

```python
from strategy.jobs.run_scan import run_scanner, ScannerMode

# SMOKE mode - always works
run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=Path(...))

# REAL mode - M4 will implement (currently raises RuntimeError)
run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=Path(...))
```

### TruthReport CONTRACT (schema v3.0.0)

```json
{
  "schema_version": "3.0.0",
  "run_mode": "SMOKE_SIMULATOR",
  "health": {
    "gate_breakdown": {"revert": N, "slippage": N, "infra": N, "other": N}
  },
  "top_opportunities": [...],
  "stats": {...}
}
```

### Confidence Scoring CONTRACT

```python
CONFIDENCE_WEIGHTS = {
    "quote_fetch": 0.25,
    "quote_gate": 0.25,
    "rpc": 0.20,
    "freshness": 0.15,
    "adapter": 0.15,
}
# from monitoring.truth_report import calculate_confidence
```

### Gate Breakdown CONTRACT

```python
GATE_BREAKDOWN_KEYS = frozenset(["revert", "slippage", "infra", "other"])
```

### Ranking CONTRACT (Deterministic)

```
Sort key: is_profitable DESC → net_pnl_usdc DESC → net_pnl_bps DESC → confidence DESC → spread_id ASC
```

## M3 → M4 Transition

### M3 Closure ✅
- [x] All tests pass (`pytest -q`)
- [x] CI gate passes (`scripts/ci_m3_gate.py`)
- [x] spread_id roundtrip stable
- [x] Ranking deterministic
- [x] No silent mode substitution
- [x] API contract: `ScannerMode`, `run_scanner` exported

### M4 Start Criteria
- [x] M3 Gate proof documented (this file)
- [ ] `--mode real` runs pipeline (execution disabled)
- [ ] Real RPC quotes (1 chain × 1-2 DEX × 1-2 pairs)
- [ ] Pinned block invariant
- [ ] Real reject reasons in histogram
- [ ] `ci_m4_gate.py` created

## Links

- M3 Gate Run: `data/runs/ci_m3_gate_20260123_110359`
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
- M4 Roadmap: REAL scan, pinned block, real reject reasons, execution disabled
