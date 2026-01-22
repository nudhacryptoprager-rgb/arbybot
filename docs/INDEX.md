# Status Index

_Last updated: 2026-01-22_

## Active Milestones

| Milestone | Status | Latest SHA | Latest Artifacts |
|-----------|--------|------------|------------------|
| M0 — Bootstrap + Quote Pipeline | ✅ Done | - | - |
| M1 — Real Gas Price + Paper Trading | ✅ Done | - | - |
| M2 — Registry-driven scanning + Truth Report | ✅ Done | - | - |
| M3 — Opportunity Engine + Quality | 🔶 Code Done | `52834c0` | `data/runs/verify_v7/` |

## Current Focus

**M3 — Opportunity Engine** is code-complete but awaiting validation on REAL scan.

### Latest Patch: 2026-01-22 — Quality improvements
- execution_blockers field explains why not ready
- STF classifier for QUOTE_REVERT
- Unified units (amount_in_token vs amount_in_numeraire)
- gate_breakdown in health section
- Adaptive slippage for SMOKE mode

### Definition of Done for M3
1. ✅ pytest green
2. ✅ SMOKE artifacts valid
3. ❌ **REGISTRY_REAL scan required**
4. ❌ **Golden artifacts in docs/artifacts/**

## Quick Links
- [Status_M0.md](Status_M0.md) — Bootstrap
- [Status_M1.md](Status_M1.md) — Gas + Paper Trading
- [Status_M2.md](Status_M2.md) — Registry + Truth Report
- [Status_M3.md](Status_M3.md) — Opportunity Engine (current)
- [ARCHIVE_MAP.md](ARCHIVE_MAP.md) — Historical documents

## Verify Commands
```powershell
# Full test suite
python -m pytest -q

# Smoke scan
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\verify

# Check artifacts
Get-ChildItem data\runs\verify\reports\
```

## Rules
1. One active Status per milestone
2. New patches = new section in existing file (not new file)
3. Old versions go to `archive/`
4. No spaces in filenames
5. Update this INDEX with each patch (SHA + date)
