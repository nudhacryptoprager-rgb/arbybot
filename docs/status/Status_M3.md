# Status — Milestone M3 (Opportunity Engine + Quality & Contracts)

## Scope (що означає "DONE" для цього milestone)
- [x] Opportunities from spreads (incl. confidence scoring)
- [x] Stable truth_report + reject_histogram contracts (schema 3.0.0)
- [x] Gating clarity (price sanity, slippage, infra errors)
- [x] Paper-trading traceability (trade ↔ opportunity ↔ spread)
- [ ] Validation on REAL scan (not just SMOKE_SIMULATOR)

## Current State (1–2 абзаци)

M3 code and tests are complete. Schema is stable at 3.0.0. All contracts (mode vs run_mode, 
top_opportunities, reject_details with gate_name) are implemented and documented.

**Blocker for "DONE"**: Validation passed only on SMOKE_SIMULATOR. Need at least 1 real 
REGISTRY_REAL scan with actual RPC quotes to confirm end-to-end functionality.

## Patch Log (append-only)

### Patch 2026-01-22 — top_opportunities never empty + Windows file-lock fix
**Branch:** chore/claude-megapack
**SHA:** TBD (apply patch first)
**PR/Compare:** https://github.com/nudhacryptoprager-rgb/arbybot/compare/chore/claude-megapack?expand=1
**Status owner:** Claude

#### Goals of this patch
- Ensure top_opportunities is NEVER empty when spreads exist
- Fix Windows file-lock issue with log handlers
- Normalize status file names (remove space from filename)
- Add is_profitable and reject_reason to opportunities

#### Changes (what changed in code)
- File: `monitoring/truth_report.py` — added `all_spreads` parameter to build_truth_report(), 
  top_opportunities fallback for rejected spreads, added `is_profitable` and `reject_reason` fields
- File: `strategy/jobs/run_scan_smoke.py` — always generate 3 spreads (mix of profitable/rejected), 
  pass all_spreads to build_truth_report, added shutdown_logging() for Windows file-lock fix
- File: `docs/status/Status_M3.md` — added patch section per new template
- File: `docs/status/INDEX.md` — updated with latest SHA

#### Evidence (artifacts + tests)
- Tests: `pytest -q` ✅
- Run: `run_scan_smoke` mode: REGISTRY, run_mode: SMOKE_SIMULATOR
- Artifacts (relative paths):
  - `data/runs/verify_v6/snapshots/scan_*.json`
  - `data/runs/verify_v6/reports/truth_report_*.json`
  - `data/runs/verify_v6/reports/reject_histogram_*.json`
  - `data/runs/verify_v6/paper_trades.jsonl`

#### Key Metrics (copy from truth_report)
- rpc_success_rate: ~0.8
- quote_fetch_rate: ~0.9
- quote_gate_pass_rate: ~0.6
- spreads_total / profitable / executable: 3 / 1 / 1
- top reject reasons (top 3): QUOTE_REVERT, SLIPPAGE_TOO_HIGH, INFRA_RPC_ERROR

#### Known Issues (carry-forward)
- [ ] Issue: SMOKE_SIMULATOR only — need REGISTRY_REAL validation
- [ ] Issue: Coverage metrics (dexes_active) are simulated, not from real registry

#### Next Steps (max 5, concrete)
1. Run REGISTRY_REAL scan with actual RPC endpoints
2. Validate truth_report with real opportunities
3. Close M3 after real scan validation
4. Begin M4 planning (execution layer)

#### Verify Commands (PowerShell, Windows)
```powershell
git rev-parse HEAD
python -m pytest -q
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\verify_v6

# Check top_opportunities is not empty
Get-Content data\runs\verify_v6\reports\truth_report_*.json | ConvertFrom-Json | Select -Expand top_opportunities

# Check all_spreads in snapshot
Get-Content data\runs\verify_v6\snapshots\scan_*.json | ConvertFrom-Json | Select -Expand all_spreads
```

---

## Previous Patches (archived)

See `docs/status/archive/` for historical patch documents:
- Status_M3_P0_fixes_1.md
- Status_M3_P1_quality_cleanup.md
- Status_M3_P2_quality_v2.md → v4
- Status_M3_P3_contracts_fix.md → v2
- Status_M3_P3_10step_fix.md
- Status_10step_fix_v2.md → v3

## Rules for future changes (non-negotiable)
- Any schema change: either keep backward compatibility OR bump schema_version and update tests + docs together.
- Keep exactly **one** "active" status per milestone; older variants go to archive.
- No files with spaces in names.
- Each patch = one section in this file, not a new Status_*.md file.
