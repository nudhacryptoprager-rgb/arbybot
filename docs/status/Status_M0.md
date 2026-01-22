# Status M0 — Bootstrap + Quote Pipeline Foundation

_Last cleaned: 2026-01-21_

## Scope
M0 covers project bootstrap: repository structure, CLI entrypoints, logging, core models/errors, plus initial quote-pipeline accounting needed to produce snapshots/reject reasons.

## Done (from existing Status_M0 + Status_M0_1)
- Repository skeleton + packaging, basic config, CLI entrypoints.
- Structured logging foundation.
- Core “no-float” model layer and error taxonomy.
- Quote pipeline accounting & diagnostics:
  - Pipeline stage metrics (attempted/fetched/passed).
  - Reject reasons captured (incl. curve-related rejects).
  - Snapshot enriched with `sqrt_price_x96_after`, `implied_price`.
  - Snapshot includes `dexes_passed_gate`.
  - Reject histogram has top samples and negative-slippage rejection.
  - Raw spread detection (`spread_bps`) available for downstream opportunity engine.

## Evidence
Source documents:
- `docs/Status_M0.md`
- `docs/Status_M0_1.md`

## Known gaps / risks
- This milestone is “foundation”: it does not guarantee real execution, only consistent data + artifacts.
- Any future schema changes must keep backward compatibility or bump schema explicitly.

## Verify (Windows / PowerShell)
```powershell
python -m pytest -q
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\smoke_m0_check
```
