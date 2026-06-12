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

## 0b) Уточнення тригера: "поява другої механіки", а не "момент 0" (підтверджено)

Аналіз runtime (1605 sniper-кандидатів, `multi_venue_tokens=0`) показав, що
свіжі long-tail токени у момент створення пулу існують лише на **одному** DEX.
Для них cross-DEX/cross-mechanic edge **фізично не існує** (немає дзеркала) —
ні для нас, ні для MEV. Тобто поточний фокус на pool-creation event (момент 0)
ловить найгірший момент для нашого типу edge.

Рішення (фіксує напрямок, не код):
- **Тригер входу = перехід `token_seen_on_dexes: 1 → 2`** (поява другої venue з
  іншою pricing-механікою), а НЕ сам launch. До появи другого пулу edge = 0;
  лізти в atomic launch-sniping (перші мс) свідомо НЕ йдемо — там co-located
  боти, ми гарантовано програємо.
- **Двоступеневий лаг** (це і є вікно, яке шукаємо):
  1. лаг між першим і другим пулом (хвилини–дні) — edge ще не існує;
  2. лаг між появою другого пулу та його індексацією великими searcher-ботами
     (секунди–хвилини) — це наше реальне вікно. Великі боти консервативні до
     свіжих токенів (rug-ризик), а cross-mechanic пари (CLMM↔Curve↔ve33)
     покриті меншою кількістю ботів, ніж CLMM↔CLMM.
- **Тривалість цього вікна = невідома → міряти Фазою 2** (`spread_lifetime`) +
  **Фазою 1.5** (`time_to_second_pool_s`).
  Медіана `lifetime_s` у секундах → ніша зайнята MEV, відступаємо; у хвилинах →
  batch-вхід достатній. Це робить Фазу 2 не "nice-to-have", а тим, що емпірично
  доводить, чи long-tail вікно взагалі існує для нас.

Наслідок для метрик: `multi_venue_tokens=0` на sniper-кандидатах — це НЕ баг і
НЕ провал, а доказ, що ми міряємо у неправильній точці часу (момент 0 замість
переходу 1→2). Фаза 2/3 мають працювати на токенах, які вже отримали другу
venue, а не на свіжих single-DEX launch-токенах.

## 0c) Чому sniper бачить пули "переважно на uniswap_v4" (об'єктивна причина)

Перевірено `config/new_pool_factories.yaml`: WS-лісенер підписаний на **9 фабрик
паралельно**, НЕ лише v4. Тобто домінування v4 — НЕ звуження пошуку в коді, а
структурна властивість ринку Base.

Сконфігуровані фабрики й їхні механіки:

| DEX | adapter_type | Механіка | Статус |
|-----|--------------|----------|--------|
| uniswap_v3 | uniswap_v3 | CLMM (ticks) | execution-ready |
| aerodrome_slipstream | aerodrome_slipstream | CLMM (ticks) | execution-ready |
| aerodrome | ve33 | ve(3,3) volatile+stable | execution-ready |
| pancakeswap_v3 | uniswap_v3 | CLMM | execution-ready |
| uniswap_v4 | uniswap_v4 | CLMM (singleton) | `discovery_only` |
| uniswap_v2 | uniswap_v2 | XYK | `discovery_only`, experimental |
| sushiswap_v2 | uniswap_v2 | XYK | `discovery_only` |
| baseswap_v2 | uniswap_v2 | XYK | `discovery_only` |
| sushiswap_v3 | uniswap_v3 | CLMM | `discovery_only`, experimental |

Заміряна launch-частота (verification-нотатки конфігу, з живого ланцюга):
- uniswap_v4 ≈ **575 подій/год** (дешевий singleton `Initialize`, без деплою
  per-pool контракту → масовий memecoin-launch саме тут);
- uniswap_v2 ≈ 22 події/год;
- решта (v3-форки, ve33) — одиничні події у вузьких діапазонах.

