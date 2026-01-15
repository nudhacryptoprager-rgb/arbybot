# Status_M3_P2_quality_v2.md — Quality Cleanup v2 по 10 директивам Team Lead

**Дата:** 2026-01-15  
**Milestone:** M3 P2 Quality Cleanup v2  
**Статус:** ✅ **IMPLEMENTED + CONTRACT FIX**

---

## P0 FIX: OpportunityRank Contract (Team Lead Alert)

**Проблема:** `OpportunityRank.__init__() got an unexpected keyword argument 'executable'`

**Root Cause:** Зміна dataclass полів без backward compatibility (property замість field)

**Рішення (Варіант А):**
```python
@dataclass
class OpportunityRank:
    # ... інші поля ...
    executable: bool = False  # КРИТИЧНО: реальне поле, не property
    paper_executable: bool = False
    execution_ready: bool = False

@dataclass  
class TruthReport:
    # ... інші поля ...
    total_pnl_bps: int = 0  # КРИТИЧНО: реальне поле, не property
    total_pnl_usdc: float = 0.0
```

**Resilience (run_scan.py):**
```python
try:
    truth_report = generate_truth_report(snapshot, paper_stats)
    save_truth_report(truth_report, reports_dir)
except Exception as truth_err:
    logger.error(f"Truth report generation failed: {truth_err}")
    # snapshot/reject_histogram/paper_trades все одно записані
```

**Нові тести:**
- `test_opportunity_rank_accepts_executable_field`
- `test_opportunity_rank_has_paper_executable_field`
- `test_truth_report_accepts_total_pnl_fields`
- `test_truth_report_to_dict_includes_executable`
- `test_opportunity_rank_default_values`

---

## Контекст

Team Lead проаналізував артефакти після M3_P1 і виявив, що quality cleanup потребує глибших змін. Цей документ описує реалізацію всіх 10 нових директив.

---

## Критичні проблеми (з аналізу Team Lead)

1. **PRICE_SANITY_FAILED (240/880)** — "космічні" роз'їзди між Sushi та Uniswap anchor
2. **QUOTE_GAS_TOO_HIGH (260/880)** — газ-естімейт 500k-800k+ при max_gas 200k-500k
3. **TICKS_CROSSED_TOO_MANY (200/880)** — gates працюють як "рубильник"
4. **QUOTE_REVERT (120/880)** — registry/fee tiers не валідні для деяких DEX
5. **"executable=true" на папері** — змішування "можна виконати" з "прибутково"
6. **Cumulative PnL нереалістичний** — агрегація "сигналів", а не "угод"
7. **Confidence=0.861 константний** — plausibility=0.8 як дефолт
8. **Контракт ErrorCode** — не зафіксований тестами
9. **Bottleneck — параметри/політики** — не RPC

---

## Реалізовані директиви

### ✅ Крок 1: Quarantine по фактах

Реалізовано в попередньому P1, інтегровано в run_scan.

### ✅ Крок 2: Amount-ladder адаптивний по pool fitness

**Рішення:** Додано `PoolFitness` клас в `strategy/gates.py`:

```python
class PoolFitness:
    """Track pool fitness for adaptive amount selection."""
    
    def record_success(self, pair, dex_id, fee, amount)
    def record_failure(self, pair, dex_id, fee, amount, reason)
    def get_max_amount(self, pair, dex_id, fee) -> int | None
    def is_pool_unfit(self, pair, dex_id, fee) -> bool
```

Логіка:
- Якщо QUOTE_GAS_TOO_HIGH на малому amount → pool unfit
- Якщо тільки на великому → зменшити max_amount для pool

### ✅ Крок 3: Ticks thresholds по типу токена

**Рішення:** Оновлено `get_adaptive_ticks_limit()`:

```python
def get_pair_type(pair: str | None) -> str:
    """Classify pair as 'volatile', 'stable', or 'normal'."""

TICKS_LIMITS_VOLATILE = {10**16: 5, 10**17: 8, 10**18: 15, 10**19: 25}
TICKS_LIMITS_STABLE = {10**16: 2, 10**17: 3, 10**18: 5, 10**19: 10}
TICKS_LIMITS_BY_SIZE = {10**16: 3, 10**17: 5, 10**18: 10, 10**19: 20}
```

Результат:
- Volatile pairs (WETH/ARB, WETH/LINK) отримують більше tolerance
- Stable pairs (USDC/USDT) отримують менше tolerance

### ✅ Крок 4: 2-рівнева PRICE_SANITY перевірка

**Рішення:** Оновлено `gate_price_sanity()`:

