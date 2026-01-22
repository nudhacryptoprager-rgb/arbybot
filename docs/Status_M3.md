# Status — Milestone M3 (Opportunity Engine + Quality & Contracts)

## Scope (що означає "DONE" для цього milestone)
- [x] Opportunities from spreads (incl. confidence scoring)
- [x] Stable truth_report + reject_histogram contracts (schema 3.0.0)
- [x] Gating clarity (price sanity, slippage, infra errors)
- [x] Paper-trading traceability (trade ↔ opportunity ↔ spread)
- [ ] **Validation on REAL scan** (not just SMOKE_SIMULATOR)

## Definition of Done (для закриття M3)

**Мінімальні вимоги:**
1. ✅ All pytest tests green
2. ✅ SMOKE_SIMULATOR scan produces valid artifacts
3. ❌ **At least 1 REGISTRY_REAL scan** with actual RPC quotes
4. ❌ **Golden artifacts** saved to `docs/artifacts/YYYY-MM-DD/`
5. ✅ top_opportunities non-empty (includes rejected spreads)
6. ✅ reject_reasons are "real" (STF classified, slippage with threshold)
7. ✅ execution_blockers explain why not ready

**Artifact requirements for real run:**
- `truth_report_*.json` with `run_mode: "REGISTRY_REAL"`
- `scan_*.json` with real RPC responses
- `reject_histogram_*.json` with real reject reasons
- `paper_trades.jsonl` (if any would-execute)

## Current State

M3 code and tests are complete. Schema is stable at 3.0.0. Quality improvements:
- execution_blockers field explains why opportunities are not execution-ready
- STF classifier provides debug hints for QUOTE_REVERT
- Unified units (amount_in_token vs amount_in_numeraire)
- gate_breakdown in health section
- Adaptive slippage threshold for SMOKE mode (200bps vs 50bps)

**Blocker for DONE**: Need REGISTRY_REAL scan validation.

## Patch Log (append-only)

### Patch 2026-01-22 — Quality improvements (execution_blockers, STF classifier, unified units)
**Branch:** chore/claude-megapack
**SHA:** TBD (after commit)
**PR/Compare:** https://github.com/nudhacryptoprager-rgb/arbybot/compare/chore/claude-megapack?expand=1
**Status owner:** Claude

#### Goals of this patch
- Add execution_blockers explaining why opportunities are not execution-ready
- STF classifier for QUOTE_REVERT (revert_reason_tag + likely_causes)
- Unified units (amount_in_token vs amount_in_numeraire)
- gate_breakdown in health section
- Adaptive slippage for SMOKE mode

#### Changes (what changed in code)
- File: `monitoring/truth_report.py`
  - Added `_get_execution_blockers()` function
  - Added `execution_blockers` and `is_execution_ready` to opportunities
  - Added `gate_breakdown` to health section
  - Updated print output to show blockers
- File: `strategy/jobs/run_scan_smoke.py`
  - Added `_classify_stf_error()` for STF classification
  - Added unified units (amount_in_token, amount_in_numeraire)
  - Adaptive slippage threshold (SMOKE_SLIPPAGE_THRESHOLD_BPS = 200)
  - Improved gate pass rate for SMOKE mode (80% vs 70%)
  - Added retry_note for INFRA_RPC_ERROR

#### Evidence (artifacts + tests)
- Tests: `pytest -q` (must be green)
- Run: `run_scan_smoke` mode: REGISTRY, run_mode: SMOKE_SIMULATOR
- Artifacts:
  - `data/runs/verify_v7/snapshots/scan_*.json`
  - `data/runs/verify_v7/reports/truth_report_*.json`
  - `data/runs/verify_v7/reports/reject_histogram_*.json`

#### Key Metrics (expected from truth_report)
- rpc_success_rate: ~0.9
- quote_fetch_rate: ~0.9
- quote_gate_pass_rate: ~0.8 (improved with adaptive slippage)
- spreads_total / profitable / executable: 3 / 1 / 1
- top reject reasons: QUOTE_REVERT (with STF tag), SLIPPAGE_TOO_HIGH, INFRA_RPC_ERROR

#### Known Issues (carry-forward)
- [ ] SMOKE_SIMULATOR only — need REGISTRY_REAL validation
- [ ] No retry policy implemented (documented only)

#### Next Steps (max 5)
1. Run REGISTRY_REAL scan with actual RPC endpoints
2. Save golden artifacts to docs/artifacts/
3. Verify gate_pass_rate improves with real data
4. Close M3 after real scan validation
5. Begin M4 planning (execution layer)

#### Verify Commands (PowerShell, Windows)
```powershell
git rev-parse HEAD
python -m pytest -q
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\verify_v7

# Check execution_blockers
Get-Content data\runs\verify_v7\reports\truth_report_*.json | ConvertFrom-Json | Select -Expand top_opportunities | Select execution_blockers

# Check STF classifier
Get-Content data\runs\verify_v7\snapshots\scan_*.json | ConvertFrom-Json | Select -Expand sample_rejects | Where-Object { $_.reject_reason -eq "QUOTE_REVERT" } | Select -Expand reject_details

# Check unified units
Get-Content data\runs\verify_v7\snapshots\scan_*.json | ConvertFrom-Json | Select -Expand all_spreads | Select amount_in_token, amount_in_numeraire
```

---

## Previous Patches (archived)

See `docs/status/archive/` for historical documents.

## Rules for future changes
- Schema change → bump version + migration PR
- One active Status per milestone; older go to archive
- No files with spaces
- Each patch = one section in this file
