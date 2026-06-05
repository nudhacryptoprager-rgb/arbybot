# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: **RUNTIME_VALIDATED__PRODUCTIVE_GATE_PASS** (обережно) — canonical soak на **виправленому** M8.2/bridge contour: `qsr=0.8923`, `ci_m9_productive_gate` **PASS**. **Economics не доведена** (`cycles_positive_gross=0`). **2-leg**: shadow-only. **depth100** не acceptance.

**M8.2 symbol/address bug:** виправлено в `cross_dex_expand.py` (символ і `token0_addr/token1_addr` канонізуються разом). Попередні claims `graph_ready_from_expansion=8` **інвалідовані** (був неправильний mapping).

**Expansion після fix:** `routes_admitted=2`, `multi_venue_tokens=1`; bridge dedupe: `expansion_routes_raw_input=2` → `expansion_routes_after_dedupe=0`; `graph_ready_from_expansion=0`, `graph_ready_total=9` — **не** claim «expansion працює» без `graph_ready_from_expansion > 0`.

**Verified vs bridge (розділено):** canonical `m9_graph_latest.json` (`qsr≈0.89`, inventory=`m9_verified_inventory`) підтверджує **QSR contour**, не M8→M9 ingestion. Bridge-shadow (fresh 2026-06-05): `data/tmp/m9_graph_bridge_shadow_latest.json` — `bridge_cycles_found=0`, `cycles_with_m8_pool=0`, `cross_mechanic_cycles=0`, `graph_edges_from_m8=2`; productive diagnostic **2 routes** (`route_qsr=0.50`). **Dynamic M8→M9 bridge ingestion не доведений.**

**Cross-Mechanic Sniper Edge (гілка):** Phase 1 reviewed and guarded (`allowed_dex_ids`, cross-mechanic score). **Existence blocker (canonical):** `M8_2_FRESH_MULTI_VENUE_UNIVERSE_TOO_SMALL` — bridge-shadow потребує свіжого M8 sniper + `cross_mechanic_tokens >= 2` + `bridge_routes_in_m9 >= 4` / `unique_tokens >= 3` перед soak; `graph_ready_from_expansion=0` коли expansion-дзеркала вже в base (dedupe).

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
