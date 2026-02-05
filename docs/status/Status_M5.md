# Milestone 5 — Production small

> **Оновлено**: 2026-02-05 19:48 UTC  
> **SHA**: `60dd4ac`  
> **Статус**: ✅ PASS

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

M5_0 closed on SHA: `60dd4ac`. Close only if:

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

**RESULT: PASS + data\runs\manual_run_20260205_194841**

Команда:
```bash
python -m scripts.ci_m5_gate --online --config config/real_minimal.yaml --cycles 1 --gas-usd-estimate 0.10
```

Артефакти:
- Scan: `data/runs/manual_run_20260205_194841/snapshots/scan_20260205_194843.json`
- Daily report: `data/runs/manual_run_20260205_194841/reports/daily_report_2026-02-05T18-48-44.308180+00-00.json`

Провенанс (v3 tick/sqrt_price_x96):
- `uniswap_v3`: tick=-200741, sqrt_price_x96=3467988426551225090982811
- `sushiswap_v3`: tick=-200738, sqrt_price_x96=3468418291105540965540117 ✅

cost_model: `{"type": "gas_only", "gas_usd_estimate": 0.1}`

## Юніт-тести

```
449 passed, 5 subtests passed
```

## Наступні кроки

1. ~~Запустити канонічну команду з реальним RPC для верифікації slot0()~~ ✅
2. Додати генерацію `spread_signals` у truth_report
3. Заповнити `top_opportunities` з реальних signals
4. Додати газ oracle інтеграцію (M6)

## SHA закриття M5

_(заповнюється при закритті milestone)_

---

Next: Milestone 6
