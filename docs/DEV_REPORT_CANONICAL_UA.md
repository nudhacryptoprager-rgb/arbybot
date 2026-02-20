# DEV REPORT (Канонічний Формат, UA)

Цей документ визначає єдиний формат звіту від агента-розробника для проєкту ARBY3 / arbybot.

Пріоритет source-of-truth:
1) `Roadmap.md`
2) `docs/status/Status_M4.md`
3) rolling артефакти в `data/runs/_rolling/` і runDir bundle в `data/runs/<run_id>/...`

Обмеження безпеки:
- Не надсилати секрети, API-ключі, `.env` вміст.
- Не пропонувати комітити runtime `data/runs/**` у git.

## 0) Output Path + Retention (v2.3.4)

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

## 1) Вхідні дані, які обов'язково додаються до звіту

Rolling (канонічний operational інтерфейс):
- `data/runs/_rolling/_latest.json`
- `data/runs/_rolling/run_summary_latest.json`
- `data/runs/_rolling/m4_stability_agg.json`

Якщо `mode=ONLINE`, додати runDir bundle (мінімум):
- `data/runs/<run_id>/reports/`
- `data/runs/<run_id>/snapshots/` (якщо існує)

## 2) Provenance (v2.0+)

Канонічний provenance:
- `run_context.run_timestamp` (ISO-8601) - primary identifier для конкретного run
- `run_context.code_identity` (v2.0.1+) - `ts:<ISO-8601>` (SHA-free, детермінований формат рядка)
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

**RULE**: Завжди використовуй повний шлях `python scripts/...` (не `python ci_*.py`).

python -m pytest -q: <PASS|FAIL> (duration: <...>)
python scripts/ci_full_pipeline.py --mode ci: <PASS|FAIL|NOT RUN> (reason: <...>)
python scripts/ci_m4_execution_gate.py --offline --profile profit --strict: <PASS|FAIL>
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: <PASS|FAIL|NOT RUN> (reason)
python scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/<DIR>: <PASS|FAIL|NOT RUN> (reason)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
run_dir_bundle (ONLINE):
  - data/runs/<DIR>/reports
  - data/runs/<DIR>/snapshots

## 4) Key Results (числа з артефактів)

**Де брати метрики (v2.0.1):**
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

## 5) Contract Checks (коротко)
status/reasons consistency: <OK|NOT OK> + 1 рядок
rolling discipline (3 files only): <OK|NOT OK>
v2.x provenance contract: <OK|NOT OK> (run_timestamp, code_identity, no runs_by_code_sha)
runtime artifacts not committed: <OK|NOT OK>

## 6) Blockers / Risks (max 5)
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