**Висновок:** на момент launch токен майже завжди на ОДНОМУ дексі (v4). ve33 /
Curve / Balancer-stable пули створюються пізніше і рідше (рішення проєкту:
gauge/bribe, peg, weighted-pool), а не на момент launch. Це підтверджує 0b: на
момент 0 другої механіки немає → cross-mechanic edge = 0.

**Окремий баг конфігу (не блокер фокусу, полагодити окремо):** у блоці
`sushiswap_v3` (`config/new_pool_factories.yaml`) `topic0` заданий ДВІЧІ —
правильний v3 `0x783cca1c...`, потім перезаписаний v2-шним `0x0d3648bd...`. YAML
бере останнє → sushiswav_v3 слухає неправильний topic0 і де-факто нічого не
ловить. Виправити на v3 topic0; на домінування v4 це не впливає (sushiswap_v3
дає одиниці подій навіть з правильним topic0).

## 0d) Механіка появи пулів CLMM↔stable↔ve33 (рушії лагу)

Пули на різних механіках з'являються ПОСЛІДОВНО, з різними рушіями — це і
створює вікно:

- **Фаза A (T=0, launch):** один CLMM-пул (на Base — v4), проти WETH.
  Cross-mechanic edge = 0. Максимальний launch-MEV (sniping в мс) → НЕ йдемо.
- **Фаза B (T+хвилини…години):** друге CLMM-дзеркало (uni_v3 /
  aerodrome_slipstream / pancake_v3). Це CLMM↔CLMM — найконкурентніша ніша,
  спред живе секунди, класичні боти чистять швидко → НЕ цільова.
- **Фаза C (T+години…дні):** механіка-відмінний пул — наш edge:
  - ve(3,3) на Aerodrome (рушій: emissions/bribes через gauge-голосування);
  - Curve stable (рушій: токен став peg/LST-подібним, StableSwap-крива);
  - Balancer weighted/stable (рушій: 80/20 LBP чи weighted-pool).
  Між механіками ціна вирівнюється повільніше (різні криві потребують адаптера
  під обидві математики; менше ботів мають готові ve33/Curve/Balancer адаптери
  поряд з CLMM; свіжа ліквідність асиметрична → спред структурний).

## 0e) Production-конвеєр "пошук 2 пулів" (тригер 1→2, не момент 0)

Зсув з event-driven (момент 0) на state-transition-driven (перехід 1→2 venue).
Усі будівельні блоки вже існують — бракує лише тригера й телеметрії, це інкремент:

1. **Watch-list + активний scan, не пасивне очікування.** Sniper (9 фабрик)
   пише новий токен у pending-реєстр (`m8_pending_pairs.json`) з
   `token_seen_on_dexes=1`, `first_seen_ts`. Одразу після першого pool event —
   **fast token-neighborhood scan** по всіх enabled DEX (див. 0g), а не чекати
   batch M8.2. Арб-рішень на момент 0 не приймаємо.
2. **Детектор переходу 1→2.** Сигнал входу = `token_seen_on_dexes: 1→2` І
   `cross_mechanic=true`. M8.2 (`cross_dex_expand`) уже рахує `cross_mechanic` /
   `mirror_score` — викликати ЙОГО на тригер переходу, а не batch-ом по всьому
   реєстру (= quick-win orchestrator-інтеграції з розділу нижче).
3. **Квотинг + existence.** M9 quote двох ніг → `gross_bps`; обов'язковий
   honeypot/sell-side probe (Фаза 3b), бо long-tail = високий rug-ризик.
4. **Вимір вікна (Фаза 2 — ГЕЙТ перед production).** `spread_lifetime` після
   появи другого пулу. Без цієї цифри production-вхід заборонений.
5. **Production-вхід** лише після того, як Фаза 2 покаже медіану `lifetime_s` у
   безпечному діапазоні. Real execution off до окремого unlock.

## 0f) Чи встигнемо зайти за секунди (рівні MEV)

- **Рівень 1 — atomic same-block MEV (мс):** sandwich/backrun усередині ОДНОГО
  пулу на чужих свопах. Апаратно не встигаємо й не треба — він НЕ закриває
  cross-mechanic спред між ДВОМА пулами. Інша гра.
