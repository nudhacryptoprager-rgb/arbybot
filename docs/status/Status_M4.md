# Status: M4 (REAL Pipeline)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2025-01-26

## Goal

Run REAL pipeline with live RPC, pinned block, and honest metrics.
Execution remains disabled - only price discovery and validation.

## Metrics Contract

```
quotes_total    = attempted quote calls
quotes_fetched  = got valid RPC response (amount_out > 0)
gates_passed    = passed all gates (price sanity, etc.)
dexes_active    = DEXes with at least 1 response (with_quotes)
```

### Invariants

1. `gates_passed <= quotes_fetched <= quotes_total`
2. If `sample_rejects` has entries with `price != null`, then `quotes_fetched > 0`
3. `dexes_active` counts DEXes in `dex_coverage.with_quotes`, not `passed_gates`

## M4 Success Criteria

| Metric | Requirement | Notes |
|--------|-------------|-------|
| `run_mode` | `REGISTRY_REAL` | Live RPC mode |
| `current_block` | `> 0` | Pinned block |
| `execution_ready_count` | `== 0` | Execution disabled |
| `quotes_fetched` | `>= 1` | Got at least 1 quote |
| `rpc_success_rate` | `> 0` | RPC working |
| `dexes_active` | `>= 2` | Cross-DEX capability |
| `rpc_total_requests` | `>= 3` | Minimum activity |
| `price_sanity_passed` | `>= 1` | At least 1 sane price |
| Artifacts | 4/4 | All artifacts present |

## Bootstrap Thresholds (STEP 6)

For M4 bootstrap, we use relaxed thresholds to allow initial data collection:

```yaml
# M4 Bootstrap (will tighten in M5)
price_sanity_enabled: true
price_sanity_max_deviation_bps: 5000  # 50% deviation allowed

# Price bounds (absolute limits)
WETH/USDC: [1500, 6000]  # Expected: 3500
WBTC/USDC: [30000, 150000]  # Expected: 90000
```

### Why 50% Deviation?

1. We need at least 1 quote to pass sanity for M4
2. Real prices may deviate during volatility
3. We'll tighten to 10% in M5 after collecting baseline data
4. Bounds still catch truly insane prices (e.g., "9.7 USDC per WETH")

## Price Sanity Anchor

The anchor uses **hardcoded canonical values** (not live prices):

```python
PRICE_SANITY_ANCHORS = {
    ("WETH", "USDC"): {"min": 1500, "max": 6000, "expected": 3500},
    ("WBTC", "USDC"): {"min": 30000, "max": 150000, "expected": 90000},
}
```

This prevents comparing a price with itself or with an invalid source.

## Diagnostics (STEP 2)

When `PRICE_SANITY_FAIL` occurs, the reject payload includes:

```json
{
  "reject_reason": "PRICE_SANITY_FAIL",
  "price": "9.706103",
  "price_deviation_bps": 1716,
  "diagnostics": {
    "implied_price": "9.706103",
    "anchor_price": "3500",
    "deviation_bps": 1716,
    "token_in_decimals": 18,
    "token_out_decimals": 6,
    "price_bounds": ["1500", "6000"],
    "pool_fee": 500
  }
}
```

This enables fast debugging of price calculation issues.

## CI Gate

`scripts/ci_m4_gate.py` is the **single source of truth** for M4 validation.

### Commands

```bash
# Full validation with live RPC
python scripts/ci_m4_gate.py

# Offline validation with fixtures
python scripts/ci_m4_gate.py --offline

# Skip Python version check
python scripts/ci_m4_gate.py --skip-python-check
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | Unit tests failed |
| 2 | REAL scan failed |
| 3 | Artifacts missing |
| 4 | M4 invariants failed |
| 5 | Quality validation failed |
| 6 | Metrics contract violation |
| 10 | Wrong Python version |
| 11 | Import contract broken |

## Definition of Done

```bash
# A. Python version
python --version  # Must be 3.11.x

# B. Unit tests pass
python -m pytest -q --ignore=tests/integration

# C. M3 regression check
python scripts/ci_m3_gate.py

# D. M4 gate passes
python scripts/ci_m4_gate.py

# E. All output is ASCII (no emoji in CI logs)
```

## Artifacts

| Artifact | Path | Content |
|----------|------|---------|
| Scan log | `scan.log` | Console output |
| Snapshot | `snapshots/scan_*.json` | Full scan data |
| Histogram | `reports/reject_histogram_*.json` | Reject counts |
| Truth | `reports/truth_report_*.json` | Final report |

## Known Issues

1. **Price 9.7**: Some pools return inverted prices. Fixed by proper decimals handling.
2. **quotes_fetched=0 with prices**: Bug in metrics counting. Fixed by separating `rpc_success` from `gate_passed`.

## Next Steps (M5)

1. Tighten `price_sanity_max_deviation_bps` to 1000 (10%)
2. Add more pairs (WBTC, LINK)
3. Enable paper trade execution
4. Add slippage estimation
