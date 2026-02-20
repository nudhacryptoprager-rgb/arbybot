# Status_M3_P0_fixes.md — P0 Fixes від Team Lead

**Дата:** 2026-01-15  
**Milestone:** M3 P0 Fixes  
**Статус:** ✅ **IMPLEMENTED**

---

## 1. Виправлення за рекомендаціями Team Lead

### ✅ P0-1: PRICE_ANCHOR_MISSING в ErrorCode

**Проблема:** `ErrorCode.PRICE_ANCHOR_MISSING` використовувався в gates.py, але був відсутній в enum → AttributeError at runtime.

**Рішення:** Додано в `core/exceptions.py`:
```python
PRICE_ANCHOR_MISSING = "PRICE_ANCHOR_MISSING"  # Non-anchor quote without anchor price
```

---

### ✅ P0-2: Top opportunities дублювались

**Проблема:** В truth_report показувались 10 однакових spread_id (з різних циклів).

**Рішення:** Дедуплікація по spread_id в `monitoring/truth_report.py`:
```python
spreads_by_id: dict[str, dict] = {}
for spread in all_spreads:
    spread_id = spread.get("id", "")
    if spread_id:
        spreads_by_id[spread_id] = spread  # Last wins (most recent)
unique_spreads = list(spreads_by_id.values())
```

---

### ✅ P0-3: Top opportunities — executable-only

**Проблема:** В топах були executable=false записи, хоча вони не можуть виконатись.

**Рішення:** Фільтрація в truth_report:
```python
ranked_executable = [r for r in ranked if r["spread"].get("executable", False)]
```

---

### ✅ P0-4: Adaptive Gas Limits

**Проблема:** QUOTE_GAS_TOO_HIGH домінував у reject histogram.

**Рішення:** Адаптивні ліміти по розміру торгівлі:
```python
GAS_LIMITS_BY_SIZE = {
    10**17: 300_000,   # 0.1 ETH - tight
    10**18: 500_000,   # 1 ETH - standard
    10**19: 800_000,   # 10 ETH - larger trades
}
```

---

### ✅ P0-5: Adaptive Ticks Limits

**Проблема:** TICKS_CROSSED_TOO_MANY теж частий reject.

**Рішення:** Адаптивні ліміти:
```python
TICKS_LIMITS_BY_SIZE = {
    10**17: 5,    # 0.1 ETH - very tight
    10**18: 10,   # 1 ETH - standard
    10**19: 20,   # 10 ETH - more impact allowed
}
```

---

### ✅ P0-6: Volatile Pairs Price Sanity

**Проблема:** PRICE_SANITY_FAILED занадто частий для volatile pairs (WETH/ARB, WETH/LINK).

**Рішення:** Різні ліміти для stable/volatile pairs:
```python
MAX_PRICE_DEVIATION_BPS = 1500         # 15% for stable pairs
MAX_PRICE_DEVIATION_BPS_VOLATILE = 2500  # 25% for volatile
HIGH_VOLATILITY_PAIRS = {"WETH/LINK", "WETH/ARB", "WETH/GMX", ...}
```

---

### ✅ P0-7: Pair в reject details

**Проблема:** Важко аналізувати reject по парах.

**Рішення:** Додано `pair` в details для всіх PRICE_SANITY related rejects.

---

## 2. Нові тести

Додано 10 тестів для адаптивних лімітів:

| Test | Description |
|------|-------------|
| test_get_adaptive_gas_limit_small_trade | 0.1 ETH → 300k |
| test_get_adaptive_gas_limit_standard_trade | 1 ETH → 500k |
| test_get_adaptive_gas_limit_large_trade | 10 ETH → 800k |
| test_get_adaptive_ticks_limit_small_trade | 0.1 ETH → 5 ticks |
| test_get_adaptive_ticks_limit_standard_trade | 1 ETH → 10 ticks |
| test_get_adaptive_ticks_limit_large_trade | 10 ETH → 20 ticks |
| test_get_price_deviation_limit_stable_pair | WETH/USDC → 1500 bps |
| test_get_price_deviation_limit_volatile_pair | WETH/ARB → 2500 bps |
| test_gate_gas_uses_adaptive_limit | Інтеграційний тест |
| test_gate_ticks_uses_adaptive_limit | Інтеграційний тест |

---

## 3. Тести

**203 passed, 2 failed**

Помилки в algebra_adapter — legacy, не від цих змін.

---

## 4. Змінені файли

| Файл | Зміни |
|------|-------|
| `core/exceptions.py` | +PRICE_ANCHOR_MISSING |
| `strategy/gates.py` | Adaptive limits functions, volatile pairs |
| `monitoring/truth_report.py` | Дедуплікація, executable-only filter |
| `tests/unit/test_gates.py` | +10 нових тестів |

---

## 5. Очікувані результати після цих змін

| Метрика | До | Очікувано |
|---------|-----|-----------|
| QUOTE_GAS_TOO_HIGH | Домінує | Зменшення для великих trades |
| TICKS_CROSSED_TOO_MANY | Частий | Зменшення для великих trades |
| PRICE_SANITY_FAILED | Домінує | Зменшення для volatile pairs |
| Top opportunities дублікати | 10 однакових | Унікальні |
| Top opportunities blocked | Є | Тільки executable |

---

## 6. Наступні кроки

1. **Прогнати 20-50 циклів smoke** — перевірити частку rejects
2. **Deviation distribution звіт** — по pair/dex/fee для tuning порогів
3. **Quality score** для spreads "на межі порога"
4. **Pool quarantine** — трекати PRICE_SANITY_FAILED per pool

---

*Документ згенеровано: 2026-01-15*