```python
# Level 1: coarse filter (25%/40% for volatile)
MAX_PRICE_DEVIATION_BPS_L1 = 2500
MAX_PRICE_DEVIATION_BPS_VOLATILE_L1 = 4000

# Level 2: fine filter (15%/25% for volatile)
MAX_PRICE_DEVIATION_BPS_L2 = 1500
MAX_PRICE_DEVIATION_BPS_VOLATILE_L2 = 2500
```

Логіка:
1. L1: hard reject якщо deviation > L1
2. L2: якщо deviation > L2 але <= L1 → вимагати second anchor
3. Якщо second_anchor_price підтверджує → pass

### ✅ Крок 5: Розділення executable на 2 прапори

**Рішення:** Оновлено `OpportunityRank`:

```python
@dataclass
class OpportunityRank:
    paper_executable: bool = False   # Passes all gates on paper
    execution_ready: bool = False    # verified_for_execution + router ready
    
    @property
    def executable(self) -> bool:  # Legacy
        return self.paper_executable
```

### ✅ Крок 6: Перерахунок KPI PnL

**Рішення:** Оновлено `TruthReport`:

```python
@dataclass
class TruthReport:
    # Separate signal PnL vs would_execute PnL
    signal_pnl_bps: int = 0        # Sum of all detected opportunities
    signal_pnl_usdc: float = 0.0
    would_execute_pnl_bps: int = 0  # Only from would_execute trades
    would_execute_pnl_usdc: float = 0.0
```

### ✅ Крок 7: Plausibility як функція

**Рішення:** Створено `calculate_plausibility()`:

```python
def calculate_plausibility(spread, spread_bps, gas_bps, buy_leg, sell_leg) -> float:
    """Plausibility as function of proximity to thresholds."""
    score = 1.0
    
    # Penalties for:
    # 1. Spread threshold proximity
    # 2. Gas threshold proximity
    # 3. Ticks threshold proximity
    # 4. Price deviation proximity
    # 5. Leg latency asymmetry
    
    return max(0.0, min(1.0, score))
```

### ✅ Крок 8: Тест контракту ErrorCode

**Рішення:** Створено `tests/unit/test_error_contract.py`:

```python
class TestErrorCodeContract:
    def test_all_gate_codes_exist_in_enum()
    def test_all_quote_codes_exist_in_enum()
    def test_error_codes_have_string_values()
    def test_no_duplicate_values()
    def test_gates_module_uses_valid_codes()
    def test_reject_histogram_codes_are_valid()

class TestGateRejectReasons:
    def test_zero_output_gate_reason()
    def test_gas_gate_reason()
    def test_ticks_gate_reason()
```

### ✅ Крок 9-10: ZIP та goal

ZIP буде оновлено з HEAD коміту. Goal: -30% керованих reject-ів за 3 цикли.

---

## Змінені файли

| Файл | Зміни |
|------|-------|
| `strategy/gates.py` | +PoolFitness, +get_pair_type, +TICKS_LIMITS_VOLATILE/STABLE, 2-level price sanity, +requires_second_anchor |
| `monitoring/truth_report.py` | +paper_executable/execution_ready, +signal_pnl/would_execute_pnl, +calculate_plausibility() |
| `tests/unit/test_error_contract.py` | NEW: ErrorCode contract tests |

---

## Нові класи та функції

| Клас/Функція | Опис |
|--------------|------|
| `PoolFitness` | Track pool fitness for adaptive amounts |
| `get_pair_type()` | Classify pairs as volatile/stable/normal |
| `get_price_deviation_limits()` | Get L1/L2 limits tuple |
| `calculate_plausibility()` | Dynamic plausibility scoring |

---

## GateResult оновлення

```python
class GateResult(NamedTuple):
    passed: bool
    reject_code: ErrorCode | None = None
    details: dict | None = None
    requires_second_anchor: bool = False  # NEW: for 2-level price sanity
```

---

## Очікувані результати (Goal)

| Метрика | Before | Target | Method |
|---------|--------|--------|--------|
| QUOTE_GAS_TOO_HIGH | 260 | 182 (-30%) | PoolFitness adaptive |
| PRICE_SANITY_FAILED | 240 | 168 (-30%) | 2-level check |
| TICKS_CROSSED_TOO_MANY | 200 | 140 (-30%) | Type-based limits |
| Confidence variance | ~0.861 constant | Variable | Dynamic plausibility |

---

## Наступні кроки

1. **SMOKE 20-50 циклів** для validation
2. **Monitor PoolFitness** adjustments
3. **Track KPI trends** (signal vs would_execute)
4. **Validate ErrorCode contract** не порушений

---

*Документ згенеровано: 2026-01-15*