- **Рівень 2 — cross-DEX арб-боти (1-2 блоки, 2-4 c на Base):** реально
  закривають спред між пулами. CLMM↔CLMM (Фаза B) — швидко, програємо, НЕ йдемо.
  CLMM↔ve33/Curve/Balancer (Фаза C) на свіжому токені — гіпотеза: повільніше
  (менше крос-механіка адаптерів + свіжий токен ще не в allowlist великих ботів).

**Пряма відповідь:** якщо cross-mechanic вікно живе секунди-хвилини (а не мс), то
звичайного RPC + швидкого квотингу ДОСТАТНЬО, co-located інфраструктура не
потрібна. Мілісекундна гонка стосується launch-sniping і CLMM↔CLMM, куди свідомо
не лізем. **АЛЕ це гіпотеза до виміру:** `spread_lifetime` Фази 2 дає факт —
медіана <~1-2 c → відступаємо; десятки секунд–хвилини → batch-вхід встигає.

## 0g) Активний пошук другого пулу (узгоджено тімлідом 2026-06-06)

**Ключове уточнення:** "знайти 2 пули відразу" ≠ передбачити неіснуючий пул.
Без pending/preconfirm lane ми бачимо тільки вже створене on-chain. До появи
другого on-chain пулу edge не існує.

**Мета:** не чекати пасивно другий пул, а після першого pool event ставити токен
у watch-list і **активно** шукати `T-*` по всіх supported DEX через recent
factory logs / adapter-specific resolvers. Pending/preconf detection — окремий
R&D, не production foundation.

Реалістичні варіанти виявлення другого пулу:

| Сценарій | Механізм | Примітка |
|----------|----------|----------|
| Same tx / same block-window | обидва пули в одному tx або сусідніх блоках | ловимо обидва одразу з логів |
| Після першого пулу | fast token-neighborhood scan по factory logs / registry | раніше, ніж batch M8.2 |
| V2/V3/CLMM | `find_recent_pools_containing_token(T, from_block, to_block)` за indexed `token0/token1` | pair factory logs |
| v4 | нормалізувати pool identity/currencies; перший v4 pool = watch-list seed | окремий layout |
| Curve/Balancer/Maverick | adapter-specific token containment resolver | не `getPool(A,B)` |
| DexScreener/GeckoTerminal/The Graph | hint only (`m8_external_pool_hints_latest.json`) | on-chain verify обов'язково; **не** в M9 напряму |
| Pending/preconf | ранній сигнал | R&D; без стабільного sequencer access не production |

**Обмеження (не ігнорувати):**
- Шукати тільки `T-anchor` → пропустимо `T-C + C-anchor` (3-leg/4-leg).
- Шукати всі `T-*` без RPC budget → QSR знову впаде; backoff обов'язковий.
- Honeypot/tax gate до будь-якого positive claim.
- Поки немає `time_to_second_pool_s` — не знаємо, чи edge живе секунди, хвилини
  чи години (доповнює `spread_lifetime` Фази 2).

**Production-shadow гейт (усі умови):** `second_pool_verified=true` AND
`quoteable_routes>=2` AND `honeypot_pass=true` AND `spread_lifetime` не порожній.

## 0h) Known-token pools vs fresh long-tail (узгоджено тімлідом 2026-06-07)

Незалежний review: **новий CLMM-пул відомого токена — не наша гра** (latency/MEV,
мілісекунди–1 блок, telemetry only). **Known-token cross-mechanic** — secondary
shadow lane, не заміна fresh long-tail.

Класифікація (`m8/discovery/token_classify.py`, config-driven):
- `token_class`: `fresh_long_tail` | `known_major` | `known_midtail` |
  `unknown_unclassified`.
- `mechanic_pair`: `same_mechanic` | `cross_mechanic` | `unknown_mechanic`.

