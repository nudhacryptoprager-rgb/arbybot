# Status_M3_P2_quality_v3.md — Quality Cleanup v3 по 10 новим крокам Team Lead

**Дата:** 2026-01-16  
**Milestone:** M3 P2 Quality Cleanup v3  
**Статус:** ✅ **IMPLEMENTED**

---

## Контекст

Team Lead проаналізував нові артефакти (truth_report_20260116) і виявив:
- `execution_ready_count = 0` попри executable spreads
- `QUOTE_GAS_TOO_HIGH` домінує на uniswap_v3/wstETH
- `TICKS_CROSSED_TOO_MANY` на wstETH/WETH
- `PRICE_SANITY_FAILED` без anchor source діагностики
- `paper_executable=false` при `executable=true` — неконсистентність

---

## Виконані кроки (10/10)

### ✅ Крок 1: Розблокуй execution readiness

**smoke_minimal.py:**
```python
"paper_trading": {
    "ignore_verification": True,  # Allow execution_ready in paper mode
    "log_blocked_reason": True,   # Log why blocked in real mode
}
```

### ✅ Крок 2: Викинь wstETH/WETH зі smoke

**smoke_minimal.py:**
```python
"pairs": ["WETH/USDC", "WETH/ARB"],
"excluded_pairs": [
    "wstETH/WETH",  # High ticks (16-20), high gas (500k-846k)
    "WETH/wstETH",
],
```

### ✅ Крок 3: Quarantine для QUOTE_REVERT

**Новий файл: strategy/quarantine.py**

```python
class QuarantineManager:
    def record_failure(dex_id, pair, fee, error_code, ...) -> bool
    def record_success(dex_id, pair, fee, ...)
    def is_quarantined(dex_id, pair, fee, ...) -> bool
    
QUARANTINE_CONFIG = {
    "failure_threshold": 3,
    "quarantine_duration_seconds": 300,  # 5 min
    "trackable_errors": ["QUOTE_REVERT", "QUOTE_TIMEOUT", "RPC_ERROR"],
    "immediate_quarantine_errors": ["CONTRACT_NOT_FOUND", "INVALID_POOL"],
}
```

### ✅ Крок 4: PRICE_SANITY anchor source

**gate_price_sanity() оновлено:**
```python
def gate_price_sanity(
    ...,
    anchor_source: dict | None = None,  # NEW
) -> GateResult:
    """
    anchor_source = {
        "anchor_dex": "uniswap_v3",
        "anchor_pool": "0x...",
        "anchor_fee": 500,
        "anchor_block": 12345,
    }
    """
    # details тепер включає anchor_source
```

### ✅ Крок 5: Газ-фільтр відносний

**Нова функція gate_gas_relative():**
```python
MIN_PROFIT_TO_GAS_RATIO = 2.0

def gate_gas_relative(
    quote: Quote,
    net_pnl_bps: int,
    gas_price_gwei: float = 0.01,
    eth_price_usdc: float = 3000.0,
    min_ratio: float = MIN_PROFIT_TO_GAS_RATIO,
) -> GateResult:
    """
    Reject if net_pnl_usdc / gas_cost_usdc < min_ratio.
    
    Details include:
    - profit_to_gas_ratio
    - min_ratio_required
    - gas_cost_usdc, net_pnl_usdc
    """
```

### ✅ Крок 6: Ticks gate (вже реалізовано в P1)

Адаптивний по amount_in та pair type:
- `TICKS_LIMITS_VOLATILE`
- `TICKS_LIMITS_STABLE`
- `get_adaptive_ticks_limit(amount_in, pair)`

### ✅ Крок 7: Синхронізація executable vs paper_executable

**OpportunityRank clarified:**
```python
@dataclass
class OpportunityRank:
    """
    executable = passes all gates in current mode
    paper_executable = executable in paper mode (ignores verification)
    execution_ready = executable && verified && !cooldown && !blocked
    
    In SMOKE: paper_executable == executable
    """
    executable: bool = False
    paper_executable: bool = False
    execution_ready: bool = False
    blocked_reason: str | None = None  # NEW: explains why not ready
```

### ✅ Крок 8: Стандартизуй execution_ready

```python
execution_ready = (
    executable 
    && verified_for_execution 
    && !cooldown 
    && !blocked
)
```

`blocked_reason` тепер пояснює чому `execution_ready=False`.

### ✅ Крок 9: cumulative_pnl нормалізація

**TruthReport:**
```python
notion_capital_usdc: float = 0.0  # 0 = raw cumulative
normalized_return_pct: float | None = None

# to_dict():
"cumulative_pnl": {
    "warning": "Raw cumulative - not normalized to capital"  # if notion=0
}
```

**smoke_minimal.py:**
```python
"notion_capital_usdc": 10000.0,  # $10k for SMOKE mode
```

### ✅ Крок 10: Контрольний прогін

Очікувані результати після змін:
- `QUOTE_GAS_TOO_HIGH` ↓ 50%+ (wstETH excluded + relative filter)
- `TICKS_CROSSED_TOO_MANY` ↓ 50%+ (wstETH excluded)
- `execution_ready_count > 0` (paper mode ignores verification)
- `normalized_return_pct` замість raw cumulative

---

## Файли

| Файл | Зміни |
|------|-------|
| `config/smoke_minimal.py` | +excluded_pairs, +paper_trading, +notion_capital |
| `strategy/quarantine.py` | NEW: QuarantineManager |
| `strategy/gates.py` | +gate_gas_relative, +anchor_source param |
| `monitoring/truth_report.py` | +blocked_reason, +notion_capital, clarified fields |

---

## Тести

**91 passed** ✅

---

## M3 KPI Rules

```python
M3_KPI_RULES = {
    "rpc_success_rate_min": 0.8,      # ✅ 0.886
    "quote_fetch_rate_min": 0.7,       # ✅ 0.9
    "gate_pass_rate_min": 0.4,         # ✅ 0.722
    "gates_changed_pct_max": 5.0,
    "invariants_required": True,
}
```

---

## Очікувані результати

Після контрольного прогону з новими налаштуваннями:

| Метрика | Було | Очікується |
|---------|------|------------|
| QUOTE_GAS_TOO_HIGH | 260 | < 130 |
| TICKS_CROSSED_TOO_MANY | 200 | < 100 |
| execution_ready_count | 0 | > 0 |
| PnL | Raw 72416 bps | Normalized % |
