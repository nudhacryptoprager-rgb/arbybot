# Status: M4 (REAL Pipeline Hardening)

**Status**: IN PROGRESS  
**Branch**: `split/code`  
**Last Updated**: 2026-01-30

## Goal

Run REAL pipeline with live RPC, pinned block, and **truthful metrics**.
Execution remains disabled - only price discovery and validation.

---

## 10-Step Fix Summary

| Step | Issue | Fix | Status |
|------|-------|-----|--------|
| 1 | PRICE_SANITY_FAIL implied_price=9.93 | Price normalization with inversion detection | Done |
| 2 | Price invariant inconsistent | price = "token_out per 1 token_in" everywhere | Done |
| 3 | confidence_factors.price_stability != health | Sync confidence factors with health section | Done |
| 4 | net_pnl_usdc contract unclear | net_pnl_usdc=None when cost_model_available=False | Done |
| 5 | Schema version drift | Frozen SCHEMA_VERSION="3.2.0" | Done |
| 6 | Anchor hardcoded, causes false rejects | Dynamic anchor from first successful quote | Done |
| 7 | Revalidation=0 | 1 re-quote for top opportunity | Done |
| 8 | Coverage minimal | Config allows expansion | Config ready |
| 9 | ASCII-safe CI | No emoji in ci_m4_gate.py output | Done |
| 10 | Definition of Done unclear | Status_M4.md with commands and invariants | Done |

---

## Contracts (Frozen)

### Schema Version

**SCHEMA_VERSION = "3.2.0"** (frozen)

### Price Contract (STEP 1-2)

```
price = token_out per 1 token_in

Examples:
- WETH/USDC: price ~ 3500 (USDC per 1 WETH)
- WBTC/USDC: price ~ 90000 (USDC per 1 WBTC)

If price < 100 for WETH/USDC, it's inverted and auto-corrected.
```

### PNL Contract (STEP 4)

| Field | Type | When no cost model | When cost model available |
|-------|------|--------------------|-----------------------------|
| `signal_pnl_usdc` | str | Always present | Always present |
| `would_execute_pnl_usdc` | str | Always present | Always present |
| `gross_pnl_usdc` | str | Always present | Always present |
| `net_pnl_usdc` | str \| None | **None** | str |
| `net_pnl_bps` | str \| None | **None** | str |
| `cost_model_available` | bool | False | True |

**CRITICAL**: `net_pnl_usdc` is None in both `pnl` section AND `top_opportunities` when `cost_model_available=False`.

### Confidence Contract (STEP 3)

```
health.price_stability_factor == top_opportunities[*].confidence_factors.price_stability

Formula: price_sanity_passed / (price_sanity_passed + price_sanity_failed)
```

### Reject Reason Contract

- Canonical: `PRICE_SANITY_FAILED`
- Legacy `PRICE_SANITY_FAIL` accepted (maps to "sanity" category)

### Anchor Contract (STEP 6)

```
Priority:
1. Dynamic anchor (first successful quote for pair)
2. Hardcoded bounds (fallback only)

anchor_source: "dynamic_first_quote" | "hardcoded_bounds"
```

### Execution Contract

| Field | M4 Value |
|-------|----------|
| `execution_enabled` | False |
| `execution_blocker` | "EXECUTION_DISABLED_M4" |
| `execution_ready_count` | 0 |
| `is_actionable` | False (all opps) |

---

## M4 Success Criteria

| Metric | Requirement |
|--------|-------------|
| Python | 3.11.x |
| `run_mode` | `REGISTRY_REAL` |
| `current_block` | `> 0` (from RPC) |
| `execution_enabled` | `false` |
| `execution_ready_count` | `0` |
| `quotes_fetched` | `>= 1` |
| `rpc_success_rate` | `> 0` |
| `dexes_active` | `>= 2` |
| `price_sanity_passed` | `>= 1` |
| `price_stability_factor` | `> 0` when sanity_passed > 0 |
| `confidence_factors.price_stability` | `== health.price_stability_factor` |
| `net_pnl_usdc` | `null` (no cost model) |
| `revalidation.total` | `>= 1` (best effort) |
| Artifacts | 4/4 |

---

## What's Done

- [x] REAL scan with live RPC
- [x] Pinned block from RPC
- [x] Price normalization with inversion detection
- [x] Dynamic anchor (first quote becomes anchor)
- [x] quotes_fetched >= 1
- [x] 4/4 artifacts
- [x] Execution disabled (explicit)
- [x] ASCII-safe CI gate output
- [x] Unified reject codes (PRICE_SANITY_FAILED canonical)
- [x] PnL contract: net_pnl_usdc=None when no cost model
- [x] Confidence sync: health.price_stability_factor = confidence_factors.price_stability
- [x] Revalidation: 1 re-quote for top opportunity

## What's NOT Done (M5+)

- [ ] Full dynamic anchor (external price feed)
- [ ] Extended revalidation (signal flip detection)
- [ ] Execution state machine
- [ ] Cost model (gas/slippage estimation)
- [ ] Private send integration

---

## Definition of Done (M4)

### Commands

```powershell
# 1. Python version check
python --version  # Must be 3.11.x

# 2. Import contract
python -c "from monitoring.truth_report import calculate_confidence, calculate_price_stability_factor; print('ok')"

# 3. Unit tests
python -m pytest -q --ignore=tests/integration

# 4. CI gate (offline)
python scripts/ci_m4_gate.py --offline --skip-python-check

# 5. CI gate (online) - optional, requires RPC
python scripts/ci_m4_gate.py --online --skip-python-check
```

### Expected Invariants (OFFLINE)

```
run_mode: REGISTRY_REAL
current_block: > 0
execution_enabled: false
execution_blocker: EXECUTION_DISABLED_M4
quotes_fetched: >= 1
dexes_active: >= 2
price_sanity_passed: >= 1
pnl.net_pnl_usdc: null (no cost model)
top_opportunities[*].net_pnl_usdc: null
top_opportunities[*].is_actionable: false
health.price_stability_factor == top_opportunities[*].confidence_factors.price_stability
revalidation.total: >= 1
```

### Exit Codes (ci_m4_gate.py)

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

## Files Changed

| File | Changes |
|------|---------|
| `strategy/jobs/run_scan_real.py` | Price normalization, dynamic anchor, revalidation |
| `monitoring/truth_report.py` | Confidence sync, PnL contract, PRICE_SANITY_FAILED |
| `scripts/ci_m4_gate.py` | ASCII-safe, all contract checks |
| `tests/unit/test_truth_report.py` | Confidence sync tests, PnL contract tests |
| `docs/status/Status_M4.md` | This file |
