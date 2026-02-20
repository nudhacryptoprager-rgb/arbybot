# Канонічний шаблон звіту агента

> **⚠️ ARCHIVE (v2.0+)**: Цей шаблон містить SHA-based references.
> Для v2.x використовуй `docs/DEV_REPORT_CANONICAL_UA.md`.
> SHA tracking замінено на `run_timestamp` provenance.

Цей шаблон є обов'язковим форматом для всіх звітів і відповідей агента.

---

## Звіт (українською)

### Виконані директиви

| # | Директива | Статус |
|---|-----------|--------|
| 1 | [Опис директиви] | ✅ / ❌ / ⏳ [Коментар] |
| 2 | ... | ... |
| N | ... | ... |

### Результати останнього прогону

```
[Канонічна команда що була виконана]
```

**RESULT: PASS / FAIL + [RunDir або деталі]**

### Артефакти (ключові поля):
- `поле_1`: значення — коментар
- `поле_2`: значення — коментар
- ...

### Юніт-тести
```
[Кількість] passed, [Кількість] skipped/failed
```

### Що залишається / Наступні кроки:
- Пункт 1
- Пункт 2
- ...

### Канонічна команда:
```powershell
[Команда для повторення]
```

---

## Приклад заповненого звіту

### Виконані директиви

| # | Директива | Статус |
|---|-----------|--------|
| 1 | Канонічна команда M5 у Status_M5.md | ✅ Оновлено з `--strict --gas-usd-estimate` |
| 2 | pool_address у scan.quotes | ✅ Додано lookup із config.pools |
| 3 | tick/sqrtPriceX96 для v3 | ✅ Поля додані до QuoteCompat |
| 4 | Виправити top_opportunities policy | ✅ Тепер `[]` якщо spread_signals порожні |
| 5 | Strict режим: price + spread/confidence | ✅ Вже було |
| 6 | gas_usd_estimate у config | ✅ Додано `gas_usd_estimate: 0.10` |
| 7 | Негативний тест schema_version | ✅ Вже є |
| 8 | Запуск 5 циклів для перевірки цін | ✅ Виконано |
| 9 | Документація paper PnL vs truth_report | ✅ Додано до Status_M5.md |
| 10 | spread_signals для top_opportunities | ✅ Policy змінена |

### Результати останнього прогону

```
python -m scripts.ci_m5_gate --online --config config/real_minimal.yaml --cycles 1 --strict
```

**RESULT: PASS + data\runs\manual_run_20260205_190141**

### Артефакти daily_report:
- `pnl_available: true` — cost model увімкнено
- `pnl_reason: null`
- `paper_net_pnl_usdc: -0.10` — (0 - gas)
- `autosize: {enabled: false, reason: "not_configured"}` — завжди об'єкт
- `top_opportunities: []` — порожній (spread_signals немає)
- `top_reject_reasons: []` — порожній (rejects=0)
- `pool_address`: `0xC31E54c7a869B9...` — заповнено з config

### Юніт-тести
```
443 passed, 5 subtests passed
```

### Що залишається:
- `tick` і `sqrt_price_x96` — потрібен RPC call до slot0()

### Канонічна команда M5:
```powershell
python -m scripts.ci_m5_gate --online --config config/real_minimal.yaml --cycles 1 --strict --gas-usd-estimate 0.10
```

---

## Правила використання

1. **Мова**: Звіт завжди українською
2. **Таблиця директив**: Завжди на початку, з номерами та статусами
3. **Статуси**: ✅ виконано | ❌ не виконано | ⏳ в процесі
4. **Команди**: У fenced code blocks з `powershell` або відповідною мовою
5. **RESULT**: Канонічний рядок для CI парсингу
6. **Артефакти**: Ключові поля з коментарями
7. **Тести**: Завжди вказувати результат pytest
8. **Наступні кроки**: Що залишилось зробити

---

# Канонічний шаблон Status*.md

Всі файли `docs/status/Status_*.md` ПОВИННІ містити:

## Обов'язковий заголовок

```markdown
# Milestone N — [Назва]

> **Оновлено**: YYYY-MM-DD HH:MM UTC  
> **SHA**: `abcdef1`  
> **Статус**: ⏳ В роботі | ✅ Закрито | ❌ Заблоковано
```

## Обов'язкові секції

1. **Deliverables** — що має бути зроблено
2. **DoD-commands** — канонічні команди для перевірки
3. **Статус виконання** — таблиця з прогресом
4. **Останній прогін** — результат + runDir
5. **Юніт-тести** — passed/failed
6. **Наступні кроки / Блокери**
7. **SHA закриття** — коли milestone закритий

## Приклад Status*.md

```markdown
# Milestone 5 — Production small

> **Оновлено**: 2026-02-05 18:30 UTC  
> **SHA**: `0c84e19`  
> **Статус**: ⏳ В роботі

## Deliverables
- Daily reporting artifact
- Auto-sizing rules
- Health metrics
- CI validation

## DoD-commands

```powershell
python -m scripts.ci_m5_gate --online --config config/real_minimal.yaml --cycles 1 --strict
python -m pytest tests/unit -q
```

## Статус виконання

| # | Задача | Статус |
|---|--------|--------|
| 1 | daily_report generator | ✅ |
| 2 | gas-only cost model | ✅ |
| 3 | pool_address provenance | ✅ |
| 4 | tick/sqrtPriceX96 | ⏳ |

## Останній прогін

**RESULT: PASS + data\runs\manual_run_20260205_190141**

## Юніт-тести

443 passed, 5 subtests passed

## Наступні кроки
- Реалізувати slot0() call для tick
- Додати spread_signals генерацію

## SHA закриття

_(заповнюється при закритті milestone)_
```
