# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Reporting split:** M8.2 gates → `scripts/m8_2_acceptance_report.py` + [Status_M8_2.md](Status_M8_2.md). M9 gates → `scripts/m9_lane_acceptance_report.py` (`m9_blockers` only).

**Current runtime line:** **M8_M8_1_RUNTIME_REACHED / M8_2_QUALITY_BLOCKED / M9_ECONOMICS_NOT_EVALUATED**

| Layer | Status | Source |
|-------|--------|--------|
| M8 / M8.1 upstream | **REACHED** | [Status_M8.md](Status_M8.md), [Status_M8_1.md](Status_M8_1.md) |
| M8.2 mirror/subgraph/handoff | **QUALITY_BLOCKED** | [Status_M8_2.md](Status_M8_2.md), `data/tmp/m8_2_acceptance_report_latest.json` |
| M9 graph/cycle/economics | **NOT_EVALUATED** | `m9_lane_acceptance_report_latest.json` (`m9_blockers` only when shadow runs) |

M8.2 quality metrics, blockers, and provenance split live only in **Status_M8_2.md** — do not duplicate here. M9 shadow/economics runs only after M8.2 strict PASS (`UPSTREAM_M8_2_NOT_READY` otherwise).

**Session 2026-06-10 cycle-lane sync (pool-lane PASS vs cycle-lane FAIL):**

| Metric | Pool-lane | Cycle-lane (10m shadow) |
|--------|-----------|-------------------------|
| Maverick quoteable/verified | **73/94** | topology cycles **12** |
| Balancer quoteable/verified | **18/29** | `cycles_quoteable` **0** |
| Bridge `productive_status_stamped` | **227** | `routes_in_graph` **45** |
| Balancer metadata enriched | **94** | dominant reject **`QUOTE_REVERT`** / `OVERSIZED_VS_DEPTH` |
| `phantom` | — | **0** |

**docs_reread_confirmed:** true

**Session 2026-06-10 fresh chain + 10m shadow (sniper → M8.1 → M8.2 → bridge → shadow → RCA):**

| Layer | Metric | Value |
|-------|--------|------:|
| M8 sniper 30m | candidates / `m8_stale` | **143** / **false** |
| M8.1 anchor | passes | **354** |
| M8.2 expansion | routes / `multi_venue_tokens` / `verified_second_pool` | **672** / **14** / **5** |
| Bridge | `graph_ready_total` / active / cross-mechanic | **698** / **610** / **74** |
| M9 shadow 10m | `cycles_found` / `cycles_quoteable` / `qsr` | **337** / **0** / **0.0** |
| M9 shadow 10m | `phantom` / `m8_derived` / `direct_sniper` | **0** / **337** / **0** |
| RCA top blockers | Maverick revert / Balancer revert / RPC error | **222** / **304** / **4** |

**M8.2 symbol/address bug:** виправлено в `cross_dex_expand.py` (символ і `token0_addr/token1_addr` канонізуються разом). Попередні claims `graph_ready_from_expansion=8` **інвалідовані** (був неправильний mapping).

**Expansion після fix:** `routes_admitted=2`, `multi_venue_tokens=1`; bridge dedupe: `expansion_routes_raw_input=2` → `expansion_routes_after_dedupe=0`; `graph_ready_from_expansion=0`, `graph_ready_total=9` — **не** claim «expansion працює» без `graph_ready_from_expansion > 0`.

**Verified vs bridge (розділено):** canonical `m9_graph_latest.json` (`qsr≈0.89`, inventory=`m9_verified_inventory`) підтверджує **QSR contour**, не M8→M9 ingestion. Bridge-shadow (fresh 2026-06-05): `data/tmp/m9_graph_bridge_shadow_latest.json` — `bridge_cycles_found=0`, `cycles_with_m8_pool=0`, `cross_mechanic_cycles=0`, `graph_edges_from_m8=2`; productive diagnostic **2 routes** (`route_qsr=0.50`). **Dynamic M8→M9 bridge ingestion не доведений.**

