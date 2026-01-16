# Status_M3_P2_quality_v3.md — Quality Cleanup v3 + Стабілізація

**Дата:** 2026-01-16  
**Milestone:** M3 P2 Quality Cleanup v3 + Стабілізація  
**Статус:** ✅ **IMPLEMENTED**

---

## Контекст

Team Lead проаналізував артефакти (truth_report_20260116) і виявив:
- `execution_ready_count = 0` попри executable spreads
- Змішані поняття: `executable` (економіка) vs `execution_ready` (політика)
- Сигнатури gates дрейфують → TypeError в рантаймі
- Немає schema versioning для truth_report

---

## Виконані кроки стабілізації (10/10)

### ✅ Крок 1: ErrorCode контракт

ErrorCode enum вже містить всі необхідні коди:
- PRICE_ANCHOR_MISSING ✅
- QUOTE_GAS_TOO_HIGH ✅
- TICKS_CROSSED_TOO_MANY ✅
- Всі інші ✅

Тести test_error_contract.py перевіряють цілісність.

### ✅ Крок 2: Зацементувати сигнатури gates API

```python
def apply_single_quote_gates(
    quote: Quote,
    anchor_price: Decimal | None = None,
    is_anchor_dex: bool = False,
) -> list[GateResult]:
    """
    CEMENTED API (Team Lead):
    DO NOT ADD NEW PARAMETERS WITHOUT UPDATING:
    - tests/unit/test_gates.py
    - strategy/jobs/run_scan.py
    - All callers in the codebase
    """
```

### ✅ Крок 3: Розвести метрики

**OpportunityRank тепер має чітке розділення:**

```python
@dataclass
class OpportunityRank:
    # НОВІ ПОЛЯ (clear separation)
    executable_economic: bool = False  # passes gates + PnL > 0
    paper_would_execute: bool = False  # = executable_economic in paper mode
    execution_ready: bool = False      # + verified + !blocked
    blocked_reason: str | None = None  # WHY not execution_ready
    
    # LEGACY PROPERTIES (backward compatibility)
    @property
    def executable(self) -> bool:
        return self.executable_economic
    
    @property  
    def paper_executable(self) -> bool:
        return self.paper_would_execute
```

### ✅ Крок 4-7: Telemetry (вже реалізовано в v3)

- PRICE_SANITY: +anchor_source
- QUOTE_GAS_TOO_HIGH: +gas_cost_usdc, +profit_to_gas_ratio
- TICKS_CROSSED: +pair_type, +adaptive limits

### ✅ Крок 8: Truth report schema versioning

```python
TRUTH_REPORT_SCHEMA_VERSION = "3.0.0"
"""
Schema version history:
- 1.0.0: Initial schema
- 2.0.0: Added spread_ids vs signals terminology
- 3.0.0: Added executable_economic, execution_ready separation
         Added blocked_reason to OpportunityRank
         Added notion_capital_usdc for PnL normalization
         Added schema_version field
"""

@dataclass
class TruthReport:
    schema_version: str = TRUTH_REPORT_SCHEMA_VERSION
```

**to_dict() тепер включає:**
```json
{
  "schema_version": "3.0.0",
  "top_opportunities": [
    {
      "executable_economic": true,
      "paper_would_execute": true,
      "execution_ready": false,
      "blocked_reason": "EXEC_DISABLED_NOT_VERIFIED",
      "executable": true,  // legacy
      "paper_executable": true  // legacy
    }
  ]
}
```

### ✅ Крок 9: Counters як facts

generate_truth_report() тепер правильно підраховує:
- `executable_economic` = passes all gates AND net_pnl > 0
- `paper_would_execute` = executable_economic in paper mode
- `execution_ready` = executable_economic && verified && !blocked
- `blocked_reason` = explains why not ready

---

## Файли

| Файл | Зміни |
|------|-------|
| `monitoring/truth_report.py` | +schema_version, +executable_economic/paper_would_execute, +blocked_reason, fixed dataclass order |
| `strategy/gates.py` | Cemented apply_single_quote_gates signature |
| `tests/unit/test_error_contract.py` | Updated for new fields |

---

## Тести

**91 passed** ✅

---

## Очікувані результати

Після цих змін truth_report чітко показує:
- `executable_economic=True` + `execution_ready=False` + `blocked_reason="EXEC_DISABLED_NOT_VERIFIED"`
- Це означає: економічно вигідно, але verification policy блокує

Це дозволяє:
1. Бачити "правду про економіку" через `executable_economic`
2. Бачити "правду про execution" через `execution_ready`
3. Розуміти ЧОМУ blocked через `blocked_reason`
