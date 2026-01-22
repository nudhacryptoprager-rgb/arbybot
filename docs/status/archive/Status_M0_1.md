# Status_M0_1.md — Quote Pipeline + Spread Detection

**Дата:** 2026-01-10  
**Milestone:** M0.1 → M1.x Bridge (Quote Pipeline + Raw Spreads)  
**Статус:** ✅ **COMPLETE**

---

## 1. Виправлені логічні помилки

### ✅ 1.1 Метрики pipeline (3-stage)

| Стара метрика | Нова метрика | Опис |
|---------------|--------------|------|
| `quotes_success` | `quotes_attempted` | Скільки спроб |
| - | `quotes_fetched` | Успішно отримані та декодовані |
| - | `quotes_passed_gates` | Пройшли ВСІ gates (single + curve) |

**Rates:**
- `fetch_rate` = fetched / attempted
- `gate_pass_rate` = passed_gates / fetched

### ✅ 1.2 Curve rejects → quote_reject_reasons

**Було:** curve failures → `opportunity_reject_reasons` (неправильно)  
**Стало:** curve failures → `quote_reject_reasons` (поки opportunities=0)

### ✅ 1.3 sqrt_price_x96_after + implied_price в snapshot

```json
{
  "quotes": [{
    "sqrt_price_x96_after": "1234567890123456789",
    "implied_price": "2497.123456"
  }]
}
```

### ✅ 1.4 dexes_passed_gate в snapshot

```json
{
  "dexes_passed_gate": [
    {"dex_key": "uniswap_v3", "quoter": "0x...", "fee_tiers": [100, 500, 3000]}
  ]
}
```

### ✅ 1.5 top_samples в reject histogram

```json
{
  "quote_rejects": {
    "top_samples": {
      "QUOTE_GAS_TOO_HIGH": [
        {"dex": "sushiswap_v3", "fee": 100, "gas_estimate": 5000000, "ticks_crossed": 45}
      ]
    }
  }
}
```

### ✅ 1.6 Negative slippage rejection

```python
if slippage_bps < 0:
    return GateResult(
        passed=False,
        reject_code=ErrorCode.QUOTE_INCONSISTENT,
        details={"reason": "negative_slippage", ...}
    )
```

### ✅ 1.7 Raw spread detection (spread_bps)

```json
{
  "spreads": [{
    "dex_a": "uniswap_v3",
    "dex_b": "sushiswap_v3",
    "fee": 500,
    "amount_in": "1000000000000000000",
    "price_a": "2497.50",
    "price_b": "2495.25",
    "spread_bps": 9
  }]
}
```

### ✅ 1.8 Harness marker

```json
{
  "harness": "SMOKE_WETH_USDC"
}
```

---

## 2. Snapshot структура (з робочим RPC)

```json
{
  "timestamp": "2026-01-10T...",
  "harness": "SMOKE_WETH_USDC",
  "session_summary": {
    "total_quotes_attempted": 12,
    "total_quotes_fetched": 10,
    "total_quotes_passed_gates": 6,
    "fetch_rate": 0.8333,
    "gate_pass_rate": 0.6,
    "quote_reject_histogram": {
      "QUOTE_GAS_TOO_HIGH": 2,
      "TICKS_CROSSED_TOO_MANY": 2
    }
  },
  "cycle_summaries": [{
    "block_number": 419855259,
    "dexes_passed_gate": [...],
    "quotes_attempted": 12,
    "quotes_fetched": 10,
    "quotes_passed_gates": 6,
    "quotes": [{
      "implied_price": "2497.50",
      "sqrt_price_x96_after": "...",
      "ticks_crossed": 2,
      "latency_ms": 45
    }],
    "spreads": [{
      "dex_a": "uniswap_v3",
      "dex_b": "sushiswap_v3",
      "spread_bps": 9
    }]
  }]
}
```

---

## 3. Reject Histogram структура

```json
{
  "quote_rejects": {
    "total": 6,
    "histogram": {...},
    "sorted": {...},
    "top_samples": {
      "QUOTE_GAS_TOO_HIGH": [
        {
          "dex": "sushiswap_v3",
          "fee": 100,
          "amount_in": 1000000000000000000,
          "gas_estimate": 5000000,
          "ticks_crossed": 45,
          "latency_ms": 120,
          "details": {"gas_estimate": 5000000, "max_gas": 500000}
        }
      ]
    }
  }
}
```

---

## 4. Змінені файли

| Файл | Зміни |
|------|-------|
| `strategy/gates.py` | Negative slippage rejection |
| `strategy/jobs/run_scan.py` | 3-stage metrics, spreads, samples, harness marker |
| `tests/unit/test_gates.py` | +1 test (negative slippage) |

---

## 5. Тести

**122 passed ✅** (99 + 23 gates tests)

```bash
pytest tests/unit/ -v
```

---

## 6. Acceptance Criteria

| Критерій | Статус |
|----------|--------|
| 3-stage metrics (attempted/fetched/passed) | ✅ |
| Curve rejects → quote_reject_reasons | ✅ |
| sqrt_price_x96_after в snapshot | ✅ |
| implied_price в snapshot | ✅ |
| dexes_passed_gate в snapshot | ✅ |
| top_samples в reject histogram | ✅ |
| Negative slippage rejection | ✅ |
| spread_bps detection | ✅ |
| harness marker | ✅ |

---

## 7. Що означають метрики

**Pipeline flow:**
```
attempted (12)
    ↓ RPC calls
fetched (10) ← 2 failed: QUOTE_REVERT
    ↓ single-quote gates
    ↓ (gas, ticks, zero output)
    ↓ curve gates (slippage, monotonicity)
passed_gates (6) ← 4 failed: GAS_TOO_HIGH, TICKS_TOO_MANY
```

**Rates:**
- `fetch_rate = 10/12 = 83%` — RPC success
- `gate_pass_rate = 6/10 = 60%` — quote quality

---

## 8. Наступні кроки

1. **Opportunity PnL** — spread_bps - gas_cost_bps = net_pnl_bps
2. **Executability check** — verified_for_execution gating
3. **Configurable thresholds** — per-chain max_gas, max_ticks, max_slippage

---

*Документ згенеровано: 2026-01-10*
