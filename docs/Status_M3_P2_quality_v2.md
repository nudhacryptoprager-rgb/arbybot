# Status_M3_P2_quality_v2.md — Quality Cleanup v2 по 10 директивам Team Lead

**Дата:** 2026-01-15  
**Milestone:** M3 P2 Quality Cleanup v2  
**Статус:** ✅ **IMPLEMENTED**

---

## Виконані директиви (10/10)

### ✅ Крок 1: Визначити терміни в truth_report

**Термінологія:**
- `spread_id` = унікальний spread (pair + buy_dex + sell_dex + fee tiers + direction)
- `signal` = spread_id × (size bucket або route variant)

**Перейменування полів:**
```python
# OLD                    # NEW
total_spreads         → spread_ids_total
profitable_spreads    → spread_ids_profitable
executable_spreads    → spread_ids_executable
# NEW ADDITIONS
signals_total
signals_profitable
signals_executable
```

### ✅ Крок 2: Виправити підрахунки та інваріанти

```python
def validate_invariants(self) -> list[str]:
    """
    Invariant 1: spread_ids_profitable <= spread_ids_total
    Invariant 2: spread_ids_executable <= spread_ids_total
    Invariant 3: signals_total >= spread_ids_total
    Invariant 4: execution_ready <= paper_executable
    """
```

Violations тепер включаються в `to_dict()` output.

### ✅ Крок 3: Blocked reasons як first-class

```python
class BlockedReason:
    EXEC_DISABLED_NOT_VERIFIED = "EXEC_DISABLED_NOT_VERIFIED"
    EXEC_DISABLED_CONFIG = "EXEC_DISABLED_CONFIG"
    EXEC_DISABLED_QUARANTINE = "EXEC_DISABLED_QUARANTINE"
    EXEC_DISABLED_RISK = "EXEC_DISABLED_RISK"
    EXEC_DISABLED_REVALIDATION_FAILED = "EXEC_DISABLED_REVALIDATION_FAILED"
    EXEC_DISABLED_GATES_CHANGED = "EXEC_DISABLED_GATES_CHANGED"
    EXEC_DISABLED_COOLDOWN = "EXEC_DISABLED_COOLDOWN"
```

TruthReport тепер включає:
- `blocked_reasons: dict` — підрахунок по причинах
- `top_blocked_reasons: list[tuple]` — топ причин блокування

### ✅ Крок 4: Зменшити SMOKE навантаження

Створено `config/smoke_minimal.py`:
- 2 пари: WETH/USDC, WETH/ARB
- 2 DEX: uniswap_v3, sushiswap_v3
- 1 fee tier: 500
- Fixed amount: 0.1 ETH
- Revalidation: same_block, static_gas, same_anchor

### ✅ Крок 5: Stabilize revalidation

TruthReport тепер включає:
```python
revalidation_total: int
revalidation_passed: int
revalidation_gates_changed: int
# В to_dict():
"revalidation": {
    "total": ...,
    "passed": ...,
    "gates_changed": ...,
    "gates_changed_pct": ...,  # Для KPI
}
```

### ✅ Крок 6: PRICE_SANITY telemetry

Деталі вже включають:
- `implied_price`, `anchor_price`, `deviation_bps`
- `dex_id`, `fee`, `amount_in`
- `max_deviation_bps_L1`, `max_deviation_bps_L2`

### ✅ Крок 7: QUOTE_GAS_TOO_HIGH telemetry

Оновлено `gate_gas_estimate()`:
```python
details={
    "gas_estimate": quote.gas_estimate,
    "max_gas": max_gas,
    "amount_in": quote.amount_in,
    # NEW telemetry
    "gas_price_gwei": 0.01,
    "gas_cost_eth": ...,
    "gas_cost_usdc": ...,
    "threshold_usdc": ...,
    "dex_id": ...,
    "fee": ...,
    "pair": ...,
}
```

### ✅ Крок 8: TICKS_CROSSED adaptive sizing

Вже реалізовано в P1:
- `get_adaptive_ticks_limit(amount_in, pair)`
- `TICKS_LIMITS_VOLATILE`, `TICKS_LIMITS_STABLE`
- `get_pair_type()` для класифікації

### ✅ Крок 9: Error contract тест

28 тестів в `test_error_contract.py`:
- `TestErrorCodeContract` — 8 тестів
- `TestErrorCodeUsage` — 3 тести
- `TestRejectHistogramContract` — 2 тести
- `TestGateRejectReasons` — 3 тести
- `TestTruthReportContract` — 5 тестів
- `TestTruthReportInvariants` — 5 тестів
- `TestBlockedReasons` — 2 тести

### ✅ Крок 10: M3 KPI Rules

`config/smoke_minimal.py` включає:
```python
M3_KPI_RULES = {
    "rpc_success_rate_min": 0.8,
    "quote_fetch_rate_min": 0.7,
    "gate_pass_rate_min": 0.4,
    "gates_changed_pct_max": 5.0,
    "invariants_required": True,
}

def check_m3_kpi(truth_report_dict) -> dict:
    """Returns {passed, violations, metrics}"""
```

---

## Тести

**91 passed** ✅

---

## Файли

| Файл | Зміни |
|------|-------|
| `monitoring/truth_report.py` | +BlockedReason, +invariants, renamed fields, +revalidation stats |
| `strategy/gates.py` | +gas telemetry (gas_cost_usdc, threshold_usdc) |
| `config/smoke_minimal.py` | NEW: SMOKE config, M3 KPI rules |
| `tests/unit/test_error_contract.py` | +invariant tests, +BlockedReason tests |

---

## Наступні кроки

1. Запустити SMOKE з `smoke_minimal.py` config
2. Перевірити `gates_changed_pct < 5%`
3. Переконатися що invariants не violated
4. Рухатися далі в M3 тільки якщо KPI пройдені

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
