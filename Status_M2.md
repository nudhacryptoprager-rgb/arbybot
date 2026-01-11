# Status_M2.md — Paper Trading Session & Decision Simulation

**Дата:** 2026-01-11  
**Milestone:** M2 — Paper Trading & Decision Tracking  
**Статус:** ✅ **COMPLETE**

---

## 1. Нові features

### ✅ 1.1 PaperSession з JSONL persistence

```python
# strategy/paper_trading.py
class PaperSession:
    def __init__(
        self,
        trades_dir: Path,
        cooldown_blocks: int = 10,
        simulate_blocked: bool = True,
    ):
        ...
    
    def record_trade(self, trade: PaperTrade) -> bool:
        # Checks cooldown, determines outcome, persists to JSONL
        ...
```

**JSONL file:** `data/trades/paper_trades_{session_id}.jsonl`

### ✅ 1.2 Trade Outcome Categories

| Outcome | Condition |
|---------|-----------|
| `WOULD_EXECUTE` | executable=true AND net_pnl_bps > 0 |
| `BLOCKED_EXEC` | executable=false AND net_pnl_bps > 0 |
| `UNPROFITABLE` | net_pnl_bps <= 0 |
| `COOLDOWN` | Same spread within N blocks |

### ✅ 1.3 Cooldown/Dedupe Logic

```python
if paper_session.is_on_cooldown(spread_id, current_block):
    trade.outcome = TradeOutcome.COOLDOWN
    return False  # Not recorded
```

**Policy:** `--cooldown-blocks N` (default: 10)

### ✅ 1.4 PnL в USDC

```python
def calculate_usdc_value(amount_in_wei, implied_price, decimals=18):
    amount = Decimal(amount_in_wei) / Decimal(10 ** decimals)
    return float(amount * implied_price)

def calculate_pnl_usdc(amount_in_wei, net_pnl_bps, implied_price, decimals=18):
    trade_value = calculate_usdc_value(amount_in_wei, implied_price, decimals)
    return trade_value * (net_pnl_bps / 10000)
```

### ✅ 1.5 RPC Stats в Snapshot

```json
{
  "rpc_stats": {
    "https://arb1.arbitrum.io/rpc": {
      "total_requests": 15,
      "success_rate": 0.933,
      "avg_latency_ms": 45,
      "last_error": null
    }
  }
}
```

### ✅ 1.6 CLI Options

```bash
python -m strategy.jobs.run_scan \
    --chain arbitrum_one \
    --once \
    --paper-trading \
    --simulate-blocked \
    --cooldown-blocks 10
```

---

## 2. PaperTrade Schema

```json
{
  "spread_id": "uniswap_v3_sushiswap_v3_500_1000000000000000000",
  "block_number": 419855259,
  "timestamp": "2026-01-11T...",
  "chain_id": 42161,
  "buy_dex": "uniswap_v3",
  "sell_dex": "sushiswap_v3",
  "token_in": "WETH",
  "token_out": "USDC",
  "fee": 500,
  "amount_in_wei": "1000000000000000000",
  "buy_price": "2500.00",
  "sell_price": "2502.50",
  "spread_bps": 10,
  "gas_cost_bps": 3,
  "net_pnl_bps": 7,
  "gas_price_gwei": 0.01,
  "amount_in_usdc": 2500.0,
  "expected_pnl_usdc": 1.75,
  "outcome": "WOULD_EXECUTE",
  "executable": true,
  "buy_verified": true,
  "sell_verified": true
}
```

---

## 3. Session Stats (Cumulative)

```json
{
  "session_id": "20260111_104801",
  "stats": {
    "total_signals": 100,
    "would_execute": 25,
    "blocked_exec": 60,
    "unprofitable": 10,
    "cooldown_skipped": 5,
    "total_pnl_bps": 250,
    "total_pnl_usdc": 62.50
  }
}
```

---

## 4. Snapshot структура

```json
{
  "cycle_summaries": [{
    "block_number": 419855259,
    "gas_price_gwei": 0.01,
    "spreads": [...],
    "paper_trades": [
      {"spread_id": "...", "outcome": "BLOCKED_EXEC", "net_pnl_bps": 10, "expected_pnl_usdc": 2.50}
    ],
    "rpc_stats": {...}
  }]
}
```

---

## 5. Тести

**140 passed ✅** (122 existing + 18 paper trading)

```bash
pytest tests/unit/test_paper_trading.py -v
```

| Test Class | Tests |
|------------|-------|
| TestPaperTrade | 2 |
| TestPaperSessionCooldown | 4 |
| TestPaperSessionOutcomes | 4 |
| TestPaperSessionPersistence | 2 |
| TestPaperSessionSummary | 1 |
| TestUSDCCalculations | 5 |

---

## 6. Файли

| Файл | Зміни |
|------|-------|
| `strategy/paper_trading.py` | **NEW** - PaperSession, PaperTrade, USDC calc |
| `strategy/jobs/run_scan.py` | Integrated paper session, RPC stats |
| `chains/providers.py` | +get_gas_price() |
| `tests/unit/test_paper_trading.py` | **NEW** - 18 tests |

---

## 7. Acceptance Criteria

| Критерій | Статус |
|----------|--------|
| PaperSession з JSONL | ✅ |
| Cooldown/dedupe | ✅ |
| TradeOutcome categories | ✅ |
| PnL в USDC | ✅ |
| RPC stats в snapshot | ✅ |
| CLI options | ✅ |
| 18 paper trading tests | ✅ |

---

## 8. Поточна реальність

Зараз `WOULD_EXECUTE = 0` бо `sushiswap_v3.verified_for_execution = false`.

Це означає всі profitable spreads йдуть в `BLOCKED_EXEC`.

**Рішення для прогресу:**
1. Додати другий DEX з `verified_for_execution = true`
2. АБО: аналізувати `BLOCKED_EXEC` trades як "що б було"

---

## 9. Log Output

```
Paper session started: 20260111_104801
Block pinned: 419855259
Gas price: 0.0100 gwei
Paper trade: BLOCKED_EXEC uniswap_v3_sushiswap_v3_500_... net=10bps $2.50
Scan cycle complete: 12/12 fetched, 8 passed gates, 6 spreads, 0 executable, 4 blocked, 0 cooldown
Paper session summary: {'would_execute': 0, 'blocked_exec': 4, 'total_pnl_usdc': 0.0}
```

---

## 10. Наступні кроки (M2.x)

| Step | Description |
|------|-------------|
| M2.1 | Revalidation: requote after 1-2 blocks, track `would_still_execute` |
| M2.2 | Multiple pairs: expand beyond WETH/USDC |
| M2.3 | Second executable DEX: enable Uniswap router for execution |
| M2.4 | Execution metadata: router address, calldata template |
| M2.5 | PnL dashboard: aggregate stats over time |

---

*Документ згенеровано: 2026-01-11*
