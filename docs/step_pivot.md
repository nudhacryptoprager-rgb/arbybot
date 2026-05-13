# step_pivot.md — Детальний план реалізації M8 (New-Pool Sniping)

> **Companion document до** [`docs/STRATEGIC_PIVOT.md`](STRATEGIC_PIVOT.md).
> **Призначення:** покроковий operational guide для розробки кожної фази M8.
> Кожна фаза містить: цілі → ризики → акценти → кроки → перевірки → критерії успіху.
> **Authority:** subordinate до `Roadmap.md`, `AGENTS.md`, `docs/DOCS_POLICY.md`.

---

## Загальні принципи (наскрізні для всіх фаз)

### Дисципліна розробки
- **Один PR = одна задача з checklist** (не змішувати infra + logic + tests в одному коміті).
- **Тести пишуться ПЕРЕД інтеграцією**, не після (TDD-lite).
- **Жоден feature не вмикається без feature-flag** через ENV (`ARBY_SNIPER_ENABLE`, `ARBY_HONEYPOT_CHECK_ENABLE`, etc.).
- **Kill-switch ON by default** — `execution_enabled=false`, paper-only до Phase 3.
- **Кожна фаза закривається DEV_REPORT update + соак-evidence**.

### Артефактна політика
- Новий canonical rolling artifact M8: `data/runs/_rolling/new_pool_sniper_latest.json`.
- Daily/aggregate rolling artifacts (`m8_daily_health.json`, `m8_stability_agg.json`) дозволені лише після schema-contract тесту.
- Не плодити per-run JSON-и — тільки overwrite-rolling.
- Кожен M8 artifact має містити `schema_family`, `schema_revision`, `generated_at_utc`, `source`, `freshness_s`, `status`, `reasons`.
- Зміна схеми = оновити schema-contract test + golden fixture у `docs/artifacts/golden/`; не додавати literal version-string examples у docs поза `DEV_REPORT_LATEST.md`.

### Метрики, які треба фіксувати з Phase 1
| Метрика | Опис | Phase появи |
|---|---|---|
| `pool_creation_events_seen` | events seen на factory listener | 1 |
| `pool_creation_events_filtered_out` | відкинуті (existing, blacklist, etc.) | 1 |
| `honeypot_check_pass` / `_fail` | per token simulate result | 1 |
| `snipe_candidates_total` | passed all filters | 2 |
| `snipe_simulated_total` | paper sims executed | 2 |
| `snipe_simulated_profitable` | sims with `net_profit_usd > 0` | 2 |
| `snipe_real_attempted` / `_filled` / `_reverted` | real-trade telemetry | 3 |
| `realized_pnl_usd` | per-snipe + cumulative | 3 |
| `stable_pair_fills` / `stable_pair_net_usd` | anchor niche stats | 2+ |

---

## PHASE 1 — Foundation (Тижні 1–2)

### 1.1. Цілі фази
Збудувати infrastructure listener-ів і фільтрів, які можуть **бачити нові пули в реальному часі**, не торгуючи. Це pure-discovery етап. Жодного capital risk.

### 1.2. Очікувані проблеми та як їх вирішувати

#### Проблема А: WS-конекшн до публічних RPC нестабільний
- **Симптом:** `eth_subscribe` на logs відвалюється кожні 10–30 хв на `publicnode`/`mainnet.base.org`.
- **Мітигація:**
  - Reconnect loop з exponential backoff (вже є патерн у `m7/orderflow/`).
  - **Dual-listener:** WS primary + HTTP `eth_getLogs` polling fallback (interval 5s).
  - Tracker `last_event_seen_ts`; якщо > 60s — force reconnect.
- **Перевірка:** kill provider mid-soak → бот має відновити підписку <30s, без втрати подій (primary RPC vs secondary HTTP `eth_getLogs`; explorer API тільки optional sanity-check, не gate).

#### Проблема Б: Factory contract addresses можуть бути неправильні
- **Симптом:** listener subscribed, але `events_seen=0` за годину.
- **Мітигація:**
  - Канонічний YAML `config/new_pool_factories.yaml` з ABI hash + verification block (приклад події у тому блоці).
  - Startup self-test: завантажити останні N=100 блоків через `eth_getLogs`, перевірити що ≥1 event парситься.
  - Hard fail при startup якщо self-test не пройшов.
