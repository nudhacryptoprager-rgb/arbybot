# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-28T09:12:10Z
run_id: data/runs/_rolling (rolling artifact; M9 Session 11 — discovery wiring)
mode: OFFLINE
artifact_mode: rolling
config: config/exotic_base_anchor.yaml
code_identity:
  primary: ts:2026-05-28T09:12:10Z
  dirty: true
  desc: Session 11 — Curve factory discovery wired into bridge Stage 5a; _CHAIN_ANCHORS → config; 7 new tests; 6146 unit tests pass

## 1) Scope
goal (Roadmap): M9 — динамічний пул-юніверс: Curve pools входять у production bridge через factory.pool_list() enumeration, а не через manually curated config list
goal_status: BLOCKED
change_summary:
  - `scripts/m9_curve_discovery.py`: видалено hardcoded `_CHAIN_ANCHORS`; factory address та anchor_tokens тепер читаються з `config/adapter_metadata.yaml` через `load_adapter_metadata()`; додано `_RPC_CONFIG` для fallback RPC URLs
  - `config/adapter_metadata.yaml`: додано `factory_stable_ng: 0xd2002373...` та `anchor_tokens: {addr: symbol}` під `curve.base` — trust anchors для discovery скрипта
  - `m9/graph_arb/adapter_metadata.py`: `AdapterMetadata` отримав поля `curve_factory_stable_ng` і `curve_anchor_tokens`; loader їх парсить
  - `m9/graph_arb/bridge_builder.py` Stage 5a: нова функція `_load_curve_discovery_routes()`; discovery routes вливаються у `active_routes` без seed-флага; новий параметр `curve_discovery_path`; нова метрика `curve_discovery_count` у `bridge_source_metrics`
  - Semantic fix: `_build_static_curve_routes()` тепер `factory_verified=False` + `metadata_seeded=True` (раніше помилково `factory_verified=True`)
  - `tests/unit/test_m9_bridge_builder.py`: `_build()` ізольований від реального discovery artifact; новий клас `TestCurveDiscoveryContract` (7 тестів)
  - `docs/status/Status_M9.md`: оновлено до `CODE_VALIDATED__DISCOVERY_WIRED`
touched_files:
  - scripts/m9_curve_discovery.py
  - config/adapter_metadata.yaml
  - m9/graph_arb/adapter_metadata.py
  - m9/graph_arb/bridge_builder.py
  - tests/unit/test_m9_bridge_builder.py
  - docs/status/Status_M9.md

## 2) Commands Executed

