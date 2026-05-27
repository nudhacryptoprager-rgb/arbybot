# Current Strategy Alignment

> Цей документ фіксує поточне стратегічне вирівнювання без зміни `Roadmap.md`.
> `Roadmap.md` залишається верхньорівневим source of truth.
> Цей файл пояснює, як поточні гілки `M8`, `M8_1`, `M9` складаються в одну операційну логіку, які адаптери реально працюють, які блокери залишилися і яким буде покроковий план дій.

---

## 0. Активний Напрямок

**Поточний головний напрямок (оновлено):**

`M9_GRAPH_LONG_TAIL_SHADOW` + `M8_FRESH_LISTING_CAPTURE` (паралельний трек).

**Причини зміщення фокусу з попередньої редакції:**
- bridge M8 → M9 нарешті відкритий (`graph_ready_from_m8 > 0` на Alchemy run);
- **головний залишковий блокер економіки — структурний:** свіжі пули M8 на 90%+ — це Uniswap V4, і покриття DEX'ів з ортогональними моделями ціноутворення занадто вузьке, щоб давати спред;
- stable-stable і LST lanes досі не дають standalone proof;
- graph search готовий до multi-venue cycles, але без розширення DEX-палітри (V4-hooks, stable curves, PMM, RFQ, directional) cost-adjusted net залишатиметься близьким до нуля.

---

## 1. Пройдений шлях (з моменту попередньої редакції)

### 1.1. M8 (new-pool sniper)
- **Раніше:** не було стабільного listener'а, тільки HTTP poll Uniswap V2/V3 PairCreated.
- **Зроблено:** додано WS-listener (`m8/runtime/ws_listener.py`), парсинг Uniswap V4 PoolManager `Initialize` events, Aerodrome Slipstream PoolFactory, PancakeSwap V3, SushiSwap V2/V3, BaseSwap V2.
- **Артефакт:** `data/runs/_rolling/new_pool_sniper_latest.json` (`schema_revision=phase2.0`).
- **Поточний стан:** на Base за ~15 хв ловиться 100-120 подій; ~95% це Uniswap V4 + ~5% V2.
- **Залишений ризик:** rpc_errors під Alchemy показують 160 → factory poll частково втрачає події (silent drop, потрібен лічильник `events_potentially_missed`).

### 1.2. M8.1 (stable-anchor refresh)
- **Раніше:** окремий profit lane (stable-stable + LST).
- **Зроблено:** перероблено в **inventory / diagnostics layer**: видає active routes, quote health, coverage ranking, size frontier, pool quarantine.
- **Артефакт:** `data/runs/_rolling/m8_1_stable_anchor_latest.json` (`schema=m8_1.6`).
- **Поточний стан:** `quote_success_rate=0.8897`, `rpc_error_rate=0.1103` (на межі порогу 0.10).
- **Висновок:** standalone proof lane мертва, але як інфраструктурний шар працює.

### 1.3. M9 (graph-arb shadow)
- **Раніше:** topology працював, але не міг споживати M8 events (bridge порожній).
- **Зроблено:**
  - `bridge_builder.py` тепер мапить 9 DEX ID → adapter types (включно з `_PENDING_ADAPTER_TYPES = {balancer_stable, balancer_weighted}`; V4 переведено в production у Session 6);
  - cycle scheduler з hot/cold partitioning, RPC-error demotion, adaptive history;
  - cost-model з cost-adjusted `net_bps`;
  - hardened multi-venue gate (рахує лише quoteable dex_ids).
- **Поточний стан (Session 6, 2026-05-27, Alchemy):**
  - `qsr=0.96`, `multicall_success_rate=1.0`, `data_completeness=1.0`, `runtime_gates.all_pass=True`;
  - `cycles_with_m8=92` (M8 fluent у графі);
  - але `positive_cycles_with_m8_pool=0` → економіка ще не виграна;
  - `goal_status=BLOCKED` на `M8 multi-venue proof` + `positive_cycles_with_m8_pool > 0`.

### 1.4. Загальний прогрес від попередньої редакції
| Категорія | Було | Стало |
|---|---|---|
| Bridge M8→M9 | порожній | заповнений (`graph_ready_from_m8 > 0`) |
| V4 quoter | відсутній | hooks==0x0 path ✅ |
| Cost model | не застосовано | `cost_model_applied=true` |
| Multi-venue gate | приймав symbol collisions | рахує лише quoteable dex_ids |
| RPC infra | один Alchemy без fallback | A/B test проведено (dRPC vs Alchemy); secondary-rpc patterns відомі |
| DEX покриття | uniswap_v2/v3, ve33 (volatile), aerodrome_slipstream | + uniswap_v4 (no-hook), готовність до balancer/curve adapters |

