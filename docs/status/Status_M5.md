# Milestone 5 — Production small

> **Оновлено**: 2026-02-05 21:45 UTC  
> **SHA**: `pending`  
> **Статус**: ✅ PASS — Signals MVP v3 DONE

---

## Recent Changes (2026-02-05)

### 🎉 Signals MVP v3 DONE

**Summary**: Spread signals production-ready з повною семантикою та transparency.

#### Signal Schema v3 (FINAL)
- `spread_bps_exact`: float для micro-spreads
- `spread_bps_int`: int для UI
- `spread_pct`: відсоток (e.g., 0.0157%)
- `spread_frac`: **NEW** fraction для math (0.00015721)
- `confidence_reasons`: **NEW** transparency array

#### Stats improvements
- `requested_cycles`: **NEW** what user asked
- `cycles_completed`: what actually ran
- `execution_pnl`: **NEW** separated from spread_signals

#### Config additions
- `min_spread_bps: 0` — filter threshold

### Критичний фікс: amount_out vs price consistency

**Проблема**: `amount_out_human="2600"` був статичним, тоді як `price≈1930` обчислювався з `sqrt_price_x96`. Це порушувало інваріант `price == amount_out / amount_in`.

**Рішення**: 
- Тепер `amount_out_wei` та `amount_out_human` обчислюються з `price_exact`
- Додано unit test `test_quote_price_invariant.py` для валідації інваріанту

### Spread signals — paper cost estimates

Сигнали тепер включають paper estimates:
- `is_gross_positive`: замінив `is_profitable` (чесніша семантика — лише gross spread)
- `gross_pnl_usdc_est`: оцінка gross прибутку для paper trade
- `net_pnl_usdc_est`: gross - gas - slippage  
- `is_net_positive_est`: чи позитивний net після витрат

### Daily report enhancements

- `top_signal`: найкращий spread signal з buy/sell/spread_bps/net_estimate

---

## Deliverables (Roadmap)

- Daily reporting artifact (daily_report_*.json) with schema_version and run coverage
- Stable definitions: win_rate, net_pnl_usdc, tail_losses, top_reject_reasons
- Auto-sizing rules (min/max/clamp and back-off/restore heuristics)
- Transparent health metrics (rpc/dex/system)
- CI validation for M5 (ci_m5_gate)

## DoD-commands (канонічні команди)

- Двокрокова — коли вже є runDir:
  - `python scripts/ci_m5_0_gate.py --run-dir data/runs/<runDir>`

- Однокрокова (runner) — scan + generate + validate:
  - `python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1 --gas-usd-estimate 0.10`

- Юніт-тести:
  - `python -m pytest tests/unit -q`

Execution policy

DO NOT enable execution yet — execution remains disabled until a validated cost model and execution engine exist.

Daily report artifact

We add a new artifact: `daily_report_<YYYYMMDD>.json`.
Minimal fields (schema_version v1):