**Cross-Mechanic Sniper Edge (гілка):** **3h hot-path acceptance = PASS (topology lane)** — `data/tmp/m8_hot_path_latest.json`: `transition_triggers_1_to_2=10`. **P1 Curve admission (2026-06-10):** bridge фільтрує Curve до `QUOTE_OK_*` з `m9_curve_pool_indices_latest.json` (`curve_productive_admission_filtered=94`, active Curve **22**). RCA після fix: `QUOTE_REVERT` **0**; Curve більше не є головним blocker. **Cycle-level BLOCKED:** fresh shadow `cycles_found=362`, `cycles_quoteable=0`, `cross_mechanic_cycles=106`, `cycles_positive_gross=0`, `qsr=0.0`; `graph_ready_from_m8=8`, але `cycles_with_m8_pool=0`. Primary blockers: `NO_QUOTEABLE_CYCLES_IN_FRESH_SHADOW`, `CYCLES_WITH_M8_POOL_ZERO`, `MAVERICK_QUOTE_RPC_ERROR_DOMINANT`, `BALANCER_QUOTE_REVERT_DOMINANT`, `OVERSIZED_VS_DEPTH_DOMINATES`. Economics claim заборонений.

**External pool hints (Фаза 1.6):** `external_pool_hints_status: RUNTIME_VALIDATED` — pre-3h regen: `438 tokens`, `681 pools`, `262 verified`, `tcr=0.5982`. DexScreener/GeckoTerminal/`thegraph_token_api` + `new_pools_backfill` (5 pages). Hot-path застосовує hints → `10` transitions via `dexscreener`. **M9 bridge-shadow 30m** (post-acceptance): `data/tmp/m9_graph_bridge_shadow_latest.json` — `cycles_found=5952`, `cycles_quoteable=0`, `cycles_positive_gross=0`, `gate_acceptance=false` — **не** profit/M9 PASS.

**Напрямок гілки (узгоджено 2026-06-06, уточнено тімлідом) — активний пошук 2-го пулу, не пасивне очікування:** sniper-кандидати на момент launch майже завжди на ОДНОМУ дексі (Base ≈575 v4 launch/год). `multi_venue_tokens=0` — НЕ баг: до появи другого on-chain пулу edge не існує (без pending/preconf не передбачити неіснуючий пул). **Мета:** після першого pool event → watch-list (`m8_pending_pairs.json`) → **активний** `T-*` scan по всіх enabled DEX (factory logs / adapter resolvers), не чекати batch M8.2. Тригер входу: `token_seen_on_dexes: 1→2` + `cross_mechanic=true` → focused quote (`2,3,4` legs, incl. `T-C+C-anchor`) + honeypot → **`spread_lifetime` + `time_to_second_pool_s` (Фази 2/1.5)** як гейти перед production-shadow. Production-shadow лише якщо `second_pool_verified=true`, `quoteable_routes>=2`, `honeypot_pass=true`, `spread_lifetime` не порожній. Pending/preconf — R&D, не production foundation. Повний бриф: `docs/m9/BRANCH_BUILD_GUIDE_cross_mechanic_sniper_edge.md` (0b–0g, Фаза 1.5). `sushiswap_v3` topic0 у `config/new_pool_factories.yaml` виправлений і не є активним blocker.

**Runtime evidence (sniper lane, rolling):** `new_pool_sniper_latest.json` — fresh and **ACTIVE** after chunk mitigation: `raw_fetched=11`, `snipe_candidates_total=11`, `recent_events=11`, `rpc_errors=0`, `sniper_rpc_provider=drpc`, `sniper_rpc_failover_count=18`, `getlogs_400_count=126`, `getlogs_chunk_size=9`. Bridge enrichment now maps symbols for native/anchor cases: `m8_new_pools_input=11`, `graph_ready_from_m8=8`, `m8_funnel_reject_histogram={TOKEN_SYMBOL_INVALID:1, NOT_ANCHOR_CONNECTED:2}`. This proves short-window M8 ingestion into bridge is alive, but **not** production economics: `cycles_with_m8_pool=0`.

**Token-class policy (2026-06-07, independent review):** відмова від latency-вичищеного **known-token CLMM launch** edge (telemetry only). Стратегія лишається `1→2 venue + active scan + cross-mechanic`. **Known-token cross-mechanic** — окремий secondary shadow-клас з роздільним `spread_lifetime_by_token_class` / `spread_lifetime_by_mechanic_pair` (не змішувати з fresh long-tail). Код: `m8/discovery/token_classify.py`; bridge-shadow лише для `cross_mechanic` або `fresh_long_tail` з `connector_tokens>=1`. Production claim заборонений без `spread_lifetime`, honeypot/sell-side, net-sim.

