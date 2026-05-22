# M9 Graph Long-Tail Shadow

Цей документ є базовим operational-описом етапу `M9_GRAPH_LONG_TAIL_SHADOW`.

`Roadmap.md` лишається верхньорівневим source of truth. Цей файл деталізує:
- що саме означає консолідація `M8`, `M8_1`, `M9`;
- як ми переходимо до long-tail / exotic token focus;
- які фази, метрики, воронки і контрольні точки є канонічними;
- що дозволено вважати прогресом, а що ні.

## 1) Суть етапу

`M9_GRAPH_LONG_TAIL_SHADOW` — це не ще одна single-pair strategy.

Це перехід до такого режиму:
- discovery широке, а не вузьке;
- inventory verified, а не ручне;
- graph multi-pair, а не “улюблена пара дня”;
- proof будується через repeatable economics, а не через один красивий цикл;
- execution залишається вимкненим, доки shadow lane не доведе topology, economics, risk і simulation.

## 2) Як M8, M8_1 і M7 входять у M9

### M8 — discovery input
`M8` дає:
- new-pool events;
- factory-level pool hints;
- ранні сигнали про нові long-tail / exotic джерела ліквідності.

`M8` не дає:
- proof of profit;
- execution readiness;
- production claim.

### M8_1 — inventory and diagnostics input
`M8_1` дає:
- verified active routes;
- route health;
- quote quality;
- size frontier;
- quarantine / thin-liquidity diagnostics;
- coverage ranking.

`M8_1` не дає:
- standalone strategy proof;
- право повернутися до single-pair gate як primary lane.

### M7 — supporting infra lessons
`M7` дає:
- simulation backend patterns;
- Anvil / local fork lessons;
- provider / WS / supervisor failure modes;
- orderflow diagnostics, які можна reuse.

`M7` не дає:
- актуальну production thesis;
- право змішати old backrun lane з M9 economics.

## 3) Ціль M9

Головна ціль:
- знайти repeatable positive-gross або near-breakeven credible graph cycles у long-tail / exotic inventory;
- відсіяти unsafe tokens і toxic routes ще до execution-thought stage;
- довести, що positive economics переживає full-cycle simulation.

M9 закінчується не “коли cycles_found > 0”.
M9 прогресує тільки тоді, коли проходить повну послідовність:
1. inventory growth;
2. topology proof;
3. economics proof;
4. risk proof;
5. router simulation proof;
6. repeated short-session repeatability.

## 4) Non-goals

- не повертатися до stable-stable як primary profit lane;
- не повертатися до LST pair-lane як primary proof lane;
- не роздувати список пар вручну як substitute for discovery;
- не відкривати real execution;
- не йти в cross-chain як escape-hatch від незакритої same-chain economics проблеми;
- не вважати один lucky cycle доказом стратегії.

## 5) Етапи роботи

### M9.1 — Inventory Consolidation

Що робимо:
- зводимо M8 events, M8_1 active routes і verified gap edges в одну graph inventory model;
- підтримуємо лише verified pools / tokens / routes;
- додаємо зовнішні hints тільки через on-chain verify;
- вводимо health scoring для edges, а не тільки для pools.

Що має вийти:
- inventory регулярно оновлюється без ручного code-sprawl;
- unique pairs і active routes ростуть;
- gap edges підсилюють graph connectivity, а не шум.

Критерії успіху:
- inventory refresh додає нові verified edges;
- quarantine ratio контрольований;
- немає залежності від ручного “разового списку пар”.

### M9.2 — Graph Topology Proof

Що робимо:
- будуємо directed graph з route-level edges;
- запускаємо wide multi-pair sweeps;
- відстежуємо cycles found, quoteability, reject taxonomy, QSR.

Що має вийти:
- cycles дійсно знаходяться;
- QSR достатній для регулярної shadow роботи;
- graph sweep не розвалює provider load.

Критерії успіху:
- `cycles_found > 0`;
- `qsr` проходить робочий поріг;
- topology gate стабільно PASS у коротких прогонах.

### M9.3 — Economics Discovery

Що робимо:
- ранжуємо cycles за gross, net bps, liquidity, cost sensitivity, repeatability;
- дивимося не тільки best cycle, а розподіл;
- порівнюємо wide sweep results між short sessions, а не між окремими випадковими snapshot’ами.

