# Status: M5_0 (Infrastructure Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-31

## Goal

Consolidate infrastructure, unify contracts, and prepare for M5 multi-chain execution.

---

## Known Issues

### ⚠️ P1: Sushi V3 fee=3000 Bad Quote (ADAPTER/REGISTRY BUG)

**Symptom**: sushiswap_v3 fee=3000 returns ~8.6 USDC for 1 WETH (should be ~2600).

**Status**: Gate correctly rejects. Root cause NOT fixed.

**Evidence** (`reject_histogram_20260131_145927.json`):
```json
{
  "dex_id": "sushiswap_v3",
  "pool_fee": 3000,
  "implied_price": "8.605052",
  "expected_range": ["1500", "6000"],
  "deviation_bps": 9966,
  "error": "deviation_exceeded",
  "pool_address": "pool:sushiswap_v3:WETH:USDC:3000"  // ← KEY, not real 0x...
}
```

**Root cause candidates**:
1. `pool_address` is a KEY not real address - can't debug on-chain
2. Registry mapping wrong for sushiswap_v3:WETH/USDC:3000
3. Fee tier mismatch (3000 vs actual)
4. Token order confusion in adapter

**Files to investigate**:
- `dex/adapters/algebra.py` - Sushi v3 uses Algebra (not Uniswap V3 ABI)
- `discovery/registry.py` - pool discovery/mapping
- `config/dexes.yaml` - DEX configuration

**Workaround**: Sanity gate rejects with clear diagnostics. No execution risk.

---

## Price Sanity Contract (M5_0)

### Price Orientation

**Contract**: Price is ALWAYS `quote_token per 1 base_token`.

| Pair | Expected | Example |
|------|----------|---------|
| WETH/USDC | ~2600-3500 | "2600 USDC per 1 WETH" |

### NO INVERSION (CRITICAL)

**Rule**: `inversion_applied` is **ALWAYS** `False`.

We **NEVER** auto-invert prices. If a quote looks wrong:
- It's a **suspect quote** (bad adapter data), NOT inversion
- Flag as `suspect_quote=true`, `suspect_reason="way_below_expected"`
- Let sanity gate reject with clear diagnostics

**Why no auto-inversion?**
- 8.6 USDC/WETH is NOT "inverted 2600" - it's just garbage data
- Auto-inverting would mask the real bug (adapter/registry issue)
- Diagnostics are clearer without false "inversion" claims

### Deviation Formula

```python
deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
MAX_DEVIATION_BPS_CAP = 10000  # 100%

# Example: price=8.6, anchor=2600
# |8.6 - 2600| / 2600 * 10000 = 9966 bps
# Not capped (raw < 10000), but exceeds max_deviation_bps=5000 → FAIL
```

### Diagnostics Fields

| Field | Value | Meaning |
|-------|-------|---------|
| `inversion_applied` | `false` | Always false (we never invert) |
| `suspect_quote` | `true/false` | Quote looks obviously wrong |
| `suspect_reason` | `"way_below_expected"` | Why it's suspect |
| `deviation_bps` | `9966` | Deviation (may be capped) |
| `deviation_bps_raw` | `9966` | Raw deviation (never capped) |
| `deviation_bps_capped` | `false` | True if raw > 10000 |

---

## M5_0 Pass Criteria

**What "PASS" means**:
1. All 3 artifacts exist (scan, truth_report, reject_histogram)
2. `schema_version` valid (X.Y.Z)
3. `run_mode` exists and consistent
4. `quotes_total >= 1`, `quotes_fetched >= 1`
5. `dexes_active >= 1`
6. `price_sanity_passed` and `price_sanity_failed` exist

**Sanity fails ARE allowed** if:
- Real anomalies (documented in Known Issues)
- NOT system-wide bugs

---

## CI Gate Usage (v1.3.0)

```powershell
# Explicit (RECOMMENDED)
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_xxx

# List candidates
python scripts/ci_m5_0_gate.py --list-candidates

# Offline
python scripts/ci_m5_0_gate.py --offline
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL (validation) |
| 2 | FAIL (artifacts missing) |
| 3 | FAIL (fixture rejected) |

---

## Definition of Done (M5_0)

```powershell
# 1. Unit tests
python -m pytest tests/unit/test_price_sanity_inversion.py -v

# 2. Full pytest
python -m pytest -q

# 3. Gate
python scripts/ci_m5_0_gate.py --offline

# 4. (Optional) Real run
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
python -m strategy.jobs.run_scan_real --cycles 1 --output-dir "data\runs\real_$ts"
python scripts/ci_m5_0_gate.py --run-dir "data\runs\real_$ts"
```

---

## Apply Commands

```powershell
# Copy files
Copy-Item outputs/core/validators.py core/
Copy-Item outputs/tests/unit/test_price_sanity_inversion.py tests/unit/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# Verify
python -m pytest tests/unit/test_price_sanity_inversion.py -v
python -m pytest -q

# Commit
git add core/validators.py tests/unit/test_price_sanity_inversion.py docs/status/Status_M5_0.md
git commit -m "fix(M5_0): inversion_applied=false always, suspect_quote for bad data"
```