**Sniper discovery RPC lane (2026-06-05 patch):** `M8_SNIPER_DISCOVERY_RPC_LANE_MISSING` **resolved in code** — sniper `eth_getLogs` більше не ділить productive M9 quote PRIMARY за замовчуванням. Resolution: `--rpc-url` → `BASE_SNIPER_RPC_PRIMARY` → `BASE_RPC_SECONDARY` → `BASE_RPC_PRIMARY`; failover → `BASE_SNIPER_RPC_SECONDARY` / `BASE_RPC_PRIMARY`. Metrics: `sniper_rpc_provider`, `sniper_rpc_failover_count`, `getlogs_400_count`, `getlogs_429_count`, `getlogs_chunk_size`, `ws_provider`, `http_fallback_provider`. **Runtime acceptance pending** — потрібен 60m sniper + M8.1→M8.2→30m hot-path після патчу.

**Canonical gate contour:** `verified inventory` + `--min-effective-depth-usd 50` + `ARBY_M9_MAX_CYCLES_PER_LENGTH=3:20,4:6` + productive RPC bootstrap. Bridge evidence: окремий shadow artifact, не перезапис `m9_graph_latest.json`.

**Session 2026-06-05 post-fix M8→M9 refresh:**

| Layer | Metric | Value |
|-------|--------|------:|
| M8 sniper 15m | candidates / status | **68** / ACTIVE (`--skip-self-test`; WS V4; HTTP `eth_getLogs` 400) |
| M8.1 anchor | completed | yes |
| M8.2 expansion | routes / multi-venue | **2** / **1** (`BASEAI_USDC`) |
| Bridge rebuild | `graph_ready_total` / `from_expansion` / `from_m8` | **9** / **0** / **29** |
| Verified diagnostic | route_qsr (productive admission) | **1.00** (22/22) |
| Soak 15m depth50 (verified) | `qsr` / gate | **0.8923** / **PASS** |
| Bridge-shadow 5m | `qsr` / cycles / M8 pools in cycles | **0.0** / **0** / **0** |
| Bridge diagnostic (productive) | routes / `route_qsr` | **3** / **0.33** |
| Prior soak (pre-regen bridge) | `qsr` | 0.8264 — **не** evidence для поточного bridge |

**Session 2026-06-05 live WS hot-path (15m --quote):**

| Metric | Value |
|--------|------:|
| Mode | **live_ws** + `--quote` (bootstrap) |
| `hot_path_events_seen` | **38** |
| `hot_path_mirrors_found` | **0** |
| `event_to_mirror_ms_p50` | **65.26** |
| `event_to_quote_ms_p50` | n/a (0 quoted; mirrors < 2) |
| `reject_reason_histogram` | `REJECT_MIRROR_ROUTES_LT_2=38`, `REJECT_NOT_ANCHOR_PAIR=34` |
| `expansion_reject_histogram` | `NO_POOL=348`, `ADAPTER_RESOLVE_PENDING=120`, `SINGLE_VENUE_ONLY=39` |
| `honeypot_evidence` | probe **STUB**; strict profit evidence **not possible** |
| Acceptance | **ready_for_bridge_shadow=false** |

**Session 2026-06-05 live WS hot-path (5m dry-run):**

| Metric | Value |
|--------|------:|
| Mode | **live_ws** (`--live-ws`, not batch) |
| `hot_path_events_seen` | **9** |
| `hot_path_mirrors_found` | **0** (all `REJECT_MIRROR_ROUTES_LT_2`) |
| `hot_path_cross_mechanic_candidates` | **0** |
| `registry_multi_venue_tokens` | **1** |
| `event_to_mirror_ms_p50` | **1.1** |
| Acceptance `ready_for_bridge_shadow` | **false** |

**Session 2026-06-05 fresh M8 sniper + existence retry (20m sniper):**

