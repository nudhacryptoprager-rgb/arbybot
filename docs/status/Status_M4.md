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

## Config: config/real_minimal.yaml

```yaml
chain: arbitrum_one
chain_id: 42161

# Multiple RPC endpoints with fallback
rpc_endpoints:
  - "https://arb1.arbitrum.io/rpc"
  - "https://arbitrum-one.public.blastapi.io"
  - "https://rpc.ankr.com/arbitrum"

# Retries and backoff
rpc_retries: 3
rpc_backoff_base_ms: 500

# DEX
dexes:
  - uniswap_v3

# Pairs with multiple fee tiers
pairs:
  - token_in: WETH
    token_out: USDC
    fee_tiers: [500, 3000]
  - token_in: WETH
    token_out: USDT
    fee_tiers: [500, 3000]
```

## Features

### RPC Client
- Multiple endpoints with fallback
- Retries with exponential backoff
- Stats per endpoint
- Detailed error tracking

### Diagnostics
- `sample_rejects` with endpoint, method, error info
- `infra_samples` for RPC failures
- `rpc_stats` with per-endpoint breakdown

## Troubleshooting

### quotes_fetched = 0

1. Check RPC connectivity: `curl -X POST https://arb1.arbitrum.io/rpc`
2. Check quoter addresses in `config/dexes.yaml`
3. Check `infra_samples` in scan.json for error details
4. Try different RPC endpoints

### rpc_success_rate = 0

1. Network connectivity issue
2. All endpoints blocked/rate-limited
3. Check `rpc_stats.per_endpoint` for details

## Files

| File | Purpose |
|------|---------|
| `strategy/jobs/run_scan.py` | Entry point (SMOKE/REAL router) |
| `strategy/jobs/run_scan_real.py` | REAL pipeline with retries |
| `config/real_minimal.yaml` | Canary config |
| `scripts/ci_m4_gate.py` | M4 gate (STRICT) |
| `tests/integration/test_smoke_run.py` | Integration tests |

## Links

- M3 Status: [Status_M3.md](Status_M3.md)
- Compare: https://github.com/nudhacryptoprager-rgb/arbybot/compare/split/code
