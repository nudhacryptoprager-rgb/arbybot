# Status_M3_P2_quality_v4.md — Definition of Fix (10/10)

**Дата:** 2026-01-16  
**Milestone:** M3 P2 Quality v4  
**Статус:** ✅ **IMPLEMENTED**

---

## Контекст

Team Lead виявив критичну проблему з контрактом paper_trades.jsonl:
- `spread_id = WETH/ARB...`, але `token_out = USDC` — семантичне зламання
- Змішані поняття executable vs execution_ready
- SMOKE занадто шумний (5 пар)
- cumulative_pnl оманливий

---

## Виконані кроки (10/10)

### ✅ Крок 1: Виправити контракт paper_trades.jsonl

**PaperTrade dataclass оновлено:**

```python
@dataclass
class PaperTrade:
    """
    CONTRACT (Team Lead v4):
    - token_in/token_out must match spread_id/pair (REAL tokens)
    - numeraire is the currency for PnL (usually USDC)
    - *_numeraire fields contain values in numeraire currency
    """
    # REAL TOKENS (must match pair in spread_id)
    token_in: str       # e.g., "WETH" for WETH/ARB spread
    token_out: str      # e.g., "ARB" for WETH/ARB spread
    
    # NUMERAIRE for PnL calculations
    numeraire: str = "USDC"
    amount_in_numeraire: float = 0.0
    expected_pnl_numeraire: float = 0.0
    
    def validate_tokens_match_pair(self) -> list[str]:
        """Validates token_in/token_out match spread_id pair."""
```

**Тест для валідації:**
```python
def test_paper_trade_tokens_mismatch_detected(self):
    """Test that mismatched tokens are detected."""
    trade = PaperTrade(
        spread_id="WETH/ARB:...",
        token_in="WETH",
        token_out="USDC",  # WRONG: should be ARB!
        ...
    )
    violations = trade.validate_tokens_match_pair()
    assert len(violations) > 0  # ✅ Bug detected!
```

### ✅ Крок 2: Уніфікувати семантику executable

**OpportunityRank:**
```python
executable_economic: bool  # Passes gates + PnL > 0 (economic truth)
paper_would_execute: bool  # = executable_economic in paper mode
execution_ready: bool      # + verified + !blocked (can actually execute)
blocked_reason: str | None # WHY not execution_ready
```

### ✅ Крок 3: Truth source для paper outcomes

`generate_truth_report()` тепер рахує з opportunities:
```python
execution_ready_count = sum(
    1 for opp in top_opportunities if opp.execution_ready
)
paper_executable_count = sum(
    1 for opp in top_opportunities if opp.paper_would_execute
)
```

### ✅ Крок 4: SMOKE мінімізувати

**smoke_minimal.py:**
```python
"pairs": [
    "WETH/USDC",  # Stable baseline
    "WETH/ARB",   # Volatile baseline
],
"excluded_pairs": [
    "wstETH/WETH",  # High ticks, high gas
    "WETH/LINK",    # PRICE_SANITY issues
    "WETH/USDT",    # Quoter issues
],
"fee_tiers": [500],  # ONLY 500 for consistency
```

### ✅ Крок 5: GAS gate відносні пороги

`gate_gas_relative()` реалізовано:
```python
MIN_PROFIT_TO_GAS_RATIO = 2.0
# Reject if net_pnl_usdc / gas_cost_usdc < 2.0
```

### ✅ Крок 6: PRICE_SANITY anchor source

`gate_price_sanity()` має `anchor_source` параметр:
```python
anchor_source = {
    "anchor_dex": "uniswap_v3",
    "anchor_pool": "0x...",
    "anchor_fee": 500,
    "anchor_block": 12345,
}
```

### ✅ Крок 7: TICKS_CROSSED адаптивно

Реалізовано:
- `get_adaptive_ticks_limit(amount_in, pair)`
- `suggest_smaller_amount(current_amount)`

### ✅ Крок 8: Truth_report метрики очистити

```python
# to_dict() тепер:
"pnl_normalized": {
    "notion_capital_numeraire": 10000.0,
    "normalized_return_pct": 0.15,
    "numeraire": "USDC",
},
"cumulative_pnl": {
    "_warning": "RAW - use pnl_normalized for decisions",
}
```

### ✅ Крок 9: Інваріанти як тести

**Нові тести (34 total in test_error_contract.py):**
```python
class TestPaperTradeContract:
    test_paper_trade_has_numeraire_fields
    test_paper_trade_legacy_compatibility
    test_paper_trade_tokens_must_match_pair
    test_paper_trade_tokens_mismatch_detected  # NEW!

class TestExecutableSemantics:
    test_executable_economic_vs_execution_ready
    test_invariant_execution_ready_implies_executable_economic
```

### ✅ Крок 10: Schema versioning

```python
TRUTH_REPORT_SCHEMA_VERSION = "3.0.0"
# Included in every truth_report.json
```

---

## Тести

**97 passed** ✅ (34 error_contract + 63 gates)

---

## Файли

| Файл | Зміни |
|------|-------|
| `strategy/paper_trading.py` | +validate_tokens_match_pair(), numeraire contract |
| `monitoring/truth_report.py` | +counting from opportunities |
| `config/smoke_minimal.py` | +excluded_pairs (LINK, USDT) |
| `tests/unit/test_error_contract.py` | +test_paper_trade_tokens_mismatch_detected |

---

## Семантика виконання (Summary)

| Поле | Значення |
|------|----------|
| `executable_economic` | Passes all gates + PnL > 0 |
| `paper_would_execute` | = executable_economic (paper mode) |
| `execution_ready` | + verified + !blocked |
| `blocked_reason` | WHY not ready |

---

## Критична валідація (Team Lead Bug)

```python
# BUG DETECTED:
spread_id = "WETH/ARB:..."
token_out = "USDC"  # ❌ WRONG! Should be ARB

# FIX:
trade.validate_tokens_match_pair()
# Returns: ["token_out (USDC) != pair quote (ARB)"]
```

Тепер система детектує семантичні помилки в paper_trades!