| Layer | Metric | Value |
|-------|--------|------:|
| M8 sniper 20m | candidates | **101** (`m8_stale=False`) |
| Registry | tokens / `multi_venue_tokens` | **422** / **1** |
| M8.2 expansion | `routes_admitted_raw` / `cross_mechanic_tokens` | **2** / **1** (still BASEAI only) |
| Bridge | `graph_ready_total` / `from_expansion` / deduped pools | **6** / **0** / **2** (v4+v3 samples logged) |
| Shadow bridge (`include_expansion_duplicates_for_shadow`) | active / `cross_mechanic` routes | **8** / **2** (diagnostic dupes only) |
| Depth enrich | probed_ok (rolling) | **3** / 6 |
| Bridge-shadow (shadow inv) | `cycles_found` / `cycles_with_m8_pool` / `cross_mechanic_cycles` | **0** / **0** / **0** (3 tokens, 4 edges post-filter) |

**Existence-lane:** **BLOCKED** — `M8_2_FRESH_MULTI_VENUE_UNIVERSE_TOO_SMALL`. Після свіжого sniper `registry_multi_venue` лишається **1** → Phase 4 decision: batch mirror-resolve недостатній без hot-path (див. `BRANCH_BUILD_GUIDE` Фаза 4).

**Session 2026-06-08 distinct-pricing quote RCA (Balancer/Maverick/Curve):**

**Status: BLOCKED** — distinct-pricing **coverage + discovery quote-smoke improved**; Balancer/Maverick **discovery/indexer quote-smoke validated**, but **M9 productive quote path is not synchronized**. `raw_http_probe.py` / adapter path still must prove the same BalancerQueries + MaverickQuoter behavior before M9 shadow/economics. Curve lane **restored in shadow** but **quote not ready** (`curve_quoteable_routes=0`, indices partial **5/32**). `connector_routes_count=0`. **No M9 economics claim.** **Do not run M9 shadow** until `curve_routes_ready>0`, `curve_quoteable_routes>0`, and productive-route diagnostics prove `balancer_quoteable_routes + maverick_quoteable_routes > 0` through the M9 quote path, not only through indexer smoke.

| Layer | Metric | Value |
|-------|--------|------:|
| Balancer index | verified / quote-smoke OK | **29** / **18** (`balancer_queries` via Base `0x300Ab…`; web3 ABI encode) |
| Maverick index | verified / quote-smoke OK | **97** / **75** (`maverick_quoter` `0x49b59311`; fix: quoter≠pool_info) |
| Curve discovery | admitted pools | **50** → **32** in shadow bridge |
| Curve indices | `QUOTE_OK_INT128` pools | **5** / 32 (27 failed/skip on public RPC) |
| Expansion batch | routes admitted | **1169** (`connector_routes_count=0`) |
| Shadow bridge | active balancer / maverick / curve | **94** / **149** / **32** |
| Discovery quote-smoke | balancer / maverick / curve quoteable | **79** / **90** / **0** |
| M9 productive quote path | Balancer / Maverick | **not validated** — raw HTTP/productive adapter still differs from discovery smoke |
| Debug artifacts | balancer / maverick quote debug | present (`m9_balancer_quote_debug_latest.json`, `m9_maverick_quote_debug_latest.json`) |
| Productive admission | balancer/maverick `enabled_for_productive` | **false** until productive gate + Curve quote ready |

**Session 2026-06-09 P0 productive quote sync:**

**Status: PARTIAL_REACHED / BLOCKED** — M9 productive quote path for Balancer/Maverick is now validated at pool/route level, but cycle-level shadow still has zero quoteable cycles. Treat this as **productive pool-path sync REACHED**, not M9 economics.

| Layer | Metric | Value |
|-------|--------|------:|
| Productive diagnostic | `productive_quote_ok` | **53 / 93** |
| Productive diagnostic | Balancer / Maverick quoteable routes | **18** / **35** |
| Bridge stamp | productive Balancer / Maverick / Curve quoteable | **74** / **60** / **5** |
| Bridge stamp | `distinct_pricing_productive_quote_ready` | **true** |
| Shadow soak | `cycles_found` / `cycles_quoteable` | **424** / **0** |
| Shadow soak | `cross_mechanic_cycles` / `cycles_positive_gross` | **0** / **0** |
| Freshness | M8 / M8.1 | **stale** / **stale** |

