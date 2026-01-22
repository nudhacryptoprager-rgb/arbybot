# Status M3 P3: Core Contracts Fix

**Date:** 2026-01-18  
**SHA Base:** e91b4e5973d909008fb7ec4214d213f93fbe67b0  
**Branch:** chore/claude-megapack  
**Author:** Claude Opus 4.5  

---

## 🎯 Summary

Виконано всі 10 кроків виправлень зі списку критичних проблем. Основна мета — відновити узгоджені контракти core моделей та підготувати проєкт до реального сканера.

---

## ✅ Виконані кроки

| # | Крок | Статус | Файл(и) |
|---|------|--------|---------|
| 1 | Відновити DexType і PoolStatus | ✅ DONE | `core/constants.py` |
| 2 | Додати Token і Pool моделі | ✅ DONE | `core/models.py` |
| 3 | Quote.amount_in/out → int (wei) | ✅ DONE | `core/models.py` |
| 4 | Уніфікувати ErrorCode | ✅ DONE | `core/constants.py`, `core/exceptions.py` |
| 5 | Виправити селектор Algebra (0x2d9ebd1d) | ✅ DONE | `tests/unit/test_algebra_adapter.py` |
| 6 | Виправити bps/USDC в truth_report | ✅ DONE | `monitoring/truth_report.py` |
| 7 | Додати обов'язкові поля в paper_trades | ✅ DONE | `strategy/jobs/run_scan.py` |
| 8 | Розділити smoke/real run_scan | ✅ DONE | `strategy/jobs/run_scan.py`, `run_scan_smoke.py` |
| 9 | Прибрати side-effects з __init__.py | ✅ DONE | `strategy/jobs/__init__.py` |
| 10 | Синхронізувати docs | ✅ DONE | `docs/TESTING.md` |

---

## 📁 Змінені файли

### core/constants.py
```diff
+ class DexType(str, Enum): UNISWAP_V2, UNISWAP_V3, ALGEBRA, CURVE, BALANCER, VELODROME, AERODROME
+ class PoolStatus(str, Enum): ACTIVE, DISABLED, QUARANTINED, STALE, UNKNOWN
+ class ErrorCode(str, Enum): QUOTE_REVERT, QUOTE_TIMEOUT, INFRA_RPC_ERROR, ...
```

### core/models.py
```diff
+ @dataclass Token: chain_id, address, symbol, name, decimals, is_core
+ @dataclass Pool: chain_id, pool_address, dex_type, dex_id, token0, token1, fee, status
~ Quote.amount_in/out: str → int (wei)
+ Quote: extended fields (pool, direction, token_in_obj, token_out_obj, ...)
```

### core/exceptions.py
```diff
~ QuoteError: тепер підтримує code: ErrorCode та reason: RejectReason
```

### core/time.py
```diff
+ def now_ms() -> int: return int(time.time() * 1000)
```

### dex/adapters/algebra.py
```diff
~ Оновлено для нових моделей (Token, Pool, Quote)
~ Quote.token_in_obj, Quote.token_out_obj замість token_in, token_out
```

### tests/unit/test_algebra_adapter.py
```diff
- assert result.startswith("0xcdca1753")  # WRONG
+ assert result.startswith("0x2d9ebd1d")  # CORRECT quoteExactInputSingle
```

### monitoring/truth_report.py
```diff
- "total_bps": scan_stats.get("total_pnl_bps", 0)  # WRONG - scan_stats doesn't have it
+ "total_bps": paper_stats.get("total_pnl_bps", "0.00")  # CORRECT - paper_stats has it
```

### strategy/jobs/run_scan.py
```diff
~ Тепер placeholder для реального сканера
~ Редірект на smoke поки не реалізовано
```

### strategy/jobs/run_scan_smoke.py
```diff
+ Новий файл - явний SMOKE симулятор
+ Заповнює всі обов'язкові поля PaperTrade (pool_a, pool_b, token_in, token_out)
```

