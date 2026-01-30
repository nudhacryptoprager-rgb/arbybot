# Status: M4 (REAL Pipeline Hardening)

**Status**: CLOSING  
**Branch**: `split/code`  
**Last Updated**: 2026-01-30

## Goal

Run REAL pipeline with live RPC, pinned block, and **truthful metrics**.
Execution remains disabled - only price discovery and validation.

---

## M4 CLOSE Definition of Done

### Commands (MUST ALL PASS)

```bash
# 1. Full pytest (NO --ignore)
python -m pytest -q

# 2. CI gate offline
python scripts/ci_m4_gate.py --offline --skip-python-check

# 3. (Optional) CI gate online - requires RPC
python scripts/ci_m4_gate.py --online --skip-python-check
```

### Expected Output

```
python -m pytest -q
.........................
XX passed in Y.YYs

python scripts/ci_m4_gate.py --offline --skip-python-check
[PASS] M4 CI GATE PASSED (OFFLINE)
```

---

## Contracts (Frozen)

### Schema Version

**SCHEMA_VERSION = "3.2.0"** (frozen)

### API Contract (Backward Compatible)

```python
# check_price_sanity - MUST have default for dynamic_anchor
def check_price_sanity(
    token_in: str,
    token_out: str,
    price: Decimal,
    config: Dict[str, Any],
    dynamic_anchor: Optional[Decimal] = None,  # DEFAULT!
    fee: int = 0,
    decimals_in: int = 18,
    decimals_out: int = 6,
) -> Tuple[bool, Optional[int], Optional[str], Dict[str, Any]]:
    ...

# Diagnostics MUST always include anchor_price
diagnostics = {
    "implied_price": str,
    "anchor_price": str,  # ALWAYS PRESENT
    ...
}
```

### Price Contract

```
price = token_out per 1 token_in

Examples:
- WETH/USDC: price ~ 3500 (USDC per 1 WETH)
- WBTC/USDC: price ~ 90000 (USDC per 1 WBTC)
```

### PnL Contract

| Field | Type | No cost model | With cost model |
|-------|------|---------------|-----------------|
| `signal_pnl_usdc` | str | Always | Always |
| `would_execute_pnl_usdc` | str | Always | Always |
| `gross_pnl_usdc` | str | Always | Always |
| `net_pnl_usdc` | str \| None | **None** | str |
| `net_pnl_bps` | str \| None | **None** | str |
| `cost_model_available` | bool | False | True |

### Execution Contract

| Field | M4 Value |
|-------|----------|
| `execution_enabled` | False |
| `execution_blocker` | "EXECUTION_DISABLED_M4" |
| `execution_ready_count` | 0 |
| `is_actionable` | False (all opps) |

---

## M4 Invariants (Checked by CI Gate)

| Metric | Requirement |
|--------|-------------|
| `run_mode` | `REGISTRY_REAL` |
| `current_block` | `> 0` |
| `execution_enabled` | `false` |
| `execution_ready_count` | `0` |
| `quotes_fetched` | `>= 1` |
| `dexes_active` | `>= 2` |
| `price_sanity_passed` | `>= 1` |
| `net_pnl_usdc` | `null` (no cost model) |
| Artifacts | 4/4 |

---

## Files Changed for M4 CLOSE

| File | Change |
|------|--------|
| `strategy/jobs/run_scan_real.py` | `dynamic_anchor=None` default, `anchor_price` always in diagnostics |
| `docs/status/Status_M4.md` | This file - M4 CLOSE criteria |

---

## Exit Codes (ci_m4_gate.py)

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | Unit tests failed |
| 2 | REAL scan failed |
| 3 | Artifacts missing |
| 4 | M4 invariants failed |
| 6 | Metrics contract violation |
| 7 | Confidence inconsistent |
| 8 | PnL contract violation |
| 9 | Execution semantics invalid |
| 10 | Wrong Python version |
| 11 | Import contract broken |

---

## M4 CLOSE Commit

```bash
# After all tests pass:
git add strategy/jobs/run_scan_real.py docs/status/Status_M4.md
git commit -m "chore: close M4 contract (tests+gate green)"
```