Hard policy:
- `known_major + same_mechanic` → telemetry/control, не bridge-shadow.
- `known_major + cross_mechanic` → shadow lane з окремими метриками.
- `fresh_long_tail` + (`cross_mechanic` OR `connector_tokens>=1`) → primary shadow.

Метрики роздільно: `spread_lifetime_by_token_class`,
`spread_lifetime_by_mechanic_pair` у `m8_hot_path_latest.json`.

## 0i) External pool hints (Фаза 1.6 — hint-only, 2026-06-07)

**Blocker (recall):** `M8_2_SECOND_VENUE_RECALL_LOW` — sniper бачить тисячі подій, але
`transitions_1_to_2=0` / `TOKEN_NOT_SEEN_ELSEWHERE` без другого on-chain пулу в вікні.

**Рішення:** DexScreener + GeckoTerminal + The Graph як **hint-layer** для M8.2
token-first second-venue discovery. Hints **не** потрапляють у M9 напряму.

| Компонент | Шлях | Роль |
|-----------|------|------|
| Схема | `m8/discovery/pool_hints.py` | `PoolHint`, статуси, on-chain verify |
| DexScreener | `m8/discovery/dexscreener_hints.py` | token → pairs |
| GeckoTerminal | `m8/discovery/geckoterminal_hints.py` | token→pools + new_pools |
| The Graph | `discovery/graph_client.py` + `m8/discovery/graph_hints.py` | token pool queries |
| Refresh CLI | `scripts/m8_external_pool_hint_refresh.py` | watchlist → rolling artifact |
| Rolling artifact | `data/runs/_rolling/m8_external_pool_hints_latest.json` | єдиний canonical hints JSON |
| M8.2 merge | `cross_dex_expand.py --external-hints` | registry → MirrorIndex → hints → verify |
| M9 gate | `bridge_builder.py` | відкидає `hint_status=HINT_ONLY` |

**Статуси hint:** `HINT_ONLY` → `HINT_STALE` / `HINT_DEX_UNSUPPORTED` →
`HINT_POOLID_VERIFIED` (V4 poolId) / `HINT_FACTORY_VERIFIED` (factory getPool) /
`HINT_ONCHAIN_VERIFIED` (bytecode/Curve/Maverick) → `QUOTE_SMOKE_OK` →
`BRIDGE_SHADOW_READY`.

**Verify modes (`--verify-mode`):** `none` | `light` (bytecode only) |
`specialized` (default) — V4 via StateView poolId; V2/V3 via factory; Balancer
`getPoolTokens`; Curve `coins`; Maverick `tokenA/tokenB`.

**Blocker (was):** `V4_POOL_ID_SPECIALIZED_VERIFY_MISSING` — v4 poolId ≠ contract
address; `eth_getCode` давав false `verified=0`. Fixed in `hint_verifier.py`.

**Примітка:** `subgraph_ready` у M8.2 = локальна mini-graph готовність (≥2 venues,
connectors, routes), **не** інтеграція з The Graph API.

**Команди:**
```powershell
py -3.11 scripts/m8_external_pool_hint_refresh.py --chain base --sources dexscreener,geckoterminal,thegraph --watchlist data/tmp/m8_token_watchlist_latest.json
py -3.11 scripts/m8_cross_dex_expand.py --expansion-mode token_neighborhood --external-hints data/runs/_rolling/m8_external_pool_hints_latest.json
```

Runtime acceptance: `verified_second_pool_count > 0` на full watchlist regen; expansion
має `hint_tokens_matched`, `eligible_hint_routes`, `hint_registry_overlap_tokens`;
`subgraph_ready_tokens > 0` перед M9 shadow. Hot-path quote: `setup_quote_rpc →
resolve_productive_http_rpc` (не public). Blocker після V4 fix:
`M8_2_HINT_TO_EXPANSION_MATCHING_OR_CROSSDEX_LOW` (same-DEX v4 hints ≠ cross-DEX).

## 0i.1) Coverage expansion and mirror radar (M8.2 only)

