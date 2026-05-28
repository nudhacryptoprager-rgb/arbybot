# TODO — RPC та метрики: усунення блокерів без платних провайдерів

> Контекст: попередній огляд показав, що `qsr=0.20` на dRPC (Session 7) спричинений 429-throttle, а Alchemy `qsr=0.96` (Session 6) має квоти. Мета — досягти стабільних `qsr ≥ 0.95`, `multicall ≥ 0.95`, `data ≥ 0.95` **без платних RPC (Alchemy / dRPC paid / Tenderly)**, шляхом розподілу навантаження по 15+ безкоштовних публічних endpoints для Base.
>
> Джерело-істина: [docs/CURRENT_STRATEGY.md](docs/CURRENT_STRATEGY.md) (Крок 10 — secondary fanout, Крок 11 — adaptive multicall, Крок 12 — sniper events_potentially_missed).

---

## 1. Поточні блокери (з runtime evidence)

| # | Блокер | Категорія | Доказ | Файл | Статус |
|---|---|---|---|---|---|
| B1 | dRPC primary 429-storm → qsr=0.20 | INFRA | Session 7 rolling; online qsr=0.15, rpc_err=0.85 | `m9/graph_arb/provider_router.py` | **ПІДТВЕРДЖЕНО** |
| B2 | Тільки **2 endpoints** в router (primary+secondary) | INFRA | `_SECONDARY_ENV_VAR` map; extras_count=9 завантажено, failover BUG-N1 виправлено | `m9/graph_arb/provider_router.py:43-48` | **ІНФРА READY** |
| B3 | Sniper втрачає події під час `rpc_errors` без лічильника (`events_potentially_missed`) | DATA | `rpc_errors=160` Alchemy; поле є в коді, в online=None (BUG-N2 — ws_monitor=None) | `monitoring/sniper_funnel.py:419` | **PARTIAL** |
| B4 | Adaptive multicall EMA не логує `chunk_scale` в артефакт | DATA | `_adaptive_chunk_scale` глобальна; поле є у коді, online=None (BUG-N2) | `m9/graph_arb/multicall_snapshot.py:75` | **PARTIAL** |
| B5 | `record_success()` відсутній у runner (sweep telemetry некоректна) | DATA | dRPC ok=0, 429=9 — telemetry коректна після BUG-N1 fix | `m9/graph_arb/runner.py` | **RESOLVED** ✅ |
| B6 | Публічний Base RPC pool не активований за замовч. (тільки 1 fallback) | INFRA | extras=9 завантажено; `ARBY_USE_PUBLIC_POOL=1` активовано; BUG-N1 fix дозволяє failover | `core/rpc_urls.py:55` | **ACTIVATED** ✅ |

---

## 2. Безкоштовні Base RPC endpoints для полістичного fanout

> Дослідження через chainlist.org/chain/8453 + docs.base.org. Усі endpoints без API key.

| Endpoint | Провайдер | Очікувана латентність | Throttle policy |
|---|---|---|---|
| `https://mainnet.base.org` | Base team (офіційний) | ~250-400 ms | м'який — best-effort |
| `https://base-rpc.publicnode.com` | PublicNode (Allnodes) | ~150-250 ms | дуже м'який |
| `https://base.llamarpc.com` | LlamaNodes | ~200-300 ms | м'який |
| `https://1rpc.io/base` | 1RPC (privacy-focused) | ~200-400 ms | помірний |
| `https://base.blockpi.network/v1/rpc/public` | BlockPI | ~150-250 ms | м'який |
| `https://base.meowrpc.com` | MeowRPC | ~200-350 ms | м'який |
| `https://base.drpc.org` | dRPC public tier | ~200-400 ms | агресивний 429 |
| `https://endpoints.omniatech.io/v1/base/mainnet/public` | Omnia | ~250-400 ms | помірний |
| `https://base-pokt.nodies.app` | Nodies (POKT) | ~200-350 ms | м'який |
| `https://rpc.therpc.io/base` | TheRPC | ~250-400 ms | помірний |
| `https://base.rpc.subquery.network/public` | SubQuery | ~250-400 ms | помірний |
| `https://base-mainnet.public.blastapi.io` | BlastAPI | ~250-400 ms | м'який |