---

## 2. Чому M8/M8.1 ↔ M9 досі не дає прибуткового циклу

Bridge відновлено, runtime gates зелені. Залишилось **три** структурні причини відсутності `positive_cycles_with_m8_pool`:

1. **Топологія DEX-моделей одноманітна.** Усі поточні quoteable adapters — це варіанти CPMM (x·y=k) або CLMM (tick math). Між ними спред мінімальний, бо вони реагують на ринок схожою кривою. Свіжий V4-пул проти V3-пулу дає різницю в межах ~2-5 bps, а cost ≈ 11 bps з'їдає net.
2. **Свіжий M8-токен майже завжди має лише одне venue в першу годину.** Multi-venue gate (структурно правильний для стійкості) ріже tail-токени, поки MEV-bots їх знаходять і вирівнюють.
3. **Cost model не диференційована за DEX-сімейством.** 11 bps константа занадто оптимістична для V4-hooks (gas) і занадто песимістична для Curve stable (slippage <1 bps), Aerodrome stable (~4 bps), RFQ (0 bps slippage за межами quoter quote).

> **Висновок:** Прорив = **ортогональні pricing-моделі** (stable curve, PMM, RFQ, hooks-dynamic-fee, directional) + **time-gated relax** single-venue policy для перших 30 хв життя пулу + **per-adapter cost model**.

---

## 3. Якісне розширення покриття DEX'ів з ортогональною моделлю ціноутворення

> Принцип: чим більше різних математичних моделей реагують на той самий ринковий рух, тим більше тимчасових спредів виникає на межах між ними. Це і є джерело long-tail arbitrage.

### 3.1. Карта моделей ціноутворення

| Сімейство | Формула / механіка | Реакція на свіжий токен | Орієнтовний spread proxy* |
|---|---|---|---|
| **CPMM** (Uniswap V2, BaseSwap, SushiSwap V2) | `x·y = k`, fee 30 bps | повільна, лінійна | baseline |
| **CLMM** (Uniswap V3, PancakeSwap V3, Aerodrome Slipstream) | tick liquidity, активний діапазон | швидка коли ціна в діапазоні, нульова поза | ±2-5 bps vs CPMM |
| **Solidly stable** (Aerodrome stable pool, Velodrome) | `x³y + xy³ = k` | майже плоска біля peg | ±10-30 bps vs CPMM на peg-токенах |
| **Curve StableSwap** | hybrid: `An·Σxᵢ + D = An·D + Dⁿ⁺¹/(nⁿ·Πxᵢ)` | дуже плоска, потім різко крута | ±5-20 bps vs CPMM на стейблах |
| **Balancer Weighted** | `Πxᵢ^wᵢ = k`, ваги 80/20, 60/40 | асиметрична до ваги | ±20-50 bps структурний |
| **Maverick directional** | LP вибирає Right/Left/Both/Static; liquidity slide за ціною | створює temporary depegs при тренді | ±15-40 bps під час руху |
| **Uniswap V4 hooks (dynamic fee)** | hook змінює fee/curve в runtime | fee може стрибати з 1 до 100 bps | ±5-100 bps залежно від hook |
| **DODO PMM** | оракул-based mid + slippage factor `k` | reacts to oracle, не AMM | ±5-30 bps під час лагу оракула |
| **Hashflow/Bebop RFQ** | off-chain quote, on-chain settle | непомітна для CFMM | спред з'являється на CFMM↔RFQ |
| **Fluid** | smart debt + smart collateral (lending+AMM) | ціна впливається utilisation rate | ±10-25 bps під час borrow shocks |

*Spread proxy — приблизне очікуване відхилення проти baseline CPMM під час нормальної волатильності.

### 3.2. Пріоритезований план розширення покриття