- **Перевірка:** unit test `test_factory_addresses_self_test` для кожного з ≥3 factories.

#### Проблема В: Honeypot detector дає false-positives
- **Симптом:** легітимні токени відсіюються бо мають нестандартні `transfer`.
- **Мітигація:**
  - **Layered detection** (НЕ один single check):
    1. `eth_call` simulate `transfer(test_recipient, 1)` from deterministic funded test sender on pinned fork/current block → revert/success
    2. Bytecode contains известные scam patterns (e.g., owner-only transfer)
    3. `balanceOf` returns sane value after simulated mint/transfer
    4. Token має ≥N independent holders (через subgraph або scan API)
  - **Soft-reject taxonomy** — токен не одразу blacklist, а кладеться у `quarantine_pending` з reason; через 1h re-check.
- **Перевірка:** 
  - Test suite з ≥10 known scam tokens (всі мають FAIL)
  - Test suite з ≥10 known legit tokens (всі мають PASS)
  - Якщо ≥1 false positive → tune.

#### Проблема Г: Listener бачить events, але cold-lane не реагує
- **Симптом:** контракт нової pool створено, події логуються, але `snipe_candidates_total=0`.
- **Мітигація:**
  - **Явний bridge** від `pool_creation_event_emitter` до cold-lane queue.
  - Per-event tracing log: `event_id → received_ts → filter_passed → cold_queued_ts → scored_ts`.
  - End-to-end latency budget < 5s від event до queued.
- **Перевірка:** integration test з mock-events (injected через test harness), 100% events reach cold scoring.

### 1.3. Кроки реалізації (по днях)

| День | Task | Файли | Deliverable |
|---|---|---|---|
| 1 | Створити `discovery/new_pool_listener.py` skeleton + factory config YAML | `discovery/new_pool_listener.py`, `config/new_pool_factories.yaml` | Skeleton subscribes, logs raw events |
| 2 | Парсинг `PoolCreated`/`PairCreated` events для Aerodrome + UniV3 | + ABI files | Test: replay 100 historical blocks → ≥1 event parsed per factory |
| 3 | Додати UniV4 + Pancake factories | config + parser | Test: ≥3 factories self-test pass |
| 4 | `discovery/honeypot_detector.py` — layer 1 (simulate transfer) | `discovery/honeypot_detector.py` | 10 scam tests FAIL, 10 legit PASS |
| 5 | Honeypot layers 2-4 (bytecode, balance, holders) | + module | Layered score 0..1, threshold tunable |
| 6 | `execution/inventory_manager.py` — USDC balance tracker, top-up signal | `execution/inventory_manager.py` | Reads on-chain balance, emits low-balance event |
| 7 | `monitoring/sniper_artifacts.py` — write `new_pool_sniper_latest.json` | + module | Schema validation test pass |
| 8 | Cold-lane switch: feature flag `ARBY_SNIPER_MODE=1` redirects from backrun queue to new-pool queue | `m7/orderflow/bridge_runtime.py` | A/B: backrun mode unchanged, sniper mode ingests new-pool events |
| 9 | End-to-end integration test (mock RPC + event injection) | `tests/unit/test_phase1_e2e.py` | 100% events reach scored state |
| 10 | 4-hour foundation soak (paper, no trades, listener-only) | runtime script | Real RPC, log events seen |

### 1.4. На чому акцентувати

1. **Honeypot detector — найкритичніша частина.** Один false-negative = втрата всього capital у snipe. Тестове покриття має бути ≥90% branches.
2. **Atomicity of event ingestion.** Якщо подія втрачена — це назавжди. Дублікати краще, ніж пропуски.
3. **Latency.** Event → queued <5s. Інакше mirror-pool вже зʼявиться раніше.
4. **Schema discipline.** Артефакт `new_pool_sniper_latest.json` — це публічний контракт; будь-яка зміна → schema_revision update + golden fixture + schema-contract test.

