# Status: Milestone 3 (M3) — Opportunity Engine

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-22  
**Branch:** `work/20260122_1816-shortfix`

## Overview

M3 implements the Opportunity Engine: scanning, quoting, gate validation, and truth reporting.

## Current State

### ✅ Completed
- [x] Paper trading session tracking
- [x] Truth report generation with schema v3.0.0
- [x] Reject histogram with gate breakdown
- [x] Scan snapshot with all artifacts
- [x] RPC health metrics reconciliation
- [x] Execution blockers explanation
- [x] **spread_id contract v1.0** (fixed)
- [x] **slippage gate comparator** (fixed)
- [x] DEX coverage tracking (configured vs active vs passed)

### 🟡 In Progress
- [ ] Reduce QUOTE_REVERT rate (currently ~20%)
- [ ] REGISTRY_REAL scanner implementation

### ❌ Blocked
- Real RPC integration (requires REGISTRY_REAL implementation)

## Recent Patches

### Patch 2026-01-22 v11: spread_id Contract Fix + Slippage Gate Fix

**Root Cause:**
1. `parse_spread_id()` expected 4 parts but `spread_1_20260122_171426_0` has 5 parts (timestamp contains underscore)
2. Slippage gate rejected when `slippage_bps=176 < threshold_bps=200` (wrong comparator)

**Changes:**
1. ✅ **spread_id CONTRACT v1.0** — single source of truth in `core/models.py`
   - Format: `spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}`
   - Uses regex pattern: `^spread_(\d+)_(\d{8})_(\d{6})_(\d+)$`
   - `format_spread_timestamp()` — single source for timestamp formatting
   - `generate_spread_id()` — uses `format_spread_timestamp`
   - `parse_spread_id()` — returns structured dict with all components
   - `validate_spread_id()` — quick bool check

2. ✅ **slippage gate CONTRACT**
   - `check_slippage_gate(slippage_bps, threshold_bps)` — returns `True` if `slippage_bps <= threshold_bps`
   - Documented in `_make_slippage_details()`: `"slippage_gate_contract": "PASS if slippage_bps <= threshold_bps"`

3. ✅ **Roundtrip tests** — `generate -> parse -> regenerate` produces same ID

**Files Modified:**
- `core/models.py` — spread_id contract v1.0 with regex validation
- `strategy/jobs/run_scan_smoke.py` — uses `generate_spread_id()` + fixed slippage gate
- `tests/unit/test_core_models.py` — roundtrip tests + real artifact compat test

**Verify:**
```powershell
# 1. Run tests
python -m pytest -q tests\unit\test_core_models.py -v

# 2. Check spread_id roundtrip
python -c "from core.models import generate_spread_id, parse_spread_id; id=generate_spread_id(1,'20260122_171426',0); p=parse_spread_id(id); print(f'ID: {id}, valid: {p[\"valid\"]}, cycle: {p[\"cycle\"]}, ts: {p[\"timestamp\"]}, idx: {p[\"index\"]}')"

# 3. Check real artifact example
python -c "from core.models import parse_spread_id; r=parse_spread_id('spread_1_20260122_171426_0'); print(r)"

# 4. Check slippage gate
python -c "from strategy.jobs.run_scan_smoke import check_slippage_gate; print('176<=200:', check_slippage_gate(176, 200)); print('250<=200:', check_slippage_gate(250, 200))"

# 5. Smoke run
python -m strategy.jobs.run_scan --mode smoke --cycles 1 --output-dir data\runs\verify_v11

# 6. Verify spread_id in artifacts parses
$scan = Get-Content data\runs\verify_v11\snapshots\scan_*.json | ConvertFrom-Json
python -c "from core.models import parse_spread_id; import sys; r=parse_spread_id(sys.argv[1]); print(r)" $scan.all_spreads[0].spread_id
```

## Contracts

### spread_id CONTRACT v1.0

```
Format: spread_{cycle}_{YYYYMMDD}_{HHMMSS}_{index}

When split by "_", produces 5 parts:
  [0] "spread" - literal prefix
  [1] cycle    - int, 1-indexed
  [2] date     - str, YYYYMMDD
  [3] time     - str, HHMMSS
  [4] index    - int, 0-indexed

Example: "spread_1_20260122_171426_0"
  -> cycle=1, date="20260122", time="171426", index=0
```

### opportunity_id CONTRACT

```
Format: "opp_{spread_id}"
Example: "opp_spread_1_20260122_171426_0"
```

### Slippage Gate CONTRACT

```
check_slippage_gate(slippage_bps, threshold_bps):
  - slippage_bps <= threshold_bps -> PASS (return True)
  - slippage_bps > threshold_bps  -> FAIL (SLIPPAGE_TOO_HIGH)

Example:
  check_slippage_gate(176, 200) -> True  (passes)
  check_slippage_gate(250, 200) -> False (fails)
```

### Scan/TruthReport SEMANTIC CONTRACT

```
opportunities: 
  Spreads that pass all gates AND are profitable.
  Execution candidates.

all_spreads:
  All evaluated spreads (including rejected/unprofitable).
  For debugging/analysis.

top_opportunities (in truth_report):
  Top-N by PnL, may include non-profitable for debugging.
  Each has execution_blockers explaining why not execution-ready.
```

## Definition of Done (M3 Closure)

- [x] pytest green
- [x] spread_id roundtrip stable
- [x] slippage gate comparator correct
- [x] SMOKE artifacts valid (3 files generated)
- [x] top_opportunities non-empty
- [x] reject_reasons classified (STF, etc.)
- [x] execution_blockers explain why not ready
- [ ] REGISTRY_REAL scan produces similar structure
- [ ] Golden artifacts in `docs/artifacts/`

## Links

- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/work/20260122_1816-shortfix
- Index: `docs/status/INDEX.md`