**Goal:** збільшити шанс знайти `1->2` venue transition для M8-sniped токена,
не послаблюючи provenance і не пускаючи API-hints напряму в M9.

Цей блок належить до M8.2. Він не є M9 economics gate і не може створювати
production/economics claim.

### Priority DEX candidates

| Priority | DEX / family | Why it matters | Required work before canonical M8.2 coverage |
|----------|--------------|----------------|----------------------------------------------|
| P0 | Alien Base V2 / Area51 / V3 | Base-native launch venue; може давати early mirrors поза Uni/Aero | Move addresses to config, add factory listener, resolver, verifier, quote-smoke, depth-smoke |
| P0 | QuickSwap V2 / Algebra | Algebra/CLMM family outside current dominant Uni/Aero path | Config factories, topic/layout support, token-first resolver, quote/depth smoke |
| P0 | iZiSwap Base | Distinct CLMM implementation; useful for cross-mechanic mirrors | Config factory/quoter, pool verification, quote path, scan telemetry |
| P1 | Hydrex | Emerging Base DEX; useful as mirror radar | Treat as hint/R&D until contract/indexer proof exists |
| P1 | Pancake Infinity | Newer Pancake pool model; may capture fresh deployments | Add only after official Base factory/quoter evidence |
| P1 | Balancer V3 | Distinct-pricing lane; potential larger pricing divergence | Keep separate from Balancer V2; require Vault/router proof |

### Aggregator / API radar

Use external APIs as recall amplifiers, not as truth:

- DexScreener: primary token-pairs radar for fresh token mirrors.
- GeckoTerminal / CoinGecko new pools: second-pool discovery and stale-hint comparison.
- CoinMarketCap DEX API: additional pair/liquidity/security metadata when available.
- DexPaprika: broad DEX/token/pool/swap radar.
- Moralis: token-pair/liquidity enrichment.
- Codex/Defined: optional real-time token/pool radar if access is available.

### Truth contract

- API rows are `HINT_ONLY` until on-chain verification succeeds.
- A route becomes canonical M8.2 only after token metadata, pool contract evidence,
  pool membership, liquidity/depth evidence, and quote-smoke are available.
- Every candidate DEX must emit reason-coded rejects:
  `NO_POOL`, `INDEX_NO_MATCH`, `UNSUPPORTED_LAYOUT`, `VERIFY_FAILED`,
  `QUOTE_SMOKE_FAILED`, `DEPTH_SMOKE_FAILED`.
- New coverage must be visible in the token-first scan matrix; pool-first rows are
  not sufficient for M8.2 coverage claims.

### Required metrics

- `candidate_dexes_seen`
- `candidate_dexes_configured`
- `unsupported_candidate_dexes`
- `candidate_dex_attempt_matrix`
- `mirror_source_yield_by_provider`
- `api_hint_to_onchain_verified_rate`
- `stale_hint_rate`
- `second_pool_source`
- `hint_freshness_s`
- `truth_status`

### Acceptance

Coverage expansion is reached only when:

1. New DEX candidates are represented in config and scan telemetry, or explicitly
   listed as unsupported with a reason.
2. External API hints are merged into M8.2 as hints only and cannot bypass on-chain
   verification.
3. `m8_2_acceptance_report.py --strict` continues to separate coverage blockers
   from quality blockers.
4. M9 remains `NOT_EVALUATED` until M8.2 strict quality gates pass.

## 0j) Productive quote sync gate for distinct-pricing lanes

**Hard rule:** discovery/indexer quote-smoke is not the same as M9 productive quote.
Balancer/Maverick may show `QUOTE_OK_*` in `m8_*_pool_index_latest.json`, but M9
existence/economics remains blocked until the same pools quote through:

- `m9/graph_arb/raw_http_probe.py` for `--quote-backend raw_http`;
- the adapter path used by M9 runner for non-raw quote backends;
- route diagnostics over the shadow bridge inventory, not only isolated indexer smoke.

Required alignment before M9 shadow:

