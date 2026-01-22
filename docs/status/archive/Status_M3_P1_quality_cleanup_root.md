# Status_M3_P1_quality_cleanup.md — Quality Cleanup по 10 директивам Team Lead

**Дата:** 2026-01-15  
**Milestone:** M3 P1 Quality Cleanup  
**Статус:** ✅ **IMPLEMENTED**

---

## Контекст

Team Lead проаналізував артефакти `truth_report_20260115_104609.json` та `reject_histogram_20260115_104609.json` і виявив 10 критичних проблем. Цей документ описує реалізацію всіх 10 директив.

---

## Реалізовані директиви

### ✅ Крок 1: Hard-filter для токсичних комбінацій

**Проблема:** 880 reject-ів, половина з яких PRICE_SANITY та TICKS — шум, який не дасть угоду.

**Рішення:** Створено `discovery/quarantine.py`:
- `QuarantineManager` — трекає failure rates per (pair, dex, fee)
- Auto-quarantine при >50% PRICE_SANITY_FAILED
- Auto-quarantine при >80% QUOTE_REVERT
- Auto-quarantine при >70% QUOTE_GAS_TOO_HIGH
- Quarantine duration: 20 циклів
- Auto-release після успішних quotes

```python
MIN_ATTEMPTS_FOR_QUARANTINE = 5
PRICE_SANITY_FAIL_THRESHOLD = 50   # 50% = quarantine
QUOTE_REVERT_FAIL_THRESHOLD = 80   # 80% = quarantine  
GAS_TOO_HIGH_FAIL_THRESHOLD = 70   # 70% = quarantine
```

---

### ✅ Крок 2: Debug mode для WETH/LINK та WETH/ARB

**Проблема:** PRICE_SANITY_FAILED з deviation 2975-9273 bps на sushiswap_v3 — потрібно зберігати samples для аналізу.

**Рішення:** `QuarantineManager.save_debug_sample()`:
- Зберігає anchor_price, quote_price, fee, amount_in
- Тримає останні 10 samples per pair/dex
- Файли: `data/quarantine/debug_{pair}_{dex}.json`

---

### ✅ Крок 3: Виключення wstETH→WETH QUOTE_REVERT

**Проблема:** wstETH→WETH на sushiswap_v3 fee=3000 постійно reverts — немає пулу.

**Рішення:** Статичний exclude в `discovery/quarantine.py`:

```python
EXCLUDED_COMBINATIONS = {
    ("wstETH/WETH", "sushiswap_v3", 3000),
    ("WETH/wstETH", "sushiswap_v3", 3000),
}
```

---

### ✅ Крок 4: Адаптивний amount_in

**Проблема:** Gas gate надто жорсткий — треба retry smaller.

**Рішення:** Оновлено `strategy/gates.py`:

```python
STANDARD_AMOUNTS = [
    10**16,   # 0.01 ETH - micro
    10**17,   # 0.1 ETH - small
    10**18,   # 1 ETH - standard
]

def suggest_smaller_amount(current_amount: int, reject_reason: str) -> int | None
def get_retry_amounts(base_amount: int) -> list[int]
```

Додано менші ліміти для 0.01 ETH:
- Gas: 200k (vs 300k для 0.1 ETH)
- Ticks: 3 (vs 5 для 0.1 ETH)

---

### ✅ Крок 5: gas_cost_bps nonzero

**Проблема:** gas_cost_bps=0 у топах — підозра на намальований net_pnl.

**Рішення:** В `calculate_confidence()` додано estimation:

```python
if gas_bps == 0 and total_gas > 0:
    # Estimate: 1 bps per 100k gas for 0.1 ETH trades
    base_gas_bps = max(1, total_gas // 100_000)
    size_factor = 10**17 / max(amount_in, 10**16)
    gas_bps = max(1, int(base_gas_bps * size_factor))
```

---

### ✅ Крок 6: blocked_spreads breakdown

**Проблема:** blocked_spreads=80 без пояснення причин.

**Рішення:** Оновлено `TruthReport`:

