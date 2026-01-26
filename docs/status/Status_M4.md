# Status: Milestone 4 (M4) — REAL Pipeline

**Status:** 🟡 IN PROGRESS  
**Last Updated:** 2026-01-25  
**Branch:** `split/code`  
**Depends On:** M3 ✅ DONE

## M4 Contract (STRICT + CONSISTENCY)

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
  ✓ CONSISTENCY: truth_report ↔ scan match
```

## Definition of Done (Machine-Checkable)

| # | Check | Command | Requirement |
|---|-------|---------|-------------|
| A | Unit tests | `python -m pytest -q` | All green |
| B | M3 gate | `python scripts/ci_m3_gate.py` | PASS |
| C | M4 gate | `python scripts/ci_m4_gate.py` | PASS |

### M4 Gate Machine-Checkable Criteria

The gate (`scripts/ci_m4_gate.py`) validates:

**Invariants (STRICT)**
- `run_mode == "REGISTRY_REAL"`
- `current_block > 0`
- `execution_ready_count == 0`
- `quotes_fetched >= 1`
- `rpc_success_rate > 0`
- `dexes_active >= 1`
- `rpc_total_requests >= 3`
- 4/4 artifacts exist

**Consistency (truth_report ↔ scan)**
- `truth.stats.quotes_fetched == scan.stats.quotes_fetched`
- `truth.health.quote_fetch_rate ≈ scan.stats.quotes_fetched / scan.stats.quotes_total`
- `truth.health.rpc_success_rate ≈ scan.rpc_stats.success_rate`
- `truth.stats.execution_ready_count == scan.stats.execution_ready_count`
- If `execution_ready_count == 0`, NO opportunity has `is_execution_ready=True`
- If `execution_ready_count == 0`, ALL opportunities have non-empty `execution_blockers`

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
  ARBY M4 CI GATE (REAL Pipeline - STRICT + CONSISTENCY)
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
✓ quotes_fetched consistent: X
✓ quote_fetch_rate consistent: X.XXX
✓ rpc_success_rate consistent: X.XXX
✓ execution_ready_count consistent: 0
✓ No is_execution_ready=True when execution disabled
✓ All opportunities have execution_blockers
✅ Consistency check passed (truth_report matches scan)
============================================================
  ✅ M4 CI GATE PASSED (STRICT + CONSISTENCY)
============================================================
```

## Files Modified

| File | Change |
|------|--------|
| `monitoring/truth_report.py` | Use scan_stats for rates, preserve blockers, add blocker_histogram |
| `strategy/jobs/run_scan_real.py` | Pass rpc_stats to truth_report |
| `scripts/ci_m4_gate.py` | Add consistency checks |
| `tests/unit/test_truth_report.py` | Test consistency contract |
| `tests/integration/test_smoke_run.py` | Test REAL mode consistency |

## Consistency Contract

The fix ensures truth_report never "lies" about metrics:

1. **quote_fetch_rate** computed from `scan_stats.quotes_fetched / scan_stats.quotes_total`
2. **rpc_success_rate** from `rpc_stats` (RPCClient), not empty rpc_metrics
3. **execution_blockers** preserved from `all_spreads`, not recomputed
4. **is_execution_ready** = False if execution_ready_count == 0 (global override)
5. **blocker_histogram** shows why spreads are blocked

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