py -3.11 -m pytest -q: PASS (6146 passed, 6 skipped, 1 warning in 155.05s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: NOT RUN (offline session; code-only changes)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: NOT RUN
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: NOT RUN (offline session)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit: NOT RUN
py -3.11 scripts/m9_bridge_build.py --config config/exotic_base_anchor.yaml: OK (graph_ready_total=126, curve_discovery_count=0, metadata_seeded_count=0)
py -3.11 scripts/check_repo_safety.py: PASS (2 warnings — Status_M8.md bloat, rolling chain purity OK)

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/m9_bridge_inventory_latest.json (generated_at_utc: 2026-05-28T09:12:10Z)
  - data/runs/_rolling/run_summary_latest.json — ABSENT (M4/online run not performed in this session)
  - data/runs/_rolling/m4_stability_agg.json — ABSENT
  - data/runs/_rolling/m9_curve_discovery_latest.json — ABSENT (discovery not yet run against real RPC)

## 4) Key Results

bridge_inventory_latest:
  schema_version: m9_bridge_inventory.1
  generated_at_utc: 2026-05-28T09:12:10Z
  active_routes_total: 126
  graph_ready_total: 126
  factory_verified_count: 119
  depth_ok_count: 117
  metadata_seeded_count: 0   [include_config_seed=False — production mode]
  curve_discovery_count: 0   [artifact absent — discovery not yet run vs RPC]
  m8_stale: True             [M8 sniper artifact >4h old]
  m8_1_stale: False

unit_tests:
  total_passed: 6146          [+7 vs Session 10 / +12 vs Session 9]
  skipped: 6
  new_tests_session_11: 7    [TestCurveDiscoveryContract class]
  status: PASS

check_repo_safety: PASS (2 warnings — Status_M8.md bloat незмінний, не критично)

## 5) Contract Checks
status/reasons consistency: OK — bridge_source_metrics поля узгоджені; curve_discovery_count=0 коректно при відсутньому артефакті
rolling discipline (3 canonical files): PARTIAL — run_summary_latest.json та m4_stability_agg.json відсутні (M4/online run не проводився в цій сесії); m9_bridge_inventory_latest.json OK
v2.x provenance contract: OK — run_timestamp присутній, code_sha=null (deprecated), runs_since_timestamp не runs_since_sha
runtime artifacts not committed: OK — data/runs/** не в git

## 6) Blocker Classification
code_blocker: LOW — pytest PASS (6146/6146), safety PASS, bridge build OK
data_collection_blocker: MEDIUM — m9_curve_discovery_latest.json не згенерований (потрібен BASE_RPC + запуск discovery скрипта); M8 sniper артефакт stale (>4h)
market_window_blocker: UNKNOWN — M4/M9 online run не проводився в цій сесії; останній відомий результат: positive_cycles=5 (dRPC 429s, qsr~low)

### Blockers / Risks (max 5)
1. `m9_curve_discovery_latest.json` відсутній — discovery скрипт не запускався vs реального RPC; `curve_discovery_count=0` поки немає живих Curve pools у bridge production path
2. M8 sniper artifact stale (>4h) — `m8_stale=True`; нові M8 пули не надходять у bridge до refresh
3. dRPC 429 throttling — qsr~0.20 на попередніх online runs; для production потрібен Alchemy або інший RPC без rate limit
4. `min_tvl_usd` у discovery скрипті задекларований, але on-chain TVL query не реалізований (інформаційно лише)
5. Balancer discovery через Vault `PoolRegistered` events не реалізований (наступний великий блок)

## 7) GPT Lead's Previous Steps: Execution Map
step_01: DONE — `factory_verified=False` + `metadata_seeded=True` на seed routes (bridge_builder.py). Evidence: TestCurveDiscoveryContract::test_seed_routes_have_factory_verified_false PASS
step_02: DONE — `_CHAIN_ANCHORS` видалено з m9_curve_discovery.py; factory_stable_ng + anchor_tokens → config/adapter_metadata.yaml. Evidence: adapter_metadata.py loader парсить нові поля; 6146 тестів pass
step_03: DONE — `_load_curve_discovery_routes()` додано; Stage 5a вливає discovery routes у production bridge. Evidence: TestCurveDiscoveryContract::test_discovery_routes_enter_production_mode PASS
step_04: DONE — `curve_discovery_count` в bridge_source_metrics. Evidence: test_curve_discovery_count_always_in_metrics PASS; bridge artifact має поле=0
step_05: DONE — `_build()` в TestConfigSeedContract ізольований через `curve_discovery_path=nodisc.json`. Evidence: TestConfigSeedContract всі 5 тестів PASS
step_06: DONE — 7 нових тестів TestCurveDiscoveryContract. Evidence: py -3.11 -m pytest TestCurveDiscoveryContract — 7 passed
step_07: DONE — Status_M9.md оновлено → CODE_VALIDATED__DISCOVERY_WIRED. Evidence: docs/status/Status_M9.md
step_08: NO — `m9_curve_discovery.py` не запускався vs реального RPC (потребує BASE_RPC env)
step_09: NO — M4/M9 online scan не проводився в цій сесії
step_10: NO — bridge з live Curve pools не перевірявся (залежить від step_08)

## 8) Що потрібно від Lead зараз
question_1: Підтвердити, чи вважати Session 11 goal=REACHED за умови що code+tests verified, але online artifact (m9_curve_discovery_latest.json) ще не згенерований — чи потрібно обов'язково запустити discovery скрипт vs RPC?
request_1: Якщо BASE_RPC доступний — запустити: `$env:BASE_RPC="https://..."; py -3.11 scripts/m9_curve_discovery.py --chain base` і передати лог (щоб bridge показав curve_discovery_count>0)
request_2: Визначити наступний крок: (a) запустити discovery vs RPC → wire live Curve pools, або (b) перейти до Balancer discovery, або (c) перейти до M9 online run для proof positive_cycles>0

## Session Completion
session_goal: Завершити wiring Curve factory discovery у bridge Stage 5a, перенести _CHAIN_ANCHORS у config, виправити factory_verified semantic на seed routes, додати unit tests для discovery contract
goal_status: REACHED
close_allowed: true
remaining_blockers: m9_curve_discovery_latest.json не згенерований (потребує BASE_RPC + ручний запуск) — але це runtime залежність, не code blocker
evidence_session_run_dirs: data/runs/_rolling (m9_bridge_inventory_latest.json @ 2026-05-28T09:12:10Z); pytest 6146 passed @ 155.05s
primary_blocker_of_session: discovery contract gap — _CHAIN_ANCHORS hardcoded, factory discovery не wired у bridge production path
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