### strategy/jobs/__init__.py
```diff
- from strategy.jobs.run_scan import run_scanner, run_scan_cycle  # side effects
+ __all__: list[str] = []  # no imports = no side effects
```

### docs/TESTING.md
```diff
- Згадки неіснуючих файлів (test_rounding.py, test_decimal_safety.py, ...)
+ Актуальний список тестів
+ Оновлені команди для smoke
```

---

## 🧪 Команди тестування

```bash
# Перевірка імпортів core
python -c "from core.constants import DexType, PoolStatus, ErrorCode; print('OK')"
python -c "from core.models import Token, Pool, Quote; print('OK')"
python -c "from core.exceptions import QuoteError; print('OK')"

# Unit тести
python -m pytest tests/unit/test_format_money.py tests/unit/test_time.py -v

# SMOKE тест (симулятор)
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data/runs/smoke

# Перевірка артефактів
ls data/runs/smoke/
cat data/runs/smoke/paper_trades.jsonl
cat data/runs/smoke/reports/truth_report_*.json | python -c "import json,sys; print(json.dumps(json.load(sys.stdin)['cumulative_pnl'], indent=2))"
```

---

## 🔗 Залежності між модулями

```
core/constants.py
    ├── DexType, PoolStatus, ErrorCode, RejectReason, TradeOutcome
    │
    ▼
core/models.py
    ├── Token, Pool, Quote, Opportunity, Trade
    │   └── imports: DexType, PoolStatus, RejectReason, TradeOutcome
    │
    ▼
core/exceptions.py
    ├── QuoteError, ArbyError, ...
    │   └── imports: ErrorCode, RejectReason
    │
    ▼
dex/adapters/algebra.py
    ├── AlgebraAdapter.get_quote() → Quote
    │   └── imports: Token, Pool, Quote, ErrorCode, QuoteError
    │
    ▼
discovery/registry.py
    ├── PoolRegistry → list[PoolCandidate]
    │   └── imports: Token, Pool, DexType, PoolStatus
    │
    ▼
strategy/jobs/run_scan_smoke.py (симулятор)
strategy/jobs/run_scan.py (placeholder)
    └── imports: PaperSession, TruthReport, RPCHealthMetrics
```

---

## ⚠️ Відомі обмеження

1. **run_scan.py НЕ реалізований** — редіректить на smoke
2. **Adapters потребують httpx** — pip install httpx
3. **discovery/registry.py** — не тестувався з реальними даними
4. **dex/adapters/uniswap_v3.py** — потребує аналогічних виправлень

---

## 📋 Наступні кроки

1. [ ] Реалізувати реальний run_scan.py з registry → adapters → gates → snapshots
2. [ ] Виправити uniswap_v3.py адаптер аналогічно до algebra.py
3. [ ] Додати .env.example для RPC ключів
4. [ ] Створити відсутні тести (test_rounding.py, test_decimal_safety.py)
5. [ ] Оновити docs/FILES_SUMMARY.md

---

## 📊 Результат SMOKE тесту

```
TRUTH REPORT
============================================================
Timestamp: 2026-01-18T18:25:21.959134+00:00
Mode: REGISTRY

--- HEALTH ---
RPC: 90.0% success (10 requests), 124ms avg
Quotes: 90.0% fetch, 77.8% pass gates
Coverage: 1 chains, 2 DEXes, 5 pairs
Pools scanned: 10

Top reject reasons:
    QUOTE_REVERT: 2
    INFRA_RPC_ERROR: 1
    SLIPPAGE_TOO_HIGH: 1

--- CUMULATIVE PNL ---
Total: 50.00 bps ($0.500000)  ← УЗГОДЖЕНО! (було 0 bps / $0.5)
============================================================
```

---

**Status:** READY FOR REVIEW  
**Reviewed by:** ChatGPT (TL)  
**Next:** Implement real run_scan.py
