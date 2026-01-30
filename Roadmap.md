# Roadmap.md — Crypto Arbitrage Project (Single Source of Truth)
Дата: 2026-01-04  
Автор: Team Lead  
Статус: **ACTIVE** (єдиний документ, за яким працює команда)

## 1) Мета і критерії успіху
Мета: побудувати **повністю робочий** арбітражний проєкт, який:
1) генерує тільки **правдиві executable opportunities** (*Truth Engine*),
2) вміє **виконувати** угоди з контрольованим ризиком (*Execution Engine*),
3) масштабується через **адаптери протоколів** (а не “if-else по DEX-ах”),
4) має **мінімальний хардкод** лише як “trust anchors”, решта — dynamic + verify.

**Перший реальний критерій успіху** (не “кількість сигналів”):
- % quotes, що **свіжі** (blockNumber) і валідні
- % opportunities, що проходять executability gates
- fail-rate на симуляції / сабміті
- реальний net PnL на дистанції (expectancy), з tail-losses і variance

---

## 2) Стратегія (що робимо першими)
### Core (перша production-ціль)
**DEX ↔ DEX на одній мережі** з атомарним виконанням (одна транзакція / bundle) + pre-trade simulation + приватна подача.

Причина: це найшвидший шлях довести executability без операційного пекла мостів/виводів.

### Optional (після стабільного core)
**CEX ↔ DEX тільки inventory-based** (баланси вже на CEX і на DEX, без “перекину потім”).

### R&D (пізніше)
Triangular, Cross-chain — тільки після того, як Truth Engine + Execution дають реальні результати.

---

## 3) Непорушні правила (без цього PR не приймаємо)

### 3.1 Мінімальний хардкод: що дозволено
**Hardcode (TRUST ANCHORS — дозволено і треба):**
- `chain_id`, `native_symbol`, `explorer`, `rpc_fallbacks`, `ws_endpoints`
- DEX protocol anchors: `factory/router/quoter` addresses, тип протоколу (V3/V2/Algebra/ve33)
- Core tokens per chain: `USDC/USDT/DAI/WETH/WBTC` (+ локальні wrappers типу `WMNT`)
- Standard V3 fee tiers: `[100, 500, 3000, 10000]`
- ABI файли (versioned) для адаптерів

**Dynamic (заборонено хардкодити, тільки discovery+verify):**
- список пулів/пар (крім “core sanity pairs” для smoke tests)
- “список робочих токенів” (крім core tokens)
- TVL/volume/активність
- “найкращий DEX” — визначається quoting/curve, а не руками

### 3.2 No float money
Усі суми в **wei-int** або `Decimal`. `float` заборонений у quoting/price/PnL.

### 3.3 Directional pricing only
- DEX BUY = quote→base (ExactOutput), DEX SELL = base→quote (ExactInput)
- CEX BUY = ask + fee, CEX SELL = bid - fee
- Mid price для арбу заборонений.
- Інверсія “1/price” заборонена для оцінки BUY.

### 3.4 Every reject has a reason code
Жодних “no opportunity” без причин: `STALE_BLOCK`, `SLIPPAGE_TOO_HIGH`, `CEX_DEPTH_LOW`, `REVERT_NO_LIQUIDITY`, тощо.

### 3.5 Simulate before sign
Жодної угоди без simulation/preview (eth_call/trace/Tenderly або еквівалент).

---

## 4) Повна структура репозиторію (канонічна)

> **Важливо:** назви файлів тут — канон. Не створювати дублікати (наприклад `clock.py` замість `time.py`).

