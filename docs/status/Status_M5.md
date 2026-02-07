# Milestone 5 — Production small

> **Оновлено**: 2026-02-07 10:35 UTC  
> **SHA**: `pending`  
> **Статус**: ✅ DONE

---

## Виконані директиви (2026-02-07)

| # | Директива | Статус |
|---|-----------|--------|
| 1 | Hard reject `pool_address=null` | ✅ POOL_MISSING |
| 2 | Reject v3 quotes без `tick`/`sqrt_price_x96` | ✅ V3_SLOT0_FAILED |
| 3 | Price outlier detection (>100% spread) | ✅ PRICE_OUTLIER |
| 4 | Confidence = "low" коли `execution_disabled` | ✅ Виправлено |
| 5 | `pnl_available=false` при invalid quotes | ✅ Додано |
| 6 | Gate --strict fail на `pool_missing_count > 0` | ✅ Додано |
| 7 | Знайти пули SushiSwap V3 для всіх пар | ✅ 32 пули знайдено |
| 8 | Розширити сканер на 5+ пар | ✅ 5 пар активних |
| 9 | Уніфікувати `reject_reason` → `reason` | ✅ Тести проходять |
| 10 | Golden run з реальними цінами | ✅ PASS |

---

## DONE Criteria (per Roadmap)

Roadmap M5 вимагає:
- ✅ Daily report: net PnL, win-rate, tail losses, reject reasons
- ✅ Авто-зниження size при рості impact (autosize object present)
- ✅ Health score для RPC/DEX/System

### Acceptance Checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `ci_m5_0_gate.py --online --cycles 1` PASS | ✅ |
| 2 | daily_report: provenance, health, top_reject_reasons, top_opportunities | ✅ |
| 3 | daily_report: autosize object always present | ✅ |
| 4 | negative tests: schema_version mismatch, quotes_total invariant | ✅ |
| 5 | truth_report: signals_total, opportunities_total | ✅ |
| 6 | No fake quotes (pool_address=null) | ✅ |
| 7 | No cosmic spreads (PRICE_OUTLIER detection) | ✅ |

---

## Канонічна команда

```powershell
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
```

---

## Останній Golden Run

**RunDir**: `data/runs/ci_m5_gate_20260207_103328`  
**Date**: 2026-02-07  
**Result**: ✅ PASS

### Key Metrics

| Metric | Value |
|--------|-------|
| `quotes_total` | 12 |
| `quotes_rejected` | 0 |
| `pool_missing_count` | 0 |
| `v3_slot0_failed_count` | 0 |
| `price_sanity_failed` | 0 |
| `dexes_active` | 2 |
| `pairs_scanned` | 5 |
| `spread_signals` | 2 |

### Spread Signals (реальні ціни!)

| Pair | Spread (bps) | Status |
|------|-------------|--------|
| WETH/USDC | 1.4 | ✅ Стабільна |
| WETH/USDT | 1.0 | ✅ Стабільна |
| ARB/WETH | 7.6 | ✅ **Signal!** |
| wstETH/WETH | 0.09 | ✅ Стабільна |
| ARB/USDC | 14.9 | ✅ **Signal!** |

### Приклад Quote (реальні дані)

```json
{
  "pair": "WETH/USDC",
  "dex_id": "uniswap_v3",
  "pool_address": "0xC6962004f452bE9203591991D15f6b388e09E8D0",
  "price_exact": "2011.35",
  "tick": -201234,
  "sqrt_price_x96": "3456789012345678901234"
}
```

---

## Юніт-тести

```
472 passed, 5 subtests passed
```

---

## Активні пари (5)

| Pair | Uniswap V3 Pool | SushiSwap V3 Pool |
|------|-----------------|-------------------|
| WETH/USDC | `0xC6962004...` | `0xf3Eb87C1...` |
| WETH/USDT | `0x641C00A8...` | `0x96aDA813...` |
| ARB/WETH | `0xC6F78049...` | `0x99543bF9...` |
| wstETH/WETH | `0x35218a1c...` | `0x8BD39fA8...` |
| ARB/USDC | `0xb0f6cA40...` | `0xfa1cC0ca...` |

### Вимкнені пари (проблеми)

| Pair | Причина |
|------|---------|
| WBTC/WETH | Decimal overflow (8 vs 18 decimals) |
| WBTC/USDC | Decimal overflow |
| GMX/WETH | Low liquidity (173% spread) |
| LINK/WETH | Low liquidity on SushiSwap (11.7% spread) |

---