Що має вийти:
- видно, чи economics реально наближається до нуля або в плюс;
- можна відрізнити structural negative market від недостатнього inventory;
- near-breakeven cycles не губляться серед шуму.

Критерії успіху:
- `cycles_positive_gross > 0` або з’являється repeatable near-breakeven frontier;
- best cycle і top percentile distribution покращуються, а не лише один top outlier;
- economics gate перестає бути постійно заблокованим одним і тим самим reason.

### M9.4 — Long-Tail Risk Layer

Що робимо:
- honeypot checks;
- transfer tax detection;
- transfer restriction / blacklist checks;
- liquidity sanity / reserve sanity;
- price-anchor sanity для long-tail tokens;
- quarantine contract для unsafe assets.

Що має вийти:
- risky cycles не доходять до router sim;
- unsafe tokens отримують явний reject reason, а не губляться як generic failure;
- граф залишається широким, але без “отруйних” edges.

Критерії успіху:
- risk verdict є для top cycles;
- risk rejects мають явну taxonomy;
- toxic routes не маскуються під economics failure.

### M9.5 — Router Simulation Shadow

Що робимо:
- проганяємо full-cycle router simulation тільки для credible cycles;
- перевіряємо path direction, leg-by-leg execution feasibility, gas, slippage, token basis;
- відділяємо quote-positive from execution-positive.

Що має вийти:
- видно, чи cycle переживає реальний execution path;
- simulation failures мають зрозумілу taxonomy;
- стає ясно, чи blocker у risk, calldata, gas, slippage, allowance logic або в economics.

Критерії успіху:
- є cycles, для яких `router_sim_passed > 0`;
- принаймні частина positive / near-breakeven cycles не руйнується на simulation stage;
- breakdown повний і придатний для reviewer-а.

### M9.6 — Repeatability and Hold Discipline

Що робимо:
- запускаємо короткі, повторювані graph sweeps;
- перевіряємо, що позитивні або near-breakeven cycles не одиничні;
- не відкриваємо execution, навіть якщо один run красивий.

Що має вийти:
- є повторюваність;
- є стабільна інтерпретація, чому gate PASS або BLOCKED;
- оператор не перескакує до production discussion завчасно.

Критерії успіху:
- positive cycles або simulation-passed cycles з’являються не один раз;
- QSR і provider stability не деградують на wide coverage;
- decision policy лишається дисциплінованою.

## 6) Аспекти підвищеного контролю

### 6.1 Long-tail token safety
Потрібен підвищений контроль над:
- honeypot mechanics;
- transfer-tax tokens;
- blacklist / transfer restriction logic;
- різкими liquidity cliffs;
- deceptive anchors і тонкими пулами, де quote є, але size непридатний.

### 6.2 Provider load and QSR
Потрібен підвищений контроль над:
- paid RPC burst pressure;
- edge-level pruning;
- async quote fanout;
- timeouts / reverts, які розмивають economics картину;
- деградацією wide sweep через інфру, а не через ринок.

### 6.3 Inventory purity
Потрібен підвищений контроль над:
- ручними one-off pair additions;
- stale edges;
- duplicate route families;
- false graph connectivity через неперевірені edges.

### 6.4 Proof discipline
Потрібен підвищений контроль над:
- спокусою оголосити прогрес тільки тому, що cycles_found високий;
- single-cycle overfitting;
- змішування supporting-layers з proof-lane semantics;
- підміною execution proof словами “topology works”.

## 7) Нові канонічні метрики

### Discovery / Inventory
- `verified_tokens_total`
- `verified_pools_total`
- `active_routes_total`
- `gap_edges_total`
- `gap_edges_verified_total`
- `inventory_refresh_yield`
- `quarantine_ratio`
- `route_health_pass_rate`

### Graph / Quote
- `unique_pairs`
- `unique_pools`
- `cycles_found`
- `cycles_quoteable`
- `qsr`
- `quote_rpc_error_rate`
- `quote_revert_rate`
- `best_cycle_net_bps`
- `cycle_net_bps_p50`
- `cycle_net_bps_p90`

### Economics
- `cycles_positive_gross`
- `positive_gross_rate`
- `near_breakeven_cycles_total`
- `cost_sensitivity_score`
- `repeatable_positive_cycles_5m`
- `repeatable_positive_cycles_30m`