```
arby/
  README.md
  Roadmap.md

  pyproject.toml
  .env.example

  config/                         # ✅ HARD (trust anchors) + soft strategy params
    chains.yaml                   # ✅ HARD: chain_id, rpc, ws, explorer, native token
    core_tokens.yaml              # ✅ HARD: USDC/USDT/WETH/WBTC/DAI (+ wrappers per chain)
    dexes.yaml                    # ✅ HARD: DEX anchors + adapter type (V3/V2/Algebra/ve33)
    cex.yaml                      # ✅ HARD-ish: endpoints, symbols map, rate limits (НЕ ціни)
    fees.yaml                     # ✅ HARD-ish: maker/taker fees per exchange (+ overrides)
    strategy.yaml                 # ✅ SOFT: sizes, thresholds, weights

  data/                           # ✅ DYNAMIC outputs (generated; no manual edits)
    registry.sqlite               # verified tokens/pools
    snapshots/                    # json snapshots per run
    trades/                       # executions + paper trades
    reports/                      # daily summary dumps

  core/
    models.py                     # Quote, Opportunity, RejectReason, Trade, PnL
    constants.py                  # enums, defaults
    math.py                       # bps, normalization, net PnL, safe conversions
    time.py                       # freshness rules, block pinning helpers
    logging.py                    # structured JSON logger
    exceptions.py                 # typed exceptions and codes

  chains/
    providers.py                  # RPC pool, failover, WS, timeouts, retries
    block.py                      # latest block fetch, pinning, latency metrics
    tokens.py                     # token validation (decimals/name/symbol), caching
    multicall.py                  # optional batching
    gas.py                        # chain gas model (L2 нюанси дозволені)

  dex/
    registry.py                   # maps (chain,dex)->adapter from config/dexes.yaml
    adapters/
      base.py                     # DexAdapter interface
      uniswap_v3.py               # V3 adapter (ExactInput/ExactOutput, ticksCrossed)
      algebra.py                  # Algebra adapter (Camelot/Lynex/THENA клас)
      uniswap_v2.py               # V2 router adapter
      ve33.py                     # later (Aerodrome/Velodrome клас)
    abi/                          # ✅ HARD (versioned ABIs)
      uniswap_v3_quoter_v2.json
      algebra_quoter.json
      uniswap_v2_router.json

  cex/
    adapters/
      base.py                     # CexAdapter interface
      bybit.py
      mexc.py
      okx.py                      # optional
    symbols.py                    # internal pair -> exchange symbol map
    fees.py                       # loads fees.yaml + account overrides
    depth.py                      # orderbook fill model + depth checks
    rate_limit.py                 # backoff/jitter + taxonomy

  discovery/
    dexscreener.py                # dynamic candidates fetch
    filters.py                    # coarse filters (volume, age)
    verify.py                     # on-chain verify pools/tokens -> registry.sqlite
    scoring.py                    # pool confidence scoring (soft)

  engine/
    quote_engine.py               # quote curve (3–4 sizes), directional pricing
    opportunity_engine.py         # compute net PnL, reject reasons, ranking
    risk.py                       # exposure limits, circuit breaker, kill switch
    portfolio.py                  # later: inventory state

  execution/
    simulator.py                  # pre-trade simulation gate
    private_tx.py                 # private send / bundle integration
    dex_dex_executor.py           # atomic DEX↔DEX execution
    state_machine.py              # trade lifecycle

  strategy/
    scanner.py                    # scan loops (multi-chain), outputs opportunities
    live_paper.py                 # paper-run using same engines
    backtest_replay.py            # replay snapshots for regression
    jobs/
      run_scan.py                 # CLI entrypoints
      run_paper.py

  monitoring/
    truth_report.py               # CLI: reject histogram, top opps, health
    alerts.py                     # Telegram/Discord
    health.py                     # RPC/DEX/CEX health score

  tests/
    unit/
      test_decimal_conversions.py
      test_pnl_directional.py
      test_currency_normalization.py
    integration/
      test_v3_quotes_arbitrum.py  # optional; can be skipped in CI
```

### 4.1 Де лежать хардкодні дані (обов’язково)
- `config/chains.yaml` — лише мережі/інфра
- `config/dexes.yaml` — лише anchors + adapter type
- `config/core_tokens.yaml` — лише core токени
- `dex/abi/*.json` — ABI (versioned, з приміткою джерела)