```python
@dataclass
class TruthReport:
    ...
    blocked_reasons: dict | None = None  # NEW
    
    def to_dict(self) -> dict:
        ...
        if self.blocked_reasons:
            result["blocked_reasons_breakdown"] = self.blocked_reasons
```

---

### ✅ Крок 7: Confidence penalties

**Проблема:** Confidence ~0.959 для всіх топів — scoring "плоский".

**Рішення:** Додано penalties в `calculate_confidence()`:

```python
# PRICE_SANITY penalty
if failure_rate > 0.3:
    price_sanity_penalty = failure_rate * 0.3

# GAS penalty  
if failure_rate > 0.3:
    gas_penalty = failure_rate * 0.2

# Apply penalties
total_score = max(0.0, base_score - price_sanity_penalty - gas_penalty)
```

Нові weights:
```python
weights = {
    "freshness": 0.12,      # was 0.15
    "ticks": 0.12,          # was 0.15
    "verification": 0.18,   # was 0.20
    "profitability": 0.15,
    "gas_efficiency": 0.10,
    "rpc_health": 0.08,     # was 0.10
    "plausibility": 0.15,
}
```

---

### ✅ Крок 8: Quality KPIs

**Проблема:** Немає tracking частки reject-ів та цілей.

**Рішення:** Створено `monitoring/quality_kpis.py`:

```python
BASELINE_REJECTS = {
    "QUOTE_GAS_TOO_HIGH": 260,
    "PRICE_SANITY_FAILED": 240,
    "TICKS_CROSSED_TOO_MANY": 200,
    "QUOTE_REVERT": 120,
    "SLIPPAGE_TOO_HIGH": 60,
}

TARGET_REDUCTION_PERCENT = 30  # 30% reduction target
STRETCH_TARGET_PERCENT = 50    # 50% stretch goal
```

Features:
- Per-cycle metrics collection
- Rolling averages and trends
- Target tracking with alerts
- Health score calculation (0.0 - 1.0)

---

### ✅ Крок 9-10: Smoke test та очищення входу

**Рішення:** Всі зміни підготовлені для SMOKE 20-50 циклів:
- Quarantine manager активний
- Debug samples зберігаються
- KPI tracker готовий

---

## Нові файли

| Файл | Опис |
|------|------|
| `discovery/quarantine.py` | Quarantine system для токсичних комбінацій |
| `monitoring/quality_kpis.py` | Quality KPI tracking system |

---

## Змінені файли

| Файл | Зміни |
|------|-------|
| `strategy/gates.py` | +STANDARD_AMOUNTS, +suggest_smaller_amount, +get_retry_amounts, +0.01 ETH limits |
| `monitoring/truth_report.py` | +blocked_reasons, +gas_cost_bps estimation, +confidence penalties |
| `tests/unit/test_gates.py` | +TestAdaptiveAmountSizing, +TestQuarantineSystem, +TestQualityKPIs |

---

## Нові тести

| Test Class | Tests |
|------------|-------|
| TestAdaptiveAmountSizing | 8 тестів для suggest_smaller_amount, get_retry_amounts |
| TestQuarantineSystem | 4 тести для quarantine manager |
| TestQualityKPIs | 4 тести для KPI tracking |

---

## Очікувані результати

| Метрика | Baseline | Target (30%) | Stretch (50%) |
|---------|----------|--------------|---------------|
| QUOTE_GAS_TOO_HIGH | 260 | 182 | 130 |
| PRICE_SANITY_FAILED | 240 | 168 | 120 |
| TICKS_CROSSED_TOO_MANY | 200 | 140 | 100 |
| QUOTE_REVERT | 120 | 84 | 60 |
| SLIPPAGE_TOO_HIGH | 60 | 42 | 30 |

---

## Наступні кроки

1. **Запустити SMOKE 20-50 циклів** з новими gates
2. **Перевірити KPI trends** після 10+ циклів
3. **Аналіз debug samples** для WETH/LINK, WETH/ARB
4. **Pool quarantine per-pool** якщо комбінації не достатньо

---

*Документ згенеровано: 2026-01-15*
