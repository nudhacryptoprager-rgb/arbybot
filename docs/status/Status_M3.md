# Status M3 — Opportunity Engine + Quality & Contracts hardening

_Last cleaned: 2026-01-21_

## Scope
M3 focuses on producing high-quality opportunities from scan data, with strict schema/contracts and diagnostics:
- opportunities from spreads (incl. confidence scoring / ranking where present)
- stable truth_report + reject_histogram contracts
- gating clarity (price sanity, slippage, infra errors)
- paper-trading traceability (trade ↔ opportunity ↔ spread)

## Progress summary (from existing M3 docs)
### P0 — Fixes
- Stabilization fixes required by team lead review (P0 fixes doc).

### P1 — Quality cleanup
- Cleanup aimed at reducing noisy rejects and improving truth_report usefulness.

### P2 — Quality iterations (v2→v4)
- Multiple quality iterations; v4 is the latest status document in this series.

### P3 — Contracts + 10-step critical fix
- Contracts fixes for core models / truth_report schema.
- 10-step “critical fixes” consolidated into a single narrative (latest = v3).

## Evidence
Source documents:
- `docs/Status_M3.md`
- `docs/Status_M3_P0_fixes_1.md`
- `docs/Status_M3_P1_quality_cleanup.md`
- `docs/Status_M3_P2_quality_v2.md`
- `docs/Status_M3_P2_quality_v3.md`
- `docs/Status_M3_P2_quality_v4.md`
- `docs/Status_M3_P3_contracts_fix.md`
- `docs/Status_M3_P3_contracts_fix_v2.md`
- `docs/Status_M3_P3_10step_fix.md`
- `docs/Status_10step_fix_v2.md`
- `docs/Status_10step_fix_v3.md`  ← **source of truth for the latest “10-step” series**

## Rules for future changes (non-negotiable)
- Any schema change: either keep backward compatibility OR bump schema_version and update tests + docs together.
- Keep exactly **one** “active” status per subphase; older variants go to archive.

## Verify (Windows / PowerShell)
```powershell
python -m pytest -q
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\smoke_m3_check
```