### 4.2 Де НЕ можна хардкодити
- `discovery/*` не містить ручних адрес токенів/пулів (крім smoke pairs)
- `engine/*` не містить “списків пар”
- `strategy/scanner.py` не містить адрес контрактів (вони тільки в config + adapter)

---

## 5) Milestones (послідовність робіт)

### Milestone 0 — Bootstrap (1 день)
**Deliverables**
- Repo skeleton + CI + lint/format
- Structured JSON logging
- CLI: `run_scan`, `run_paper`

**Acceptance**
- `python -m strategy.jobs.run_scan` запускається на 1 мережі з 1 адаптером і генерує валідний звіт (навіть якщо порожній).

---

### Milestone 1 — Truth Engine (3–4 дні)
**Мета:** прибрати фейки. Opportunity = executable net PnL.

#### M1.1 Quote model + block freshness (P0)
- Quote містить `block_number`, `timestamp`, `gas_estimate`, `ticks_crossed`
- Фіксація block на scan (pin)
- Кожен quote логить block_number

**Done:** відсутні “заморожені” ціни; block_number рухається.

#### M1.2 No-float enforcement (P0)
- Заборонити float в quote/PnL (review gate + tests)
- Safe converters в `core/math.py`

**Done:** у quoting pipeline немає float.

#### M1.3 Currency normalization (P0)
- USDC↔USDT конвертація через CEX cross або reject
- Всі PnL в одній валюті

**Done:** будь-який мікс USDC/USDT або нормалізовано, або відкинуто з reason.

#### M1.4 Directional PnL + fee truth + depth (P0)
- CEX depth fill model на notional (не top-of-book)
- fees тільки з `config/fees.yaml` (+ account overrides)
- PnL рахується bid/ask + fees + gas

**Done:** paper не показує 100% win-rate; кожна “угода” має cost breakdown.

#### M1.5 Quote curve + slippage gate (P0)
- Quote curve на 3–4 sizes
- `MAX_SLIPPAGE_BPS` реально відсікає

**Done:** opportunities існують тільки якщо impact на робочому size прийнятний.

#### M1.6 Error taxonomy (P0)
- Typed errors: revert vs infra (timeout/rate limit/bad abi/bad address)
- Жодних bare except

**Done:** кожен fail має `error_code` + коротке повідомлення.

---

### Milestone 2 — Adapters (2–3 дні)
**Мета:** реальна мульти-DEX підтримка через адаптери протоколів.

#### M2.1 Adapter interface + registry (P0)
- `DexAdapter` + `dex/registry.py`
- scanner працює лише через registry

**Done:** додати DEX = запис у `config/dexes.yaml` + adapter class.

#### M2.2 Harden UniswapV3Adapter (P0)
- ExactInput + ExactOutput
- ticksCrossed/gasEstimate використовуються в executability/confidence
- fee tiers конфігуровані

**Done:** V3 adapter дає стабільні quotes і метадані.

#### M2.3 AlgebraAdapter skeleton (P1)
- Мінімальний quotes + error taxonomy
- Smoke test: 1 пара на 1 мережі

**Done:** “could not call contract” зникає як клас проблеми — є конкретна причина.

#### M2.4 UniswapV2Adapter skeleton (P1)
- getAmountsOut/router quotes
- Smoke test

**Done:** покриваємо V2 DEX-и без V3 quoter.

---

### Milestone 3 — Opportunity Engine (після M1–M2)
- Confidence score (freshness + adapter reliability + ticksCrossed + curve stability)
- Ranking: net_usd, net_bps, confidence
- `monitoring/truth_report.py`: reject histogram + top opps + health

---

### Milestone 4 — Execution v1 (DEX↔DEX atomic)
- Trade state machine
- Pre-trade simulation gate
- Private send/bundle integration
- Post-trade accounting: realized PnL, gas paid, slippage realized
- Kill switch / circuit breaker

