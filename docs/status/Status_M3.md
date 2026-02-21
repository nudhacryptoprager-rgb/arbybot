# Status: Milestone 3 (M3) - Opportunity Engine

**Status:** [DONE]
**Updated:** 2026-01-23 (historical milestone closure)
**Evidence (historical):** `data/runs/ci_m3_gate_20260123_110359`

M3 is CLOSED and this file is FROZEN. Any new work belongs to the next milestone Status file.

## Proof (Historical)

Minimum proof for M3 closure (historical):
- `py -3.11 -m pytest -q` -> PASS
- `py -3.11 scripts/ci_m3_gate.py` -> PASS

Notes:
- This repo is SHA-free for provenance in v2.x. Do not use git SHA as evidence.
- Keep the runDir path above as the historical reference for M3.

## M3 Gate Artifacts (Historical)

Expected artifact families produced by smoke:
- `reports/scan_*.json`
- `reports/reject_histogram_*.json`
- `reports/truth_report_*.json`
- `scan.log`

## Commands (Windows PowerShell)

```powershell
# Always use Python 3.11 on Windows
py -0p
py -3.11 --version

# Unit tests
py -3.11 -m pytest -q

# M3 gate
py -3.11 scripts/ci_m3_gate.py

# Manual smoke run
py -3.11 -m strategy.jobs.run_scan --mode smoke --cycles 1 --output-dir data/runs/manual_test
```

## Frozen Contracts (M3)

This milestone locked deterministic ranking and stable artifact emission for SMOKE scanning.

### Ranking Contract (Deterministic)

Sort key:
`is_profitable` DESC -> `net_pnl_usdc` DESC -> `net_pnl_bps` DESC -> `confidence` DESC -> `spread_id` ASC

### Gate Breakdown Contract

`GATE_BREAKDOWN_KEYS = {"revert", "slippage", "infra", "other"}`

## Links

- Evidence runDir (historical): `data/runs/ci_m3_gate_20260123_110359`
- Next milestone: `docs/status/Status_M4.md`
- Source of truth: `Roadmap.md`