### 1.5. Критерії успіху Phase 1
- [ ] ≥3 factory listeners active (Aerodrome + UniV3 + UniV4 або Pancake)
- [ ] 4-hour soak: `pool_creation_events_seen > 0` (real events on Base)
- [ ] Dual-source reconciliation: primary RPC and secondary HTTP `eth_getLogs` agree for factory events
- [ ] Honeypot detector: 10/10 scam reject, 10/10 legit accept (test fixtures)
- [ ] ≥30 unit tests (listener + detector + inventory) green
- [ ] Schema `new_pool_sniper_latest.json` зафіксована з `schema_family="m8_sniper"` and non-empty `schema_revision`
- [ ] DEV_REPORT_LATEST.md оновлено секцією Phase 1

---

## PHASE 2 — Sniping Live (Тижні 3–4)

### 2.1. Цілі фази
Перейти від "бачимо нові пули" до "вирішуємо чи знайдеш увійти + плануємо вихід" — все ще **paper-only**. Додати stable-stable anchor як низько-ризик baseline.

### 2.2. Очікувані проблеми та як їх вирішувати

#### Проблема А: Як зрозуміти, що pool "профітабельний"?
- **Контекст:** на момент створення пулу немає history, немає orderbook, немає decimal-prices.
- **Мітигація:**
  - **Phase A: Liquidity gate** — pool ignored поки initial liquidity < $1000 USD-eq (через token decimal heuristic).
  - **Phase B: Spread estimation** — після перших ≥3 swaps, оцінити effective spread.
  - **Phase C: Mirror search** — за 60s намагатися знайти ту саму пару на Uniswap V3/V4 (через scout + factory truth).
  - **Phase D: Decision** — entry тільки якщо (initial liquidity ≥ $1k) AND (estimated spread ≥ 50 bps) AND (mirror found OR strong base-token).
- **Перевірка:** історичний replay 50 нових пулів за минулий тиждень → ≥10% мали б тригернути entry за алгоритмом; з них ≥30% мали б profit at exit.

#### Проблема Б: Exit стратегія — найважче питання
- **Симптом без стратегії:** capital залипає у scam-token або потрапляє в "dump after pump".
- **Мітигація — 3-layer exit:**
  1. **Time-based:** hard `max_hold_blocks = 200` (≈400s на Base) — primary safety.
  2. **TWAP profit-take:** sell 50% коли realized_profit > target, решта на trailing-stop.
  3. **Emergency exit:** на будь-який revert/honeypot-trigger → market dump на 100% позиції з max slippage.
- **Перевірка:** unit tests для всіх 3 exit paths; chaos test: simulate 100 random price paths.

#### Проблема В: Slippage prediction для нової пари
- **Симптом:** price impact для $100 trade на свіжому пулі може бути 10–50%.
- **Мітигація:**
  - Constant-product math з poll-time reserves (для V2/Aerodrome).
  - Conservative buffer: actual_max_slippage = predicted_slippage × 2.0.
  - Per-pool circuit breaker: якщо realized_slippage > 3× predicted → blacklist pool.
- **Перевірка:** symbolic test + replay test проти історичних trades.

#### Проблема Г: Stable-stable arb потребує іншої логіки
- **Контекст:** не "snipe-and-exit", а "fill-on-spread-and-flip".
- **Мітигація:**
  - Окремий module `strategy/stable_pair_arb.py` (не плутати з sniper).
  - Trigger: `spread_bps > 30` (after fees) на pre-defined pair list.
  - Roundtrip-atomic execution (обидві ноги в одній tx через swap router або flash loan).
- **Перевірка:** paper soak — ≥2 fills/24h на cbETH/WETH або USDC/USDbC.

### 2.3. Кроки реалізації

