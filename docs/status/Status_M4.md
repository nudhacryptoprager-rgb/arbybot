# Status: Milestone 4 (M4) — REAL Pipeline

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-25  
**Branch:** `split/code`  
**Depends On:** M3 ✅ DONE

## M4 Contract (STRICT)

```
REAL mode must:
  ✓ run_mode == "REGISTRY_REAL"
  ✓ current_block > 0 (pinned from RPC)
  ✓ execution_ready_count == 0 (execution disabled)
  ✓ quotes_fetched >= 1
  ✓ rpc_success_rate > 0
  ✓ dexes_active >= 1
  ✓ rpc_total_requests >= 3
  ✓ 4/4 artifacts generated
```

## Recent Fix: RPCHealthMetrics Contract

**Problem:** `run_scan_real.py` called `rpc_metrics.record_rpc_call(success, latency_ms)` but method didn't exist in `RPCHealthMetrics` class.

**Solution:** Added `record_rpc_call(success: bool, latency_ms: int | float)` method to `monitoring/truth_report.py`.

**API Contract:**
```python
class RPCHealthMetrics:
    # PRIMARY method used by run_scan_real.py RPCClient
    def record_rpc_call(self, success: bool, latency_ms: int | float) -> None: ...
    
    # Legacy methods (backward compatible)
    def record_success(self, latency_ms: int = 0) -> None: ...
    def record_failure(self) -> None: ...
```

## Definition of Done

| Check | Command | Requirement |
|-------|---------|-------------|
| A | `python -m pytest -q` | All tests green |
| B | `python scripts/ci_m3_gate.py` | PASS (M3 preserved) |
| C | `python scripts/ci_m4_gate.py` | PASS (STRICT criteria) |

## Verification Commands

```powershell
# Setup venv
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Run tests
python -m pytest -q

# Run gates
python scripts/ci_m3_gate.py
python scripts/ci_m4_gate.py
```

## Expected Output

### ci_m4_gate.py (PASS)

```
============================================================
  ARBY M4 CI GATE (REAL Pipeline - STRICT)
============================================================
✅ Unit Tests (pytest -q) PASSED
✅ REAL Scan (1 cycle) PASSED
✓ Found: scan.log
✓ Found: scan_*.json
✓ Found: reject_histogram_*.json
✓ Found: truth_report_*.json
✅ All 4 artifacts present
✓ run_mode: REGISTRY_REAL
✓ current_block: XXXXXXXX (pinned)
✓ execution_ready_count: 0 (execution disabled)
✓ quotes_fetched: X/Y
✓ rpc_success_rate: XX.X%
✓ dexes_active: 1
✓ rpc_total_requests: X
✅ M4 invariants satisfied (STRICT)
============================================================
  ✅ M4 CI GATE PASSED (STRICT)
============================================================
```

## Files Modified

| File | Change |
|------|--------|
| `monitoring/truth_report.py` | Added `record_rpc_call(success, latency_ms)` method |
| `tests/unit/test_health_metrics.py` | Added unit tests for RPCHealthMetrics contract |

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
