# ЗВІТ РОЗРОБКИ

## 0) Метадані
timestamp_utc: 2026-05-14T06:56:44Z  
run_id: data/runs/_rolling/new_pool_sniper_latest.json  
mode: ONLINE_CONTROL + OFFLINE_CI  
artifact_mode: rolling  
config: config/new_pool_factories.yaml, M8 listener factory на Base  
repo_revision_reviewed: split/code / a10d2bc27dcb485ae89bd028852ee1c6415366bb  
code_identity:
  primary: runtime provenance для поточного M8 контрольного артефакту базується на rolling timestamp
  dirty: true - змінено M8 factory config, parser listener, unit-тести та цей звіт
  desc: Aerodrome ve33 factory переведено на layout PoolCreated; звіт переписано українською без передчасного закриття Phase 1

## 1) Обсяг роботи
goal (Roadmap пункт): M8 перехід до new-pool sniping, Phase 1 listener-only foundation.  

change_summary:
- Поточний DEV report переписано українською мовою.
- Прибрано некоректне формулювання "M8 Phase 1 Complete / Steps 1-10 Done".
- Зафіксовано фактичний стан: ядро listener працює, але повне закриття Phase 1 ще не дозволене.
- Виправлення Aerodrome factory доведене на рівні parser/config/test та коротким live-пробом.
- Multi-factory runtime-soak після виправлення ще потрібен як доказ для чесного закриття Phase 1.
- Поточний rolling artifact є контрольним `EMPTY`, а не доказом multi-factory live activity.
- Стандартний CI без винятку все ще блокується наявним `intent.txt` tier limit.

touched_files:
- config/new_pool_factories.yaml
- discovery/new_pool_listener.py
- tests/unit/test_m8_sniper_listener.py
- docs/DEV_REPORT_LATEST.md

## Завершення сесії
session_goal: привести поточний DEV report до української мови та вирівняти його з фактичним M8 статусом без передчасного закриття Phase 1  
goal_status: IN_PROGRESS  
close_allowed: false  
remaining_blockers: M8_RUNTIME_SOAK_AFTER_AERODROME_FACTORY_FIX_PENDING; PLAIN_CI_BLOCKED_BY_INTENT_TIER_LIMIT  
evidence_session_run_dirs: data/runs/ci_m5_gate_offline_20260514_090223; data/runs/ci_m4_gate_offline_20260514_070223  
primary_blocker_of_session: M8_NON_UNISWAP_FACTORY_COVERAGE_NOT_VERIFIED  
blocker_status_before: PARTIAL  
blocker_status_after: SELF_TEST_REACHED_RUNTIME_SOAK_PENDING  
docs_reread_confirmed: true  

## 2) Виконані команди
py -3.11 -m pytest tests/unit/test_m8_sniper_listener.py tests/unit/test_m8_sniper_funnel.py tests/unit/test_m8_sniper_artifacts.py tests/unit/test_m8_sniper_factory_probe.py -q: PASS, 203 passed  
py -3.11 -m pytest tests/unit -q: PASS, 5382 passed, 6 skipped, 1 warning  
py -3.11 scripts/check_repo_safety.py: FAIL, наявний INTENT_TIER_LIMIT, intent.txt має 77 pairs проти baseline 64  
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: PASS, 1 warning for Status_M7.md bloat  
py -3.11 scripts/ci_full_pipeline.py --mode ci: FAIL, блокується тим самим наявним INTENT_TIER_LIMIT  
py -3.11 scripts/ci_full_pipeline.py --mode ci --allow-intent-edit: PASS, усі обов'язкові offline gates пройдено  
py -3.11 scripts/sniper_factory_probe.py --chain base --from-block 45925000 --to-block 45926000 --rpc-url https://mainnet.base.org: PASS для Aerodrome у цьому діапазоні, raw_logs=1, parse_ok=1  
ARBY_SNIPER_ENABLE=1 py -3.11 scripts/sniper_smoke_run.py --chain base --duration-minutes 0 --poll-interval-s 1 --blocks-back 1 --rpc-url https://mainnet.base.org: self_test PASS для всіх налаштованих factories; поточний poll створив EMPTY artifact  

## 3) Використані артефакти
rolling:
- data/runs/_rolling/new_pool_sniper_latest.json

rolling_absent_in_workspace:
- data/runs/_rolling/_latest.json
- data/runs/_rolling/run_summary_latest.json
- data/runs/_rolling/m4_stability_agg.json

run_dir_bundle:
- data/runs/ci_m5_gate_offline_20260514_090223
- data/runs/ci_m4_gate_offline_20260514_070223

