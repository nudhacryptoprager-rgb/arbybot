# Status: Milestone 3 (M3) — Opportunity Engine

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-22  
**Branch:** `work/20260122_1739-shortfix`

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
- [x] Schema version policy (SCHEMA_VERSION constant)
- [x] Gate breakdown contract (revert/slippage/infra/other)
- [x] Error code mapping (QUOTE_REVERT ≠ INFRA_RPC_ERROR)
- [x] spread_id/opportunity_id contract
- [x] Preflight validation for quote params
- [x] DEX coverage tracking (configured vs active vs passed)

### 🟡 In Progress
- [ ] Reduce QUOTE_REVERT rate (currently ~20-30%)
- [ ] Improve gate pass rate (target: >70%)
- [ ] REGISTRY_REAL scanner implementation

### ❌ Blocked
- Real RPC integration (requires REGISTRY_REAL implementation)

## Recent Patches

### Patch 2026-01-22: 10-Step Quality Fixes

**Changes:**
1. ✅ `--mode smoke/real` in run_scan.py (no silent redirect)
2. ✅ `configured_dexes` vs `dexes_active` tracking
3. ✅ `gate_breakdown` canonical contract with tests
4. ✅ Error code mapping (QUOTE_REVERT/INFRA separate)
5. ✅ Reduced simulated slippage for better pass rate
6. ✅ Preflight validation for quote params
7. ✅ spread_id/opportunity_id contract with tests
8. ✅ Smoke artifacts contract test
9. ✅ Schema version policy test
10. ✅ WORKFLOW.md status location guidance

**Files Modified:**
- `strategy/jobs/run_scan.py` — explicit --mode
- `strategy/jobs/run_scan_smoke.py` — preflight validation, dex coverage
- `monitoring/truth_report.py` — gate breakdown, dex coverage, error mapping
- `core/models.py` — spread_id contract
- `tests/unit/test_truth_report.py` — schema/gate tests
- `tests/unit/test_core_models.py` — spread_id tests
- `tests/integration/test_smoke_run.py` — artifacts contract test
- `docs/WORKFLOW.md` — status location guidance

**Verify:**
```powershell
# Tests pass
python -m pytest -q

# --mode help works
python -m strategy.jobs.run_scan --help

# --mode real raises RuntimeError
python -m strategy.jobs.run_scan --mode real 2>&1 | Select-String "not yet implemented"

# Smoke run generates all 3 artifacts
python -m strategy.jobs.run_scan --mode smoke --cycles 1 --output-dir data\runs\verify_v10
Get-ChildItem data\runs\verify_v10\snapshots\scan_*.json
Get-ChildItem data\runs\verify_v10\reports\reject_histogram_*.json
Get-ChildItem data\runs\verify_v10\reports\truth_report_*.json
```

## Schema Contract

**Version:** 3.0.0

**Breaking changes require:**
1. Bump SCHEMA_VERSION in `monitoring/truth_report.py`
2. Migration PR
3. Test update (`test_schema_version_policy`)

**Gate Breakdown Contract:**
```json
{
  "gate_breakdown": {
    "revert": 0,
    "slippage": 0,
    "infra": 0,
    "other": 0
  }
}
```

**spread_id Contract:**
- Format: `spread_{cycle}_{timestamp}_{index}`
- Example: `spread_1_20260122_093438_0`

**opportunity_id Contract:**
- Format: `opp_{spread_id}`
- Example: `opp_spread_1_20260122_093438_0`

## Definition of Done (M3 Closure)

- [x] pytest green
- [x] SMOKE artifacts valid (3 files generated)
- [x] top_opportunities non-empty
- [x] reject_reasons classified (STF, etc.)
- [x] execution_blockers explain why not ready
- [x] Schema version policy enforced by test
- [x] Gate breakdown contract enforced by test
- [ ] REGISTRY_REAL scan produces similar structure
- [ ] Golden artifacts in `docs/artifacts/`

## Links

- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/work/20260122_1739-shortfix
- Index: `docs/status/INDEX.md`