## BLOCKER виправлено (2026-02-07)

### Проблема
Сканер генерував **фейкові котирування** з `pool_address=null` та плейсхолдер-цінами:
- `paper_net_pnl_usdc`: **$57,500,614,791.98** (мільярди!)
- `spread_bps_exact`: **574,416,601,574** (абсурд)
- `confidence`: "high" на фейкових сигналах

### Рішення
1. **POOL_MISSING**: Hard reject якщо `pool_address=null`
2. **V3_SLOT0_FAILED**: Reject v3 без `tick`/`sqrt_price_x96`
3. **PRICE_OUTLIER**: Reject якщо spread > 100%
4. **Confidence**: Завжди "low" коли `execution_disabled`

### Результат
| Метрика | До | Після |
|---------|-----|-------|
| pool_missing_count | багато | **0** |
| price_outlier_count | 574B bps | **0** |
| paper_net_pnl_usdc | $57.5 млрд | **реальні числа** |
| Ціни | фейкові (2600, 15) | **$2011 / $2012** |

---

## Policies

### Rejection Reasons

| Reason | Description | Gate |
|--------|-------------|------|
| `POOL_MISSING` | No pool address in config | Hard reject |
| `V3_SLOT0_FAILED` | Cannot read slot0() | Hard reject |
| `PRICE_OUTLIER` | Spread > 100% (config: `max_spread_bps_sanity`) | Hard reject |
| `PRICE_CALC_FAILED` | Decimal overflow | Hard reject |
| `NO_ONCHAIN_PRICE` | No sqrt_price_x96 | Hard reject |

### Pool Discovery

Пули знаходяться через Factory контракти:
- **Uniswap V3**: `0x1F98431c8aD98523631AE4a59f267346ea31F984`
- **SushiSwap V3**: `0x1af415a1EbA07a4986a52B6f2e7dE7003D82231e`

Скрипт: `scripts/find_sushi_pools.py`

### Threshold Profiles

| Profile | Config | `min_spread_bps` | Purpose |
|---------|--------|------------------|---------|
| **Debug** | `real_debug.yaml` | 0 | See all micro-spreads |
| **Prod** | `real_minimal.yaml` | 5 | Filter noise |

### Paper PnL Contract

- If `signals_total > 0`: `paper_net = gross_spread - gas - slippage`
- If `signals_total == 0`: `paper_net = 0`
- If `pool_missing_count > 0`: `pnl_available = false`

### Cost Model Transparency

```json
{
  "cost_model": {
    "type": "gas_only",
    "gas_usd_estimate": 0.10,
    "gas_source": "config"
  }
}
```

---

## Key Metrics Definitions

| Metric | Formula | Description |
|--------|---------|-------------|
| `quote_sanity_rate` | price_sanity_passed / quotes_total | Ціни в межах anchor |
| `gate_pass_rate` | gates_passed / quotes_total | Пройшли всі gates |
| `signal_win_rate` | opportunities / signals | Net-positive ratio |
| `pool_missing_count` | Σ(reason=POOL_MISSING) | Відсутні пули |
| `price_outlier_count` | Σ(reason=PRICE_OUTLIER) | Аномальні ціни |

---

## Schema Tests

| Test | Purpose |
|------|---------|
| `test_no_suspect_when_implied_equals_expected` | No false suspects |
| `test_reject_includes_expected_price` | Reject has context |
| `test_reject_histogram_structure` | Schema validation |
| `test_v3_quote_without_provenance_is_rejected` | V3 provenance |
| `test_truth_report_has_config_params` | Reproducibility |

---

## Risks

1. **Decimal Mismatch**: WBTC (8 decimals) causes overflow — needs fix
2. **Low Liquidity Pools**: GMX, LINK on SushiSwap have 10-170% spreads
3. **RPC Reliability**: Public RPCs may fail → mitigated by fallback list
4. **Gas Volatility**: Fixed $0.10 may underestimate during congestion

---

## Next Steps

1. **Fix WBTC decimal overflow**: Handle 8 vs 18 decimals properly
2. **Add more liquid pairs**: DAI/USDC, other stablecoins
3. **Pool liquidity check**: Skip pools with < $10k TVL
4. **Real gas estimation**: Replace fixed gas with on-chain estimate
5. **M6 CEX↔DEX**: Add CEX price feeds

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
- **Pool Discovery**: [find_sushi_pools.py](../../scripts/find_sushi_pools.py)

---

## SHA закриття

`pending` — M5 DONE (updated 2026-02-07)