runtime_policy:
- Runtime artifacts під data/runs/** є лише evidence і не мають комітитися.

## 4) Ключові результати
latest_m8_sniper:
  schema_family: m8_sniper
  schema_revision: phase1.2
  generated_at_utc: 2026-05-14T06:56:44Z
  status: EMPTY
  reasons: NO_EVENTS_YET
  pool_creation_events_seen: 0
  parse_ok: 0
  parse_failed: 0
  snipe_candidates_total: 0
  rpc_calls_made: 4
  rpc_errors: 0
  cycles_completed: 1

factory_current_control:
- uniswap_v3: raw_logs=0, parse_ok=0, candidates=0 у короткому контрольному poll
- aerodrome_slipstream: raw_logs=0, parse_ok=0, candidates=0 у короткому контрольному poll
- aerodrome: raw_logs=0, parse_ok=0, candidates=0 у короткому контрольному poll
- pancakeswap_v3: raw_logs=0, parse_ok=0, candidates=0 у короткому контрольному poll

factory_fix_evidence:
- Старий Aerodrome ve33 topic PairCreated був неправильним для фактичної factory activity на Base.
- Правильна подія Aerodrome: PoolCreated(address,address,bool,address,uint256).
- Правильний layout: token0=topics[1], token1=topics[2], stable=topics[3], pool=data word 0.
- Історичний live-проб по Base blocks 45925000-45926000 знайшов Aerodrome raw_logs=1 і parse_ok=1.
- Smoke self_test спарсив sample logs для uniswap_v3, aerodrome_slipstream, aerodrome і pancakeswap_v3.

phase_status:
- Status_M8.md залишається source of truth: goal_status=IN_PROGRESS.
- phase1_status дорівнює REACHED_CORE_LISTENER, а не повному закриттю Phase 1.
- multi_factory_coverage_status був PARTIAL і має змінюватися лише після fresh runtime soak evidence.
- pipeline_ready=false і production_profit_ready=false залишаються коректними.
- close_allowed=false залишається коректним.

## 4.1) Теоретичний net profit
theoretical_net_profit:
  mode: not_applicable_for_m8_phase1_listener
  gross_pnl_usdc: null
  cost_breakdown:
    gas_usd: null
    slippage_bps: null
    slippage_usd: null
    l1_cost_usd: null
    total_cost_usd: null
  net_pnl_usdc: null
  disclaimer: "M8 Phase 1 є listener-only. Реальних угод не виконувалося, реальний прибуток не заявляється."

## 5) Перевірки контрактів
status/reasons consistency: OK для поточного artifact, EMPTY з NO_EVENTS_YET є консистентним  
rolling discipline: OK для M8 primary rolling artifact; M4 rolling triplet відсутній у цьому workspace  
provenance contract: OK для M8 report scope, поточний artifact використовує generated_at_utc і rolling path  
runtime artifacts not committed: OK, data/runs/** залишається runtime-only  
docs language: OK, поточний report українською мовою  
completion language: OK, claim про завершення Phase 1 прибрано  

## 6) Класифікація блокерів
code_blocker: MEDIUM - plain CI падає, доки intent tier limit не вирішено або явно не дозволено  
data_collection_blocker: MEDIUM - усі factory parsers проходять self_test, але post-fix long runtime soak ще відсутній  
market_window_blocker: LOW - короткий поточний poll не мав new events; це очікувано і не є доказом failure  
infra_blocker: LOW - public Base RPC достатній для контрольних probes, але для serious soak потрібен archive/stable RPC  
release_blocker: HIGH - Phase 1 не можна закривати, доки runtime artifact не доведе post-fix multi-factory behavior  

## 6.1) Блокери / ризики
- Попередній DEV report завищував готовність M8; це виправлено.
- Status_M8.md ще потребує post-soak update після fresh evidence.
- Поточний rolling artifact є EMPTY і не може підтримувати закриття Phase 1.
- `sniper_factory_probe.py` ще потребує chunked scanning для ширших історичних діапазонів, щоб уникати RPC 413 failures.
- `intent.txt` tier limit треба вирішити до використання strict plain CI як release evidence.

## 7) Карта виконання попередніх 10 кроків тімліда
step_01: DONE evidence: Aerodrome config тепер використовує PoolCreated signature і verified topic0  
step_02: DONE evidence: ve33_pool_created parser додано і покрито тестами  
step_03: DONE evidence: legacy ve33_pair_created parser залишено для compatibility  
step_04: DONE evidence: targeted M8 tests пройдено, 203 passed  
step_05: DONE evidence: full unit suite пройдено, 5382 passed, 6 skipped  
step_06: DONE evidence: Aerodrome historical probe має parse_ok=1 на Base block range 45925000-45926000  
step_07: DONE evidence: smoke self_test пройшов для всіх чотирьох налаштованих factories  
step_08: PARTIAL evidence: поточний rolling artifact є EMPTY після короткого контрольного poll  
step_09: PARTIAL evidence: 4h post-fix runtime soak ще не запущено  
step_10: NO evidence: Status_M8.md не оновлено після post-fix soak, бо soak evidence ще не існує  

## 8) Що потрібно від тімліда зараз
request_1: Запустити 4h M8 soak зі stable Base RPC endpoint перед дозволом будь-якої мови про закриття Phase 1.
request_2: Вирішити або явно прийняти виняток `intent.txt` tier-limit перед використанням plain CI як release gate.
request_3: Після появи fresh soak evidence спочатку оновити Status_M8.md, потім оновити цей report з нового artifact.
