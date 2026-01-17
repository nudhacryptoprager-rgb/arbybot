## Summary
- What changed:

## Status updated
- [ ] Updated docs/Status_*.md

## Run evidence (required for scan-related PRs)
- [ ] pinned block != null
- [ ] quotes_fetched >= 1
- [ ] snapshot contains quotes + real reject reasons

## How to reproduce
- Scan:
  - `python -m strategy.jobs.run_scan --chain arbitrum_one --once --no-json-logs`
- Tests:
  - `pytest -q`

## Artifacts (links in repo)
- Run folder: `data/runs/YYYY-MM-DD/<run_id>/`
- truth_report:
- reject_histogram:
- snapshot(s):
- scan.log.txt:

## Notes / risks
- gates/adapters/rpc:
