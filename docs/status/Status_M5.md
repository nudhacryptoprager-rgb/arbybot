# Milestone 5 — Production small

> **Оновлено**: 2026-02-06 10:25 UTC  
> **SHA**: `748b46d`  
> **Статус**: ✅ Signals MVP DONE

---

## Deliverables

- Daily reporting artifact (`daily_report_*.json`) with schema_version
- Spread signals with paper cost estimates
- Transparent health metrics (rpc/dex/system)
- CI validation (`ci_m5_0_gate.py`)

## DoD-commands

```powershell
# Канонічна команда (scan + artifacts)
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 5

# Юніт-тести
python -m pytest tests/unit -q

# CI gate (online)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 5
```

---

## Статус виконання

| # | Задача | Статус |
|---|--------|--------|
| 1 | daily_report generator | ✅ |
| 2 | spread_signals з paper estimates | ✅ |
| 3 | tick/sqrtPriceX96 provenance | ✅ |
| 4 | config_params logging | ✅ |
| 5 | net_negative_reason field | ✅ |
| 6 | spread_frac as string | ✅ |
| 7 | spread_bps_ui (renamed from int) | ✅ |
| 8 | signals_total / opportunities_total | ✅ |
| 9 | execution_pnl separated | ✅ |
| 10 | pnl deprecated (v3.3 removal) | ✅ |

---

## Signals vs Opportunities (raw vs filtered)

| Layer | Purpose | Threshold |
|-------|---------|-----------|
| `spread_signals` | Raw detected spreads (for debug) | `min_spread_bps` |
| `top_opportunities_net_positive` | Filtered opportunities | `min_net_pnl_usdc_est` |

**Contract**:
- `signals_total` = count of all detected spreads (may include net-negative)
- `opportunities_total` = count of spreads passing net threshold (actionable)
- When `signals_total > 0` but `opportunities_total = 0` → micro-spreads eaten by gas

### Example: Net-Negative Signal

```json
{
  "spread_bps_exact": 0.5422,
  "spread_bps_ui": 0,
  "gross_pnl_usdc_est": 0.0542,
  "net_pnl_usdc_est": -0.0458,
  "is_net_positive_est": false,
  "net_negative_reason": "micro_spread_net_negative_due_to_gas"
}
```

**Interpretation**: Spread exists (0.54 bps), but gas ($0.10) > gross ($0.05), so net is negative.
This is **expected behavior** — the signal is valid for debug, but not an opportunity.

---

## Останній прогін

```powershell
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 5
```

**RESULT: PASS + data\runs\manual_run_20260206_102300**

### Артефакти (ключові поля):

- `pairs`: 5 (WETH/USDC, WETH/USDT, WBTC/WETH, ARB/WETH, LINK/WETH) ✅
- `signals_total`: 1 — raw signals detected ✅
- `opportunities_total`: 1 — net-positive opportunities ✅
- `spread_bps_exact`: 4.9833 — real spread ✅
- `spread_bps_ui`: 4 — honest floor() ✅
- `net_pnl_usdc_est`: +0.3983 — **NET POSITIVE** ✅
- `is_net_positive_est`: true ✅
- `net_negative_reason`: null (not needed) ✅
- `stats.requested_cycles`: 5 ✅
- `stats.cycles_completed`: 5 ✅

**Note**: signals_total=1, opportunities_total=1 — real opportunity detected and actionable.

---

## Юніт-тести

```
465 passed, 5 subtests passed
```

---

## Key Definitions

| Field | Type | Semantics |
|-------|------|-----------|
| `spread_bps_exact` | float | Basis points — **USE FOR LOGIC/RANKING** |
| `spread_bps_ui` | int | floor() — honest, may be 0 — **UI DISPLAY ONLY, NEVER FOR LOGIC** |
| `spread_pct` | float | **Percent** (0.0036 = 0.0036%, NOT fraction) |
| `spread_frac` | string | **Fraction** as string (no scientific notation, e.g. "0.000036") |
| `*_est` fields | float | **Paper only** — estimates, not execution |
| `net_pnl_usdc_est` | float | Paper estimate: gross - gas - slippage |
| `net_negative_reason` | string | Why net < 0 (null if positive) |
| `execution_pnl` | object | Execution PnL (DISABLED in M5, requires gas oracle) |

### Paper vs Execution (Strong Guarantee)

| Layer | Status | Purpose |
|-------|--------|---------|
| Paper (`*_est` fields) | ✅ ACTIVE | Estimates based on config gas/slippage |
| Execution (`execution_pnl`) | ❌ DISABLED | Requires gas oracle (M6) |

**Contract**: `paper != execution`. Paper estimates are for signal ranking only.

### Canonical Config Params

```yaml
paper_size_usd: 1000
gas_usd_estimate: 0.10
paper_slippage_bps: 0
min_spread_bps: 0              # debug=0; production=2-5 or net-only
min_net_pnl_usdc_est: 0.0      # break-even threshold for opportunities
```

### Policy

- `spread_bps_exact` — **source of truth** for logic, gates, ranking
- `spread_bps_ui` — floor(), may be 0, **UI display only** (NEVER use for filtering/ranking)
- `spread_pct` = percent, `spread_frac` = fraction (both derived from `spread_bps_exact`)
- Net-negative micro-spreads excluded from `top_opportunities_net_positive`
- `net_negative_reason` explains why net < 0
- **Debug profile**: `min_spread_bps: 0` — shows all positive spreads
- **Production profile**: either `min_spread_bps: 2-5` or net-only filter via `min_net_pnl_usdc_est`
- **Tuning rule**: if net always < 0, raise threshold — don't trust opportunities

### Deprecation Plan: `pnl` → `execution_pnl`

| Schema Version | `pnl` Field | `execution_pnl` Field |
|----------------|-------------|----------------------|
| m5:truth:v3.2 | ✅ Present (deprecated) | ✅ Present |
| m5:truth:v3.3 | ❌ Removed | ✅ Present |

**Migration**:
- Consumers should use `execution_pnl` now
- `pnl` contains `_deprecated: true` and `_migration` message
- Unit test: `test_pnl_marked_deprecated` verifies deprecation

---

## Наступні кроки

1. ~~Розширити universe (5-10 пар)~~ ✅ Done (5 pairs)
2. ~~Ранжування signals за net_pnl~~ ✅ Done
3. Gas oracle інтеграція (M6)
4. Schema v2 bump: remove deprecated `pnl` field

---

## SHA закриття

`748b46d` — Signals MVP DONE