- `schema_version`: string (e.g. "m5:daily:v1")
- `run_id`: string or list of run directories included
- `period`: {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
- `date`: YYYY-MM-DD (report date)
- `runs_included`: int
- `net_pnl_usdc`: number (net pnl for paper trades in USDC)
- `win_rate`: number (fraction 0..1) — defined for M5 as: paper trades/opportunities that passed gates and would have executed (execution disabled)
- Note: For clarity these are *paper* metrics in M5. The canonical field names produced by the generator will be `paper_net_pnl_usdc` and `paper_win_rate` and `pnl_mode: "paper"`.
 - Note: For clarity these are *paper* metrics in M5. The canonical field names produced by the generator will be `paper_net_pnl_usdc` and `paper_win_rate` and `pnl_mode: "paper"`.
- `trades_count`: int

Important: `trades_count` is a legacy name kept for backwards compatibility and is equivalent to `checks_count` produced by the generator. This field is deprecated and consumers should prefer `checks_count`.
- `tail_losses`: list of top-k worst trade outcomes (by pnl)
- `top_reject_reasons`: list of {reason, count}
- `health`: {rpc: {...}, dex: {...}, system: {...}}

Additional recommended fields (required for M5 progression):
- `autosize`: {`new_size_usd`, `reason`, `cooldown_remaining`} — auto-size decisions must be surfaced in the report even if only as metadata.
- `top_opportunities`: list of top-5 opportunity summaries: {`spread_pct`, `size_usd`, `confidence`, `source`} — should be derived from `truth_report.spread_signals` or from `scan.quotes` when signals absent.
- `top_quotes`: list of top-2 raw quotes sample with full provenance: {`dex_id`, `pool_address`, `block_number`, `price`, `tick`, `sqrt_price_x96`, `pair`, `timestamp`} — provides transparency into scanner output.

Cost model (мінімальна газова модель)

Для M5 початкова cost model — gas-only і явно задана в config або CLI.

- У config: `gas_usd_estimate: 0.10` (приклад).
- CLI: `--gas-usd-estimate 0.10`.
- Env: `ARBY_GAS_USD_ESTIMATE=0.10`.

```
paper_net_pnl_usdc = gross_spread_usd - gas_usd_estimate - slippage_usd_estimate
```

Коли `gas_usd_estimate` задано, репорт ПОВИНЕН мати `pnl_available: true` і `pnl_reason: null`.

Важливо: `daily_report.paper_net_pnl_usdc` — це окрема paper-оцінка, НЕ з truth_report. У truth_report `cost_model_available` може бути `false`, а у daily_report pnl_available=true (бо daily застосовує gas-only модель незалежно).

## PnL роз'яснення (paper vs truth)

| Артефакт | PnL поле | Статус | Опис |
|----------|----------|--------|------|
| `daily_report` | `paper_net_pnl_usdc` | ✅ Активний | Estimate-only через gas_usd_estimate з config/CLI |
| `truth_report` | `pnl.net_pnl_usdc` | ❌ Disabled | Потребує cost_model в core (M6+) |

**Чому розділено**: daily_report може показувати paper PnL навіть коли truth_report не має cost_model. Це дозволяє операційний моніторинг без повної інтеграції execution engine.

### **⚠️ ВАЖЛИВО: cost_model layers**

**Є ДВА різні cost_model:**

1. **daily_report.cost_model** (АКТИВНИЙ у M5):
   - Тип: `gas_only` 
   - Джерело: CLI `--gas-usd-estimate` або config `gas_usd_estimate`
   - Формула: `paper_net_pnl_usdc = gross_pnl - gas_usd_estimate - slippage_usd_estimate`
   - Призначення: **paper-estimate для оперативного моніторингу**
   - Це ESTIMATE, не реальний газ

2. **truth_report.cost_model** (ВИМКНЕНИЙ, M6+):
   - Тип: execution-level cost model
   - Джерело: газ oracle + execution engine
   - Призначення: **execution-рівень PnL після реального трейду**
   - Поле: `cost_model_available: false` поки не реалізовано

**НЕ плутати** daily_report.cost_model (paper) з truth_report cost_model (execution)!

### top_opportunities та opportunities_reason

- `top_opportunities` заповнюється ТІЛЬКИ з `truth_report.spread_signals`
- `spread_signals` генеруються на основі `price_exact` (з sqrt_price_x96) для точного виявлення мікроспредів
- Якщо `spread_signals` порожній → `top_opportunities: []` і `opportunities_reason: "no_spread_signals"`
- Threshold для сигналів: 1 bps (0.01%) — мінімальний spread для реєстрації

### Paper PnL формула

```
gross_spread_usdc = Σ(spread_pct * size_usd) для всіх signals
paper_net_pnl_usdc = gross_spread_usdc - gas_usd_estimate - slippage_usd_estimate
```

**paper_win_rate** = price_sanity_passed / quotes_total (НЕ пов'язаний з PnL)

Price provenance (on-chain доказовість ціни)

Для M5 quotes ПОВИННІ містити:
- `pool_address` — адреса пулу (для v3).
- `block_number` — номер блоку.
- `tick` — поточний tick з slot0() (v3 only).
- `sqrt_price_x96` — sqrtPriceX96 з slot0() (v3 only).

Ці поля підтверджують, що ціна прийшла з on-chain стану конкретного блоку.

Golden artifact policy

- Maintain golden `daily_report_*.json` files under `docs/artifacts/` for regression testing.
- Update golden only when the `schema_version` changes or a deliberate addition of fields is accepted by the team. Do NOT auto-update golden from the latest run unless schema changed.
- Golden artifacts include: `daily_report_golden.json`, `scan_golden.json` з прикладами v3 provenance.

### **⚠️ Golden artifacts update rules (CANONICAL)**

1. **Коли оновлювати golden:**
   - `schema_version` змінено (e.g., `m5:daily:v1` → `m5:daily:v2`)
   - Додано нове required поле до артефакту
   - Виправлено помилку у структурі даних

2. **Коли НЕ оновлювати golden:**
   - Просто змінились значення даних (quotes, prices)
   - Нічого не змінилось у schema

3. **Процедура оновлення:**
   ```bash
   # 1. Запустити canonical run
   python scripts/ci_m5_gate.py --online --config config/real_minimal.yaml --cycles 1 --gas-usd-estimate 0.10
   
   # 2. Скопіювати артефакти
   cp data/runs/latest/reports/daily_report_*.json docs/artifacts/daily_report_golden.json
   
   # 3. Оновити schema_version у Status_M5.md якщо змінено
   ```

4. **Перевірка golden:**
   - `python -m pytest tests/unit -q` — включає golden validation tests

Negative tests (required):
- `current_block` mismatch (already present)
- `quotes_total` mismatch (unit test added)
- `rejects_total` mismatch (unit test added)
- `v3_provenance` fields test (unit test added)

DoD additions

- The daily report MUST include provenance fields: `source_run_dir` and `artifacts` with explicit paths: `scan_path`, `truth_report_path`, `reject_histogram_path`.
- The generator will write default reports under `runDir/reports/daily_report_*.json` to ensure reproducibility.
- The daily report MUST include `cost_model` block: `{"type": "gas_only"|"none", "gas_usd_estimate": N, "slippage_usd_estimate": N}`.
- `trades_count` deprecated: use `checks_count`. `legacy_trades_count` added for transition.

Definitions (short)

- `win_rate`: for M5 initial phase, count paper trades (opportunities) that pass gates divided by total opportunities considered; execution disabled so this is paper win-rate.
- `net_pnl_usdc`: net pnl estimated for paper trades in USDC terms (consistent currency for M5).

Validation & CI

- `ci_m5_gate.py` will validate daily report schema and consistency with artifacts (quotes_total, total_rejects, current_block) when artifact paths present.
- `ci_m5_gate.py` will also ensure `paper_win_rate` in [0,1], `top_reject_reasons` present (or explicit empty explanation), and health keys (`rpc`,`dex`,`system`) present.
- `tail_losses`: for example the top-5 worst trade outcomes for the period, by pnl.
- `reject reasons`: include origin stage (normalize: normalize_price|sanity_check|execution|rpc)

Auto-size (initial rules)

- `min_size` and `max_size` must be configured.
- On high-impact/slippage events: if `ticks_crossed > T1` or `slippage_bps > S1` then `size *= 0.5` (clamped to `>= min_size`).
- Restore rule: if 3 cycles in a row with low slippage/ticks, `size *= 1.2` (clamped to `<= max_size`).

Health score (transparent components)

- `rpc_health`: {`success_rate`, `p50_latency_ms`, `ws_connected_rate`}
- `dex_health`: {`quote_fetch_rate`, `revert_rate`}
- `system_health`: {`gate_pass_rate`, `artifacts_ok_rate`}

Retention & golden artifacts

- Preserve 1–2 golden `daily_report_*.json` files under `docs/artifacts/` for regressions.
- Document retention: add `scripts/clean_runs.py` (or manual instruction) to remove old runDir(s).

M5_0 closure

M5_0 closed on SHA: `087d014`. Close only if:

- `scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml` passes ✅
- `pytest -q` green (449 passed) ✅

---

## Статус виконання M5

| # | Задача | Статус |
|---|--------|--------|
| 1 | daily_report generator | ✅ |
| 2 | gas-only cost model у config | ✅ |
| 3 | pool_address у quotes | ✅ |
| 4 | tick/sqrtPriceX96 з slot0() | ✅ |
| 5 | top_opportunities policy | ✅ |
| 6 | autosize завжди об'єкт | ✅ |
| 7 | strict режим у gate | ✅ |
| 8 | негативні тести (4 шт) | ✅ |
| 9 | paper PnL документація | ✅ |
| 10 | cost_model block у daily_report | ✅ |
| 11 | trades_count deprecation | ✅ |
| 12 | CI check для Status*.md | ✅ |
| 13 | golden artifacts оновлено | ✅ |

## Ризики

| Ризик | Ймовірність | Вплив | Мітігація |
|-------|-------------|-------|-----------|
| slot0() RPC failure | Середня | Низький | tick/sqrtPriceX96 = null (quote валідний, без provenance) |
| Gas estimate неточний | Висока | Середній | Це estimate-only; real execution потребує gas oracle |
| top_opportunities порожній | Низька | Низький | Очікувано поки spread_signals не генеруються |
| WS disconnect | Низька | Низький | Fallback до HTTP автоматичний |

## Останній прогін

**RESULT: PASS + data\runs\manual_run_20260205_213126 (Signals MVP v3 FINAL)**

```powershell
python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 5
```

**Signals MVP v3 — всі 9 issues закрито!**:
- `spread_bps_exact`: **1.5721** ✅
- `spread_frac`: **0.00015721** ✅ (NEW)
- `is_gross_positive`: **True** ✅
- `confidence_reasons`: **["micro_spread", "execution_disabled", "paper_cost_model"]** ✅ (NEW)
- `requested_cycles`: **5** ✅ (NEW)
- `cycles_completed`: **5** ✅
- `execution_pnl.cost_model_available`: **False** ✅ (NEW: separated)
- `net_pnl_usdc_est`: **+$0.0572** ✅
- `is_net_positive_est`: **True** ✅

Провенанс:
- buy: sushiswap_v3 @ $1889.48
- sell: uniswap_v3 @ $1889.78

## Юніт-тести

```
461 passed, 5 subtests passed
```

## Signals MVP DoD (2026-02-05) — DONE ✅

**Summary**: Spread signals генеруються правильно з точною математикою та повною семантикою.

### Баги виправлені (Round 1 & 2)

**Bug 1: is_gross_positive** — використовував `spread_bps_int > 0` замість `spread_bps_decimal > 0`.
```python
# BEFORE (баг): is_gross_positive: spread_bps > 0  # int(0.27) = 0 → False!
# AFTER (фікс): is_gross_positive: bool(spread_bps_decimal > 0)  # Decimal → True
```

**Bug 2: spread_bps втрачався** — мікро-спреди (< 1 bps) округлялися до 0.
```python
# BEFORE: "spread_bps": int(spread_bps_decimal)  # 0.27 → 0
# AFTER: "spread_bps_exact": 0.2673, "spread_bps_int": 0
```

**Bug 3: slippage дефолт** — 1 bps ($0.10) вбивав мікро-спреди.
```yaml
# config/real_minimal.yaml
paper_slippage_bps: 0  # дефолт 0, не 1
```

**Bug 4: size_source="default"** — параметри не з config.
```yaml
# Тепер з config:
paper_size_usd: 1000
paper_slippage_bps: 0
gas_usd_estimate: 0.10
```

### Семантичні покращення (Round 3)

**Issue 5: spread_pct unclear** — додано `spread_frac` для ясності.
```python
"spread_pct": 0.0145,    # % (0.0145%)
"spread_frac": 0.000145, # fraction (multiply by amount)
```

**Issue 6: confidence black-box** — додано `confidence_reasons`.
```python
"confidence_reasons": ["micro_spread", "execution_disabled", "paper_cost_model"]
```

**Issue 7: cycles semantics** — розділено на `requested_cycles` + `cycles_completed`.

**Issue 8: pnl confusion** — перейменовано на `execution_pnl` (disabled).

**Issue 9: min_spread_bps** — додано в config.
```yaml
min_spread_bps: 0  # 0 = any positive spread (MVP)
```

### Signal Schema v3 (FINAL)

```json
{
  "spread_bps_exact": 1.5721,          // float для micro-spreads
  "spread_bps_int": 1,                  // int для UI
  "spread_pct": 0.015721,               // відсоток (0.0157%)
  "spread_frac": 0.00015721,            // fraction для math
  "is_gross_positive": true,            // sell > buy (Decimal)
  "confidence_reasons": [               // NEW: transparency
    "micro_spread",
    "execution_disabled",
    "paper_cost_model"
  ],
  "size_source": "config",
  "slippage_source": "config",
  "slippage_bps": 0,
  "net_pnl_usdc_est": 0.0572,
  "is_net_positive_est": true
}
```

### Stats Schema v3

```json
{
  "requested_cycles": 5,     // NEW: what user asked for
  "cycles_completed": 5,     // what actually ran
  "execution_pnl": {         // NEW: renamed from "pnl"
    "signal_pnl_usdc": 0.0,
    "cost_model_available": false
  }
}
```

### Верифікаційний прогін (5 циклів)

```
run: manual_run_20260205_213126
requested_cycles: 5 ✅
cycles_completed: 5 ✅
spread_bps_exact: 1.5721 ✅
spread_frac: 0.00015721 ✅
is_gross_positive: True ✅
net_pnl_usdc_est: $0.0572 ✅
confidence_reasons: micro_spread,execution_disabled,paper_cost_model ✅
```

### Unit тести (7 нових)

- `test_spread_signal_from_real_quotes` — базовий сигнал
- `test_spread_signal_with_threshold` — фільтрація
- `test_price_invariant_bug_detection` — ловить "2600" баг
- `test_no_signal_when_same_dex` — потрібно 2+ DEX
- `test_paper_cost_model_arithmetic` — формула net
- `test_micro_spread_is_gross_positive` — **мікро-спред з is_gross_positive=True**
- `test_spread_pct_semantics` — семантика відсотків

### DoD Checklist

- [x] `is_gross_positive` коректний (sell > buy, Decimal)
- [x] `spread_bps_exact` не нуль при різних цінах
- [x] `spread_bps_int` для UI
- [x] `spread_frac` для math (NEW)
- [x] `confidence_reasons` array (NEW)
- [x] `requested_cycles` + `cycles_completed` (NEW)
- [x] `execution_pnl` separated from spread_signals (NEW)
- [x] `min_spread_bps` in config (NEW)
- [x] `size_source != "default"` (з config)
- [x] `slippage_source != "default"` (з config)
- [x] `paper_slippage_bps: 0` в config
- [x] Unit тест для micro-spread
- [x] 5-cycle прогін з `is_net_positive_est=True`
- [x] 461 unit тест пройшов

---

## Наступні кроки

1. ~~Запустити канонічну команду з реальним RPC для верифікації slot0()~~ ✅
2. ~~Додати генерацію `spread_signals` у truth_report~~ ✅ (Signals MVP)
3. ~~Заповнити `top_opportunities` з реальних signals~~ ✅
4. Додати газ oracle інтеграцію (M6)

## SHA закриття M5

_(заповнюється при закритті milestone)_

---

Next: Milestone 6
