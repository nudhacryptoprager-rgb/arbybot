# DEV REPORT — v2.3.2-fix Session (2026-02-20)

## Session Summary

Implemented 10 fix steps from lead review of commit `8d308b6`. Focus: Status file discipline, profit truth semantics, auto-quarantine.

---

## Changes Made

### 1. Status File Separation (docs/status/)

**Files Modified:**
- [docs/status/INDEX.md](docs/status/INDEX.md) - Added M5_0 as active milestone
- [docs/status/Status_M5_0.md](docs/status/Status_M5_0.md) - Rewrote header: DONE/frozen → ACTIVE, updated gate version to v2.3.0
- [docs/status/Status_M4.md](docs/status/Status_M4.md) - Removed M5_0 infra tables, added reference to Status_M5_0.md

**Rationale:**
- M4 Status was mixed with M5_0 infra content
- M5_0 was incorrectly marked DONE/frozen
- Each milestone now has clean separation

### 2. Profit Truth Semantics (v2.3.2)

**Files Modified:**
- [m4/fixtures.py](m4/fixtures.py) - Added `profit_truth_available` field computation
- [m4/gates.py](m4/gates.py) - Added WARN_PROFIT_DIAGNOSTIC quality warning when profit is diagnostic

**New Fields:**
```json
{
  "metrics": {
    "profit_is_diagnostic": true,
    "profit_truth_source": "ONE_LEG_DIAGNOSTIC",
    "cost_model_available": false,
    "profit_truth_available": false  // NEW: canonical M4 DoD field
  }
}
```

**Logic:**
```python
profit_truth_available = (not profit_is_diagnostic) and cost_model_available
```

When `profit_truth_available=False` and `profit_status=PASS`:
- `WARN_PROFIT_DIAGNOSTIC` added to quality_reasons
- `quality_status` set to WARN
- Quality warning added: `PROFIT_DIAGNOSTIC: profit_is_diagnostic=True, profit_truth_available=False`

### 3. Auto-quarantine PRICE_SANITY_FAILED

**File Modified:**
- [strategy/quarantine.py](strategy/quarantine.py) - Added `PRICE_SANITY_FAILED` to trackable_errors

**Before:**
```python
"trackable_errors": [
    "QUOTE_REVERT",
    "QUOTE_TIMEOUT",
    "RPC_ERROR",
],
```

**After:**
```python
"trackable_errors": [
    "QUOTE_REVERT",
    "QUOTE_TIMEOUT",
    "RPC_ERROR",
    "PRICE_SANITY_FAILED",  # v2.3.2: Auto-quarantine price sanity failures
],
```

### 4. New Unit Tests

**File Created:**
- [tests/unit/test_profit_truth_available.py](tests/unit/test_profit_truth_available.py) - 7 tests covering profit truth logic

**Test Coverage:**
- `test_profit_truth_available_computation` - Formula verification
- `test_diagnostic_profit_should_warn` - Quality warning logic
- `test_true_profit_should_not_warn` - No warning when profit is real
- `test_fail_profit_no_diagnostic_warning` - No warning when already failing
- `test_default_source_is_diagnostic` - Default values
- `test_diagnostic_source_implies_diagnostic_flag` - Consistency
- `test_atomic_source_implies_real_profit` - Two-leg atomic execution

---

## Test Results

```
889 passed, 1 skipped, 1 warning, 15 subtests passed in 9.56s
```

All tests pass. No regressions.

---

## Current State Summary

| Aspect | Status | Notes |
|--------|--------|-------|
| Policy Version | 2.0.8 | Unchanged |
| Gate Version | v2.3.2 | New profit_truth_available |
| Unit Tests | 889 PASS | +7 new tests |
| profit_truth_available | Added | Canonical M4 DoD field |
| Auto-quarantine | PRICE_SANITY_FAILED added | 3 consecutive failures → quarantine |
| Status files | Separated | M4/M5_0 clean split |

---

## Key Contracts (v2.3.2)

### Profit Truth Contract

```
profit_truth_available = (NOT profit_is_diagnostic) AND (execution_pnl.cost_model_available)
```

- If `profit_truth_available=False` and `profit_status=PASS`:
  - `WARN_PROFIT_DIAGNOSTIC` added to quality_reasons
  - `quality_status` downgraded to `WARN`
  - Human-readable warning in quality_warnings

### profit_truth_source Values

| Value | Meaning |
|-------|---------|
| `ONE_LEG_DIAGNOSTIC` | One-leg quote, simulated (default) |
| `ONE_LEG_UNVERIFIED` | One-leg quote, not verified |
| `ROUNDTRIP_CANONICAL` | Roundtrip profitable (two legs) |

---

## Sushi PRICE_SANITY_FAILED Diagnosis

Pools with price sanity failures (already disabled in config/real_minimal.yaml):

| Pool | Detail | Evidence |
|------|--------|----------|
| sushiswap_v3_WBTC_WETH_500 | tick=887271, price~3.4e28 vs anchor 35 | ci_m5_gate_20260217 |
| sushiswap_v3_LINK_USDC_3000 | price~19.9 vs anchor 9.0 | ci_m5_gate_20260217 |
| sushiswap_v3_ARB_USDC_3000 | price~1.009 vs anchor 0.11 (inverted) | ci_m5_gate_20260217 |
| sushiswap_v3_WETH_DAI_3000 | price~60.96 vs anchor 1980 (scaling) | ci_m5_gate_20260219 |

**Root Cause:** SushiSwap on Arbitrum uses Algebra quoter. Price scaling differs from Uniswap V3 anchor prices.

**Mitigation:**
1. Pools moved to `disabled_pools` in config
2. `PRICE_SANITY_FAILED` now auto-quarantines after 3 consecutive failures

---

## Next Commands

```powershell
# Verify offline gate
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict

# Full CI pipeline
py -3.11 scripts/ci_full_pipeline.py --mode ci

# Online scan (if RPC available)
py -3.11 -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml
```

---

## Files Changed

| File | Change Type |
|------|-------------|
| docs/status/INDEX.md | Modified |
| docs/status/Status_M5_0.md | Modified |
| docs/status/Status_M4.md | Modified |
| m4/fixtures.py | Modified |
| m4/gates.py | Modified |
| strategy/quarantine.py | Modified |
| tests/unit/test_profit_truth_available.py | Created |

---

## Blockers Remaining

1. **M4 NOT CLOSED**: `profit_is_diagnostic=True`, `execution_pnl.cost_model_available=False`
   - Need roundtrip profitable signals OR execution cost model
   
2. **DIVERSITY WARNING**: unique_routes_cross_dex=2 < target=4
   - More Sushi pools working needed (currently disabled due to PRICE_SANITY)

3. **Sushi Quoter Path**: Algebra quoter integration incomplete
   - Price scaling differs from V3 anchor
   - Investigation deferred to M5.1

---

*Generated: 2026-02-20*
*Policy: 2.0.8 | Gate: v2.3.2*
