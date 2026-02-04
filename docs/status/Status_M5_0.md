# Status: M5_0 Infrastructure Hardening

**Status**: IN PROGRESS  
**Last Updated**: 2026-02-01

## Overview

M5_0 focuses on API stability and import contract hardening after 4 waves of "Enum drift" broke core.models imports.

## API Stability Policy (GUARDRAIL)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PUBLIC SYMBOLS ONLY GROW, NEVER DISAPPEAR.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If renamed → MUST provide alias: OldName = NewName
If deprecated → MUST keep alias for 2 milestones minimum

Any rename/delete in core.constants without alias → M5_0 "not Done"
```

## Enum Drift History

| Wave | Symbol | Status |
|------|--------|--------|
| 1 | DexType | ✅ Fixed |
| 2 | TokenStatus | ✅ Fixed |
| 3 | PoolStatus | ✅ Fixed |
| 4 | TradeDirection | ✅ Fixed |

## Required Public Symbols (core.constants)

```python
# Enums - DO NOT REMOVE
DexType
TokenStatus
PoolStatus
TradeDirection   # ← Wave 4 fix
ExecutionBlocker

# Constants - DO NOT REMOVE
ANCHOR_DEX_PRIORITY
PRICE_SANITY_BOUNDS
PRICE_SANITY_MAX_DEVIATION_BPS
CURRENT_EXECUTION_BLOCKER
SCHEMA_VERSION
CHAIN_IDS
DEX_IDS
DEFAULT_QUOTE_AMOUNT_WEI
```

## CI Gate v2.0.0

### Canonical Commands

```bash
# Offline (ALWAYS works, IGNORES ALL ENV)
python scripts/ci_m5_0_gate.py --offline

# Online (runs real scan)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL validation |
| 2 | FAIL missing artifacts |
| 3 | FAIL scanner error |

## Test Import Contract

The "police" test catches Enum drift before suite fails:

```bash
# Run FIRST (< 0.2 seconds)
python -m pytest tests/unit/test_imports_contract.py -v

# If it fails → restore symbol in core/constants.py
# DO NOT weaken the test!
```

## Definition of Done

- [x] TradeDirection restored in core.constants
- [x] test_imports_contract.py covers all 5 Enums
- [x] "constants must not shrink" regression test
- [x] ci_m5_0_gate.py --offline works
- [x] API Stability Policy documented
- [ ] core.models imports without error (needs repo sync)
- [ ] Full test suite green (needs repo sync)

## REAL Block Policy (M5_0)

- **REAL_BLOCK must be fetched from RPC**: runs with `run_mode=REGISTRY_REAL` or when `--online` are required to pin the current block via RPC provider. Sentinel values (0, 1, 999999999) are forbidden and indicate a failed block pin.
- **Gate behavior**: `scripts/ci_m5_0_gate.py --online` will fail with a clear message if the produced `truth_report` contains a sentinel `current_block` value (exit code 1).
- **Scanner behavior**: `strategy.jobs.run_scan_real` will attempt to obtain the block via the RPC provider registry and raise `core.exceptions.BlockPinError` (ErrorCode.INFRA_BLOCK_PIN_FAILED) if pinning fails instead of writing a fake sentinel block.
- **Reject diagnostics**: validators must always expose `deviation_bps_raw` (unclamped) and `deviation_bps` (clamped to caller `max_deviation_bps`) and `deviation_bps_capped` flag should be `true` when raw > requested max.
 - **Reject diagnostics**: validators must always expose `deviation_bps_raw` (unclamped) and `deviation_bps` (clamped to caller `max_deviation_bps`) and `deviation_bps_capped` flag should be `true` when raw > requested max.
 - **CAP semantics**: CI gate will now reject runs where any `reject_histogram` entry has `deviation_bps_raw > max_deviation_bps` but `deviation_bps_capped` is false.

## Files Changed

