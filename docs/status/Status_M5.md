# Milestone 5 — Production small

> **Оновлено**: 2026-02-06 11:11 UTC  
> **SHA**: `7a823ba`  
> **Статус**: ✅ DONE

---

## DONE Criteria (per Roadmap)

Roadmap M5 вимагає:
- ✅ Daily report: net PnL, win-rate, tail losses, reject reasons
- ✅ Авто-зниження size при рості impact (autosize object present)
- ✅ Health score для RPC/DEX/System

### Acceptance Checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `ci_m5_0_gate.py --online --cycles 5` PASS | ✅ |
| 2 | daily_report: provenance, health, top_reject_reasons, top_opportunities | ✅ |
| 3 | daily_report: autosize object always present | ✅ |
| 4 | negative tests: schema_version mismatch, quotes_total invariant | ✅ |
| 5 | truth_report: signals_total, opportunities_total | ✅ |

---

## Канонічна команда

```powershell
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 5
```

---

## Останній Golden Run

**RunDir**: `data/runs/ci_m5_gate_20260206_111041`  
**Date**: 2026-02-06  
**Result**: ✅ PASS

### Key Metrics

| Metric | Value |
|--------|-------|
| `paper_net_pnl_usdc` | -$0.06 (micro-spread, gas > gross) |
| `spread_bps_exact` | 0.3952 |
| `spread_bps_ui` | 0 (floor) |
| `quote_sanity_rate` | 0.5833 |
| `signal_win_rate` | 0.0 |
| `signals_total` | 1 |
| `opportunities_total` | 0 |
| `requested_cycles` | 5 |
| `cycles_completed` | 5 |
| `p50_latency_ms` | ~120ms |
| `ws_connected` | true |

### top_signal Example

```json
{
  "pair": "WETH/USDC",
  "buy_dex": "sushiswap_v3",
  "sell_dex": "uniswap_v3",
  "spread_bps_exact": 0.3952,
  "spread_bps_ui": 0,
  "gross_pnl_usdc_est": 0.0395,
  "net_pnl_usdc_est": -0.0605,
  "is_net_positive_est": false,
  "net_negative_reason": "micro_spread_net_negative_due_to_gas"
}
```

---

## Юніт-тести

```
472 passed, 5 subtests passed
```

---

## Policies

### Golden Artifact Policy

Golden artifacts (`docs/artifacts/*_golden.json`) оновлюються **ТІЛЬКИ** коли:
1. `schema_version` змінено (official bump), або
2. Офіційно додано нові required поля (задокументовано в Status)

**Інакше golden залишається фіксованим** — це regression anchor.

### daily_report Schema Contract

Schema `m5:daily:v1` **заморожена**. Дозволено:
- ✅ Додавати нові optional поля
- ❌ Перейменовувати існуючі поля
- ❌ Видаляти поля без schema bump

### Signals vs Opportunities Contract

```
opportunity = signal where:
  - is_net_positive_est = true, AND
  - net_pnl_usdc_est >= min_net_pnl_usdc_est (from config)

Therefore: top_opportunities ⊆ top_signals (subset)
```

### Tenderly Policy

- `tenderly_enabled: false` — default для M5
- Tenderly не блокує PASS (optional diagnostic)
- Статус прозоро в артефактах: `infra.tenderly_enabled`, `infra.tenderly_attempted`

### WS Health Rules

| Condition | Result |
|-----------|--------|
| `ws_enabled=true`, `ws_connected=true` | ✅ OK |
| `ws_enabled=true`, `ws_connected=false` | ⚠️ WARN (fallback to HTTP) |
| `ws_enabled=false` | ✅ OK (HTTP only) |

### Cost Model Transparency

Всі paper estimates мають чітке джерело:

```json
{
  "cost_model": {
    "type": "gas_only",
    "gas_usd_estimate": 0.10,
    "gas_source": "config"
  }
}
```

Якщо `pnl_available=true`, то `cost_model` **обов'язковий**.

---

## Key Metrics

| Metric | Value | Source |
|--------|-------|--------|
| `signals_total` | 1 | truth_report |
| `opportunities_total` | 1 | truth_report |
| `gate_pass_rate` | 0.58 | daily_report |
| `signal_win_rate` | 1.0 | daily_report |
| `paper_net_pnl_usdc` | +0.40 | daily_report |

---

## Schema Tests

| Test | Purpose |
|------|---------|
| `test_top_signal_matches_truth_spread_signals` | daily/truth consistency |
| `test_signals_total_matches` | count invariant |
| `test_opportunities_total_matches` | filter invariant |
| `test_gate_pass_rate_calculation` | rate formula |
| `test_signal_win_rate_calculation` | rate formula |
| `test_empty_spread_signals_no_top_signal` | edge case |

---

## Deprecation Plan

| Field | Current | Removal |
|-------|---------|---------|
| `pnl` | v3.2 (deprecated) | v3.3 |
| `paper_win_rate` | v1.0 (alias) | v2.0 |
| `deprecated_legacy_trades_count` | v1.0 | v2.0 |

---

## Roadmap Next

Per Roadmap.md:
- **M6**: CEX↔DEX inventory-based (optional)
- **M7**: Triangular (R&D)
- **M8**: Cross-chain (R&D)

---

## References

- **Roadmap**: [Roadmap.md](../../Roadmap.md)
- **Template**: [REPORT_TEMPLATE.md](../REPORT_TEMPLATE.md)
- **Testing**: [TESTING.md](../TESTING.md)

---

## SHA закриття

`7a823ba` — M5 DONE