| Пріоритет | Adapter | Pricing model | Чому критично саме зараз |
|---|---|---|---|
| **P0** | `uniswap_v4_with_hooks` (whitelist popular hooks) | hooks-dynamic | 90% свіжих M8-подій — це V4; no-hook вже працює, треба whitelist hooks |
| **P0** | `aerodrome_stable` (гілка в `ve33.py`) | Solidly stable curve `x³y+xy³=k` | відкриває peg-арбітраж (USDC/USDe/EURC/cbBTC) — найдешевша leg для cycle exit |
| **P1** | `curve_stableswap` adapter | hybrid stable invariant | Curve на Base $651k/24h; стабільний quote, низький slippage |
| **P1** | `maverick_v2` adapter | directional liquidity | створює структурні temporary depegs під час тренду |
| **P2** | `balancer_v2_v3_query` | weighted + boosted-stable | unblock `_PENDING_ADAPTER_TYPES` |
| **P2** | `pancakeswap_infinity_clmm` | CLMM з гібридним рутером | diff +/-3 bps на тих же парах |
| **P3** | `fluid_smart_pool` | lending-AMM | сезонні арбітражі при borrow shocks |
| **P3** | `solidly_v3` (Base) | ve(3,3) + CLMM | гібридна модель |
| **P4** | `dodo_pmm_v2` | oracle PMM | реактивний на oracle lag |
| **P4** | `hashflow` / `bebop` / `native_rfq` | RFQ off-chain | quote, не AMM — окрема поверхня цін |

> Адаптери P0+P1 покривають >95% обсягу торгів на Base (підтверджено CoinGecko/DefiLlama) + дають 4 ортогональні криві (CPMM, CLMM, Solidly stable, Curve hybrid, directional, V4-hooks). Цього достатньо для прориву економіки.

---

## 4. Покрокова імплементація плану

> Кроки в порядку виконання. Кожен крок самодостатній, з ресурсами, артефактом-доказом і командою перевірки. Жоден крок не вмикає real execution — kill switch ON залишається до кроку 14.

### Phase A — Розблокування економіки (1-2 тижні)

**Крок 1. Per-adapter cost model**
- Файл: `m9/graph_arb/cost_model.py` (новий або існуючий).
- Зміна: hard-coded `cost_bps=11` → `cost_by_adapter` мапа `{uniswap_v3: 8, uniswap_v4_nohook: 10, uniswap_v4_hook: 14, ve33_volatile: 12, ve33_stable: 4, aerodrome_slipstream: 9, curve_stable: 3, balancer_weighted: 10, maverick_v2: 9, dodo_pmm: 6, rfq: 2}`.
- Тест: `tests/unit/test_cost_model_per_adapter.py` — перевірити кожний ключ.
- Артефакт-доказ: `m9_graph_latest.json` → `cost_breakdown_by_adapter` non-null.

**Крок 2. Time-gated single-venue policy**
- Файл: `m9/graph_arb/bridge_builder.py:185-210`.
- Зміна: якщо `pool_age_seconds < 1800` і token має 1 quoteable venue + anchor token (WETH/USDC) — пропустити в граф з marker `freshness_window=True`.
- Тест: `tests/unit/test_time_gated_single_venue.py`.
- Артефакт-доказ: bridge_inventory → `fresh_window_admitted_count > 0`.

**Крок 3. Token price refresh з CoinGecko**
- Файл: `config/token_prices.yaml` (новий), `m9/graph_arb/runner.py` (видалити `_TOKEN_PRICE_USD_BASE`).
- Зміна: 5-хвилинний refresh через free CoinGecko API; fallback на yaml.
- Тест: mock CoinGecko response.
- Артефакт-доказ: `m9_graph_latest.json.token_prices_source = "coingecko"|"yaml_fallback"`.

**Крок 4. MEV-untouched freshness score**
- Файл: `m9/graph_arb/cycle_scheduler.py` (новий компонент `_mev_untouched_bonus`).
- Зміна: при `pool_age < 1800` подивитися `eth_getLogs(Swap)` за останні 30 блоків; якщо немає відомих arb-routers (1inch, 0x, KyberSwap, відомі MEV builders) → `+10 score`.
- Whitelist arb-routers: окремий yaml `config/known_arb_routers.yaml`.
- Артефакт-доказ: scheduler dump → `mev_untouched_bonus_applied_count`.

### Phase B — Розширення DEX-палітри (2-4 тижні)

