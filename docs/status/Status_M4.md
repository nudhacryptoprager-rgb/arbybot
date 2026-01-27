# Status: M4 (REAL Pipeline Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-27

## Goal

Run REAL pipeline with live RPC, pinned block, and **truthful metrics**.
Execution remains disabled - only price discovery and validation.

---

## Contracts (Frozen)

### Schema Version

**SCHEMA_VERSION = "3.2.0"** (frozen, do not change without test sync)

### PNL Contract

| Field | Type | Rule |
|-------|------|------|
| `signal_pnl_usdc` | str | Always present |
| `would_execute_pnl_usdc` | str | Always present |
| `gross_pnl_usdc` | str | Always present |
| `net_pnl_usdc` | str \| None | None when `cost_model_available=False` |
| `cost_model_available` | bool | Always present |

### Reject Reason Contract

**Canonical key: `PRICE_SANITY_FAILED`**

Both `PRICE_SANITY_FAIL` and `PRICE_SANITY_FAILED` are accepted (mapped to `sanity` category), but new code should use `PRICE_SANITY_FAILED`.

### Execution Contract

| Field | Value | Rule |
|-------|-------|------|
| `execution_enabled` | False | M4: always False |
| `execution_blocker` | "EXECUTION_DISABLED_M4" | When disabled |
| `execution_ready_count` | 0 | M4: always 0 |
| `is_actionable` | False | Per-opportunity |

---

## M4 Success Criteria

| Metric | Requirement |
|--------|-------------|
| Python | 3.11.x |
| `run_mode` | `REGISTRY_REAL` |
| `current_block` | `> 0` (from RPC) |
| `execution_enabled` | `false` |
| `execution_ready_count` | `0` |
| `quotes_fetched` | `>= 1` |
| `rpc_success_rate` | `> 0` |
| `dexes_active` | `>= 2` |
| `price_sanity_passed` | `>= 1` |
| `price_stability_factor` | `> 0` when sanity_passed > 0 |
| Artifacts | 4/4 |

---

## What's Done

- [x] REAL scan with live RPC
- [x] Pinned block from RPC
- [x] quotes_fetched >= 1
- [x] 4/4 artifacts (scan.log, scan_*.json, reject_histogram_*.json, truth_report_*.json)
- [x] Execution disabled (explicit)
- [x] ASCII-safe CI gate output
- [x] Unified reject code (PRICE_SANITY_FAILED)
- [x] PnL contract: net_pnl_usdc=None when no cost model
- [x] Confidence consistency: price_stability_factor > 0 when sanity_passed > 0

## What's NOT Done (M5+)

- [ ] Execution state machine (stub only)
- [ ] Simulator gate (stub only)
- [ ] Accounting module (stub only)
- [ ] Kill switch (stub only)
- [ ] Private send integration
- [ ] Cost model (gas/slippage estimation)
- [ ] Flash swap execution

---

## Single Command Validation

```powershell
# Run this to verify M4 contract
python scripts/ci_m4_gate.py --offline --skip-python-check
```

**Exit codes:**
- 0: PASS
- 1: Unit tests failed
- 2: REAL scan failed
- 3: Artifacts missing
- 4: M4 invariants failed
- 6: Metrics contract violation
- 7: Confidence inconsistent
- 8: Profit not truthful
- 9: Execution semantics invalid
- 10: Wrong Python version
- 11: Import contract broken

---

## Definition of Done

All must pass:

```powershell
# A. Python version
python --version  # Must be 3.11.x

# B. Import contract
python -c "from monitoring.truth_report import calculate_confidence; print('ok')"

# C. Unit tests
python -m pytest -q --ignore=tests/integration

# D. M4 gate
python scripts/ci_m4_gate.py --offline --skip-python-check
```
