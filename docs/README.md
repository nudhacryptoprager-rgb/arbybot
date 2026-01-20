# Golden Fixtures: Smoke Test Baseline

This directory contains reference artifacts from smoke test runs.
These are committed to git as reproducible baselines for review.

## Contents

- `scan_*.json` - Scan snapshot with stats, reject histogram, opportunities
- `truth_report_*.json` - Truth report with health, PnL, RPC metrics
- `reject_histogram_*.json` - Reject reason counts
- `scan.log.txt` - Log file (renamed from .log for git)

## Usage

Compare new smoke runs against these baselines:

```powershell
# Run smoke test
python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/verify

# Compare outputs
diff data/runs/verify/reports/truth_report_*.json docs/artifacts/smoke/*/truth_report_*.json
```

## When to Update

Update golden fixtures when:
1. Schema changes (new fields added)
2. Logic changes (different reject reasons)
3. Significant improvement in metrics

Always document changes in PR description.

## Structure

```
docs/artifacts/smoke/
└── YYYYMMDD/
    ├── README.md
    ├── scan_YYYYMMDD_HHMMSS.json
    ├── truth_report_YYYYMMDD_HHMMSS.json
    ├── reject_histogram_YYYYMMDD_HHMMSS.json
    └── scan.log.txt
```