**Session 2026-06-10 P1 Curve productive admission:**

**Status: PARTIAL_REACHED / BLOCKED** — Curve admission fix **REACHED**; M8 bridge ingestion and cross-mechanic topology are partially unblocked; cycle quoteability/economics remain **BLOCKED**.

| Layer | Metric | Value |
|-------|--------|------:|
| Curve indices regen | `QUOTE_OK_INT128` pools | **22 / 116** |
| Bridge shadow | Curve before/after admission filter | **116 → 22** (`filtered=94`) |
| Productive stamp | curve / balancer / maverick quoteable | **22 / 79 / 60** |
| RCA post-fix | `QUOTE_REVERT` / curve leg-errors | **0** / **30** |
| RCA post-fix | Balancer / Maverick leg-errors | **305** / **250** |
| RCA post-fix | dominant reject reasons | `QUOTE_CONFIG_MISSING__BALANCER_POOL_ID=305`, `QUOTE_RPC_ERROR=280` |
| Shadow 5m (post M8 enrichment) | `cycles_found` / `cycles_quoteable` | **362** / **0** |
| Shadow 5m | `cross_mechanic_cycles` / `cycles_positive_gross` | **106** / **0** |
| Shadow 5m | `cycles_with_m8_pool` / `graph_ready_from_m8` | **0** / **8** |
| Shadow 5m | cycle rejects | `OVERSIZED_VS_DEPTH=261`, `CYCLE_QUOTE_FAILED=91`, `PHANTOM_QUOTE_BPS_OVERFLOW=10` |
| M8 sniper refresh | status / candidates / recent events | **ACTIVE** / **11** / **11** |
| M8.1 anchor refresh | candidates / passes / quote success | **3279** / **354** / **1.0** |
| M8.2 expansion regen | `routes_admitted` / `graph_ready_from_expansion` | **514** / **387** |
| Bridge shadow | `graph_ready_total` / active routes / cross-mechanic tags | **634** / **540** / **77** |
| Config | `balancer_vault` / `maverick_v2` `enabled_for_productive` | **true** |
| Honeypot gate | `positive_gross_counts_as_evidence(strict=True)` | **enabled** in artifact builder |

**Session 2026-06-07 distinct-pricing lane refresh (superseded partial):** Curve discovery admitted **6** pools (artifact) → **26** in bridge (prior run); curve-only `distinct_pricing_lane_ready=true` — **invalid** per-lane gate.

**Session 2026-06-07 3h hot-path + M9 bridge-shadow (M8.2 acceptance):**

| Layer | Metric | Value |
|-------|--------|------:|
| Hints regen | tokens / pools / verified / tcr | **438** / **681** / **262** / **0.5982** |
| Expansion | routes / `subgraph_ready_tokens` / `connector_routes` | **839** / **3** / **0** |
| 3h hot-path | events / transitions / mirrors / cross_mech | **314** / **10** / **1** / **1** |
| 3h infra | `duration_fulfilled` / `ws_health` / provider | **true** / **OK_RECONNECTED** / **alchemy** |
| 3h acceptance | `ready_for_bridge_shadow` / `crossdex_transition_rate` | **true** / **0.0318** |
| M9 shadow 30m | `cycles_found` / `cycles_quoteable` / `positive_gross` / gate | **5952** / **0** / **0** / **false** |

**Session 2026-06-05 Cross-Mechanic brief (10-step pipeline, same day):**

| Layer | Metric | Value |
|-------|--------|------:|
| Unit tests | `test_m8_cross_dex_expand` + token_age + bridge | **54 passed** |
| M8.2 regen | routes / `cross_mechanic_tokens` | **2** / **1** (BASEAI_USDC: v4+v3) |
| Bridge rebuild | `from_expansion` / `cross_mechanic` in active | **0** / **0** (dedupe vs base) |
| Depth enrich | probed_ok / failed | **2** / **7** |
| Bridge diagnostic | routes / `route_qsr` | **2** / **0.50** |
| Bridge-shadow 10m intent | `cycles_found` / `cycles_with_m8_pool` / `cross_mechanic_cycles` | **0** / **0** / **0** (early `EXIT_NO_CYCLES`; 1 route in graph) |