1. Balancer productive path must use the same working BalancerQueries/Vault target,
   ABI encoding, asset ordering, sender/recipient, and amount policy as the indexer
   smoke that produced `QUOTE_OK_BALANCER`.
2. Maverick productive path must use the same working Maverick quoter target and ABI
   as the indexer smoke that produced `QUOTE_OK_MAVERICK`; old PoolInformation
   `calculateSwap` responses with `0x` are a blocker, not market evidence.
3. `bridge_source_metrics` must keep separate fields for discovery quote-smoke and
   M9 productive quote diagnostics. Never collapse them into one `quoteable` claim.
4. `enabled_for_productive=false` stays for Balancer/Maverick until productive route
   diagnostics prove non-zero quote success on fresh shadow inventory.

Acceptance for this gate:

- Balancer/Maverick route diagnostic through M9 quote path has `route_qsr > 0`.
- Debug artifacts identify the actual quote target and ABI path.
- A short shadow run may start only after Curve has at least one quoteable route and
  Balancer/Maverick productive diagnostics are non-zero.
- Passing this gate is **pool/route-level only**. It does not imply M9 economics.
  The next gate is cycle-level: `cycles_quoteable > 0`,
  `cross_mechanic_cycles > 0`, and only then positive gross/net evidence may be
  evaluated.

## 0k) Quote-size truth gate before economics

**Hard rule:** M9 economics is invalid if USD notional is converted through
truncated symbols or default token metadata. The branch target is fresh long-tail
tokens plus second-venue mirrors, but the quote engine must still size every leg
by canonical token address.

Required before any economics claim:

1. Token decimals are resolved by lowercase token address first. Symbols and
   truncated labels such as `0xd9aaec`, `0x833589`, or `0x420000` are display
   labels only and must not drive decimals.
2. Token prices are resolved by address first. Unknown price must reject with an
   explicit reason such as `UNKNOWN_PRICE`; it must not silently fall back to
   `1.0`.
3. Liveness probes and economics probes are separate. Tiny probes may prove a
   route can quote, but they must not be counted as economic opportunity checks
   when gas/L1 cost dominates the notional.
4. `effective_depth_usd` is required for productive distinct-pricing routes, or
   the route must stay in liveness/shadow diagnostics only.
5. Legacy bridged tokens such as USDbC may stay as diagnostic/control lanes, but
   they should not dominate the quote budget for the fresh-long-tail thesis.

Acceptance for this gate:

- `token0_decimals` / `token1_decimals` are present on productive bridge routes,
  or the builder has an address-keyed cache proving the same metadata.
- Top cycles show human-scale raw `amount_in` for 6-decimal stablecoins.
- Balancer `BAL#304` / Maverick size reverts caused by oversized notional are
  near zero before increasing soak duration.
- Artifacts expose separate `qsr_liveness` and `qsr_econ` (or equivalent fields)
  when both probe classes are used.

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

### Фаза 1.5 — Активний пошук другого пулу (ПЕРЕД Фазою 2)

Мета: прискорити перехід `1→2 venue` — не чекати batch, тригерити scan одразу
після першого pool event (див. 0g).

1.5a. **Hot-path після першого pool event:** `token T → recent factory-log scan`
     across all enabled DEX (`m8/discovery/hot_path_ws.py` / `hot_path_mirror.py`).

1.5b. **V2/V3/CLMM:** `find_recent_pools_containing_token(T, from_block, to_block)`
     за indexed `token0/token1` у factory logs
     (новий хелпер у `m8/discovery/` або розширення `cross_dex_expand.py`).

1.5c. **v4:** нормалізувати pool identity/currencies; перший v4 pool = watch-list seed.

1.5d. **Curve/Balancer/Maverick:** adapter-specific token containment resolver
     (не pair-only `getPool`); reuse mirror index + `scripts/m8_discover_*_pools.py`.

1.5e. **Rolling watch-list artifact** (розширити `m8_pending_pairs.json` або
     `data/tmp/m8_token_watchlist_latest.json`): `token`, `first_pool`, `first_dex`,
     `first_block`, `seen_on_dexes`, `mechanics_seen`, `scan_backoff_stage`.

