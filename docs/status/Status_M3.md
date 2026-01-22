# Status: Milestone 3 (M3) — Opportunity Engine

**Status:** 🟢 READY FOR CLOSURE  
**Last Updated:** 2026-01-22  
**Branch:** `split/code`

## Overview

M3 implements the Opportunity Engine: scanning, quoting, gate validation, and truth reporting.

## Done Criteria (M3)

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

## M3 Acceptance (Definition of Done)

### Automatic Check (1 command → 4 artifacts)

```bash
# Run smoke scan (1 cycle)
python -m strategy.jobs.run_scan --mode smoke --cycles 1 --output-dir data/runs/m3_acceptance

# Verify 4 artifacts generated:
ls data/runs/m3_acceptance/snapshots/scan_*.json        # ✅ scan snapshot
ls data/runs/m3_acceptance/reports/reject_histogram_*.json  # ✅ reject histogram
ls data/runs/m3_acceptance/reports/truth_report_*.json      # ✅ truth report
ls data/runs/m3_acceptance/scan.log                         # ✅ scan log
```

### truth_report Contract (required keys)

```json
{
  "schema_version": "3.0.0",
  "health": {
    "gate_breakdown": {"revert": N, "slippage": N, "infra": N, "other": N},
    "top_reject_reasons": [...],
    "dex_coverage": {...}
  },
  "top_opportunities": [...],
  "stats": {...}
}
```

### CI Gate

```bash
python scripts/ci_m3_gate.py
# → runs pytest -q
# → runs smoke scan
# → checks 4 artifacts (including scan.log)
# → exit 0 if all pass
```

## Contracts

### spread_id CONTRACT v1.1 (Backward Compatible)

```
Current format: spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}
Example: spread_1_20260122_171426_0

Parser accepts:
- v1.1: spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index} (full)
- v1.0: spread_{cycle}_{YYYYMMDD}_{HHMMSS} (no index)
- legacy: spread_{anything}

Key property: tests NEVER flap due to format changes.
```

### Confidence Scoring CONTRACT

```python
# Fixed weights (do not change without migration)
CONFIDENCE_WEIGHTS = {
    "quote_fetch": 0.25,
    "quote_gate": 0.25,
    "rpc": 0.20,
    "freshness": 0.15,
    "adapter": 0.15,
}

# Monotonicity properties:
# - Worse reliability → confidence does not increase
# - Better freshness → confidence does not decrease
```

### Ranking CONTRACT (Deterministic)

```
Sort key (all DESC except spread_id ASC):
  1. is_profitable DESC (True > False)
  2. net_pnl_usdc DESC (higher PnL first)
  3. net_pnl_bps DESC (higher bps first)
  4. confidence DESC (higher confidence first)
  5. spread_id ASC (alphabetical tiebreaker)

Same input → same output order.
```

### Gate Breakdown CONTRACT

```python
GATE_BREAKDOWN_KEYS = frozenset(["revert", "slippage", "infra", "other"])

# Mapping:
# QUOTE_REVERT → revert
# SLIPPAGE_TOO_HIGH → slippage
# INFRA_RPC_ERROR → infra
# * → other
```

### Mode CONTRACT

```bash
python -m strategy.jobs.run_scan --mode smoke  # ✅ SMOKE_SIMULATOR (works)
python -m strategy.jobs.run_scan --mode real   # ❌ RuntimeError (not implemented)
```

No silent mode substitution. If `--mode real` but REGISTRY_REAL not implemented → explicit error.

## Checklist

### ✅ Completed
- [x] Paper trading session tracking
- [x] Truth report generation (schema v3.0.0)
- [x] Reject histogram with canonical gate breakdown
- [x] Scan snapshot with all artifacts
- [x] RPC health metrics reconciliation
- [x] Execution blockers explanation
- [x] spread_id CONTRACT v1.1 (backward compatible)
- [x] Confidence scoring (deterministic + monotonicity)
- [x] Ranking CONTRACT (deterministic sort)
- [x] DEX coverage tracking
- [x] Explicit mode error (no silent substitution)
- [x] CI gate script
- [x] Requirements-dev.txt

### 🟡 M4 Skeleton Created
- [x] execution/state_machine.py
- [x] execution/simulator.py
- [x] execution/dex_dex_executor.py

### ❌ M4 (Not Started)
- [ ] REGISTRY_REAL scanner
- [ ] Live RPC integration
- [ ] Flash swap execution
- [ ] Private mempool submission
- [ ] Post-trade accounting
- [ ] Kill switch implementation

## Test Coverage

```bash
# Unit tests
pytest tests/unit/test_core_models.py -v    # spread_id + confidence
pytest tests/unit/test_truth_report.py -v   # ranking + gate breakdown
pytest tests/unit/test_confidence.py -v     # confidence scoring

# Full suite
pytest -q
```

## M3 → M4 Transition

### M3 Closure Criteria
1. ✅ All tests pass (`pytest -q`)
2. ✅ CI gate passes (`python scripts/ci_m3_gate.py`)
3. ✅ spread_id roundtrip stable
4. ✅ Ranking deterministic
5. ✅ No silent mode substitution
6. ⬜ Code review approved

### M4 Start Criteria
1. ✅ M4 skeleton files created
2. ⬜ M3 PR merged to main
3. ⬜ M4 branch created from main

## Links

- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
- M4 Roadmap: execution layer, flash swaps, kill switch