**Крок 5. Aerodrome stable curve (гілка в `ve33.py`)**
- Файл: `dex/adapters/ve33.py`.
- Зміна: `if pool.stable: use_stable_invariant_quote()` (формула `k = x³y + xy³`, ітеративне розв'язання).
- Тест: `tests/unit/test_ve33_stable_curve.py` з опорними значеннями з контракту Aerodrome.
- Артефакт-доказ: cycle з Aerodrome stable pool → quote success.

**Крок 6. Uniswap V4 hooks whitelist**
- Файл: `dex/adapters/uniswap_v4.py`.
- Зміна: `_KNOWN_HOOKS = {hook_addr: hook_type}` (no-fee-dynamic, no-impl-swap, simple-volatility-oracle). Не-whitelisted → quarantine.
- Тест: на mock hooks.
- Артефакт-доказ: `m8 → m9` свіжі V4 з whitelisted hooks приходять у граф.

**Крок 7. Curve StableSwap adapter**
- Файл: `dex/adapters/curve_stable.py` (новий).
- Зміна: прямий RPC до `get_dy(i, j, dx)` через Pool ABI; підтримка 2-, 3-, 4-coin pools.
- Тест: snapshot quote проти live Curve на Base.
- Артефакт-доказ: cycle через Curve pool у `m9_graph_latest.json.cycles_with_curve > 0`.

**Крок 8. Maverick V2 adapter**
- Файл: `dex/adapters/maverick_v2.py` (новий).
- Зміна: квоти через RouterV2 `calculateSwap()`; врахування directional mode pool'у.
- Тест: на snapshot quote.
- Артефакт-доказ: `cycles_with_maverick > 0`.

**Крок 9. Balancer Vault `queryBatchSwap`**
- Файл: `dex/adapters/balancer_vault.py` (новий).
- Зміна: один Vault contract → query всі pools (weighted + composable-stable) одним call.
- Перевести з `_PENDING_ADAPTER_TYPES`.
- Артефакт-доказ: `pending_adapter_count = 0`.

### Phase C — Інфраструктура для масштабу (1-2 тижні)

**Крок 10. Secondary RPC fanout обов'язковий**
- Файл: `m9/graph_arb/runner.py:228-235`.
- Зміна: `--strict-bridge` вимагає `BASE_RPC_SECONDARY`; race-fallback з 100 ms таймаутом, окрема rate-limit бухгалтерія per provider.
- Артефакт-доказ: `rpc_provider_stats` у infra_telemetry.

**Крок 11. Adaptive multicall chunk shrink**
- Файл: `m9/graph_arb/multicall_snapshot.py:164`.
- Зміна: якщо `success_rate < 0.85` за останні 60s → `chunk_scale *= 0.5`; якщо `> 0.95` → відновлення.
- Артефакт-доказ: `multicall_chunk_history` в artifact.

**Крок 12. Sniper events potentially missed counter**
- Файл: `m8/runtime/smoke_run.py`.
- Зміна: додати `events_potentially_missed` (factory error rate × очікуваний rate).
- Артефакт-доказ: `new_pool_sniper_latest.json` нове поле.

### Phase D — Економічний доказ (доки не PASS — sleep on it)

**Крок 13. Soak 24h з повним адаптерним набором**
- Команда:
  ```powershell
  .\.venv\Scripts\python.exe scripts/m9_rolling_orchestrator.py `
      --duration 86400 --secondary-rpc $env:BASE_RPC_SECONDARY `
      --strict-bridge
  ```
- Артефакт-доказ: `m9_stability_agg_24h.json` з `positive_cycles_with_m8_pool > 0` стійко в ≥3 sweeps.

**Крок 14. Real execution gate review (НЕ вмикати)**
- Файл: `docs/status/Status_M9.md` оновити.
- Передумови:
  - `positive_cycles_with_m8_pool > 0` стабільно;
  - router simulation для top 10 cycles;
  - honeypot/transfer-tax/transfer-restriction перевірки для long-tail tokens;
  - explicit human approval.

---

## 5. Ролі Шарів (без змін від попередньої редакції, з оновленням M9)

**`M8`**
- new-pool listener + discovery (фокус: Uniswap V4, Aerodrome Slipstream, V2/V3 на Base);
- видає fresh pool hints і route candidates;
- **не є** standalone profit claim.

**`M8_1`**
- config-driven inventory + diagnostics layer;
- видає active routes, quote health, coverage ranking, size frontier, pool quarantine;
- **не є** головною proof lane.

**`M9`**
- graph-arb shadow + execution-ready cost-adjusted economics;
- топологія розблокована, bridge заповнений;
- залишилось: positive `cycles_with_m8_pool` після кроків Phase A+B.

---

## 6. Карта Evidence (оновлено)

**Operational artifacts (rolling, перезаписуються):**
- `data/runs/_rolling/new_pool_sniper_latest.json`
- `data/runs/_rolling/m8_1_stable_anchor_latest.json`
- `data/runs/_rolling/m9_bridge_inventory_latest.json`
- `data/runs/_rolling/m9_graph_latest.json`
- `data/runs/_rolling/run_summary_latest.json`
- `data/runs/_rolling/m4_stability_agg.json`

**Inventory artifacts:**
- `data/tmp/m8_1_exotic_inventory_latest.json`
- `data/tmp/m9_shadow_inventory_with_gap_edges.json`
- `data/tmp/m9_depth_enriched_inventory.json`

**Status files:**
- `docs/status/Status_M8.md`
- `docs/status/Status_M8_1.md`
- `docs/status/Status_M9.md`

---

## 7. Поточне Читання Gates

**M8 listener gate:** discovery infrastructure usable; rpc_errors на Alchemy показують втрати — потребує counter (Крок 12).

**M8.1 lane gates:** inventory infrastructure usable; rpc_error_rate на межі (0.1103 vs 0.10 поріг) — secondary RPC (Крок 10) виправить.

**M9 graph gate:**
- Session 6 Alchemy: `qsr=0.96`, `multicall=1.0`, `data=1.0`, `runtime_gates.all_pass=True` ✅
- `cycles_with_m8=92` ✅
- `positive_cycles_with_m8_pool=0` ❌ — основний блокер до economic proof.

---

## 8. Production Policy (без змін)

Real execution залишається вимкненим. `kill_switch_active=true`, `execution_enabled=false`.

Перед будь-якою production discussion потрібні (повний список):
- positive-gross cycles у fresh multi-pair `M9` graph gate з участю M8-пулів;
- router simulation для top positive cycles;
- gas, fee, slippage, token-basis breakdown per adapter;
- honeypot, transfer-tax, transfer-restriction, liquidity safety gates для long-tail tokens;
- repeated short gates зі стабільною positive economics (мінімум 3 sweeps підряд);
- explicit human approval перед вимкненням kill switch.

---

## 9. Deprecated / Supporting Paths

Не вважати active profit proof:
- stable-stable two-leg arbitrage на Base;
- LST two-leg arbitrage на Base;
- single-pair gates як proof gates;
- old `M7` public-infrastructure backrun economics;
- standalone `M8` new-pool sniping без graph + risk + simulation confirmation.

---

## 10. Наступне Операційне Правило (оновлено)

Discovery має бути **спочатку широким, потім ranked, потім focused** + **DEX-palette diverse** + **time-gated for freshness**.

**Правильний flow:**
1. Розширити verified long-tail і exotic inventory (continue).
2. Додати ортогональні pricing-моделі (Phase B — кроки 5-9).
3. Побудувати або оновити graph inventory.
4. Запускати короткі multi-pair graph sweeps з per-adapter cost model.
5. Ранжувати cycles за cost-adjusted net, QSR, liquidity, freshness_score, mev_untouched_bonus.
6. Симулювати лише cycles з positive cost-adjusted net або credible near-breakeven economics.
7. Тримати real execution disabled до Phase D PASS + human approval.

---

## Додаток A — Джерела веб-дослідження (2026-05-27)

- **Uniswap V4 architecture** (`blog.uniswap.org/uniswap-v4`): hooks, singleton PoolManager, flash accounting, EIP-1153 transient storage, dynamic fees, TWAMM, custom oracles. Підтверджує, що V4 — це не один pricing model, а **сімейство** залежно від hook'а.
- **Maverick Protocol** (`docs.mav.xyz`): Dynamic Distribution AMM, directional liquidity modes (Right/Left/Both/Static). Створює "ціна слідує за trend'ом" — джерело тимчасових depegs.
- **DODO PMM** (`docs.dodoex.io/product/pmm-algorithm`): oracle-based mid-price + slippage factor `k`; формула концентрує liquidity навколо oracle quote.
- **CoinGecko Top Base DEXs by 24h volume** (2026-05-27 snapshot): Aerodrome Slipstream $434M (44.3%), Aerodrome Slipstream 3 $192M, PancakeSwap V3 $138M (14.1%), Uniswap V3 $125M (12.8%), Uniswap V4 $43M (4.4%, 16 554 пулів — найбільший за різноманіттям), Aerodrome V2 $17M, Hydrex Integral $5.6M, Balancer V2 $2.7M, PancakeSwap Infinity CLMM $2.5M, Curve $651k, Fluid $649k, Maverick V2 $182k. Підтверджує: P0+P1 покривають >95% обсягу.
- **DefiLlama Base DEX rankings**: Aerodrome (1 chain) $696M weekly, Uniswap (44 chains) $342M weekly, PancakeSwap $152M.

---

**Кінець документа.** Цей файл перезаписується (не версіонується), згідно `docs/DOCS_POLICY.md`.
