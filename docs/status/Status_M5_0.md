# Status: M5_0 (Infrastructure Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-31

## Goal

Consolidate infrastructure, unify contracts, and prepare for M5 multi-chain execution.

---

## Price Sanity Contract (M5_0)

### Price Orientation

**Contract**: Price is ALWAYS `quote_token per 1 base_token`.

| Pair | Base | Quote | Expected Price | Meaning |
|------|------|-------|----------------|---------|
| WETH/USDC | WETH | USDC | ~2600-3500 | "2600 USDC per 1 WETH" |
| WBTC/USDC | WBTC | USDC | ~60000-100000 | "60000 USDC per 1 WBTC" |

### NO Auto-Inversion (M5_0 Change)

**Previous behavior (BAD)**: If price < 100 for WETH/USDC, auto-invert to 1/price.
- Problem: 9 USDC/WETH → inverted to 0.11 → even more confusing

**New behavior (GOOD)**: Detect anomaly but DO NOT auto-fix.
- If price is obviously wrong, flag it and REJECT
- Diagnostics clearly show: `price_anomaly=way_below_expected`
- Root cause is in quoter/adapter, not sanity gate

### Deviation Formula

```python
deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
```

Cap at 10000 bps (100%) with `deviation_bps_capped=true` flag.

---

## Known Issues

### 1. Sushiswap V3 Bad Quotes (ROOT CAUSE IN ADAPTER)

**Symptom**: sushiswap_v3 fee=3000 returns 9 USDC for 1 WETH (should be ~2600).

**Status**: ⚠️ Sanity gate correctly rejects, but root cause not fixed.

**Root cause candidates**:
- `dex/adapters/algebra.py` - wrong pool address mapping
- `discovery/registry.py` - pool discovery issues
- Token order (token0/token1) confusion

**Workaround**: Gate rejects bad quotes with clear diagnostics.

**TODO (M5)**: Debug adapter with extended logging:
```python
# In adapter, add:
logger.debug(f"Quote {pool_address}: token0={token0}, token1={token1}, sqrtPriceX96={sqrtPriceX96}")
```

### 2. Execution Blocker Naming

**Current**: `EXECUTION_DISABLED_M4` in M5_0 artifacts.

**Decision**: Keep `EXECUTION_DISABLED_M4` as canonical (no stage drift).
- Reason: Changing would break artifact compatibility
- Alternative: Add `EXECUTION_DISABLED` without stage suffix in M5

---

## CI Gate Usage (v1.3.0)

### Priority: CLI > ENV > auto

```powershell
# 1. Explicit (RECOMMENDED for CI)
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260131_xxx

# 2. ENV variables
$env:ARBY_RUN_DIR = "data\runs\real_xxx"
$env:ARBY_REQUIRE_REAL = "1"
python scripts/ci_m5_0_gate.py

# 3. Offline fixture
python scripts/ci_m5_0_gate.py --offline

# 4. List candidates (helpful when lost)
python scripts/ci_m5_0_gate.py --list-candidates
```

### ENV Variables

| Variable | Description |
|----------|-------------|
| `ARBY_RUN_DIR` | Explicit run directory |
| `ARBY_GATE_MODE` | `offline` / `latest` |
| `ARBY_GATE_OUT_DIR` | Fixture output dir |
| `ARBY_REQUIRE_REAL` | If "1", reject `_fixture=true` |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL (validation) |
| 2 | FAIL (artifacts missing) |
| 3 | FAIL (fixture rejected) |

### Find Real RunDirs

```powershell
# PowerShell
Get-ChildItem data\runs | Sort-Object LastWriteTime -Desc | Select -First 5

# Or use gate helper
python scripts/ci_m5_0_gate.py --list-candidates
```

---

## Files Changed

| File | Change |
|------|--------|
| `core/validators.py` | NO auto-inversion, better diagnostics, single anchor_source |
| `tests/unit/test_price_sanity_inversion.py` | Tests for new contract |
| `scripts/ci_m5_0_gate.py` | v1.3.0: `--list-candidates`, helpful suggestions |
| `tests/unit/test_ci_m5_0_gate.py` | ENV priority tests |
| `strategy/jobs/run_scan_real.py` | Aligned with new validators |
| `docs/TESTING.md` | ENV examples, find runDir |
| `docs/status/Status_M5_0.md` | This file |

---

## Contracts (Frozen)

### Schema Version
```
SCHEMA_VERSION = "3.2.0" (in core/constants.py)
```

### Anchor Selection Priority
```python
ANCHOR_DEX_PRIORITY = ("uniswap_v3", "pancakeswap_v3", "sushiswap_v3")
```

### ExecutionBlocker
```python
ExecutionBlocker.EXECUTION_DISABLED_M4  # Keep as canonical
ExecutionBlocker.NOT_PROFITABLE
ExecutionBlocker.LOW_CONFIDENCE
```

---

## Definition of Done (M5_0)

```powershell
# 1. Python version
python --version  # Must be 3.11.x

# 2. Import contract
python -c "from core.validators import normalize_price, check_price_sanity, select_anchor; print('OK')"

# 3. Full pytest
python -m pytest -q

# 4. Price sanity tests (MUST BE TRACKED IN GIT)
python -m pytest tests/unit/test_price_sanity_inversion.py -v

# 5. Gate tests
python -m pytest tests/unit/test_ci_m5_0_gate.py -v

# 6. Offline gate
python scripts/ci_m5_0_gate.py --offline

# 7. (Optional) Real scan + gate
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
python -m strategy.jobs.run_scan_real --cycles 1 --output-dir "data\runs\real_$ts"
python scripts/ci_m5_0_gate.py --run-dir "data\runs\real_$ts" --require-real
```

---

## Signal-Only Profitability

Until cost model (M5+):
- `is_profitable=true` → **signal-only** (gross spread > threshold)
- `is_profitable_net=null` (no net without gas)
- `cost_model_available=false`

---

## Apply Commands

```powershell
# Copy files
Copy-Item outputs/core/validators.py core/
Copy-Item outputs/scripts/ci_m5_0_gate.py scripts/
Copy-Item outputs/tests/unit/test_price_sanity_inversion.py tests/unit/
Copy-Item outputs/tests/unit/test_ci_m5_0_gate.py tests/unit/
Copy-Item outputs/docs/TESTING.md docs/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# ADD test to git (IMPORTANT!)
git add tests/unit/test_price_sanity_inversion.py

# Verify
python -m pytest tests/unit/test_price_sanity_inversion.py -v
python -m pytest -q

# Gate
python scripts/ci_m5_0_gate.py --offline

# Commit
git add core/validators.py scripts/ci_m5_0_gate.py `
    tests/unit/test_price_sanity_inversion.py tests/unit/test_ci_m5_0_gate.py `
    docs/TESTING.md docs/status/Status_M5_0.md
git commit -m "fix(M5_0): no auto-inversion + single anchor_source + helpful gate"
```
