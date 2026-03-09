# DEV REPORT (Канонічний Формат, UA)

Цей документ визначає єдиний формат звіту від агента-розробника для проєкту ARBY3 / arbybot.

Пріоритет source-of-truth:
1) `Roadmap.md`
2) Status файли в `docs/status/` (див. `docs/status/INDEX.md`)
3) rolling артефакти в `data/runs/_rolling/` і runDir bundle в `data/runs/<run_id>/...`

Обмеження безпеки:
- Не надсилати секрети, API-ключі, `.env` вміст.
- Не пропонувати комітити runtime `data/runs/**` у git.

## 0) Output Path + Retention

**Правило**: У репо завжди рівно 1 актуальний DEV REPORT: `docs/DEV_REPORT_LATEST.md` (overwritten).

Дозволені файли:
- `docs/DEV_REPORT_LATEST.md` - єдиний DEV REPORT що трекається в git
- `docs/DEV_REPORT_CANONICAL_UA.md` - цей документ (шаблон формату)

Заборонені файли (автоматичний FAIL в check_repo_safety.py):
- `docs/DEV_REPORT_YYYY-MM-DD_v*.md` або будь-які версійні DEV_REPORT файли
- Кілька DEV_REPORT файлів одночасно (bloat)

Provenance в DEV_REPORT_LATEST.md:
- `timestamp_utc` копіюється з `run_summary_latest.run_context.run_timestamp` (UTC)
- `code_identity.primary` копіюється з `run_summary_latest.run_context.code_identity`
- НЕ використовувати локальний час або runDir timestamp

## 0.1) UTF-8 Viewing

PowerShell може показувати mojibake для українського тексту. Це **не пошкодження файлу**, а проблема кодування консолі.

**Canonical viewing commands:**
```powershell
# Перегляд з правильним кодуванням (PowerShell 5.1)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Get-Content docs/DEV_REPORT_LATEST.md -Encoding UTF8

# Або через chcp
chcp 65001 | Out-Null; Get-Content docs/DEV_REPORT_LATEST.md

# VS Code (рекомендовано для review)
code docs/DEV_REPORT_LATEST.md
```

**Перевірка чи є mojibake в файлі:**
```powershell
# Якщо це поверне 0 матчів - файл в порядку
Get-ChildItem docs/*.md | ForEach-Object { 
  $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
  $text = [System.Text.Encoding]::UTF8.GetString($bytes)
  if ($text -match 'Р|С|в') { Write-Host "POSSIBLE_MOJIBAKE: $($_.Name)" }
}
```

## 0.2) Session Completion Gate (MANDATORY)

**Rule**: Кожен DEV REPORT **обов'язково** містить session completion інформацію.

**Обов'язкові поля:**
```md
## Session Completion
session_goal: <Коротке формулювання мети сесії (з Roadmap або останнього audit)>
goal_status: <REACHED|BLOCKED|IN_PROGRESS>
close_allowed: <true|false>
remaining_blockers: <список або "none">
evidence_session_run_dirs: <список runDirs створених у цій сесії>
primary_blocker_of_session: <головний blocker який вирішує ця сесія>
blocker_status_before: <ACTIVE|UNRESOLVED>
blocker_status_after: <RESOLVED|BLOCKED|IN_PROGRESS>
docs_reread_confirmed: <true|false>
```

**Семантика полів:**
| Field | Description |
|-------|-------------|
| `session_goal` | Одне речення: що має бути досягнуто в цій сесії |
| `goal_status` | `REACHED` = мета досягнута з evidence; `BLOCKED` = explicit blocker; `IN_PROGRESS` = робота триває |
| `close_allowed` | `true` тільки якщо `goal_status=REACHED` або `goal_status=BLOCKED` з документованим blocker |
| `remaining_blockers` | Якщо `IN_PROGRESS` або `BLOCKED`, перерахувати що залишилось |
| `evidence_session_run_dirs` | runDirs **із поточної сесії** (не з попередніх), які підтверджують claims |
| `primary_blocker_of_session` | Головний project blocker цієї сесії (один!) |
| `blocker_status_before` | Статус primary blocker на початку сесії |
| `blocker_status_after` | Статус на кінець: `RESOLVED` (з evidence) або `BLOCKED` (з причиною) |
| `docs_reread_confirmed` | Agent підтвердив перечитання AGENTS.md, Roadmap.md, Status, WORKFLOW.md |

