# Status_M1.md — Real Gas Price + Paper Trading

**Дата:** 2026-01-11  
**Milestone:** M1 → M2 Bridge (Real Gas + Paper Sim)  
**Статус:** ✅ **COMPLETE**

---

## 1. Нові features

### ✅ 1.1 Real Gas Price (eth_gasPrice)

```python
# chains/providers.py
async def get_gas_price(self) -> tuple[int, int]:
    response = await self.call("eth_gasPrice")
    gas_price_wei = int(response.result, 16)
    return gas_price_wei, response.latency_ms

# run_scan.py
gas_price_wei, gas_latency = await provider.get_gas_price()
gas_price_gwei = gas_price_wei / 10**9
```

### ✅ 1.2 Paper Trading Simulation

```json
{
  "paper_trades": [
    {
      "spread_id": "uniswap_v3_sushiswap_v3_500_1000000000000000000",
      "action": "WOULD_EXECUTE",
      "block_number": 419855259,
      "buy_dex": "uniswap_v3",
      "sell_dex": "sushiswap_v3",
      "expected_pnl_bps": 10,
      "gas_price_gwei": 0.01
    },
    {
      "spread_id": "...",
      "action": "BLOCKED_BY_EXECUTION_GATE",
      "blocked_reason": {
        "buy_verified": true,
        "sell_verified": false
      }
    }
  ]
}
```

### ✅ 1.3 Extended Spread Schema

```json
{
  "spreads": [{
    "id": "uniswap_v3_sushiswap_v3_500_1000000000000000000",
    "buy_leg": {
      "dex": "uniswap_v3",
      "price": "2497.50",
      "amount_out": "2497500000",
      "gas_estimate": 150000,
      "ticks_crossed": 2,
      "verified_for_execution": true
    },
    "sell_leg": {
      "dex": "sushiswap_v3",
      "price": "2500.75",
      "amount_out": "2500750000",
      "gas_estimate": 180000,
      "ticks_crossed": 3,
      "verified_for_execution": true
    },
    "fee": 500,
    "amount_in": "1000000000000000000",
    "spread_bps": 13,
    "gas_price_gwei": 0.01,
    "gas_cost_bps": 3,
    "net_pnl_bps": 10,
    "profitable": true,
    "executable": true
  }]
}
```

### ✅ 1.4 Curve Gates Fix

```python
# БУЛО: curve gates на fetched_quotes (включало сміттєві)
# СТАЛО: curve gates тільки на single_passed_quotes

single_passed_quotes: list[Quote] = []
# ... додаємо тільки після проходження single gates
if len(single_passed_quotes) >= 2:
    curve_failures = apply_curve_gates(single_passed_quotes)
```

---

## 2. Snapshot структура (з робочим RPC)

```json
{
  "harness": "SMOKE_WETH_USDC",
  "cycle_summaries": [{
    "block_number": 419855259,
    "gas_price_gwei": 0.01,
    "quotes_attempted": 12,
    "quotes_fetched": 12,
    "quotes_passed_gates": 8,
    "spreads": [{
      "id": "...",
      "buy_leg": {...},
      "sell_leg": {...},
      "gas_price_gwei": 0.01,
      "net_pnl_bps": 10,
      "executable": true
    }],
    "paper_trades": [
      {"action": "WOULD_EXECUTE", "expected_pnl_bps": 10},
      {"action": "BLOCKED_BY_EXECUTION_GATE", "blocked_reason": {...}}
    ]
  }]
}
```

---

## 3. Paper Trade Actions

| Action | Опис |
|--------|------|
| `WOULD_EXECUTE` | net_pnl_bps > 0 AND executable = true |
| `BLOCKED_BY_EXECUTION_GATE` | net_pnl_bps > 0 AND executable = false |

---

## 4. Gas Cost Formula

```python
def calculate_gas_cost_bps(gas_a, gas_b, amount_in_wei, gas_price_wei):
    total_gas = gas_a + gas_b  # Both legs
    gas_cost_wei = total_gas * gas_price_wei  # Real price!
    return (gas_cost_wei * 10000) // amount_in_wei
```

---

## 5. Log Output

```
Block pinned: 419855259
Gas price: 0.0100 gwei (10000000 wei)
Spread (EXECUTABLE): buy@uniswap_v3 sell@sushiswap_v3 = 13 bps - 3 gas = 10 net (fee=500, size=1000000000000000000, gas=0.01gwei)
PAPER TRADE: uniswap_v3→sushiswap_v3 net=10 bps (would execute)
Scan cycle complete: 12/12 fetched, 8 passed gates, 6 spreads, 4 executable, 2 blocked
```

---

## 6. Змінені файли

| Файл | Зміни |
|------|-------|
| `chains/providers.py` | +get_gas_price() method |
| `strategy/jobs/run_scan.py` | Real gas, extended spread schema, paper trades |

---

## 7. Тести

**122 passed ✅**

```bash
pytest tests/unit/ -v
```

---

## 8. Acceptance Criteria

| Критерій | Статус |
|----------|--------|
| eth_gasPrice from RPC | ✅ |
| gas_price_gwei in snapshot | ✅ |
| Extended spread with both legs | ✅ |
| paper_trades[] in snapshot | ✅ |
| WOULD_EXECUTE action | ✅ |
| BLOCKED_BY_EXECUTION_GATE action | ✅ |
| Curve gates on correct quotes | ✅ |

---

## 9. Прогрес M1→M2

| Етап | Статус |
|------|--------|
| M1.1 Block pinning | ✅ |
| M1.2 Quote fetching | ✅ |
| M1.3 Quote gates | ✅ |
| M1.4 Spread detection | ✅ |
| M1.5 Net PnL | ✅ |
| M1.6 Executability | ✅ |
| M1.7 Real gas price | ✅ |
| M1.8 Paper trading | ✅ |

**M1 Complete. Ready for M2 (Execution Simulation).**

---

## 10. Наступні кроки (M2)

1. **Slippage simulation** — estimate actual fill price
2. **Trade tracking** — accumulate paper PnL over time
3. **Router simulation** — simulate swap tx
4. **Multiple pairs** — expand beyond WETH/USDC

---

*Документ згенеровано: 2026-01-11*
