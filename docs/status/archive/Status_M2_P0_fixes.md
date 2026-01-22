# Status_M2_P0_fixes.md — M2.2.x P0 Fixes

**Дата:** 2026-01-11  
**Milestone:** M2.2.x P0 Fixes (перед M2.3 AlgebraAdapter)  
**Статус:** ✅ **COMPLETE**

---

## 1. P0 Fixes Summary

| # | Проблема | Рішення | Статус |
|---|----------|---------|--------|
| 1 | reject_histogram total=0 але samples є | Fallback: build histogram from samples | ✅ |
| 2 | rpc_success_rate середнє без ваги | Weighted by total_requests | ✅ |
| 3 | QUOTE_INVALID_PARAMS домінує | Розбито на конкретні коди | ✅ |
| 4 | executable_spreads = 0 | sushiswap_v3 verified_for_execution=true | ✅ |
| 5 | expected_usdc хардкод $2500 | Використовує implied_price з buy_leg | ✅ |
| 6 | pair хардкод "WETH/USDC" | Береться з spread/quote | ✅ |
| 7 | Gate thresholds хардкод | Винесено в config/strategy.yaml | ✅ |

---

## 2. Error Taxonomy Fix

### Було:
```python
except (AttributeError, KeyError, ValueError, TypeError) as e:
    quote_reject_reasons[ErrorCode.QUOTE_INVALID_PARAMS.value] += 1
```

### Стало:
```python
except (AttributeError, KeyError, ValueError, TypeError) as e:
    if isinstance(e, (AttributeError, KeyError)):
        error_code = ErrorCode.INFRA_BAD_ABI  # Missing field
    elif isinstance(e, ValueError):
        error_code = ErrorCode.QUOTE_REVERT    # Bad data
    else:
        error_code = ErrorCode.VALIDATION_ERROR
```

**Результат:** Кожен fail має конкретну причину (M1.6 requirement).

---

## 3. Gate Config

**Новий файл:** `strategy/config.py`

```python
@dataclass
class GateThresholds:
    max_gas_estimate: int = 500_000
    max_ticks_crossed: int = 10
    max_price_deviation_bps: int = 1000
    max_slippage_bps: int = 500
    ...

@dataclass
class StrategyConfig:
    defaults: GateThresholds
    chain_overrides: dict[int, dict]
```

**config/strategy.yaml:**
```yaml
gate_defaults:
  max_gas_estimate: 500000
  max_ticks_crossed: 10

gate_overrides:
  arbitrum_one:
    max_gas_estimate: 400000
    max_quote_age_ms: 1000
```

---

## 4. Spread Data (Updated)

```json
{
  "id": "uniswap_v3_sushiswap_v3_500_...",
  "pair": "WETH/USDC",
  "token_in_symbol": "WETH",
  "token_out_symbol": "USDC",
  "buy_leg": {
    "dex": "uniswap_v3",
    "price": "3456.789...",
    ...
  },
  "gas_cost_bps": 45,
  "net_pnl_bps": 12,
  ...
}
```

---

## 5. DEXes Status

| DEX | verified_for_quoting | verified_for_execution |
|-----|---------------------|----------------------|
| uniswap_v3 | ✅ | ✅ |
| sushiswap_v3 | ✅ | ✅ |

---

## 6. Тести

**152 passed ✅**

---

## 7. Файли змінені

| Файл | Зміни |
|------|-------|
| `strategy/jobs/run_scan.py` | Error taxonomy fix, InfraError catch |
| `strategy/config.py` | **NEW** - Gate thresholds config |
| `monitoring/truth_report.py` | Removed hardcodes |
| `config/strategy.yaml` | Added gate_defaults, gate_overrides |
| `config/dexes.yaml` | sushiswap_v3 verified |

---

## 8. Roadmap Alignment

| Milestone | Status | Notes |
|-----------|--------|-------|
| M0 Bootstrap | ✅ | Complete |
| M1 Truth Engine | ✅ | Complete |
| M2 Adapters | ✅ | UniV3 + SushiV3 |
| M2.2.x P0 | ✅ | This doc |
| **M2.3 Algebra** | 🔜 | Next: Camelot |
| M3 Opportunity | 🔜 | After M2.3 |

---

## 9. Наступні кроки

| Priority | Step |
|----------|------|
| P0 | M2.3: AlgebraAdapter skeleton for Camelot |
| P1 | RPC fallback smoke test |
| P1 | Add 1-2 more pairs to intent |
| P2 | pool_address compute (keccak) |

---

*Документ згенеровано: 2026-01-11*