**Контракт:**
- `goal_status=REACHED` вимагає: `evidence_session_run_dirs` містить fresh runDirs з поточного patch set
- `goal_status=BLOCKED` вимагає: `remaining_blockers` не порожній, описує конкретний blocker
- `goal_status=IN_PROGRESS` забороняє: completion language ("All done", "Session complete")
- `close_allowed=true` дозволений ТІЛЬКИ якщо `goal_status != IN_PROGRESS`
- `close_allowed=true` вимагає: `blocker_status_after` = `RESOLVED` або `BLOCKED`
- `blocker_status_after=RESOLVED` вимагає: `evidence_session_run_dirs` підтверджує fix
- `blocker_status_after=IN_PROGRESS` забороняє: `close_allowed=true`
- `docs_reread_confirmed=true` обов'язково для кожної сесії

**Заборонені патерни:**
- Оголошення "session complete" без `goal_status=REACHED`
- Використання runDirs з попередніх сесій як "fresh evidence"
- Порожній `remaining_blockers` при `goal_status=BLOCKED`
- `close_allowed=true` з `blocker_status_after=IN_PROGRESS`
- Закриття сесії без зміни `blocker_status_before` → `blocker_status_after`
- `docs_reread_confirmed=false` при спробі закрити сесію

## 1) Вхідні дані, які обов'язково додаються до звіту

Rolling (канонічний operational інтерфейс):
- `data/runs/_rolling/_latest.json`
- `data/runs/_rolling/run_summary_latest.json`
- `data/runs/_rolling/m4_stability_agg.json`

Якщо `mode=ONLINE`, додати runDir bundle (мінімум):
- `data/runs/<run_id>/reports/`
- `data/runs/<run_id>/snapshots/` (якщо існує)

## 2) Provenance

Канонічний provenance:
- `run_context.run_timestamp` (ISO-8601) - primary identifier для конкретного run
- `run_context.code_identity` - `ts:<ISO-8601>` (SHA-free, детермінований формат рядка)
- `run_context.code_sha` / `run_context.evidence_sha` - `null` (deprecated)

Rolling агрегатор:
- використовує `runs_since_timestamp` (не `runs_since_sha`)
- не має містити `runs_by_code_sha` (deprecated), заміна: `runs_by_date`

## 3) DEV REPORT (шаблон, копіпаст 1-в-1)

```md
# DEV REPORT

## 0) Meta
timestamp_utc: <YYYY-MM-DDTHH:MM:SSZ>
run_id: <run_id або data/runs/<run_id>>
mode: <OFFLINE|ONLINE>
artifact_mode: rolling
config: <yaml + profile, без секретів>
code_identity:
  primary: <ts:<ISO-8601>>
  dirty: <true/false + коротко що саме>
  desc: <1 рядок, що змінено>

## 1) Scope (що і навіщо)
goal (Roadmap пункт): <точне посилання на Roadmap.md секцію/пункт>
change_summary:
  - <до 10 булетів>
touched_files:
  - <список шляхів>

## 2) Commands Executed (лише факти)

**RULE**: Завжди використовуй повний шлях `py -3.11 scripts/...` (не `py -3.11 ci_*.py`).

py -3.11 -m pytest -q: <PASS|FAIL> (duration: <...>)
py -3.11 scripts/ci_full_pipeline.py --mode ci: <PASS|FAIL|NOT RUN> (reason: <...>)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: <PASS|FAIL>
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: <PASS|FAIL|NOT RUN> (reason)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/<DIR>: <PASS|FAIL|NOT RUN> (reason)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/<DIR>/reports
  - data/runs/<DIR>/snapshots

## 4) Key Results (числа з артефактів)

**Де брати метрики:**
- `signals_count` → `run_summary_latest.metrics.signals_count`
- `total_net_usdc` (run) → `run_summary_latest.metrics.total_net_usdc`
- `total_net_usdc` (window) → `m4_stability_agg.quick_stats.total_net_usdc`
- `low_sample_rate` → `m4_stability_agg.quick_stats.low_sample_rate`
- `data_run_rate` → `_latest.data_run_rate` або `m4_stability_agg.quick_stats.data_run_rate`
- `unique_pairs/unique_routes` → `m4_stability_agg.quick_stats.unique_pairs/unique_routes`
- `run_mode` → `run_summary_latest.inputs.run_mode`

```md
latest:
  schema_version: <...>
  run_status: <...>
  agg_status: <...>
  data_run_rate: <...>              # top-level
  low_sample_rate: <...>            # from quick_stats
run_summary_latest:
  schema_version: <...>
  status: <...>
  metrics.signals_count: <...>
  metrics.total_net_usdc: <...>
  profit_status: <...>
  drift_status: <...>
  quality_status: <...> | quality_reasons: <...>
  run_timestamp: <...>
  code_identity: <...>
  inputs.run_mode: <...>            # REGISTRY_REAL or FIXTURE_OFFLINE