| File | Change |
|------|--------|
| core/constants.py | +TradeDirection, API stability comment |
| core/validators.py | AnchorQuote.dex_id required |
| monitoring/__init__.py | Export all symbols |
| monitoring/truth_report.py | EXECUTION_DISABLED (not _M4) |
| scripts/ci_m5_0_gate.py | v2.0.0, --offline/--online |
| tests/unit/test_imports_contract.py | +TradeDirection, regression guard |
| tests/unit/test_ci_m5_0_gate.py | Mode tests |
| docs/status/Status_M5_0.md | API stability policy |

## Apply Commands

```powershell
# Copy files
Copy-Item outputs/core/constants.py core/
Copy-Item outputs/core/validators.py core/
Copy-Item outputs/monitoring/__init__.py monitoring/
Copy-Item outputs/monitoring/truth_report.py monitoring/
Copy-Item outputs/scripts/ci_m5_0_gate.py scripts/
Copy-Item outputs/tests/unit/test_imports_contract.py tests/unit/
Copy-Item outputs/tests/unit/test_ci_m5_0_gate.py tests/unit/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# Run import tests FIRST
python -m pytest tests/unit/test_imports_contract.py -v

# Verify core.models imports
python -c "import core.models; print('core.models ok')"

# Run gate
python scripts/ci_m5_0_gate.py --offline

# Commit
git add -A
git commit -m "fix(M5_0): TradeDirection (wave 4) + API stability policy"
```

## Recent Compatibility Fixes (claude iteration)

- Restored compatibility wrappers in `monitoring/truth_report.py`:
	- `build_truth_report`, `build_health_section`, `build_gate_breakdown`, `calculate_price_stability_factor`, `calculate_confidence` (float-returning wrapper) and `calculate_confidence_label` (legacy label helper).
	- `RPCHealthMetrics` regained `rpc_success_count`, `rpc_fail_count`, `rpc_latency_ms_total` and `record_rpc_call()` method.
- Restored integration entrypoints in `strategy/jobs/run_scan_real.py`:
	- `run_scanner(...)` wrapper, `check_price_sanity(...)` delegating to `core.validators`, and `Quote` re-export alias.

## Recent Fixes (2026-02-04T00:00:00Z)

Summary: applied compatibility-layer fixes to restore public API contracts for monitoring, validators, and real/smoke scanners; added an adapter for `Quote` to accept legacy kwargs; ensured CI gate offline/online modes and cap semantics. Full unit test suite now passes locally.

- **Tests:** `python -m pytest -q` → 424 passed (local run on 2026-02-04)

Files changed in this iteration:

- `monitoring/truth_report.py` — restored facade (RPCHealthMetrics, TruthReport.save, helpers)
- `strategy/jobs/run_scan_real.py` — run_scanner, check_price_sanity wrapper, Quote adapter to accept legacy kwargs and preserve `rpc_success`/`gate_passed`, artifact fixes (pnl, quotes_sample)
- `core/validators.py` — deviation cap semantics, diagnostics (deviation_bps_raw, deviation_bps, deviation_bps_capped)
- `core/constants.py` — ensured required public symbols exist (Enums, SCHEMA_VERSION)
- `scripts/ci_m5_0_gate.py` — offline/online modes and cap-consistency validation

Notes & Next steps:

- Keep compatibility wrappers for two milestones and plan migration of callers to canonical implementations.
- Recommend adding focused unit tests for `Quote` adapter and cap-edge-case rejects (I can add these next).


### How to verify

Run the following commands locally:

```bash
python -m pytest tests/unit/test_truth_report.py -q
python -m pytest tests/unit/test_confidence.py -q
python -m pytest tests/integration/test_smoke_run.py -q
python scripts/ci_m5_0_gate.py --offline
```

### Risks and plan

- These are lightweight compatibility wrappers to restore public API surface; plan is to keep wrappers for two milestones and then migrate callers to new implementations.
- Risk: If underlying implementations were intentionally changed, wrappers may mask deeper semantic shifts. Next step: add tests asserting semantic behavior and schedule migration.