### M5_0 — Infra: RPC Providers, Streaming, Tracing (No Execution)

Goal: Improve data quality + stability without changing execution semantics.

Scope:
- Provider abstraction layer (HTTP + optional WS)
- Multi-provider routing (public RPC / Alchemy) with retries, backoff, timeouts
- Optional Tenderly tracing/simulation hook for diagnostics (not required for pass)
- Centralized asyncio concurrency control (semaphores, connection pooling)
- Observability: richer RPC health metrics and artifact invariants

Done Criteria:
- Full test suite green (unit + integration)
- M4 gate remains green (offline)
- New M5_0 gate script passes offline (recorded fixtures)
- Config supports selecting provider per chain (env + yaml)
- No execution enabled; execution_ready_count remains 0

---

### Milestone 5 — Production small
- Daily report: net PnL, win-rate, tail losses, reject reasons
- Авто-зниження size при рості impact/ticksCrossed
- Health score для RPC/DEX/CEX

---

### Milestone 6 (Optional) — CEX↔DEX inventory-based
- Inventory manager + rebalance planner
- CEX execution state machine + partial fills
- Fee truth per-account/per-pair

---

### Milestone 7 (R&D) — Triangular
- Graph builder + cycle finder + atomic multi-hop execution

### Milestone 8 (R&D) — Cross-chain
- Bridge adapters + time-risk model + settlement tracker

---

## 6) Definition of Done (для будь-якого модуля)
- Є unit tests на ключову математику
- Нема bare except
- Логи містять blockNumber, latency, reason codes
- Будь-який “profit” має breakdown: fee + gas + slippage + currency basis
- Якщо USDC/USDT змішані — або нормалізовано, або reject

---

## 7) Non-goals на старті
- “Підтримка всіх DEX-ів/всіх мереж”
- UI/дашборди/краса
- Cross-chain “бо цікаво”
- “AI ranking” до truth + execution

---

## 8) Ролі і відповідальність
- **Engine dev**: quote_engine, opportunity_engine, risk
- **DEX dev**: adapters + on-chain нюанси + ABI
- **CEX dev**: depth, fees, symbols, rate limits
- **Infra dev**: providers, failover, caching, observability
- **QA**: tests, replay snapshots, regression

---

## 9) 7-денний очікуваний результат (чекпойнт)
Через 7 днів ми маємо:
- quotes свіжі (blockNumber), без “заморожених”
- directional PnL в одній валюті з breakdown
- opportunities відсіяні по slippage/depth/fees/revert із reason codes
- мінімум 2 DEX адаптери працюють через registry
- paper показує реалістичну картину (є reject-и, є 0/мінус; немає 100% win-rate)

> Якщо через 7 днів система все ще показує “все в плюс і завжди” — Truth Engine провалено, повертаємось до Milestone 1.


---

# Appendix A — Intent-driven Universe Enablement (Tokens/Chains/Pools)

Цей додаток описує, як **запустити в роботу universe** з `intent.txt` (мінімальний список пар) на всіх мережах та підхопити **всі можливі пули** в рамках підтримуваних протоколів/DEX-ів.

> Джерело truth для universe: `intent.txt` (chain:BASE/QUOTE).  
> Важливо: ми **не довіряємо символам** як адресам. Символ = лише “намір”, адреса підтверджується тільки через verify. fileciteturn15file0

## A1) Де це лежить у проєкті

### HARD (trust anchors)
- `config/chains.yaml` — chain_id, RPC/WS endpoints, explorer
- `config/dexes.yaml` — список DEX на кожній мережі + `adapter_type` + factory/router/quoter addresses
- `config/core_tokens.yaml` — core tokens per chain (USDC/USDT/DAI/WETH/WBTC + wrappers типу WMNT)
- `dex/abi/*` — ABI (versioned)

### DYNAMIC (генерується)
- `data/registry.sqlite` — verified tokens, pools, pair-universe, health metrics
- `data/snapshots/*` — quotes/opportunities/rejects з reason codes

