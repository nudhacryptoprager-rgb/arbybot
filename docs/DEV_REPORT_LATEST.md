# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
soak_id: M7.E1.34n-soak9
soak_started_at_utc: 2026-04-24T10:25:06Z
soak_ended_at_utc: 2026-04-24T10:55:10Z
mode: ONLINE (Base, 30 хв, strict provider + archive, premium only).
artifact_mode: rolling
run_dir reference: ci_m5_gate_arbitrum_one_20260417_145636_478653

## 1) Scope — soak9 (після відгуку "перевести Base на dRPC")
Зафіксовано дві зміни, потрібні після soak8:
- **Base WS/HTTP primary → dRPC** у `config/chains.yaml`.
- **Rate-limit-aware reconnect** у `m7/orderflow/mode_ws_live.py` з
  `ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S=30` + опт-аут Flashblocks WS
  через `ARBY_BASE_USE_FLASHBLOCKS_WS=0` (default).

## 2) Правки у цьому циклі
- `config/chains.yaml` → для `base`:
  `rpc_endpoints` primary тепер `https://base.drpc.org`
  (потім publicnode → mainnet.base.org → blastapi);
  `ws_endpoints` primary `wss://base.drpc.org` (потім publicnode →
  blastapi). Flashblocks preconf залишено лише як read-path.
- `m7/orderflow/mode_ws_live.py`:
  - Flashblocks WS як primary hot-WS тепер гейтиться env
    `ARBY_BASE_USE_FLASHBLOCKS_WS` (default 0). У default-гарячому шляху
    `resolve_rpc_ws(...)` бере перший `ws_endpoints` → dRPC.
  - Reconnect-гілка тепер детектує rate-limit signature
    (`"Too many request"`, JSON-RPC `code: 15`, HTTP 429, `"rate limit"`)
    і замість `min(8, 1.5^n)` використовує
    `ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S` (default 30 с),
    обмежене залишком `ws_timeout`.

## 3) Валідаційні гейти
- pytest: `py -3.11 -m pytest tests/unit -q` → **4255 passed, 6 skipped,
  1 warning** (стабільно від soak8).
- repo safety: `py -3.11 scripts\check_repo_safety.py` → **PASS, 0
  warnings** (усі 20 гейтів).

## 4) Повні метрики soak9
### 4.1 Supervisor (30 хв, end=2026-04-24T10:55:10Z)
- 5/5 лейнів живі; `crash_restarts=0/100`, `max_crash_restarts_hit=False`.
- cycles_completed: `m7_hot=0`, `m7_cold=1`, `m7_hot_discovery=0`,
  `m7_cold_discovery=1` → **2** рестарти. Soak7=69, soak8=8, soak9=**2**.
- **`m7_hot` і `m7_hot_discovery` відпрацювали весь 30-хв window на
  одному підпроцесі** — жодного exit до `Shutting down`.

### 4.2 Rollup PROD (session_id=b119a66d)
Session:
- `session_windows_seen=3`, `session_events_seen_total=132`
- `session_bridge_pool_hit_total=77`
- **`session_fast_path_scored_total=10`** (перший не-нуль за 3 прогони)
- `session_ws_reconnect_total=23`, `session_ws_recv_error_total=23`
- `session_ws_recv_timeout_total=0`, `session_ws_subscribe_total=24`
- `session_ws_connected_windows=3`, `session_ws_failed_windows=0`
- `session_exit_reason_histogram={recv_error_reconnect_failed:2, ws_timeout:1}`
- `last_exit_reason=ws_timeout` (здоровий timeout, не kill)

Кумулятив:
- `windows_seen=919`, `events_seen_total=2464`
- `fast_path_scored_total=657`, `fast_path_positive_total=67`
- `sim_attempted_total=961`, `sim_passed_total=245`
- `roundtrip_attempted_total=245`, `roundtrip_success_total=228`
- `strict_provider_breaches_total=15` (без +), `submit_ready_total=0`
- `bridge_hit_but_not_fast_scored = {windows:56, bridge_hits:141,
  reason_histogram:{HOT_SKIP_UNKNOWN_PAIR:38, TOKEN_ADDRESS_UNKNOWN:18}}`

### 4.3 Rollup DISC (session_id=50254bed)
Session:
- `session_windows_seen=3`, `session_events_seen_total=77`
- `session_bridge_pool_hit_total=57`
- `session_fast_path_scored_total=0`
- `session_ws_reconnect_total=17`, `session_ws_recv_error_total=17`
- `session_ws_subscribe_total=18`, `session_ws_failed_windows=0`
- `session_exit_reason_histogram={ws_timeout:1, recv_error_reconnect_failed:2}`

Кумулятив:
- `windows_seen=959`, `events_seen_total=2472`
- `fast_path_scored_total=668`, `sim_passed_total=223`,
  `roundtrip_success_total=213`, `strict_provider_breaches_total=11`
- `bridge_hit_but_not_fast_scored = {windows:79, bridge_hits:231,
  reason_histogram:{HOT_SKIP_UNKNOWN_PAIR:57, TOKEN_ADDRESS_UNKNOWN:22}}`

