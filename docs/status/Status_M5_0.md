# Status: M5_0 Infrastructure Hardening

**Status**: ✅ DONE  
**Last Updated**: 2026-02-09  
**Closure SHA**: `93c08b0`  
**Final RunDir**: `data/runs/ci_m5_gate_20260208_113637`

## Closure Summary

M5_0 is **frozen**. Any future changes require a separate PR with clear ROI justification.

**Key invariants preserved**:
- `execution_enabled=false` in all M5_0/M5 modes (no side-effects)
- Offline fixtures use `infra.rpc_provider="fixture"` (minimal, not fake-real)
- WARN skipped in fixtures mode (documented below)
- Gate v2.1.0 stable

**Reproduction commands**:
```bash
# Offline gate (0 WARN)
python scripts/ci_m5_0_gate.py --offline --strict

# Online gate (real scan)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

---

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
- [x] core.models imports without error
- [x] Full unit test suite green locally
- [x] Integration smoke tests are opt-in (ARBY_RUN_INTEGRATION / ARBY_ONLINE_TESTS)
 - [ ] DoD enforcement: online gate must run with strict checks (require-infra-hosts + require-cross-artifact) by default

Known gaps:

- infra.tenderly_ok/tenderly_error: tenderly diagnostics added but not fully exercised in CI (no network calls by default); values may be `not_checked` until a tenderly check is implemented.

## REAL Block Policy (M5_0)

- **REAL_BLOCK must be fetched from RPC**: runs with `run_mode=REGISTRY_REAL` or when `--online` are required to pin the current block via RPC provider. Sentinel values (0, 1, 999999999) are forbidden and indicate a failed block pin.
- **Gate behavior**: `scripts/ci_m5_0_gate.py --online` will fail with a clear message if the produced `truth_report` contains a sentinel `current_block` value (exit code 1).
- **Scanner behavior**: `strategy.jobs.run_scan_real` will attempt to obtain the block via the RPC provider registry and raise `core.exceptions.BlockPinError` (ErrorCode.INFRA_BLOCK_PIN_FAILED) if pinning fails instead of writing a fake sentinel block.
- **Reject diagnostics**: validators must always expose `deviation_bps_raw` (unclamped) and `deviation_bps` (clamped to caller `max_deviation_bps`) and `deviation_bps_capped` flag should be `true` when raw > requested max.
 - **Reject diagnostics**: validators must always expose `deviation_bps_raw` (unclamped) and `deviation_bps` (clamped to caller `max_deviation_bps`) and `deviation_bps_capped` flag should be `true` when raw > requested max.
 - **CAP semantics**: CI gate will now reject runs where any `reject_histogram` entry has `deviation_bps_raw > max_deviation_bps` but `deviation_bps_capped` is false.

## RPC / Infra Contract (M5_0 enhancements)

- The gate now resolves RPC endpoints from environment using a single source-of-truth logic:
	1. Explicit `ALCHEMY_RPC_HTTP` / `ALCHEMY_RPC_WS` (highest priority).
	2. `ALCHEMY_API_KEY` + `NETWORK`/`chain_id` (build Alchemy HTTP/WS via `core.rpc_urls`).
	3. Public fallback for the canonical network.

- Supported canonical networks: `arbitrum`, `base`, `linea`, `mantle` (aliases: `arbitrum_one` → `arbitrum`).

- The gate sets `ARBY_RPC_HTTP_PRIMARY` / `ARBY_RPC_WS_PRIMARY` in the scanner subprocess env to ensure the scanner uses the resolved provider.

- Artifacts now include a small `infra` section (no secrets): `rpc_provider`, `transport`, `ws_enabled`, `ws_connected`, `ws_error`, `tenderly_enabled`.

- WS is optional by default. The gate exposes flags and an optional CLI switch to require WS (`--ws-required`).

- Tenderly is optional. If `TENDERLY_ACCESS_KEY` (and related vars) present, `infra.tenderly_enabled=true` is written; otherwise `false`.

DoD enforcement note:

- The gate now promotes a strict M5_0 profile for DoD: when running `--online`, the gate will enable `require-infra-hosts` and `require-cross-artifact` checks by default to prevent PASS with semantically-invalid data. `tenderly` remains optional and is enforced only when `--require-tenderly` is explicitly provided.

Blockers to resolve before DoD online runs:

- BLOCKER: RPC host mismatch — runs must not map `chain_id=42161` to a `mantle-` host (scan/truth infra must reflect the correct network).
- BLOCKER: `truth_report.health` must be derived from `stats` so `price_sanity_failed` and related counters are consistent across artifacts.

Additional infra transparency (new requirements):

- Artifacts MUST include these infra fields (no secrets): `infra.rpc_provider`, `infra.rpc_http_host`.
- Optionally include `infra.rpc_ws_host` when WS is attempted.
- If `ARBY_REQUIRE_ALCHEMY=1` (or `REQUIRE_ALCHEMY=1`) is set, the gate must fail if resolved provider is not `alchemy`.
- Tenderly: when `tenderly_enabled=true`, artifacts must include either `tenderly_ok=true` or a non-empty `tenderly_error` string.
- WS: when `ws_enabled=true`, artifacts must include `ws_attempted`, `ws_connected`, and either `ws_error` or `ws_fallback_to_http` if not connected.

These checks are enforced by `scripts/ci_m5_0_gate.py`.

These rules are implemented in `core/rpc_urls.py`, `scripts/ci_m5_0_gate.py`, and `strategy/jobs/run_scan_real.py`.

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



## M5_0 Closure Summary (finalization checklist)

This section records what has been implemented, verified, and which DoD commands were executed to allow closing M5_0 and moving work to Milestone 5 (Production small).

**Implemented & Verified**

- RPC resolver unified and chain_id precedence fixed (`core/rpc_urls.py`) — prevents Arbitrum→Mantle host mismatch.
- Early RPC resolution + env injection in scanner (`strategy/jobs/run_scan_real.py`): `ARBY_RPC_HTTP_PRIMARY`, `ARBY_RPC_WS_PRIMARY`, `ARBY_RPC_HTTP_HOST` are set for reproducibility.
- Infra diagnostics added to artifacts (`infra.*`): `rpc_provider`, `rpc_http_host`, `rpc_ws_host`, `ws_attempted`, `ws_connected`, `ws_error`, `ws_handshake_ms`, `tenderly_enabled`, `tenderly_ok`, `tenderly_error` (no secrets written).
- WS handshake evidence implemented and skipped in unit tests via `ARBY_SKIP_RPC=1` to keep tests deterministic.
- Optional Tenderly probe implemented (only enforced with `--require-tenderly`).
- Suspect vs sanity separation implemented:
	- `suspect_examples` and `truth_report.suspect_summary` added
	- `stats` now includes `suspect_quotes` and `suspect_reasons` separate from sanity rejects
	- `reject_histogram` contains sanity rejects only (deviation > max)
- Cap semantics and deviation diagnostics: validators expose `deviation_bps_raw`, `deviation_bps`, `deviation_bps_capped`.
- CI gate enhancements (`scripts/ci_m5_0_gate.py`): `--require-infra-hosts`, `--require-cross-artifact`, `--require-tenderly`, and online strict profile enabling infra+cross checks by default.
- Tests and test harness improvements:
	- `ARBY_SKIP_RPC=1` default for unit tests (no external RPC calls)
	- New unit tests added covering RPC mapping, suspect counters, reject inclusion, autosize logic, and daily report aggregation.
- Added `docs/status/Status_M5.md` (Milestone 5 plan) and initial daily report generator `scripts/generate_daily_report.py` and minimal `ci_m5_gate.py` validator for M5.

**Artifacts produced**

- Completed 5 online scanner runs during validation; artifacts written to `data/runs/manual_run_*` with `scan_*.json`, `truth_report_*.json`, and `reject_histogram_*.json` containing infra diagnostics.
- Example daily report generator can convert a run into `daily_report_<date>.json` (schema_version `m5:daily:v1`).

**Unit test results (local)**

- Full unit suite: `python -m pytest tests/unit -q` → 434 passed, 5 subtests passed (current local run).

**DoD reproduction commands executed**

- Unit tests green:
	- `python -m pytest -q` (green locally)
- Online strict gate profile executed via scanner + gate:
	- `python -m strategy.jobs.run_scan --mode real --cycles 1 --config config/real_minimal.yaml` (produced artifacts)
	- `python scripts/ci_m5_0_gate.py --online --require-infra-hosts --require-cross-artifact` (strict checks; used during validation)

These commands were exercised during development and validation; gate flags ensure infra transparency and cross-artifact consistency for the DoD.

**Blockers cleared**

- RPC host mismatch for Arbitrum fixed (chain_id mapping prioritized).
- `truth_report.health` derived from `stats` to ensure cross-artifact consistency.

**Open / Known minor gaps**

- Tenderly checks are optional and not exercised by default in CI; `tenderly_ok` may be `disabled` unless keys are provided.
- Golden daily reports and formal retention policy are prepared (docs change) but not yet populated with curated golden artifacts — recommend adding 1–2 artifacts to `docs/artifacts/`.

## Offline Mode Infra Skip (v2.1.0 enhancement)

**Rationale**: Offline mode uses `run_mode=FIXTURE_OFFLINE` artifacts which deliberately omit infra fields (`rpc_provider`, `rpc_http_host`, `chain_id`, etc.). These fields are absent by design because offline mode generates deterministic fixtures for CI without network calls.

**Behavior (gate v2.1.0+)**:
- In offline mode (`--offline` flag or `run_mode` containing `FIXTURE`), the gate **skips infra validation entirely**.
- This eliminates WARN noise that would otherwise appear for missing infra fields.
- Result: clean CI output with 0 WARN for valid offline runs.

**Online mode** continues to validate infra fields when:
- `--require-infra-hosts` is provided (explicit requirement).
- `--require-real` is provided (rejects FIXTURE artifacts).
- `ARBY_REQUIRE_ALCHEMY=1` is set (requires Alchemy provider).

**Tests**: `tests/unit/test_ci_m5_0_gate_infra_skip.py` validates:
1. Offline mode has 0 WARN for missing infra fields.
2. Online mode with `--require-real` fails on FIXTURE artifacts.

## Final closure record

- M5_0: considered complete and ready to close when the following two checks pass in CI/runner:
	1. `python -m pytest -q` → green
	2. `python scripts/ci_m5_0_gate.py --online --require-infra-hosts --require-cross-artifact` → exit code 0

- Local verification performed on workspace HEAD: `e56cfd5` (replace with CI tag if different).

If both pass in the CI environment (with allowed environment secrets configured), this `Status_M5_0.md` should be updated with the CI run SHA(s) and the milestone marked CLOSED.

---

Next: move work to Milestone 5 (`docs/status/Status_M5.md`) — daily reporting, autosize, health metrics, and M5 CI gate.

