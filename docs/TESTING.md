# ARBY3 Testing Guide

_Last cleaned: 2026-01-21_

## Quick commands (Windows / PowerShell)
Run all tests:
```powershell
python -m pytest -q
```

Run smoke scan (writes artifacts):
```powershell
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$out = "data\runs\session_$ts"
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir $out
```

## What “green” means
A change is acceptable only if:
- `python -m pytest -q` is green
- smoke scan produces:
  - snapshot `snapshots\scan_*.json`
  - reports `reports\truth_report_*.json` and `reports\reject_histogram_*.json`
  - (optional) `paper_trades*.jsonl`

## CI note
If CI fails but local is green, treat CI as source of truth and fix CI first.
