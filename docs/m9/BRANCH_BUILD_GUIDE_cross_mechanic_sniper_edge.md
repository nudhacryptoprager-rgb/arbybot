# Branch Build Guide — Cross-Mechanic Sniper Edge

> Призначення: настанова, що регулює побудову поточної гілки `split/code`
> (напрямок Cross-Mechanic Sniper Edge). Це НЕ Roadmap, НЕ Status, НЕ DEV_REPORT.
> Source of truth лишається `Roadmap.md` → `docs/status/Status_M9.md` →
> `docs/m9/M9_GRAPH_LONG_TAIL_SHADOW.md`. Цей файл — executor brief для гілки.
>
> Канонічний план-артефакт сесії:
> `.cursor/plans/cross-mechanic_sniper_edge_35865297.plan.md` (НЕ редагувати).

## 0) Стратегічна теза (підтверджена користувачем)

Edge = **свіжий long-tail токен** з дзеркалами на **різних механіках
ціноутворення** (CLMM vs ve(3,3) vs Curve vs Balancer). Це
information/structural edge, менш покритий MEV через складність крос-механіка
матчингу. **НЕ** latency edge на ліквідних парах.

Рішення, що фіксують архітектуру:
- Крос-механіка = **обидва**: admit будь-яке дзеркало, але крос-механіка має
  вищий `mirror_score`.
- Вікно edge = **невідоме → виміряти спершу** (Фаза 2), не будувати streaming
  наосліп.

Ядро thesis — це **M8 (снайпінг)** + **M8.2 (крос-механіка матчинг)**.
M9 — валідатор existence, не головний актор.

## 1) Що ВЖЕ зроблено в цій гілці (Фаза 1 — DONE)

Реалізовано і покрито тестами (`tests/unit/test_m8_cross_dex_expand.py`,
`tests/unit/test_token_contract_age.py` — 7 passed).

### 1a. Не-CLMM механіки у M8.2 factory resolve
Файл: `m8/discovery/cross_dex_expand.py`
- Прибрано `_FACTORY_RESOLVE_SKIP` (тихий skip).
- Додано `_FACTORY_RESOLVE_PENDING_ADAPTERS = {curve_stable, balancer_stable,
  maverick_v2}` → ці адаптери дають явний reject `ADAPTER_RESOLVE_PENDING`
  (видимий per-dex у `reject_reason_histogram`), а не зникають мовчки.
- Додано гілку `_resolve_via_factory` для `aerodrome_v2_stable` (solidly stable
  curve, `getPool(t0,t1,stable=True)`). `ve33` (volatile+stable) вже працював.

### 1b. Крос-механіка score
Файл: `m8/discovery/cross_dex_expand.py`
- Хелпер `_pricing_model_for_dex(dex_id)` перевикористовує
  `m9.graph_arb.cost_model.adapter_pricing_model`.
- Кожен admitted route несе: `pricing_model`, `mirror_pricing_models` (list),
  `cross_mechanic` (bool), `mirror_score` (= кількість distinct моделей).
- `summary` несе: `cross_mechanic_tokens`, `same_mechanic_tokens`,
  `pricing_model_pairs` (histogram типу `clmm_ticks+solidly_volatile_xyk`).

### 1c. Token-freshness signal (annotation, не фільтр)
Файл: `m8/discovery/cross_dex_expand.py`
- `_token_freshness(exotic_addr)` за `registry.tokens[*].first_seen_ts` і вікном
  `m8_2_fresh_token_window_s` (default 6h, RPC-free).
- Route несе `token_is_fresh`, `token_is_known_registry`.
- `summary.fresh_token_admitted`, `summary.fresh_token_window_s`.
- On-chain `m8/discovery/token_contract_age.py` лишається для сильнішого probe
  (creation block), але як admission signal поки використовується дешевий
  registry-сигнал.

### 1d. Config-bound registry venues (review fix)
Файл: `m8/discovery/cross_dex_expand.py`
- Registry venues більше не можуть тихо розширити universe поза `config/exotic_base_anchor.yaml`.
- `_registry_pools_for_pair(...)` приймає `allowed_dex_ids` із `discovery_dexes_from_config()`.
- Якщо registry містить venue на DEX, який не enabled for discovery у поточному config, цей venue ігнорується.
- Це захищає Phase 1 метрики `dexes_checked`, `admitted_by_dex`, `cross_mechanic_tokens` від фальшивого coverage.

Acceptance Фази 1: PASS (`py -3.11 -m pytest tests/unit/test_m8_cross_dex_expand.py tests/unit/test_token_contract_age.py -q` = 10 passed).

## 2) Що ЗАЛИШИЛОСЯ зробити (настанови для наступного executor)

