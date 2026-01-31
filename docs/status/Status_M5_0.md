# Status: M5_0 (Infrastructure Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-31

## Goal

Consolidate infrastructure, unify contracts, and prepare for M5 multi-chain execution.

---

## Price Orientation Contract (M5_0)

**UNIFIED CONTRACT**: Price is ALWAYS expressed as `quote_token per 1 base_token`.

| Pair | Base | Quote | Price Example | Meaning |
|------|------|-------|---------------|---------|
| WETH/USDC | WETH | USDC | 3500 | "3500 USDC per 1 WETH" |
| WBTC/USDC | WBTC | USDC | 90000 | "90000 USDC per 1 WBTC" |
| ARB/WETH | ARB | WETH | 0.0003 | "0.0003 WETH per 1 ARB" |

**Invariants**:
1. `base_token = token_in` (the token you're selling)
2. `quote_token = token_out` (the token you're receiving)
3. `price = amount_out_normalized / amount_in_normalized`

**Inversion Detection** (for known pairs):
- If WETH/USDC price < 100, it's likely inverted and will be auto-corrected
- After inversion: `raw_price * final_price ≈ 1`
- Diagnostics include: `inversion_applied`, `raw_price`, `normalized_price`

---

## Known Issues Fixed

### Price Inversion Sanity Bug (2026-01-30)

**Symptom**: PRICE_SANITY_FAILED with 9999bps deviation on valid pools.

**Root Cause**: 
1. `anchor_source = dynamic_first_quote` - first quote became anchor regardless of DEX quality
2. Price orientation mismatch: quote returned WETH/USDC (~0.1), anchor expected USDC/WETH (~2700)
3. No normalization before comparison → massive artificial deviation

**Fix Applied**:
1. Two-phase scan: fetch ALL quotes first, THEN select anchor
2. `select_anchor()` uses priority: `uniswap_v3` > `pancakeswap_v3` > `sushiswap_v3` > median > hardcoded
3. `normalize_price()` auto-corrects inverted prices for known pairs
4. Extended diagnostics: `raw_price`, `final_price_used_for_sanity`, `inversion_applied`, `numeraire_side`

---

## 10 Критичних Зауважень (Що Було Не Так)

| # | Issue | Impact | Status |
|---|-------|--------|--------|
| 1 | Price sanity дублюється в gates.py і run_scan_real.py | Contract drift | Fixed |
| 2 | ErrorCode contract drift (INFRA_BAD_ABI missing) | Runtime crash | Fixed |
| 3 | Anchor = "first success" → можна отруїти | Security | **Fixed** |
| 4 | Недостатня діагностика sanity-fail | Debug hard | **Fixed** |
| 5 | SCHEMA_VERSION локально в truth_report | Drift risk | Fixed |
| 6 | Execution blocker strings scattered | Inconsistency | Fixed |
| 7 | REAL pipeline окремо від run_scan | M5 risk | Documented |
| 8 | Provider policy incomplete | No rate-limit | TODO M5 |
| 9 | Concurrency control weak | RPC storm | TODO M5 |
| 10 | No offline golden fixture | CI fragile | Fixed |

---

## M5_0 CI Gate Usage

### Mode Selection Priority: CLI > ENV > auto

| Priority | Source | Example |
|----------|--------|---------|
| 1 | `--run-dir PATH` | `python scripts/ci_m5_0_gate.py --run-dir data/runs/xxx` |
| 2 | `ARBY_RUN_DIR` env | `ARBY_RUN_DIR=data/runs/xxx python scripts/ci_m5_0_gate.py` |
| 3 | `--offline` | `python scripts/ci_m5_0_gate.py --offline` |
| 4 | `ARBY_GATE_MODE` env | `ARBY_GATE_MODE=offline python scripts/ci_m5_0_gate.py` |
| 5 | Auto-detect | `python scripts/ci_m5_0_gate.py` (finds latest valid runDir) |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ARBY_RUN_DIR` | Explicit run directory path |
| `ARBY_GATE_MODE` | Mode: `offline`, `latest` |
| `ARBY_GATE_OUT_DIR` | Output dir for fixture |
| `ARBY_REQUIRE_REAL` | If "1", reject fixture data |

### Commands

**Explicit (RECOMMENDED for CI)**
```powershell
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456
```

**Offline fixture**
```powershell
python scripts/ci_m5_0_gate.py --offline
python scripts/ci_m5_0_gate.py --offline --out-dir data/runs/my_fixture
```

**Require real data**
```powershell
python scripts/ci_m5_0_gate.py --run-dir data/runs/xxx --require-real
# or via ENV:
$env:ARBY_REQUIRE_REAL = "1"
python scripts/ci_m5_0_gate.py --run-dir data/runs/xxx
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS - all checks passed |
| 1 | FAIL - one or more checks failed |
| 2 | FAIL - artifacts missing or unreadable |
| 3 | FAIL - fixture rejected (--require-real) |

---

## Files Changed

| File | Change |
|------|--------|
| `core/constants.py` | Centralized constants + ExecutionBlocker enum |
| `core/exceptions.py` | Added INFRA_BAD_ABI to ErrorCode |
| `core/validators.py` | `select_anchor()` with priority logic |
| `strategy/jobs/run_scan_real.py` | Two-phase scan, proper anchor selection |
| `scripts/ci_m5_0_gate.py` | ENV fallback, --require-real |
| `tests/unit/test_ci_m5_0_gate.py` | ENV priority tests, --require-real tests |
| `tests/unit/test_price_sanity_inversion.py` | Orientation consistency tests |
| `docs/TESTING.md` | ENV examples, CI usage |
| `docs/status/Status_M5_0.md` | This file |

---

## Contracts (Frozen)

### Schema Version
```
SCHEMA_VERSION = "3.2.0" (in core/constants.py)
```

### Price Orientation
```python
# Price = quote_token per 1 base_token
# For WETH/USDC: price ≈ 3500 (USDC per WETH)
# Inversion invariant: raw_price * final_price ≈ 1 when inversion_applied=True
```

### Anchor Selection Priority
```python
ANCHOR_DEX_PRIORITY = ("uniswap_v3", "pancakeswap_v3", "sushiswap_v3")
# 1. Quote from anchor_dex (first available in priority)
# 2. Median of valid quotes
# 3. Hardcoded bounds (fallback)
```

### ExecutionBlocker (Canonical)
```python
ExecutionBlocker.EXECUTION_DISABLED_M4
ExecutionBlocker.SMOKE_MODE_NO_EXECUTION
ExecutionBlocker.NOT_PROFITABLE
ExecutionBlocker.LOW_CONFIDENCE
ExecutionBlocker.NO_COST_MODEL
ExecutionBlocker.INVALID_SIZE
```

---

## Definition of Done (M5_0)

```powershell
# 1. Python version
python --version  # Must be 3.11.x

# 2. Import contract
python -c "from core.constants import DexType, SCHEMA_VERSION, ExecutionBlocker; print(SCHEMA_VERSION)"
python -c "from core.validators import select_anchor, normalize_price; print('OK')"

# 3. Full pytest (NO --ignore)
python -m pytest -q

# 4. Price sanity inversion tests (orientation consistency)
python -m pytest tests/unit/test_price_sanity_inversion.py -v

# 5. M5_0 gate tests
python -m pytest tests/unit/test_ci_m5_0_gate.py -v

# 6. M5_0 gate (offline)
python scripts/ci_m5_0_gate.py --offline

# 7. (Optional) Real scan validation
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
python -m strategy.jobs.run_scan_real --cycles 1 --output-dir "data\runs\real_$ts"
python scripts/ci_m5_0_gate.py --run-dir "data\runs\real_$ts" --require-real
```

**All must be green for M5_0 to be considered complete.**

---

## Signal-Only Profitability Note

Until cost model is implemented (M5+):
- `is_profitable=true` means **signal-only** (gross spread > threshold)
- `is_profitable_net=null` (no net calculation without gas costs)
- `cost_model_available=false` in truth_report

Do NOT interpret `is_profitable=true` as guaranteed profit!

---

## Apply Commands

```powershell
# Copy new/updated files
Copy-Item outputs/strategy/jobs/run_scan_real.py strategy/jobs/
Copy-Item outputs/scripts/ci_m5_0_gate.py scripts/
Copy-Item outputs/tests/unit/test_price_sanity_inversion.py tests/unit/
Copy-Item outputs/tests/unit/test_ci_m5_0_gate.py tests/unit/
Copy-Item outputs/docs/TESTING.md docs/
Copy-Item outputs/docs/status/Status_M5_0.md docs/status/

# Verify tests pass
python -m pytest tests/unit/test_price_sanity_inversion.py -v
python -m pytest tests/unit/test_ci_m5_0_gate.py -v
python -m pytest -q

# Run M5_0 gate
python scripts/ci_m5_0_gate.py --offline

# Commit
git add strategy/jobs/run_scan_real.py scripts/ci_m5_0_gate.py \
        tests/unit/test_price_sanity_inversion.py tests/unit/test_ci_m5_0_gate.py \
        docs/TESTING.md docs/status/Status_M5_0.md
git commit -m "fix(M5_0): price orientation contract + ENV fallback for gate"
```
