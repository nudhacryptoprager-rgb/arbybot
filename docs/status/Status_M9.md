# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: **UNIFIED_PIPELINE_CODE_READY__RUNTIME_NOT_VALIDATED** — Alchemy+dRPC available locally; **no new provider registrations** until A/B proves insufficient. Public RPC **forbidden for productive gate** (`BASE_RPC=publicnode` must not drive HTTP).

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

`goal_status`: **BLOCKED** (`UNIFIED_PIPELINE_CODE_READY__RUNTIME_NOT_VALIDATED`) | Depth write: **partial** (136/154) | Economics: **not validated** (`qsr < 0.8` on latest soak)  
`execution_enabled`: false | `kill_switch_active`: true

---

**Previous Status**: RUNTIME_VALIDATED__V4_DEPTH_VISIBLE__M9_PRODUCTIVE_TOPOLOGY_BLOCKED — Session 2026-06-01 (see history below).
