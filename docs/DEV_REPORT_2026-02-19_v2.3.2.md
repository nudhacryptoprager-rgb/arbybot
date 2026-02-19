# DEV REPORT 2026-02-19 v2.3.2 (UA)

## Статус сесії

**Дата:** 2026-02-19  
**Версія політики:** v2.0.8  
**Версія гейту:** v2.3.2  
**Commit:** (pending)

## Виконані кроки (10/10)

| # | Крок | Статус |
|---|------|--------|
| 1 | Clean encoding/ASCII у Status файлах | [DONE] |
| 2 | Повне розділення M4/M5_0 evidence | [DONE] |
| 3 | profit_truth_available контракт у Roadmap | [DONE] |
| 4 | Переписати тести на реальний код | [DONE] |
| 5 | Підготовка ONLINE evidence | [DONE] |
| 6 | Enable Clean PnL v1 | [DONE] |
| 7 | Roundtrip canonical logic | [DONE] |
| 8 | Sushi PRICE_SANITY regression test | [DONE] |
| 9 | Discovery/intent integration | [DONE] |
| 10 | Canonical DEV REPORT UA | [DONE] |

## Нові/змінені файли

### Код (production)

| Файл | Зміна |
|------|-------|
| `m4/gates.py` | +`compute_profit_truth_available()`, +`apply_profit_diagnostic_warning()` |
| `strategy/artifacts.py` | +`_compute_execution_pnl()` helper для Clean PnL v1 |
| `discovery/index_factories.py` | +`verify_pool_exists()`, +`validate_pool_address()` |
| `core/rpc_urls.py` | +`get_rpc_url()` simple helper |

### Тести

| Файл | Тести |
|------|-------|
| `tests/unit/test_profit_truth_available.py` | 12 тестів (реальний код з m4/gates.py) |
| `tests/unit/test_sushi_price_sanity_regression.py` | 11 тестів |
| `tests/unit/test_discovery_factories.py` | 16 тестів |

### Документація

| Файл | Зміна |
|------|-------|
| `docs/status/INDEX.md` | Емоджі → ASCII, дата оновлена |
| `docs/status/Status_M5_0.md` | Емоджі → ASCII |
| `docs/status/Status_M4.md` | Видалено M5_0 infra evidence |
| `Roadmap.md` | +v2.3.2 Profit Truth Semantics section |

## Артефакти на диску

```
data/runs/_rolling/
├── _latest.json                  (2026-02-19)
├── run_summary_latest.json       (2026-02-19)
└── m4_stability_agg.json         (2026-02-19)
```

## Тести

```
926 passed, 12 skipped, 1 warning
```

### Нові тести по категоріям

- **profit_truth_available:** 12 тестів (compute + apply helpers)
- **sushi PRICE_SANITY:** 11 регресійних тестів
- **discovery factories:** 16 тестів (PoolIndex, verify, validate)

## Команди для верифікації

```powershell
# Unit tests
py -3.11 -m pytest -q

# M4 gate offline (profit profile)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict

# Full pipeline CI
py -3.11 scripts/ci_full_pipeline.py --mode ci

# M5_0 gate offline
py -3.11 scripts/ci_m5_0_gate.py --offline
```

## Блокери / TODO для ONLINE

1. **RPC Rate Limit:** Потрібен ALCHEMY_API_KEY для ONLINE run
2. **Rolling refresh:** Після ONLINE run оновити `_rolling/` артефакти
3. **Roundtrip evidence:** Потрібен profitable roundtrip для `profit_truth_available=True`

## Контракти

### profit_truth_available (v2.3.2)

```
profit_truth_available = (NOT profit_is_diagnostic) AND cost_model_available

profit_is_diagnostic = truth_mode_m42 OR (roundtrip.profitable_count == 0)
cost_model_available = (gas_usd_estimate > 0)
```

### profit_truth_source

| Значення | Умова |
|----------|-------|
| `ROUNDTRIP_CANONICAL` | roundtrip.profitable_count > 0 |
| `ONE_LEG_DIAGNOSTIC` | truth_mode_m42=True |
| `ONE_LEG_UNVERIFIED` | інакше |

## Наступні кроки

1. Запустити ONLINE scan: `py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml`
2. Оновити rolling артефакти після успішного run
3. Створити commit з усіма змінами
