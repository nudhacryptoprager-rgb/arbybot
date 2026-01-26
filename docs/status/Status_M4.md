# Status: Milestone 4 (M4) — REAL Pipeline

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-26  
**Branch:** `split/code`  
**Depends On:** M3 ✅ DONE

## M4 Contract (SANITY + CONFIDENCE)

```
REAL mode must:
  ✓ Python 3.11.x (STEP 10)
  ✓ run_mode == "REGISTRY_REAL"
  ✓ current_block > 0 (pinned from RPC)
  ✓ execution_ready_count == 0 (execution disabled)
  ✓ quotes_fetched >= 1
  ✓ rpc_success_rate > 0
  ✓ dexes_active >= 2 (cross-DEX)
  ✓ rpc_total_requests >= 3
  ✓ price_sanity_passed >= 1 (STEP 1)
  ✓ 4/4 artifacts generated
  
  QUALITY VALIDATION:
  ✓ No "1 WETH -> 9.57 USDC" (price sanity gate) (STEP 1-2)
  ✓ dex_buy != dex_sell for opportunities
  ✓ pool != "unknown"
  ✓ amount_in > 0 for profitable opps (STEP 3)
  ✓ PnL consistent with amounts (STEP 4)
  ✓ Confidence is dynamic, not constant 0.85 (STEP 5)
  ✓ Tests deterministic (ARBY_OFFLINE=1) (STEP 6)
```

## Definition of Done (Machine-Checkable)

| # | Check | Command | Requirement |
|---|-------|---------|-------------|
| A | Python version | `python --version` | 3.11.x |
| B | Unit tests | `python -m pytest -q --ignore=tests/integration` | All green |
| C | M3 gate | `python scripts/ci_m3_gate.py` | PASS |
| D | M4 gate | `python scripts/ci_m4_gate.py` | PASS |
| E | M4 offline | `python scripts/ci_m4_gate.py --offline` | PASS |

## 10 Steps Implementation Summary

| # | Step | Status | Description |
|---|------|--------|-------------|
| 1 | Price sanity gate | ✅ | WETH/USDC must be 1500-6000, not 9.57 |
| 2 | Quote normalization | ✅ | Decimals correct, "1 ETH -> 9.57 USDC" rejected |
| 3 | Opportunity fields | ✅ | amount_out_buy_numeraire, net_pnl_usdc consistent |
| 4 | PnL split | ✅ | signal_pnl_* vs would_execute_pnl_* |
| 5 | Dynamic confidence | ✅ | Based on rpc_health, coverage, stability, spread |
| 6 | Deterministic tests | ✅ | ARBY_OFFLINE=1 + mock RPC fixtures |
| 7 | CI --offline mode | ✅ | Gate runs on fixtures without network |
| 8 | RPC config | ✅ | env-var overrides for timeout/retries/backoff |
| 9 | Minimum realism | ✅ | If all prices insane → MINIMUM_REALISM_FAIL |
| 10 | Python 3.11 pin | ✅ | .python-version + gate check |

## Key Changes

### STEP 1: Price Sanity Gate

```python
# run_scan_real.py
PRICE_SANITY_ANCHORS = {
    ("WETH", "USDC"): {"min": 1500, "max": 6000, "expected": 3500},
}

def check_price_sanity(token_in, token_out, price, config):
    # Reject prices outside sane bounds
    # "1 WETH -> 9.57 USDC" is rejected
```

### STEP 4: PnL Split

```python
# truth_report.py
pnl = {
    "signal_pnl_usdc": "5.000000",      # Theoretical
    "would_execute_pnl_usdc": "4.500000"  # After costs
}
```

### STEP 5: Dynamic Confidence

```python
# run_scan_real.py
def calculate_confidence(...):
    factors = {
        "rpc_health": rpc_success_rate,
        "quote_coverage": quote_fetch_rate,
        "price_stability": 1.0 - deviation/1000,
        "spread_quality": ...,
        "dex_diversity": 1.0 if dex_count >= 2 else 0.5,
    }
    return weighted_average(factors)
```

### STEP 8: Env-Var Overrides

```bash
# Override RPC settings
export ARBY_RPC_URL="https://custom.rpc.com"
export ARBY_RPC_TIMEOUT=15
export ARBY_RPC_RETRIES=5
export ARBY_PRICE_SANITY_DISABLED=1
```

### STEP 10: Python 3.11 Pin

```
# .python-version
3.11.9
```

## Verification Commands

```powershell
# STEP 10: Check Python version
python --version  # Should be 3.11.x

# Run unit tests
python -m pytest -q --ignore=tests/integration

# STEP 10: M3 regression protection
python scripts/ci_m3_gate.py

# Run M4 gate (live RPC)
python scripts/ci_m4_gate.py

# STEP 7: Run M4 gate offline (no network)
python scripts/ci_m4_gate.py --offline
```

## Expected ci_m4_gate.py Output

```
============================================================
  ARBY M4 CI GATE (SANITY + CONFIDENCE)
============================================================

STEP: Python Version Check
✓ Python version: 3.11.9

STEP: Unit Tests (pytest -q)
✅ Unit Tests PASSED

STEP: REAL Scan (1 cycle)
✅ REAL Scan PASSED

STEP: Artifact Sanity Check
✓ Found: scan.log
✓ Found: scan_*.json
✓ Found: reject_histogram_*.json
✓ Found: truth_report_*.json
✅ All 4 artifacts present

STEP: M4 Invariants Check (STRICT + SANITY)
✓ run_mode: REGISTRY_REAL
✓ current_block: 275XXXXXX
✓ execution_ready_count: 0
✓ quotes_fetched: X/Y
✓ rpc_success_rate: XX.X%
✓ dexes_active: 2
✓ rpc_total_requests: X
✓ price_sanity_passed: X
✅ M4 invariants satisfied (STRICT)

STEP: Cross-DEX + Quality Validation
✓ Cross-DEX opportunity: uniswap_v3 → sushiswap_v3
✓ All pools identified (no 'unknown')
✓ All profitable opps have amount_in > 0
✓ Confidence is dynamic: [0.82]
✓ All opps have execution_blockers
✅ Cross-DEX + Quality validation passed

============================================================
  ✅ M4 CI GATE PASSED (LIVE)
============================================================
```

## Files Modified

| File | Change |
|------|--------|
| `.python-version` | NEW: Python 3.11.9 pin |
| `config/real_minimal.yaml` | Env-var overrides, price sanity config |
| `strategy/jobs/run_scan_real.py` | Price sanity gate, dynamic confidence |
| `monitoring/truth_report.py` | PnL split, schema 3.1.0, sanity breakdown |
| `scripts/ci_m4_gate.py` | --offline mode, Python check, quality validation |
| `tests/integration/test_smoke_run.py` | Mock RPC fixtures |
| `tests/unit/test_truth_report.py` | PnL split, confidence tests |

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