### Код (нові/оновлені модулі)
- `discovery/intent_loader.py` — парсить `intent.txt`, дає canonical pair-universe
- `discovery/verify.py` — on-chain verify токенів/пулів
- `discovery/index_factories.py` — **factory-based enumeration** пулів для підтримуваних DEX-ів
- `discovery/dexscreener.py` — fallback discovery (не як truth, а як “hint/source”)
- `dex/registry.py` + `dex/adapters/*` — quoting/adapter support
- `strategy/scanner.py` — цикл скану, який працює тільки з registry

## A2) Як ми запускаємо “всі токени + всі мережі” з intent.txt

### Крок 1 — Парсинг intent.txt → canonical universe
**Виконує:** `discovery/intent_loader.py`

Правила:
1) Рядок формату `chain:AAA/BBB` додає пару (unordered) в universe для chain.
2) Все, що починається з `#` — коментар.
3) Canonical form:
   - chain: `arbitrum_one` → canonical chain key (мапінг у `chains.yaml`)
   - pair: `token0/token1` де `token0 < token1` (лексикографічно) **для ключів**, але original ordering зберігаємо окремо як “preferred quoting direction”.

**Збереження:**
- `registry.sqlite` таблиці `intent_pairs(chain_id, sym_a, sym_b, added_at, source='intent')`

> Пара у intent — це мінімум. Далі ми розширюємо пул-лист, але не розширюємо список пар без явного рішення. fileciteturn15file0

### Крок 2 — Token resolution: symbol → verified token address (per chain)
**Виконує:** `discovery/verify.py` (через discovery hints)

Порядок (жорсткий):
1) Якщо символ входить у `config/core_tokens.yaml` для цієї мережі → беремо address+decimals як trust anchor.
2) Якщо символ НЕ core:
   - спочатку беремо **кандидатні адреси** з discovery (DexScreener або DEX factory lookups)
   - потім робимо on-chain verify: `decimals()`, `symbol()`, `name()`, `totalSupply()>0` (sanity)
   - **ніколи** не приймаємо токен лише по “symbol з API”.

**Збереження:**
- `registry.sqlite` таблиця `tokens(chain_id, address, decimals, symbol_onchain, name, first_seen, last_verified, is_core, status)`

> Якщо виявлено 2 різні адреси з одним символом — обидві зберігаються, але лише одна може бути “canonical” після ручного рішення (`status='candidate'`).

### Крок 3 — “All possible pools”: factory-based enumeration (основний метод)
**Виконує:** `discovery/index_factories.py`

Ціль: для кожної `intent pair` на кожному chain, пройти по **всіх DEX-ах**, які ми реально підтримуємо адаптерами, і знайти всі пули. fileciteturn15file0

#### Для Uniswap V3 / Pancake V3 (adapter_type = `uniswap_v3`)
- Для кожної fee tier з `core/constants.py: V3_FEE_TIERS`
- Виклик: `factory.getPool(tokenA, tokenB, fee)`
- Якщо повернуло адресу != 0x0 → пул додаємо

#### Для V2 DEX (adapter_type = `uniswap_v2`)
- Виклик: `factory.getPair(tokenA, tokenB)`
- Якщо адреса != 0x0 → pair-пул додаємо

#### Для Algebra (adapter_type = `algebra`)
- Використовуємо factory метод, відповідний Algebra (залежить від ABI), аналогічно `getPool/getPair`

**On-chain verify pool:**
- токени пулу `token0/token1` відповідають очікуваним
- для V3: `fee()` збігається
- sanity liquidity:
  - V2: `getReserves()` > 0
  - V3: `liquidity()` > 0 (або slot0 valid)

**Збереження:**
- `registry.sqlite` таблиця `pools(chain_id, dex_id, pool_address, token0, token1, pool_type, fee, first_seen, last_verified, status)`