**Provenance fields (additive):** sniper/registry/expansion routes несуть `source_event_block`, `pool_first_seen_block`, `token_first_seen_ts`; окремий probe `scripts/m8_token_contract_age_probe.py` → `data/tmp/m8_token_contract_age_latest.json` (pool events ≠ token contract age).

**Session 2026-06-05 A/B depth (prior, pre-refresh):**

| Run | `min_depth_usd` | `qsr` | Gate |
|-----|----------------:|------:|------|
| Soak A | **50** | 0.8561 | PASS |
| Soak B | 100 | 0.6190 | FAIL |

**QSR failure histogram (prior soak `qsr=0.7261`)**: домінує **`QUOTE_ZERO_OUTPUT`** на TOSHI/DEGEN/BRETT long-tail legs (не RPC). Infra: `http_408/429/5xx=0`.

**Provider**: Alchemy HTTP primary, dRPC WS/secondary (`ARBY_PROVIDER_POOL_MODE=weighted`). Public `BASE_RPC` не використовується в productive.

**Recommended gate contour**: `data/tmp/m9_verified_inventory.json` + `--min-effective-depth-usd 50` + `ARBY_M9_MAX_CYCLES_PER_LENGTH=3:20,4:6` + productive RPC `.env` (не комітити).

**Session 2026-06-04 productive validation (Alchemy primary):**

| Step | Metric | Value |
|------|--------|------:|
| `check_rpc_endpoints` | HTTP alchemy / WS drpc | **PASS** |
| Verified depth enrich | `with_depth` / active | **429 / 507** |
| Bridge inventory | `with_depth` / QUARANTINED | **136 / 154**, **128** quarantined |
| Route diagnostic (4 routes) | `route_qsr` | **0.50** (Alchemy HTTP) |
| Verified soak 15m | `qsr` | **0.7261** |
| Verified soak 15m | `depth_aware_known_rate` | **0.9737** |
| Verified soak 15m | `data_completeness` | **1.0** |
| Verified soak 15m | `provider_failover_count` | **0** |
| `ci_m9_productive_gate` | result | **FAIL** (`qsr` only) |

**Session 2026-06-04 RPC pool evidence:**

| Check | Provider class | Result |
|-------|----------------|--------|
| Env contract | `ALCHEMY_API_KEY`, `BASE_WSS` | present; `BASE_RPC_PRIMARY` / `SECONDARY` / `ARBY_PROVIDER_POOL_MODE` **unset** (set in `.env`, do not commit) |
| `check_rpc_endpoints` (dedicated override) | HTTP **alchemy**, WS **drpc** | **PASS** — `chain_id` OK, `archive_ok`, `newHeads` OK |
| A/B 50 routes | **alchemy** | `archive_ok`, `p95≈141ms`, `408/429/5xx=0`, `route_qsr=0` (bridge quote reverts dominate) |
| A/B 50 routes | **drpc** HTTP | `archive_ok`, **`http_408=50`** — not equal-weight productive; use as **secondary/WS only** with health penalty |

**Recommended `.env` (local only):** `BASE_RPC_PRIMARY` = Alchemy HTTP, `BASE_RPC_SECONDARY` = dRPC HTTP (same key path as `BASE_WSS`), `BASE_WSS` unchanged, `ARBY_REQUIRE_DEDICATED_RPC=1`, `ARBY_PROVIDER_POOL_MODE=weighted`. Public endpoints only with `ARBY_USE_PUBLIC_POOL=1` for diagnostics.

**Session 2026-06-04 evidence (pipeline):**

| Layer | Metric | Value |
|-------|--------|------:|
| Unit tests | targeted M8/M9 + pool_quality | 102+ passed |
| Bridge inventory | with_depth / active | **136 / 154** |
| Bridge | pool_quality_histogram | QUARANTINED=128, DEPTH_OK=7 |
| Route diagnostic (productive) | routes_probed / route_qsr | 11 / **0.18** |
| Verified soak 6m | qsr / all_pass | **0.077 / false** |
| RPC | publicnode depth | OK; dRPC free **408** under load |

**Blocker**: dedicated sustained HTTP RPC + reduce toxic long-tail (128/154 quarantined) before QSR≥0.8.