**Загальний агрегат:** при rotation по 6-8 endpoints і обмеженні 5 RPS/endpoint, ефективний throughput ≈ 30-40 RPS без жодного API key.

---

## 3. План впровадження (фази, з проміжним контролем)

### Фаза 1 — Інфраструктура router (мінімальна, backward-compatible)

| Крок | Зміна | Файл | Тест |
|---|---|---|---|
| 1.1 | Додати `_PUBLIC_HTTP_FALLBACKS` (список 8 безкоштовних endpoints для Base/Arbitrum) | `core/rpc_urls.py` | `tests/unit/test_public_http_fallbacks.py` |
| 1.2 | Додати helper `iter_public_http_fallbacks(network)` | `core/rpc_urls.py` | те ж |
| 1.3 | Розширити `ProviderRouter` — приймати `extras: list[str]` (tertiary+); fanout cycle при exhaustion primary+secondary | `m9/graph_arb/provider_router.py` | `tests/unit/test_provider_router_pool.py` |
| 1.4 | `ProviderRouter.from_env` зчитує `BASE_RPC_POOL` (comma-separated) + автоматично додає `iter_public_http_fallbacks` якщо `ARBY_USE_PUBLIC_POOL=1` | `m9/graph_arb/provider_router.py` | те ж |

**Проміжний контроль 1:** `python -m pytest tests/unit/test_provider_router_pool.py tests/unit/test_public_http_fallbacks.py -q`

### Фаза 2 — Sniper events_potentially_missed (Крок 12 з CURRENT_STRATEGY)

| Крок | Зміна | Файл | Тест |
|---|---|---|---|
| 2.1 | У `SniperFunnel.snapshot()` додати поле `events_potentially_missed` = `sum_per_dex(dex_errors[d] * avg_logs_per_poll[d])` | `monitoring/sniper_funnel.py` | `tests/unit/test_sniper_events_missed.py` |

**Проміжний контроль 2:** `python -m pytest tests/unit/test_sniper_events_missed.py -q`

### Фаза 3 — Експозиція adaptive chunk_scale в артефакт (видимість Кроку 11)

| Крок | Зміна | Файл | Тест |
|---|---|---|---|
| 3.1 | Додати `get_adaptive_chunk_scale()` exportable getter | `m9/graph_arb/multicall_snapshot.py` | `tests/unit/test_multicall_chunk_visible.py` |

**Проміжний контроль 3:** `python -m pytest tests/unit/test_multicall_chunk_visible.py -q`

### Фаза 4 — Інтеграційна перевірка

**Контроль 4:** `python -m pytest tests/unit -q` (всі 6146+ тестів мають пройти)

---

## 4. Очікувані метрики після впровадження

| Метрика | До | Після Фази 1-4 (offline) |
|---|---|---|
| `qsr` на free pool | 0.20 (Session 7 dRPC) | ≥ 0.85 |
| `provider_router.providers` count | 1-2 | 6-10 |
| `events_potentially_missed` (M8) | відсутнє | експортується |
| Тести | 6146 PASS | 6149+ PASS |

---

## 5. ENV-змінні (нові)

```
# Розділені комою додаткові endpoints. Якщо порожньо — використовується тільки primary+secondary.
BASE_RPC_POOL=https://base.llamarpc.com,https://base.blockpi.network/v1/rpc/public,https://1rpc.io/base

# Опціонально: автоматично долити публічні fallbacks з _PUBLIC_HTTP_FALLBACKS у router pool.
ARBY_USE_PUBLIC_POOL=1
```

---

## 6. Обмеження (що НЕ робимо)

- **НЕ** змінюємо публічний API `ProviderRouter.__init__` без backward-compat (новий kwarg `extras=None`).
- **НЕ** видаляємо існуючі поля у funnel snapshot.
- **НЕ** додаємо нові залежності (тільки stdlib).
- **НЕ** торкаємось `kill_switch_active` / execution gates (kill switch ON залишається).
