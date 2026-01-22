# WIP: split/code Quality Fixes

**Branch:** `split/code`  
**Base SHA:** `fb42518a2d69f9d15d2cef7bbe21af56bb2afad9`  
**Date:** 2026-01-22  
**Owner:** Claude

## What Was Done

This patch resolves merge conflicts and implements 10 quality fixes:

1. ✅ **Status file created** (this file)
2. ✅ **Merge conflicts resolved** in truth_report.py and run_scan_smoke.py
3. ✅ **TruthReport API contract** documented with backward compatibility note
4. ✅ **Simulated reject_details** marked with `source: "SMOKE_SIMULATOR"`
5. ✅ **Retry promise clarified** as "planned, not implemented"
6. ✅ **Single source for stats** via `build_scan_stats()` function
7. ✅ **Dex coverage honest** with `simulated_dex: true` flag
8. ✅ **Warning clarified** to be more specific
9. ✅ **Artifact policy** documented below
10. ✅ **Tests updated** with run_mode, schema_version, top_reject_reasons asserts

## What Changed

### monitoring/truth_report.py
- Merged both conflict branches
- Schema contract comment: "3.0.0 — keep backward compatible"
- `chain_id` in all opportunities
- No ambiguous `amount_in` field (only `amount_in_numeraire`)
- `paper_executable_spreads` terminology

### strategy/jobs/run_scan_smoke.py
- `source: "SMOKE_SIMULATOR"` in all reject_details
- `simulated_dex: true` in stats for SMOKE mode
- `chain_id` in all reject_details
- `slippage_basis` and `slippage_formula` documented
- `gate_breakdown` synced between scan.json and truth_report
- Retry note clarified: "PLANNED (not yet implemented)"

### tests/unit/test_truth_report.py
- `test_schema_version_policy()` — ensures SCHEMA_VERSION is constant
- `test_run_mode_in_report()` — validates run_mode field
- `test_top_reject_reasons_format()` — validates format [[reason, count], ...]

## How to Verify

```powershell
# 1. Check no merge conflicts
git status

# 2. Syntax check
python -m compileall monitoring strategy -q

# 3. Run tests
python -m pytest -q tests\unit\test_truth_report.py
python -m pytest -q

# 4. Smoke run
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\verify_v9

# 5. Check simulated marker
Get-Content data\runs\verify_v9\snapshots\scan_*.json | ConvertFrom-Json | Select -Expand sample_rejects | Select -First 1 | Select -Expand reject_details | Select source

# 6. Check chain_id in reject_details
Get-Content data\runs\verify_v9\snapshots\scan_*.json | ConvertFrom-Json | Select -Expand sample_rejects | Select -First 1 | Select -Expand reject_details | Select chain_id
```

## What Remains

- [ ] REGISTRY_REAL scan validation (not SMOKE)
- [ ] Golden artifacts in docs/artifacts/
- [ ] Actual retry implementation (currently documented as "planned")

## Artifact Policy

**Rule:** `data/runs/**` is NOT committed to git.

- **Local runs:** `data/runs/<timestamp>/` — for development, debugging
- **Golden artifacts:** `docs/artifacts/<YYYY-MM-DD>/<session>/` — committed only when validating milestone
- **Reports:** Only truth_report, reject_histogram, scan snapshot for golden

**Rationale:** Prevents repo bloat; keeps diagnostic data local.

## Contract Stability

**TruthReport Schema 3.0.0** — DO NOT modify fields without:
1. Bump SCHEMA_VERSION constant
2. Migration PR
3. Test update

**Backward Compatibility Fields:**
- `spread_ids_executable` (deprecated, use `paper_executable_spreads`)
- `signals_*` mirrors `spread_ids_*`

## Links

- Artifacts (local): `data/runs/verify_v9/`
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
