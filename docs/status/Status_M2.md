# Status M2 — Registry-driven scanning + Truth Report baseline

_Last cleaned: 2026-01-21_

## Scope
M2 stabilizes the scan pipeline end-to-end in “registry-driven” mode and produces reliable artifacts:
- snapshots (`scan_*.json`)
- reject histogram (`reject_histogram_*.json`)
- truth report (`truth_report_*.json`)
- paper trades (`paper_trades*.jsonl`) where applicable

## Done (from existing M2 docs)
- Registry-driven pipeline wiring (pairs/pools discovery feeding the scan loop).
- P0 fixes that make truth_report + reject_histogram usable for diagnosis.
- M2.3 indicates readiness to proceed into M3 opportunity engine work once contracts are stable.

## Evidence
Source documents:
- `docs/Status_M2.md`
- `docs/Status_M2.1.md`
- `docs/Status_M2.2.md`
- `docs/Status_M2_P0_fixes.md`
- `docs/Status_M2.3.md`

## Known gaps / risks
- Quality depends on stable schema contracts (truth_report / histogram / snapshot).
- RPC instability will show as INFRA_* rejects and reduces apparent coverage.

## Verify (Windows / PowerShell)
```powershell
python -m pytest -q
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\smoke_m2_check
```