| День | Task | Файли | Deliverable |
|---|---|---|---|
| 11 | `strategy/sniper_entry_decision.py` — 4-phase decision engine | + module | Replay 50 historical pools, ≥10% trigger rate |
| 12 | `strategy/sniper_exit_strategy.py` — 3-layer exit | + module | Unit tests: 100 random price paths, no infinite holds |
| 13 | Slippage predictor + circuit breaker | `execution/slippage_guard.py` | Test: catch 3× over-prediction |
| 14 | Mirror-pool search integration з existing scout | `discovery/mirror_finder.py` | Mock-test: identify Uniswap V3 mirror within 60s |
| 15 | `strategy/stable_pair_arb.py` — окремий модуль | + module | Spread detector + roundtrip planner |
| 16 | Stable-pair config: `config/stable_pairs.yaml` (cbETH/WETH, USDC/USDbC, wstETH/ETH, eUSD/USDC) | + config | Loaded into scout |
| 17 | Paper-execution simulator (no signing, just compute would-be PnL) | `execution/paper_signer.py` extend | Per-event: store sim result у sniper artifact |
| 18 | Telemetry expansion: per-snipe trace (decision → entry → exits → PnL) | `monitoring/sniper_telemetry.py` | Dashboard endpoint `/api/m8/snipes_history` |
| 19 | Integration test: end-to-end mock snipe (event → decision → entry → exit) | `tests/unit/test_phase2_e2e.py` | Profitable sim path + losing sim path |
| 20 | 24-hour paper soak | runtime | Real factory events, paper executions |

### 2.4. На чому акцентувати

1. **Decision engine — найбільше тестування.** Це місце де ми вирішуємо "yes/no" — баг тут = втрата $$$.
2. **Conservative bias.** Краще пропустити 5 profitable snipes ніж зайти в 1 honeypot. Precision/safety > recall у Phase 2.
3. **Per-snipe trace.** Кожен decision має full audit trail у JSON — потрібно для аналізу.
4. **Stable-pair НЕ ділить state з sniper.** Це окремий стрім, своя черга, свої метрики.

### 2.5. Перевірки на цьому етапі

| Перевірка | Команда | Очікуваний результат |
|---|---|---|
| Unit suite | `py -3.11 -m pytest tests/unit -q` | All pass |
| Phase 2 contract tests | `py -3.11 -m pytest tests/unit/test_phase2_*.py -v` | ≥20 tests pass |
| Historical replay | `py -3.11 scripts/sniper_replay.py --hours 168` | Trigger rate ≥10%, sim profitable rate ≥30% |
| 24h paper soak | target CLI: `py -3.11 scripts/start_nonstop_runtime.py --sniper-mode --hours 24` | ≥1 snipe sim profit > 0, ≥2 stable fills |
| Dashboard | `GET /api/m8/snipes_history` | Returns ≥1 snipe event з full trace |

### 2.6. Критерії успіху Phase 2
- [ ] 24h paper soak: `snipe_simulated_total ≥ 5`, `snipe_simulated_profitable ≥ 1`
- [ ] Stable-pair anchor: `stable_pair_fills ≥ 2` за 24h
- [ ] Чітка таксономія reject-причин (`why_not_snipe` analog of `why_not_active`)
- [ ] Жодного infinite-hold у sim (max_hold_blocks ALWAYS triggers)
- [ ] Total ≥60 unit tests (cumulative across phases) — все green
- [ ] DEV_REPORT update з Phase 2 metrics

---

## PHASE 3 — Production-Ready (Тижні 5–6)

### 3.1. Цілі фази
Перший real-capital trial з **$200–$500**. Фокус на operational discipline: telemetry, backout policy, kill-switch responsiveness.

### 3.2. Очікувані проблеми та як їх вирішувати

#### Проблема А: Real-tx revert rate може бути високий
- **Контекст:** на свіжих пулах nonce-конкуренція, gas-price race, MEV-frontrun від інших sniper-bots.
- **Мітигація:**
  - **Priority fee dynamic adjustment:** на Base priority_fee = base_fee × 1.5 (per-block).
  - **Tx replacement strategy:** якщо stuck > 5s, replace з вищим fee.
  - **Per-pool revert tracking:** якщо ≥3 reverts на цьому pool → blacklist pool на 1h.
- **Перевірка:** Phase 3 soak — `tx_revert_rate < 30%`. Якщо вище — назад у Phase 2 і tuning.

#### Проблема Б: Wallet/keystore безпека
- **Критичність:** Phase 3 — це перші real-keys в production.
- **Мітигація:**
  - Окремий "trading wallet" з обмеженим капіталом ($500 max).
  - НІКОЛИ не commit-ити `.env` з private key.
  - Key зберігається у OS keyring (Windows Credential Manager) або encrypted file.
  - **Max-loss circuit:** hard cap `daily_max_loss_usd = $50` — після перевищення kill-switch trips.