1.5f. **Transition detector:** при `seen_on_dexes: 1→2` одразу focused quote
     (не чекати orchestrator cycle).

1.5g. **Focused quote:** cycle lengths `2,3,4` через connector tokens (`T-C + C-anchor`).

1.5h. **Метрики (additive):** `time_to_second_pool_s`, `same_tx_second_pool_count`,
     `same_block_second_pool_count`, `cross_mechanic_transition_count`.

1.5i. **RPC budget:** короткий fast scan після launch, потім backoff
     `30s → 2m → 10m → 1h`.

Acceptance Фази 1.5: після live sniper/hot-path soak видно
`time_to_second_pool_s` (хоча б p50) і `cross_mechanic_transition_count >= 0`
(або явний `NO_SECOND_POOL_IN_WINDOW` з причиною). Додатково:
`token_class_histogram`, роздільні `spread_lifetime_by_*` (не змішувати класи).

### Фаза 1.5b — Token class shadow lanes (DONE in code)
- `m8/discovery/token_classify.py`: `token_class`, `mechanic_pair`,
  `production_lane`, `bridge_shadow_lane_eligible`.
- Hot-path artifact: `token_class_histogram`, `spread_lifetime_by_token_class`,
  `spread_lifetime_by_mechanic_pair`.
- Bridge-shadow acceptance: лише `cross_mechanic` OR `fresh_long_tail` з
  `connector_tokens>=1`; `known_major+same_mechanic` = telemetry only.

### Фаза 2 — Телеметрія часу життя спреду (визначає Фазу 4 + відповідає на MEV-лаг)
Мета: дати дані для рішення batch vs streaming БЕЗ припущень І емпірично
відповісти, чи існує long-tail вікно до того, як його "вичистить" MEV
(див. розділ 0b). `spread_lifetime` = пряма метрика того лагу.

Універсум для Фази 2: токени, що ПЕРЕЙШЛИ `token_seen_on_dexes 1→2`
(є друга venue), а НЕ свіжі single-DEX launch-токени. Інакше міряти нічого —
спреду між механіками не існує.

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
- Додати `scripts/m8_cross_dex_expand.py` у цикл
  `scripts/m9_rolling_orchestrator.py` — зараз expansion поза orchestrator, через
  що `graph_ready_from_expansion` тихо падає. Справжній баг конвеєра.
- Виправити дубльований `topic0` у `sushiswap_v3` (`config/new_pool_factories.yaml`):
  лишити лише v3 `0x783cca1c...`, прибрати помилковий v2 `0x0d3648bd...` (див. 0c).
  Зараз цей лейн де-факто глухий.

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
- НЕ будуємо production на pending/preconf lane без стабільного sequencer access.
- НЕ трактуємо DexScreener/subgraph як truth — лише hint, on-chain verify обов'язковий.
- НЕ пасивно чекаємо batch M8.2 для другого пулу — активний scan (Фаза 1.5).
- НЕ йдемо в known-token CLMM launch edge — telemetry/control only (0h).
- НЕ змішуємо `spread_lifetime` fresh long-tail і known-token pools.

## 5) Команди runtime-перевірки (canonical для гілки)

Після doc/code змін:

```powershell
py -3.11 scripts/check_repo_safety.py

py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/sniper_smoke_run.py --chain base --duration-minutes 120 --skip-self-test --skip-preflight --blocks-back 43200

py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m8_cross_dex_expand.py --expansion-mode token_neighborhood

py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m8_hot_path_runner.py --live-ws --duration-minutes 30 --quote
```

Очікувані rolling-артефакти для review: `data/runs/_rolling/new_pool_sniper_latest.json`,
`data/runs/_rolling/m8_pending_pairs.json`, `data/tmp/m8_hot_path_latest.json`,
`data/runs/_rolling/m8_cross_dex_expansion_latest.json` (runtime-only, не комітити).