### 4.4 Delta soak8 → soak9
- Supervisor restarts: 8 → **2** (-75 %).
- PROD session_fast_path_scored: 0 → **10** (∞).
- PROD exit_reason: 23× recv_error_reconnect_failed → 2× fail + 1×
  `ws_timeout` (перший здоровий timeout за три прогони).
- `last_ws_recv_error` все ще містить `Too many request, code 15` — але
  це тепер dRPC (`wss://base.drpc.org`) під час `eth_subscribe`
  resubscribe; тобто code 15 — канонічний JSON-RPC rate-limit, а не
  ексклюзив Flashblocks preconf.

## 5) Інтерпретація
1. **dRPC+cooldown 30 с розблокував fast-path.** PROD вперше має
   session-level scoring ≠ 0. 10 scored за 3 вікна ≈ 3.3 per window —
   це вже funnel, який можна виміряти.
2. **Rate-limit не зник, але перестав бути смертельним.** dRPC теж
   видає JSON-RPC code 15 на `eth_subscribe`, але 30-с cooldown збігає
   з реальним вікном скидання → перепідключення проходить, цикл не
   вмирає. 23 reconnect-events на 3 вікна — dRPC WS throttle
   прокидається раз на ~1 хв.
3. **DISC session fast_path=0** зберігся. reason_histogram той самий —
   `HOT_SKIP_UNKNOWN_PAIR`/`TOKEN_ADDRESS_UNKNOWN`. Це P0.1 з soak8-
   плану (multicall token0/token1 у prewarm), WS тут ні до чого.
4. **Перший `last_exit_reason=ws_timeout` у PROD** за 3 прогони — цикл
   завершився по таймеру, а не через провал reconnect. Ключовий
   структурний маркер прогресу.

## 6) Залишкові проблемні місця
**6.1 dRPC WS rate-limit на `eth_subscribe`.** Координати:
`m7/orderflow/mode_ws_live.py` (reconnect branch). Симптом: 23 PROD +
17 DISC reconnect-events за 30 хв. Наслідок: 2× `recv_error_reconnect_failed`
у session-histogram (vs 23 у soak8 — падіння на порядок). Current
mitigation (30-с cooldown) достатній для виживання, але витрачає
реальний час, який можна було б віддати на scoring.

**6.2 Token-resolve все ще не готовий до hot-шляху (DISC).**
`HOT_SKIP_UNKNOWN_PAIR=57`, `TOKEN_ADDRESS_UNKNOWN=22` у DISC
reason_histogram. Це означає P0.1 з soak8 (multicall token0/token1 у
`_prewarm_registry_from_pairs`) залишається обов'язковим — без нього
DISC не піднімає session_fast_path_scored.

**6.3 `submit_ready_total=0`.** Очікувано (kill switch ON); не блокер.

## 7) Шляхи покращення (soak10 backlog)
**P0 — завершити розблокування до першого submit_ready:**
1. **Multicall token0()/token1() у `_prewarm_registry_from_pairs`**
   (soak8 P0.1, знову): зібрати `pool_address` з
   `bridge_hit_not_scored_sample[]` + `hot_event_pool_histogram`, batch
   multicall, посадити в `_pool_token_cache`+`token_addresses`. Ціль:
   `HOT_SKIP_UNKNOWN_PAIR`+`TOKEN_ADDRESS_UNKNOWN` → ~0 у обох лейнах.
2. **Додати paid Alchemy WS ротацію при 2-му rate-hit на dRPC.** Уже є
   `build_alchemy_ws_url("base", $ALCHEMY_API_KEY)` у `core/rpc_urls.py`
   — потрібно підключити як secondary у `_ws_tried_urls` з таймером
   повернення на dRPC (WS-session cost amortisation).

**P1 — підняти fast_path throughput:**
3. Зважити hot-bucket перед family-cap (soak8 fix #4 як було).
4. Гейт `sim_attempted` на rolling `fast_path_scored>=20` тепер має
   сенс — PROD session вже дає 10; соак10 з P0.1 має реально
   перетнути 20.

**P2 — спостережність:**
5. Dashboard panel для `session_ws_reconnect_total/recv_error_total/
   subscribe_total/last_ws_recv_error`.
6. Форензик `strict_provider_breaches_total` (15 PROD / 11 DISC у
   кумуляті, +0 у session — спадщина, треба окремий трейс).

## 8) Аудит файлів (soak9)
- `config/chains.yaml`: Base primary RPC/WS перемкнуто на dRPC;
  Flashblocks залишено як опційний read-path.
- `m7/orderflow/mode_ws_live.py`:
  (а) Flashblocks WS як primary hot-WS тепер behind
      `ARBY_BASE_USE_FLASHBLOCKS_WS` (default 0);
  (б) reconnect-гілка має rate-limit-aware cooldown via
      `ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S=30`.
- `docs/DEV_REPORT_LATEST.md`, `docs/status/Status_M7.md` оновлено.

## 9) Черга soak10
1. Multicall token0/token1 у prewarm + unit-тест (P0.1).
2. Alchemy-WS secondary fallback після другого rate-hit dRPC (P0.2).
3. hot-bucket priority (soak8 fix #4) — після того як DISC fast_path ≠ 0.
4. Rolling-gate `sim_attempted>=20 fast_path` (soak8 fix #7) активувати.