### Risk
- `honeypot_reject_total`
- `transfer_tax_reject_total`
- `transfer_restriction_reject_total`
- `liquidity_sanity_reject_total`
- `anchor_missing_reject_total`
- `toxic_route_quarantined_total`

### Simulation
- `router_sim_attempted_total`
- `router_sim_passed_total`
- `router_sim_economic_passed_total`
- `simulation_revert_rate`
- `simulation_timeout_rate`
- `leg_failure_histogram`

## 8) Нова організація воронок

### Funnel A — Discovery to Inventory
`raw hints -> verified tokens -> verified pools -> active routes -> graph-ready edges`

Що вважається хорошим проходом:
- verified edges зростають;
- quarantine не домінує;
- growth не вимагає ручного pair-sprawl.

Що вважається поганим проходом:
- багато hints, але мало verify;
- inventory росте за рахунок шуму;
- active routes не додаються.

### Funnel B — Inventory to Economics
`graph-ready edges -> valid cycles -> quoted cycles -> economically ranked cycles -> positive or near-breakeven candidates`

Що вважається хорошим проходом:
- `cycles_found` не нульовий;
- QSR придатний;
- є хоча б фронтир біля breakeven;
- розподіл cycle economics стає кращим.

Що вважається поганим проходом:
- cycles є, але economics структурно мертва;
- QSR падає зі зростанням inventory;
- top result є outlier, а решта глибоко негативні.

### Funnel C — Economics to Execution Readiness
`credible cycles -> risk-cleared cycles -> router-sim-attempted -> router-sim-passed -> repeated shadow candidates`

Що вважається хорошим проходом:
- risk layer відсікає unsafe assets рано;
- sim запускається на credible subset, а не на все підряд;
- є repeatable simulation-passed candidates.

Що вважається поганим проходом:
- sim never starts;
- sim failures не класифіковані;
- unsafe tokens доходять до terminal stage;
- повторюваності немає.

## 9) Правила прийняття рішень

### Якщо inventory не росте
- не посилювати economics gate;
- спершу повернутися в M8 / M8_1 source layer;
- перевірити gap resolver, event coverage, verify purity.

### Якщо cycles_found є, але QSR падає
- не робити висновок “ринок мертвий”;
- спершу зменшити noise, перевірити provider load і edge pruning.

### Якщо QSR добрий, але `cycles_positive_gross = 0`
- не відкривати simulation by force;
- продовжити inventory expansion і ranking;
- окремо перевірити, чи negative gross структурний, а не наслідок вузького inventory.

### Якщо positive gross з’явився
- не говорити про production;
- спершу risk layer;
- потім full-cycle simulation;
- потім repeated short-session confirmation.

### Якщо positive gross не переживає simulation
- не списувати все на “ринок не той”;
- розкласти blocker по leg failures, gas, slippage, token basis або unsafe token mechanics.

## 10) Що вважається реальним прогресом

Реальний прогрес:
- verified inventory росте;
- graph connectivity стає кращою;
- QSR лишається придатним;
- economics розподіл рухається до нуля або в плюс;
- risk layer не пускає toxic assets далі;
- simulation дає credibility, а не тільки відмови;
- позитивні сигнали повторюються.

Нереальний прогрес:
- один гарний цикл без повторення;
- просто більше cycles_found без economics;
- більше пар без verify;
- більше simulation errors без taxonomy;
- повернення до single-pair storytelling.

## 11) Що має бути під рукою під час роботи

Rolling artifacts:
- `data/runs/_rolling/new_pool_sniper_latest.json`
- `data/runs/_rolling/m8_1_stable_anchor_latest.json`
- `data/runs/_rolling/m9_graph_latest.json`

Inventory artifacts:
- `data/tmp/m8_1_exotic_inventory_latest.json`
- `data/tmp/m9_shadow_inventory_with_gap_edges.json`

Статуси:
- `docs/status/Status_M8.md`
- `docs/status/Status_M8_1.md`
- `docs/status/Status_M9.md`

Стратегічне вирівнювання:
- `docs/CURRENT_STRATEGY.md`
- `Roadmap.md`

## 12) Production policy

До окремого дозволу lead-а і до проходження execution truth gates:
- `execution_enabled = false`
- `kill_switch_active = true`
- `real_execution_allowed = false`

M9 може довести readiness для наступної розмови.
M9 сам по собі не дає права вмикати real money mode.
