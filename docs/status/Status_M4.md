# Status: Milestone 4 (M4) — REAL Pipeline

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-26  
**Branch:** `split/code`  
**Depends On:** M3 ✅ DONE

## M4 Contract (CROSS-DEX ARBITRAGE)

```
REAL mode must:
  ✓ run_mode == "REGISTRY_REAL"
  ✓ current_block > 0 (pinned from RPC)
  ✓ execution_ready_count == 0 (execution disabled)
  ✓ quotes_fetched >= 1
  ✓ rpc_success_rate > 0
  ✓ dexes_active >= 2 (STEP 1: cross-DEX)
  ✓ rpc_total_requests >= 3
  ✓ 4/4 artifacts generated
  
  CROSS-DEX VALIDATION:
  ✓ At least 1 opportunity with dex_buy != dex_sell (STEP 1)
  ✓ No pool_buy == "unknown" (STEP 2)
  ✓ No pool_sell == "unknown" (STEP 2)
  ✓ amount_in_numeraire > 0 for profitable opps (STEP 3)
  ✓ Consistency: truth_report ↔ scan match
```

## Definition of Done (Machine-Checkable)

| # | Check | Command | Requirement |
|---|-------|---------|-------------|
| A | Unit tests | `python -m pytest -q --ignore=tests/integration` | All green |
| B | M3 gate | `python scripts/ci_m3_gate.py` | PASS |
| C | M4 gate | `python scripts/ci_m4_gate.py` | PASS |

### M4 Gate Validates (STEP 8)

1. **Artifacts** (4/4)
   - `scan.log`
   - `snapshots/scan_*.json`
   - `reports/reject_histogram_*.json`
   - `reports/truth_report_*.json`

2. **Invariants (STRICT)**
   - `run_mode == "REGISTRY_REAL"`
   - `current_block > 0`
   - `execution_ready_count == 0`
   - `quotes_fetched >= 1`
   - `rpc_success_rate > 0`
   - `dexes_active >= 2`
   - `rpc_total_requests >= 3`

3. **Cross-DEX Validation (NEW)**
   - At least 1 opportunity with `dex_buy != dex_sell`
   - No `pool_buy == "unknown"`
   - No `pool_sell == "unknown"`
   - All profitable opportunities have `amount_in_numeraire > 0`
   - All opportunities have non-empty `execution_blockers`

4. **Consistency**
   - `truth.stats.quotes_fetched == scan.stats.quotes_fetched`
   - `truth.stats.dexes_active == scan.stats.dexes_active`
   - No `is_execution_ready=True` when `execution_ready_count == 0`

## Verification Commands

```powershell
# Setup
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Run tests (STEP 10: M3 regression protection)
python -m pytest -q --ignore=tests/integration

# Run gates
python scripts/ci_m3_gate.py  # Must still pass
python scripts/ci_m4_gate.py  # New M4 criteria
```

## Expected Output

### ci_m4_gate.py (PASS)

```
============================================================
  ARBY M4 CI GATE (REAL Pipeline - CROSS-DEX)
============================================================

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

STEP: M4 Invariants Check
✓ run_mode: REGISTRY_REAL
✓ current_block: XXXXXXXX
✓ execution_ready_count: 0
✓ quotes_fetched: X/Y
✓ rpc_success_rate: XX.X%
✓ dexes_active: 2 ([uniswap_v3, sushiswap_v3])
✓ rpc_total_requests: X
✅ M4 invariants satisfied (STRICT)

STEP: Cross-DEX Opportunity Validation
✓ Found cross-DEX opportunity: uniswap_v3 → sushiswap_v3
✓ All pools identified (no 'unknown')
✓ All profitable opps have amount_in > 0
✓ All opps have execution_blockers
✅ Cross-DEX validation passed

STEP: Consistency Check
✓ quotes_fetched consistent: X
✓ dexes_active consistent: 2
✓ No is_execution_ready=True when disabled
✅ Consistency check passed

============================================================
  ✅ M4 CI GATE PASSED (CROSS-DEX)
============================================================
```

## Config: real_minimal.yaml

```yaml
# 2 DEXes for cross-DEX arbitrage
dexes:
  - uniswap_v3
  - sushiswap_v3

# Pool addresses (no "unknown")
pools:
  uniswap_v3_WETH_USDC_500: "0xC31E54c7..."
  sushiswap_v3_WETH_USDC_500: "0x90d5FF..."

# Quote sizing (amounts > 0)
quote_amount_in_wei: "1000000000000000000"  # 1 ETH
```

## Files Modified

| File | Change |
|------|--------|
| `config/real_minimal.yaml` | Added sushiswap_v3, pool addresses |
| `strategy/jobs/run_scan_real.py` | Cross-DEX spread generation |
| `monitoring/truth_report.py` | Preserve pool/amount fields |
| `scripts/ci_m4_gate.py` | Cross-DEX validation |
| `tests/integration/test_smoke_run.py` | Mock RPC support |
| `tests/unit/test_truth_report.py` | Pool/amount tests |

## 10 Steps Summary

| # | Step | Status |
|---|------|--------|
| 1 | 2 DEX active, dex_buy != dex_sell | ✅ |
| 2 | Pool IDs not "unknown" | ✅ |
| 3 | amount_in/out > 0 | ✅ |
| 4 | PnL consistent with amounts | ✅ |
| 5 | Reject histogram reflects rejects | ✅ |
| 6 | RPCHealthMetrics single API | ✅ |
| 7 | Deterministic tests (mock RPC) | ✅ |
| 8 | CI gate validates cross-DEX | ✅ |
| 9 | Status_M4.md clear criteria | ✅ |
| 10 | M3 regression protection | ✅ |

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