> Виконувати строго в порядку фаз. Не вмикати real execution. Канонічний
> `data/runs/_rolling/m9_graph_latest.json` (verified, qsr≈0.89) НЕ перезаписувати —
> existence-робота йде лише в `data/tmp/*shadow*`.

### Фаза 2 — Телеметрія часу життя спреду (визначає Фазу 4)
Мета: дати дані для рішення batch vs streaming БЕЗ припущень.

2a. `m9/graph_arb/runner.py`: для bridge-shadow run (детектиться через
`bridge_shadow_run`, вже є в коді), на кожному sweep збирати per-cycle
`(timestamp, gross_bps)` для маршрутів з `source` що починається на `m8_`.

2b. `m9/graph_arb/artifacts.py`: у блок `bridge_shadow` додати `spread_lifetime`:
для циклів з `gross_bps>0` хоч раз — скільки sweeps/секунд спред лишався
позитивним до зведення (first_positive → last_positive).

2c. Окремий артефакт `data/tmp/m9_spread_lifetime_latest.json`:
`{token, mirror_pair, first_positive_ts, last_positive_ts, lifetime_s,
peak_gross_bps, mechanic_pair}`. Це runtime-артефакт під `data/` — НЕ комітити.

Acceptance: bridge-shadow soak пише `spread_lifetime` і
`m9_spread_lifetime_latest.json`; видно медіану `lifetime_s`.

### Фаза 3 — Existence-soak на правильному універсумі
3a. Канонізувати bridge-shadow як existence-lane: M9 по
`data/runs/_rolling/m9_bridge_inventory_latest.json` (НЕ verified), cycle lengths
`2,3,4` (крос-механіка 2-leg = найчистіший edge), артефакт
`data/tmp/m9_graph_bridge_shadow_latest.json`.

Команда (canonical для гілки):
```
$env:ARBY_M9_CYCLE_LENGTHS='2,3,4'
$env:ARBY_M9_MAX_CYCLES_PER_LENGTH='2:8,3:20,4:6'
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 -u -m m9.graph_arb.runner `
  --config config/exotic_base_anchor.yaml `
  --inventory data/runs/_rolling/m9_bridge_inventory_latest.json `
  --duration-minutes 10 --productive-lane --require-factory-verified `
  --quote-backend raw_http --quote-workers 1 --max-cycles-per-sweep 20 `
  --artifact-path data/tmp/m9_graph_bridge_shadow_latest.json
```

Метрики успіху Фази 3 (existence, НЕ profit claim):
- `cycles_with_m8_pool > 0`
- `cross_mechanic_cycles > 0` (нова метрика — додати в M9 на основі route
  `cross_mechanic` прапора)
- хоч один `gross_bps > 0` на крос-механіка парі.

3b. Honeypot/tax gate перед будь-яким positive claim. Свіжий long-tail = високий
rug/honeypot ризик; `QUOTE_ZERO_OUTPUT` часто = honeypot, не порожній пул.
Перевірити stub `monitoring/sniper_honeypot.py`; для кандидатів додати
обов'язковий honeypot/transfer-tax probe (eth_call sell-side) перед тим, як
рахувати їх existence-evidence.

### Фаза 4 — Рішення batch vs streaming (ТІЛЬКИ після даних Фази 2)
- `lifetime_s` медіана = хвилини → batch достатній; додати лише M8.2 у
  `scripts/m9_rolling_orchestrator.py` (зараз поза циклом).
- `lifetime_s` = секунди → спроектувати точковий hot-path: WS new-pool event →
  миттєвий mirror-resolve → точковий M9 quote цього токена (без перебудови
  всього графа).
- НЕ комітити архітектуру streaming до цього рішення.

### Quick win (незалежно від фаз)
Додати `scripts/m8_cross_dex_expand.py` у цикл
`scripts/m9_rolling_orchestrator.py` — зараз expansion поза orchestrator, через
що `graph_ready_from_expansion` тихо падає. Справжній баг конвеєра.

## 3) Гейти і політика гілки
- Канонічний `m9_graph_latest.json` НЕ чіпати.
- Real execution off; це existence-research, не execution unlock.
- Після кожної серії змін: `py -3.11 -m pytest tests/unit -q`,
  `py -3.11 scripts/check_repo_safety.py`.
- Status оновлювати лише з fresh runtime evidence тієї ж сесії.
- Не комітити runtime-артефакти під `data/runs/**`, `data/tmp/**`.

## 4) Що НЕ робимо (свідомо знято)
- НЕ йдемо в ліквідні пари (cbETH/wstETH/стабільні) — суперечить тезі,
  latency-вичищене поле.
- НЕ будуємо streaming наосліп — спершу виміряти вікно (Фаза 2).
- НЕ вмикаємо token-age як hard-reject — поки лише annotation.