**Session 2026-06-02 evidence (historical):**

| Layer | Metric | Value |
|-------|--------|------:|
| RPC check | dRPC archive | PASS |
| Curve discovery | pools admitted | 68 |
| Bridge | graph_ready_total | 44 |
| Bridge | curve_discovery_loaded | 43 |
| Bridge | curve_indices_missing | **0** |
| Bridge | graph_ready_from_m8 | 1 |
| Bridge | structural_single_venue_blocked | 27 |
| Route diagnostic (44 routes) | route_qsr | 0.25 (11/44 OK) |
| Route diagnostic | failures | 23× QUOTE_REVERT, 10× QUOTE_RPC_ERROR |
| M9 soak 3m (RPS=5) | http_429_count | 910, qsr=0.0 |
| M9 soak 2m (RPS=3 + retry) | http_429_count | **9**, qsr=0.0063, 1 positive cycle |

### QSR root cause (this session)

1. **FIXED — missing Curve indices**: `load_adapter_metadata()` now merges `m9_curve_discovery_latest.json` → `curve_indices_missing=0`.
2. **DOMINANT — RPC rate limit**: M9 sweep with 3200 cycle quotes → **2725× HTTP 429** on dRPC (`QUOTE_RPC_ERROR` 2785). Not a selector bug.
3. **Secondary — bad Curve legs**: USDC_WETH factory pools → `QUOTE_REVERT` at $100 probe; stable USDC/USDbC/USDS legs quote OK.
4. **Topology — weak M8 cross-venue**: `graph_ready_from_m8=1` despite M8.1 `qsr=1.0`; multi-venue gate still blocks 27 events.

### Config / artifact hygiene (2026-06-02)

- `config/m9_active_manifest.yaml`: ACTIVE vs LEGACY_REQUIRED vs runtime rolling lists.
- `scripts/audit_m9_active_config.py`: classifies config/runtime/cache/tmp (`ACTIVE`, `RUNTIME_STALE`, `TMP_STALE`, …).
- `config/dexes.yaml`: M9-only Base entries aligned with `exotic_base_anchor.yaml`.
- `config/exotic_base_anchor.yaml`: `m9_dex_productivity` gates per DEX.
- Production bridge: `include_config_seed=false` (Curve/Balancer YAML pools = bootstrap only).

### Code fixes landed

- `m9/graph_arb/adapter_metadata.py`: merge factory discovery coin indices.
- `m9/graph_arb/raw_http_probe.py`: HTTP 429 exponential backoff retry.
- `scripts/discover_curve_indices.py`: `rpc_throttle` + 429 retry; decimal-aware probe dx.
- `scripts/m9_curve_discovery.py`: `resolve_rpc_http` (dRPC) instead of publicnode default.
- `scripts/m9_quote_route_diagnostic.py`: `load_root_dotenv()` for `BASE_RPC`.
- `scripts/ci_m9_productive_gate.py`: `NO_CYCLES` vs `dynamic_size_intent` messaging.

### Next (ordered)

1. Soak with **`ARBY_RPC_RPS_LIMIT=3`**, `quote_workers=1`, `--max-cycles-per-sweep 25`, bridge inventory — target `http_429_count≈0`, then raise cap slowly.
2. Re-run route diagnostic; quarantine USDC_WETH revert pools from `data/tmp/m9_revert_quarantine.json` into bridge rebuild.
3. Refresh M8 sniper (artifact stale flag) to raise `graph_ready_from_m8`.
4. Re-run route diagnostic on full 44 routes after RPC stable.
5. **Do not** claim M9 PASS until `qsr≥0.8` with fresh artifact.

`goal_status`: **BLOCKED** (economics: `cycles_positive_gross=0`) | Verified productive gate: **PASS** (`qsr=0.8923`) | M8→M9 bridge ingestion: **NOT PROVEN** (bridge-shadow `cycles_found=0`, `cycles_with_m8_pool=0`)  
`execution_enabled`: false | `kill_switch_active`: true

---

**Previous Status**: RUNTIME_VALIDATED__V4_DEPTH_VISIBLE__M9_PRODUCTIVE_TOPOLOGY_BLOCKED — Session 2026-06-01 (see history below).
