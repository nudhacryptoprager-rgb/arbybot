# Milestone 5 — Production small

> **Оновлено**: 2026-02-05 22:20 UTC  
> **SHA**: `e8edf20`  
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
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 3

# Юніт-тести
python -m pytest tests/unit -q

# CI gate (online)
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3
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
| 7 | spread_bps_int fix (min 1) | ✅ |
| 8 | top_opportunities_net_positive | ✅ |
| 9 | execution_pnl separated | ✅ |
| 10 | pnl marked deprecated | ✅ |

---

## Останній прогін

```powershell
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 5
```

**RESULT: PASS + data\runs\manual_run_20260205_222223**

### Артефакти (ключові поля):

- `pairs`: 5 (WETH/USDC, WETH/USDT, WBTC/WETH, ARB/WETH, LINK/WETH) ✅
- `quotes_total`: 12 — multi-pair scanning ✅
- `spread_signals_count`: 1 ✅
- `spread_bps_exact`: 0.5422 — micro-spread detected ✅
- `spread_bps_int`: 0 — honest floor() (< 1 bps) ✅
- `net_pnl_usdc_est`: -0.0458 — net-negative (gas > spread) ✅
- `is_net_positive_est`: false ✅
- `config_params.min_net_pnl_usdc_est`: 0.0 — threshold active ✅
- `stats.requested_cycles`: 5 ✅
- `stats.cycles_completed`: 5 ✅

**Note**: Micro-spread (0.54 bps) correctly identified as net-negative due to gas costs.
This validates the net-only filter working correctly.

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
| `spread_bps_int` | int | floor() — honest, may be 0 — **UI DISPLAY ONLY, NEVER FOR LOGIC** |
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
min_net_pnl_usdc_est: 0.0      # break-even threshold for top_opportunities
```

### Policy

- `spread_bps_exact` — **source of truth** for logic, gates, ranking
- `spread_bps_int` — floor(), may be 0, **UI display only** (NEVER use for filtering/ranking)
- `spread_pct` = percent, `spread_frac` = fraction (both derived from `spread_bps_exact`)
- Net-negative micro-spreads excluded from `top_opportunities_net_positive`
- `net_negative_reason` explains why net < 0
- **Debug profile**: `min_spread_bps: 0` — shows all positive spreads (засмічує при universe)
- **Production profile**: either `min_spread_bps: 2-5` or net-only filter via `min_net_pnl_usdc_est`

### Deprecation Plan: `pnl` → `execution_pnl`

| Schema Version | `pnl` Field | `execution_pnl` Field |
|----------------|-------------|----------------------|
| m5:truth:v1 | ✅ Present (deprecated) | ✅ Present |
| m5:truth:v2 | ❌ Removed | ✅ Present |

**Migration**:
- Consumers should use `execution_pnl` now
- `pnl` contains `_deprecated: true` and `_migration` message
- Unit test: `test_pnl_absent_after_schema_v2` verifies removal

---

## Наступні кроки

1. ~~Розширити universe (5-10 пар)~~ ✅ Done (5 pairs)
2. ~~Ранжування signals за net_pnl~~ ✅ Done
3. Gas oracle інтеграція (M6)
4. Schema v2 bump: remove deprecated `pnl` field

---

## SHA закриття

`e8edf20` — Signals MVP DONE