> Це і є наше визначення “всі можливі пули”: **всі пули для кожної intent-пари в межах підтримуваних DEX-ів** (тих, що є в `dexes.yaml` і мають адаптер).

### Крок 4 — DexScreener як доповнення (не як truth)
**Виконує:** `discovery/dexscreener.py`

Використовуємо DexScreener:
- щоб знайти “невідомі” DEX/пули, яких немає в `dexes.yaml`
- щоб оцінити rough volume/активність як додатковий сигнал

Але:
- **ніколи** не вважаємо DexScreener правдою без on-chain verify
- якщо DexScreener показує пули на DEX, якого у нас немає — ми або додаємо adapter, або ігноруємо.

### Крок 5 — Health & pruning (щоб “усі пули” не стали сміттям)
**Виконує:** `discovery/scoring.py` + регулярний job

Пули мають переходити між статусами:
- `active` — проходить verify, є liquidity, quotes stable
- `stale` — давно не оновлювався / часто таймаути
- `dead` — liquidity=0/постійні reverts
- `suspicious` — аномальні decimals/symbol mismatch/часті помилки

Пули зі статусом `dead/suspicious` не використовуються в scanning/execution.

## A3) Як scanner використовує universe і пули (runtime)

### Scanner pipeline
`strategy/scanner.py`:
1) бере список intent pairs з `registry.sqlite`
2) для кожної пари:
   - дістає всі `active` пули з `pools` (по всіх DEX-ах)
   - викликає адаптер для BUY і SELL quotes:
     - BUY: quote→base (ExactOutput)
     - SELL: base→quote (ExactInput)
   - формує quote curve на 3–4 розмірах (з `config/strategy.yaml`)
3) `engine/opportunity_engine.py` рахує net PnL та повертає reject reasons, якщо не executable

### Мінімальні параметри strategy.yaml (must-have)
- `sizes_usd`: [50, 100, 200, 400]
- `max_slippage_bps`
- `min_net_bps`
- `min_net_usd`
- `max_latency_ms`
- `min_confidence`

## A4) Як “підключити всі мережі” без хаосу

### Правило 1 — не включати мережу без smoke checks
Для кожної мережі робимо smoke check на “base pairs” з intent: WETH/USDC, USDC/USDT (якщо є). fileciteturn15file0  
**Критерії включення мережі:**
- quotes оновлюються по blockNumber
- timeouts < X%
- хоча б N активних пулів для base pairs

### Правило 2 — адаптери визначають “можливі пули”
“Усі можливі пули” = всі пули на DEX-ах, які:
1) є в `config/dexes.yaml`
2) мають adapter implementation
3) проходять verify

Якщо intent містить мережу/пару, а там пули лише на протоколі без адаптера — фіксуємо `UNSUPPORTED_DEX_TYPE` і кладемо в backlog.

## A5) Практичний план rollout (1–2 дні)

### День 1: registry + factories index (Arbitrum)
1) `intent_loader.py` → запис intent pairs у registry
2) `index_factories.py` → зібрати всі пули для intent pairs по V3/V2 (з `dexes.yaml`)
3) `verify.py` → проставити `active/dead/suspicious`

### День 2: multi-chain rollout
1) заповнити `chains.yaml` + `dexes.yaml` для Linea/Scroll/Mantle/zkSync/Base (тільки DEX-и з адаптерами)
2) прогнати indexing job по всіх мережах
3) запустити scanner + `monitoring/truth_report.py`

## A6) Коментар Team Lead щодо intent.txt
`intent.txt` — це **мінімальний список пар**, який задає бізнес-фокус (токени, мережі, напрямки). fileciteturn15file0  
Ми масштабуємось **по пулах**, а не “роздуваємо список пар”:
- для кожної intent-пари збираємо всі пули по підтримуваних DEX-ах
- фільтруємо, скоримо і тримаємо `active` список

Це дозволяє “пустити в роботу всі токени з усіма мережами з усіма можливими пулами” без ручного хаосу і без фейкових даних.
