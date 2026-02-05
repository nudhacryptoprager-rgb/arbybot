# Milestone 5 — Production small

> **Оновлено**: 2026-02-05 22:00 UTC  
> **SHA**: `pending`  
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
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 3
```

**RESULT: PASS + data\runs\manual_run_20260205_215741**

### Артефакти (ключові поля):

- `spread_bps_exact`: 0.3621 — micro-spread detected ✅
- `spread_bps_int`: 1 — UI display (min 1 for positive) ✅
- `spread_frac`: "0.0000362069" — string, no scientific notation ✅
- `is_gross_positive`: true — sell > buy ✅
- `net_pnl_usdc_est`: -0.0638 — net negative (gas > gross)
- `net_negative_reason`: "micro_spread_net_negative_due_to_gas" ✅
- `requested_cycles`: 3 ✅
- `cycles_completed`: 3 ✅

---

## Юніт-тести

```
465 passed, 5 subtests passed
```

---

## Key Definitions

| Field | Type | Semantics |
|-------|------|-----------|
| `spread_bps_exact` | float | Basis points — **USE FOR LOGIC** |
| `spread_bps_int` | int | Min 1 for positive — **UI ONLY** |
| `spread_frac` | string | Decimal fraction (no scientific notation) |
| `net_pnl_usdc_est` | float | Paper estimate: gross - gas - slippage |
| `net_negative_reason` | string | Why net < 0 |
| `execution_pnl` | object | Execution PnL (disabled in M5) |

### Paper vs Execution

| Layer | Status | Purpose |
|-------|--------|---------|
| Paper (`*_est` fields) | ✅ ACTIVE | Estimates based on config gas/slippage |
| Execution (`execution_pnl`) | ❌ DISABLED | Requires gas oracle (M6) |

---

## Наступні кроки

1. Розширити universe (5-10 пар)
2. Ранжування signals за net_pnl
3. Gas oracle інтеграція (M6)

---

## SHA закриття

_(заповнюється при закритті milestone)_
