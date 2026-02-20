# Status_M2.2.md — P0 Fixes & Truth Report

**Дата:** 2026-01-11  
**Milestone:** M2.2 — P0 Fixes + M3 Foundation  
**Статус:** ✅ **COMPLETE**

---

## 1. P0 Виправлення

### ✅ 1.1 Аномальні ціни (fee=10000 на Sushiswap)

**Виправлено:**
- fee=10000 вже прибрано з `dexes.yaml` для sushiswap_v3
- Anchor DEX (uniswap_v3) обробляється **першим** (сортування)
- Sanity gate порівнює ціни з anchor (MAX_PRICE_DEVIATION_BPS = 1000 = 10%)

```python
# gates.py
def gate_price_sanity(quote, anchor_price, max_deviation_bps=1000):
    if deviation_bps > max_deviation_bps:
        return GateResult(passed=False, reject_code=PRICE_SANITY_FAILED)
```

### ✅ 1.2 Метрики, що брешуть

**Уніфіковані лічильники:**

| Метрика | Опис |
|---------|------|
| `quotes_attempted` | Загальна к-сть спроб |
| `quotes_fetched` | Успішні RPC виклики |
| `quotes_rejected` | **Унікальні** quotes що не пройшли gates |
| `quotes_passed_gates` | Quotes що пройшли всі gates |
| `reject_reasons_histogram` | Histogram причин (може бути > quotes_rejected) |
| `total_reject_reasons` | Сума histogram |

**Логіка:**
```python
if gate_failures:
    quotes_rejected += 1  # Один раз за quote
    for failure in gate_failures:
        histogram[failure.code] += 1  # Кілька разів за quote
```

### ✅ 1.3 Pool Identity в Quotes

```json
{
  "dex": "uniswap_v3",
  "pair": "WETH/USDC",
  "pool_address": "0x...",
  "token_in": "0x...",
  "token_out": "0x...",
  "fee": 500,
  "quoter": "0x61fFE014..."
}
```

---

## 2. Truth Report (M3 Foundation)

**Новий модуль:** `monitoring/truth_report.py`

### Output приклад:

```
============================================================
TRUTH REPORT
============================================================
Timestamp: 2026-01-11T11:37:37+00:00
Mode: REGISTRY

--- HEALTH ---
RPC: 95.0% success, 45ms avg latency
Quotes: 100.0% fetch, 58.3% pass gates
Coverage: 1 chains, 2 DEXes, 2 pairs
Pools scanned: 16

Top reject reasons:
  QUOTE_TICKS_CROSSED_TOO_MANY: 4
  QUOTE_GAS_TOO_HIGH: 2

--- STATS ---
Total spreads: 6
Profitable: 4
Executable: 2
Blocked: 2

--- CUMULATIVE PNL ---
Total: 45 bps ($11.25)

--- TOP OPPORTUNITIES ---
  #1 [✓] uniswap_v3→sushiswap_v3: 15 bps ($3.75) conf=80%
  #2 [✗] sushiswap_v3→uniswap_v3: 10 bps ($2.50) conf=30%
============================================================
```

### Confidence Score:

```python
def calculate_confidence(spread):
    score = 0.0
    if executable: score += 0.4
    if net_pnl > 0: score += 0.2
    if gas_ratio < 0.3: score += 0.2
    if both_verified: score += 0.2
    return min(score, 1.0)
```

---

## 3. Файли

| Файл | Зміни |
|------|-------|
| `strategy/gates.py` | Вже має gate_price_sanity |
| `strategy/jobs/run_scan.py` | Уніфіковані метрики, anchor sorting, truth report |
| `monitoring/truth_report.py` | **NEW** - Truth report generator |
| `config/dexes.yaml` | fee=10000 прибрано для sushiswap |

---

## 4. Тести

**152 passed ✅**

---

## 5. Snapshot структура (оновлена)

```json
{
  "mode": "REGISTRY",
  "cycle_summaries": [{
    "quotes_attempted": 24,
    "quotes_fetched": 24,
    "quotes_rejected": 10,
    "quotes_passed_gates": 14,
    "reject_reasons_histogram": {
      "QUOTE_TICKS_CROSSED_TOO_MANY": 6,
      "QUOTE_GAS_TOO_HIGH": 4
    },
    "total_reject_reasons": 10
  }]
}
```

**Математика тепер сходиться:**
- attempted = 24
- fetched = 24 (100%)
- rejected = 10 (unique quotes)
- passed = 14
- 24 = 10 + 14 ✓

---

## 6. CLI Changes

```bash
# Truth report генерується автоматично
python -m strategy.jobs.run_scan --chain arbitrum_one --once --use-registry

# Output:
# data/reports/truth_report_20260111_113737.json
```

---

## 7. Acceptance Criteria

| Критерій | Статус |
|----------|--------|
| fee=10000 прибрано | ✅ |
| Anchor DEX перший | ✅ |
| Sanity gate працює | ✅ |
| Метрики уніфіковані | ✅ |
| Pool identity в quotes | ✅ |
| Truth report | ✅ |
| Confidence score | ✅ |

---

## 8. Наступні кроки

| Пріоритет | Крок |
|-----------|------|
| P1 | Adaptive sizing (зменшувати amount_in якщо ticks/gas fail) |
| P1 | Second executable DEX |
| P2 | Token discovery (DexScreener) |
| P2 | Re-quote after 1-2 blocks |

---

*Документ згенеровано: 2026-01-11*