- **Перевірка:** keyring read test (без logging key); audit що `.env` у `.gitignore`.

#### Проблема В: Slippage realized vs predicted розходиться
- **Симптом:** в paper було fine, у real — losses через slippage.
- **Мітигація:**
  - Telemetry `slippage_delta_bps = realized - predicted`, per-snipe.
  - Якщо median(slippage_delta_bps) > 20 bps за останні 10 snipes → автоматичний downsize × 0.5.
  - Окрема reject reason `slippage_predicted_too_high` блокує entry якщо predicted > threshold.
- **Перевірка:** daily report містить slippage histogram.

#### Проблема Г: Backout policy false positives
- **Симптом:** 3 LOSS in row → stop. Але losses можуть бути random; ми зупиняємось не помилково.
- **Мітигація:**
  - **Statistical backout:** не "3 losses in row", а "if cumulative_pnl_24h < -$30 OR loss_streak ≥ 5".
  - Manual override через `data/runs/_rolling/kill_switch_override.json` (вручну).
  - Auto-resume через 4h cooldown після backout.
- **Перевірка:** chaos test — simulate 100 random outcome sequences, перевірити що backout trigger rate < 10% при true win-rate 50%.

### 3.3. Кроки реалізації

| День | Task | Файли | Deliverable |
|---|---|---|---|
| 21 | Real-signing integration: secp256k1 signer + nonce manager | `execution/real_signer.py` | Test: sign known tx, validate hash |
| 22 | Priority fee strategy + tx replacement | `execution/tx_submitter.py` | Test: simulate stuck tx → replace |
| 23 | Keyring integration + safe key loading | `execution/key_manager.py` | Test: load key from keyring, never log |
| 24 | Max-loss circuit + daily-loss tracker | `execution/risk_limits.py` | Test: trip on $50 daily loss |
| 25 | M8 execution gate offline | `scripts/ci_m8_gate.py` | Validates sniper artifacts |
| 26 | M8 execution gate online stub | + online mode | Reads real wallet, no execution |
| 27 | Telemetry: slippage_delta tracking + downsize hook | extend `sniper_telemetry.py` | Auto-downsize on threshold |
| 28 | Backout policy: statistical + manual override | `execution/backout_policy.py` | Chaos test 100 sequences |
| 29 | Pre-production dry run: $200 wallet, 8h soak, sign-but-not-broadcast | runtime | Logs show signed tx hashes, 0 broadcast |
| 30 | First real soak with $200 capital, 4h | runtime | ≥1 real snipe, ≥0 net loss |

### 3.4. На чому акцентувати

1. **Security > Performance.** Real keys — це red zone. Будь-яка оптимізація що зменшує security review — відхиляється.
2. **Telemetry density.** Кожна snipe має 20+ полів у trace. Інакше неможливо debug post-mortem.
3. **Reversibility.** Будь-який Phase 3 feature має ENV flag для відключення.
4. **Daily reports.** В кінці кожного дня — JSON summary з PnL, win-rate, slippage histogram.

### 3.5. Перевірки на цьому етапі

| Перевірка | Команда | Очікуваний результат |
|---|---|---|
| Full unit suite | `py -3.11 -m pytest tests/unit -q` | All pass (≥100 нових tests) |
| M8 gate offline | `py -3.11 scripts/ci_m8_gate.py --offline` | PASS |
| Key security audit | manual review `.env`, `.gitignore`, logs | No key leakage |
| Dry-run sign-only soak (8h) | target CLI: `--phase=3-dry-run` | All signs valid, 0 broadcasts |
| First real $200 soak (4h) | target CLI: `--phase=3-real --max-capital 200` | net_pnl_usd ≥ -$20 learning budget; M8 close-out still requires net_pnl_usd ≥ 0 |
| Backout chaos test | `pytest tests/unit/test_backout_chaos.py` | Trigger rate < 10% on 50% win-rate sims |