stability_agg:
  schema_version: <...>
  agg_status: <...>
  agg_reasons: <...comma list...>
  runs_since_timestamp.runs_count: <...>
  runs_since_timestamp.data_runs_count: <...>
  quick_stats.unique_pairs: <...>
  quick_stats.unique_routes: <...>
  runs_by_date: <...>
```

## 4.1) Theoretical Net Profit (cost-aware reporting)

**RULE**: Кожен report із сигналами (signals_count > 0) **обов'язково** повинен показувати **теоретичний net profit** з повною розбивкою витрат і позначати, що це **paper/simulated**, а не real execution.

**Формат обов'язкового блоку:**
```md
theoretical_net_profit:
  mode: paper_simulated
  gross_pnl_usdc: <...>
  cost_breakdown:
    gas_usd: <...>
    slippage_bps: <...>
    slippage_usd: <...>
    l1_cost_usd: <...>           # для L2 chains (zkSync, Linea, Scroll, Mantle)
    total_cost_usd: <...>        # = gas_usd + slippage_usd + l1_cost_usd
  net_pnl_usdc: <...>            # = gross_pnl_usdc - total_cost_usd
  disclaimer: "Theoretical profit based on simulated execution. No real trades were executed."
```

**Контракт:**
- `total_cost_usd = gas_usd + slippage_usd + l1_cost_usd` (invariant)
- `net_pnl_usdc = gross_pnl_usdc - total_cost_usd`
- `mode` завжди `paper_simulated` до milestone M6 (real execution)
- Для L1 chains (mainnet, bnb): `l1_cost_usd = 0.0`
- Для L2 chains: `l1_cost_usd` обчислюється з `l1_data_gas_units * l1_gas_price_gwei * 1e-9 * eth_price_usd`

**Де брати дані:**
- `gross_pnl_usdc` → `truth_report.execution_pnl.gross_pnl_usdc`
- `gas_usd` → `truth_report.execution_pnl.cost_model_components.gas_usd`
- `slippage_usd` → `truth_report.execution_pnl.cost_model_components.slippage_usd`
- `l1_cost_usd` → `truth_report.execution_pnl.cost_model_components.l1_cost_usd`
- `total_cost_usd` → `truth_report.execution_pnl.cost_model_components.total_cost_usd`
- `net_pnl_usdc` → `truth_report.execution_pnl.net_pnl_usdc`

## 5) Contract Checks (коротко)
status/reasons consistency: <OK|NOT OK> + 1 рядок
rolling discipline (3 files only): <OK|NOT OK>
v2.x provenance contract: <OK|NOT OK> (run_timestamp, code_identity, no runs_by_code_sha)
runtime artifacts not committed: <OK|NOT OK>

## 6) Blocker Classification (обов'язково для multi-chain)

**ВАЖЛИВО**: Infra gate PASS ≠ run_summary PASS. Розрізняй три рівні:

| Blocker Type | Level | Meaning |
|--------------|-------|---------|
| `CODE` | LOW/MED/HIGH | Tests/CI/safety failing, code bugs blocking execution |
| `DATA_COLLECTION` | LOW/MED/HIGH | Runtime disables, quarantines, thin pool coverage |
| `MARKET_WINDOW` | LOW/MED/HIGH | No usable spreads in current market conditions |

**Формат reporting:**
```
code_blocker: LOW (pytest PASS, CI green, safety PASS)
data_collection_blocker: MEDIUM (N pools quarantined, M% quotes rejected)
market_window_blocker: HIGH (K/5 chains have NO_DATA despite quotes_fetched>0)
```

**Semantics:**
- `infra_gate: PASS` = quotes_fetched > 0, artifacts schema OK, no structural errors
- `run_summary.status: NO_DATA` = signals_count == 0 (no spreads above min_spread_bps)
- `run_summary.status: FAIL*` = signals exist but all rejected/excluded
- `run_summary.status: PASS` = at least 1 usable/profitable signal

**Contract**: Include blocker classification in every multi-chain status update.

## 6.1) Blockers / Risks (max 5)
- <blocker 1>
- ...

## 7) Lead's Previous 10 Steps: Execution Map
step_01: <DONE|PARTIAL|NO> evidence: <файл/метрика/лог>
...
step_10: <DONE|PARTIAL|NO> evidence: <...>

## 8) What I need from Lead now (1-3 пункти)
question_1: <...>
request_1: <...>
```

## 4) Перед відправкою звіту (обов'язково)

- Перечитай цей документ: `docs/DEV_REPORT_CANONICAL_UA.md`.
- Звіт має бути українською мовою.
- Уникай “інтерпретацій”: у Key Results вставляй цифри/статуси з артефактів.
- Звіт має бути в одному вікні, в одному полі без розділення на окремі секції для зручного копіпасту для рев'юера.