### 3.6. Критерії успіху Phase 3
- [ ] M8 gate offline + online PASS
- [ ] $200 wallet 4h real soak: ≥1 real snipe виконано (filled, not reverted)
- [ ] `tx_revert_rate < 30%`
- [ ] `slippage_delta_bps` median < 20 bps
- [ ] Backout policy не trigger-ив помилково
- [ ] Daily report JSON генерується автоматично
- [ ] Жодного key leakage в логах (audit pass)

---

## PHASE 4 — Scale (Тижні 7–8)

### 4.1. Цілі фази
Перехід на **private RPC** + **private orderflow** + **поступовий capital scaling** $500 → $2000 → $10000.

### 4.2. Очікувані проблеми та як їх вирішувати

#### Проблема А: Private RPC vendor lock-in / outages
- **Мітигація:**
  - Multi-provider: Alchemy primary + QuickNode backup.
  - Health-score routing (вже є патерн у `chains/providers.py`).
  - Daily cost cap (Alchemy має quotas): hard `daily_request_limit = 90% of plan`.
- **Перевірка:** kill primary RPC mid-soak → backup підхоплює <5s.

#### Проблема Б: Flashbots Protect / MEV-Share integration складна
- **Мітигація:**
  - Coinbase MEV-Share для Base — найпростіший шлях (HTTPS endpoint).
  - Не намагатися робити custom relayer — використати готові SDK.
  - Fallback на public mempool якщо private submit fail-ed.
- **Перевірка:** test що submit-ed bundle включений (через `eth_getTransactionByHash` після N blocks).

#### Проблема В: Capital scaling triggers different MEV behavior
- **Симптом:** при $2k snipe інші sniper-боти стають агресивніші, frontrun rate росте.
- **Мітигація:**
  - Поступовий ramp: $500 → пауза 3 дні → $1000 → пауза 3 дні → $2000.
  - Per-scale metrics: track revert_rate, slippage_delta, win_rate as function of size.
  - Auto-rollback: якщо metrics gracefully degrade на scale-up → повернутись на попередній level.
- **Перевірка:** scaling decision tree автоматизована, не ручне рішення.

#### Проблема Г: Operational stability на 7-day continuous
- **Мітигація:**
  - Memory leak monitoring (RSS per process через `psutil`).
  - Auto-restart on crash (supervisor вже є).
  - Daily heartbeat artifact `m8_daily_health.json`.
  - Pager alert (Discord webhook або Telegram) на критичні events.
- **Перевірка:** 7-day soak без manual intervention.

### 4.3. Кроки реалізації

| День | Task | Файли | Deliverable |
|---|---|---|---|
| 31 | Alchemy + QuickNode provider integration | extend `chains/providers.py` | Multi-provider self-test |
| 32 | Cost-cap circuit (daily request limit) | `core/rpc_rate_limiter.py` | Test: trip on 90% quota |
| 33 | Coinbase MEV-Share integration | `execution/mev_share_submitter.py` | Submit test bundle, validate inclusion |
| 34 | Fallback chain: MEV-Share → public mempool | `execution/tx_submitter.py` | Chaos test: MEV-Share down → fallback works |
| 35 | Capital scaling auto-decision module | `strategy/capital_scaler.py` | Decision tree test |
| 36 | Memory/CPU monitoring + auto-restart | `scripts/start_nonstop_runtime.py` extend | Test: kill -9 child → restart |
| 37 | Alert webhook (Discord/Telegram) | `monitoring/alerts.py` | Test: trigger alert on backout |
| 38 | Daily health artifact | `monitoring/daily_health.py` | Schema validation |
| 39 | M8 close-out gate (strict mode) | `scripts/ci_m8_gate.py` extend | Validates 7-day evidence |
| 40 | **7-day continuous production soak** | runtime | Final acceptance evidence |

### 4.4. На чому акцентувати

1. **Operational maturity > new features.** Phase 4 = "production hardening", не "new logic".
2. **Cost monitoring.** Alchemy/QuickNode quotas можуть exhaust і потягти $$$.
3. **Alerts must not become noise.** Threshold tuning critical — alert fatigue вбиває reliability.
4. **Scaling decisions = data-driven.** Жоден step-up без metrics evidence.

### 4.5. Перевірки на цьому етапі

| Перевірка | Команда | Очікуваний результат |
|---|---|---|
| Full unit suite | `py -3.11 -m pytest tests/unit -q` | All pass |
| M8 strict gate | `py -3.11 scripts/ci_m8_gate.py --strict --window 7d` | PASS |
| Provider failover test | manual: kill primary | <5s failover |
| MEV-Share inclusion test | test bundle submit | Included within N blocks |
| Memory soak 24h | `monitoring/daily_health.json` | RSS growth < 100MB |
| **7-day production soak** | continuous | Hits all success criteria below |

### 4.6. Критерії успіху Phase 4 = M8 Close-out
- [ ] 7 days continuous operation, **zero manual restarts**
- [ ] ≥10 real snipes виконано за тиждень
- [ ] `net_pnl_usd ≥ $0` over 7 days
- [ ] Stable-pair anchor: ≥$20 net за 7 днів
- [ ] `tx_revert_rate < 20%`
- [ ] Private RPC failover triggered ≥1 time без impact
- [ ] No security incidents (key leakage, unauthorized access)
- [ ] DEV_REPORT final M8 section + `docs/status/Status_M8.md` created
- [ ] Roadmap.md M8 marked CLOSED, M9 (Cross-chain) unlocked для R&D

---

## Cross-Phase Quality Gates

Кожна фаза має пройти **gating checklist** перед стартом наступної:

| Gate | Phase 1 → 2 | Phase 2 → 3 | Phase 3 → 4 |
|---|---|---|---|
| Unit tests green | pass: ≥30 new | pass: ≥20 new | pass: ≥20 new |
| Soak evidence | 4h listener-only | 24h paper | 4h real |
| DEV_REPORT updated | pass | pass | pass |
| Status doc updated | `docs/status/Status_M8.md` | `docs/status/Status_M8.md` | `docs/status/Status_M8.md` |
| Schema contract (if changed) | `schema_revision` update + golden fixture | `schema_revision` update + golden fixture | `schema_revision` update + golden fixture |
| No critical issues open | pass | pass | pass |
| Team review pass | pass | pass | pass |

---

## Anti-Patterns (чого НЕ робимо)

1. **Не skip-аємо Phase 1 listener-only soak.** Спокуса "одразу торгувати" → катастрофічна.
2. **Не агрегуємо stable-pair logic у sniper module.** Це два різні стріми; змішування створить bugs.
3. **Не комітимо real run artifacts** під `data/runs/**` (тільки rolling overwrite).
4. **Не змінюємо honeypot threshold "щоб більше торгувати"** — це шлях у scam trap.
5. **Не scale capital по emotion** — тільки після проходження scaling decision tree.
6. **Не реалізуємо exotic ніші (#4-#7 з ranked matrix) під час M8.** Це для post-M8 R&D.

---

## Швидке посилання — артефакти, які потрібно перевіряти

| Артефакт | Час оновлення | Інспекція |
|---|---|---|
| `data/runs/_rolling/new_pool_sniper_latest.json` | per-event | `Get-Content ... | ConvertFrom-Json | Select-Object events_seen,candidates,sims` |
| `data/runs/_rolling/m8_daily_health.json` | 1× per day | RSS, uptime, alerts |
| `data/runs/_rolling/m8_stability_agg.json` | per-run aggregate | win-rate, slippage histogram |
| `docs/DEV_REPORT_LATEST.md` | end of each phase | Phase summary section |
| `docs/status/Status_M8.md` | end of each phase | Goal status + evidence links |

---

## Final Acceptance — що означає "M8 закрито"

M8 вважається успішно закритим **тільки за виконання ВСІХ умов**:

1. 7-day continuous production soak passed
2. `net_pnl_usd ≥ 0` over closure window
3. ≥10 real snipes + ≥3 stable-pair fills with audit trail
4. M8 strict gate PASS
5. Security audit pass (no key/secret leakage)
6. Full doc set updated (DEV_REPORT, Status_M8, STRATEGIC_PIVOT decision log)
7. Operational runbook documented (`docs/m8/RUNBOOK.md`)
8. Team Lead sign-off у Status_M8 (`goal_status: REACHED`)

Якщо хоч одна умова не виконана — M8 залишається IN_PROGRESS, незалежно від pytest/CI green.
