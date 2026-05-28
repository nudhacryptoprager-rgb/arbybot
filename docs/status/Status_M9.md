# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: CODE_VALIDATED__DISCOVERY_WIRED — Session 11 (2026-05-28): Curve factory discovery wired end-to-end; 6146 unit tests pass.

**Session 11 changes:**
- `m9/graph_arb/bridge_builder.py` Stage 5a: `_load_curve_discovery_routes()` loads `m9_curve_discovery_latest.json`; routes enter `active_routes` with `source=curve_factory_discovery`, `factory_verified=True`, `metadata_seeded=False`. New `curve_discovery_count` metric in `bridge_source_metrics`. New `curve_discovery_path` param to `build_bridge_inventory()` (default: rolling path).
- `m9/graph_arb/bridge_builder.py` semantic fix: `_build_static_curve_routes()` now sets `factory_verified=False` + `metadata_seeded=True` on seed routes (previously had wrong `factory_verified=True`).
- `config/adapter_metadata.yaml`: added `factory_stable_ng` and `anchor_tokens` fields under `curve.base` (trust anchors for discovery script).
- `m9/graph_arb/adapter_metadata.py`: `AdapterMetadata` gains `curve_factory_stable_ng: Dict[str, str]` and `curve_anchor_tokens: Dict[str, Dict[str, str]]`; loader parses both fields.
- `scripts/m9_curve_discovery.py`: removed hardcoded `_CHAIN_ANCHORS` dict; factory address and anchor tokens now read from `config/adapter_metadata.yaml` via `load_adapter_metadata()`. `_RPC_DEFAULTS` replaces per-chain RPC config.
- `tests/unit/test_m9_bridge_builder.py`: 7 new tests in `TestCurveDiscoveryContract`; `_build()` in `TestConfigSeedContract` now passes `curve_discovery_path` pointing to non-existent file for isolation.

**Artifact contract (unchanged):** production bridge with no discovery artifact = `curve_discovery_count=0`, `metadata_seeded_count=0`, `graph_ready_total=126`. With `--include-config-seed-pools`: `metadata_seeded_count=2`, `graph_ready_total=128`.

**Remaining open items:**
- `m9_curve_discovery.py` needs to be run against real RPC to generate `data/runs/_rolling/m9_curve_discovery_latest.json` (requires `$env:BASE_RPC`; run: `py -3.11 scripts/m9_curve_discovery.py --chain base`)
- `min_tvl_usd` param declared but no on-chain TVL query implemented (informational only)
- Balancer discovery via Vault PoolRegistered events not yet implemented

Previous status: CODE_VALIDATED__DISCOVERY_CONTRACT_GAP — Session 10 (2026-05-28): Curve quote path wired and tested (6139 unit tests pass). DISCOVERY CONTRACT OPEN: Curve routes previously entered `active_routes` via static `adapter_metadata.yaml` seed injection (`_build_static_curve_routes`), which bypasses the M8 sniper/factory funnel. Session 10 fix: moved static injection behind `include_config_seed=True` flag (smoke-only); default production bridge excludes adapter_metadata routes; `metadata_seeded_count` metric added; `scripts/m9_curve_discovery.py` created.

Previous status: CODE_VALIDATED__RUNTIME_COVERAGE_CONFIG_PENDING — Session 8 (2026-05-28): config-driven adapter wiring complete, config populated with real Curve pool addresses (factory-stable-ng-47: USDC/MONEY, factory-stable-ng-48: crvUSD/MONEY). `curve_stable` enabled in `exotic_base_anchor.yaml` with real factory `0xd2002373543ce3527023c75e7518c274a51ce712`. economics_blocker_class logic fixed (QSR check now precedes positive_gross check). 6 new validation tests (check_curve_pools_configured). All adapter wiring (builder.py→quoter.py→quote_probe.py+raw_http_probe.py) was completed in Session 7. BLOCKED by: (a) dRPC 429 rate limiting (qsr=0.20); (b) Balancer pool_ids not yet verified on-chain (Balancer API unavailable); (c) M8 sniper WS incompatibility with Alchemy (graph_ready_from_m8=0). Config is now populated; next step is Alchemy-backed online validation run.

Previous-previous status: ALCHEMY_INFRA_PASS__STRICT_BRIDGE_BLOCKED_BY_M8_RPC_ERROR — Session 6 (2026-05-27): qsr=0.96, multicall=1.0, data=1.0, http_429=0, runtime_gates.all_pass=True; graph_ready_from_m8=0 (WS issue); positive_cycles=0 (all spreads ≤5 bps vs flat cost=11 bps).

`goal_status`: BLOCKED
`schema_family`: m9_graph_arb
`schema_revision`: m9.1
`execution_enabled`: false
`kill_switch_active`: true
`execution_mode`: paper

---

## Strategic Goal Sequence

| Step | Target | Status |
|------|--------|--------|
| Health PASS | `all_pass=True`, `qsr>=0.8`, `bridge_active` | ✅ DONE |
| V4 Adapter | `uniswap_v4` quote path (hooks==0x0) | ✅ DONE |
| DEX Coverage Gate | sushiswap_v2/baseswap_v2 in bridge, Balancer pending tracked | ✅ DONE (2026-05-26) |
| M8 Cycle Participation | `cycles_with_m8_pool > 0` | ✅ DONE (soak8: cycles_with_m8=92) |
| Cost-aware economics | `estimated_cost_bps` + cost-adjusted `net_bps` populated | ✅ DONE (2026-05-27, cost_model_applied=true) |
| Multi-venue gate hardened | Stage 4b counts only quoteable DEX IDs; symbol collision blocked | ✅ DONE |
| **Adapter slice 1** | Per-adapter cost model, Ve33Stable, Curve, Balancer, V4 hooks, fresh_window | ✅ DONE (adapter_slice_1) |
| M8 multi-venue proof | M8 token has >=2 verified quoteable venues | ⏳ PENDING |
| **Next** | `positive_cycles_with_m8_pool > 0` after orthogonal pricing families live | ⏳ PENDING |
| Final | `economics_gate_status=POSITIVE` | ⏳ PENDING |

---

## Adapter Slice 1 — Completed Changes

### Нові файли
| Файл | Призначення |
|------|-------------|
| `m9/graph_arb/cost_model.py` | Per-adapter cost map (bps): ve33_stable=4, curve_stable=3, uniswap_v3=8, ve33_volatile=12 тощо; `build_cost_breakdown(cycle_results)` |
| `dex/adapters/uniswap_v4.py` | V4 hooks whitelist policy: `is_safe_v4_hook()`, `quarantine_reason_for_hook()` |
| `dex/adapters/curve_stable.py` | Curve StableSwap: `get_dy(i,j,dx)` via RPC (int128 + uint256 selector fallback) |
| `dex/adapters/balancer_vault.py` | Balancer Vault `queryBatchSwap` adapter; vault=0xBA12222222228d8Ba445958a75a0704d566BF2C8 |

### Змінені файли
| Файл | Зміни |
|------|-------|
| `dex/adapters/ve33.py` | `Ve33StableAdapter` (ADAPTER_TYPE="ve33_stable", 90k gas), `stable_k()`, `verify_stable_k()` |
| `m9/graph_arb/bridge_builder.py` | fresh_window (Stage 4c, <3600s), V4 hooks whitelist quarantine (UNKNOWN_V4_HOOK), `fresh_window_admitted_count` в metrics |
| `m9/graph_arb/artifacts.py` | 3 нові поля: `cost_breakdown_by_adapter`, `cycles_by_adapter_family`, `positive_cycles_by_adapter_family` |

### Нові тести (tests/unit/)
- `test_cost_model_per_adapter.py` — 6 test classes (adapter map, cost_bps, cycle_cost, net, family, build_cost_breakdown)
- `test_ve33_stable_curve.py` — stable_k math, verify_stable_k, Ve33StableAdapter tagging
- `test_v4_hooks_whitelist.py` — is_safe_v4_hook (None/empty/zero=safe; unknown=quarantine)
- `test_time_gated_single_venue.py` — fresh_window: fresh → admitted_count check; stale → admitted_count=0
- `test_curve_stable_adapter.py` — encoder, decoder, CurveStableAdapter.get_quote() (mock provider)
- `test_balancer_vault_adapter.py` — vault address, selector, decoder, BalancerVaultAdapter.get_quote()

---

## Session 2026-05-27 (Session 6): Full RPC A/B Test + UTC Bug Fix

### Зроблено
- ✅ **Fix** (`scripts/m9_rolling_orchestrator.py` `_artifact_ts`): UTC timezone bug — `strptime` без timezone treated `Z` as local → age=7204s false. Fixed with `.replace(tzinfo=_dt.timezone.utc)`
- ✅ **dRPC run** (lb.drpc.live): `duration_fulfilled=True`; 3392 cycles; **2833×429** (83.6% error rate on raw_http quote path); `qsr=0.15`, `data=0.60` → gate FAIL INFRA
- ✅ **Alchemy run** (base-mainnet.g.alchemy.com/v2/...): zero 429s, `qsr=0.96`, `multicall=1.0`, `data=1.0`; `runtime_gates.all_pass=True`; MARKET_NO_POSITIVE_GROSS
- ✅ Key insight: `ARBY_RPC_RPS_LIMIT` only throttles `provider_throttle` paths, NOT the raw_http multicall/quote path

### Артефакти — Alchemy run (2026-05-27T17:22:14Z)
```
generated_at_utc: 2026-05-27T17:22:14Z
rpc_provider: alchemy, rpc_public_fallback_used: False
duration_fulfilled: True, elapsed_s: 922.0, sweeps_completed: 23
cycles_found: 4580, cycles_quoteable: 4400, cycles_positive_gross: 0
qsr: 0.9607, multicall_success_rate: 1.0, data_completeness: 1.0
http_429_count: 0, actual_http_calls: 13177
runtime_gates.all_pass: True  ✅ FIRST TIME
graph_ready_total: 119, graph_ready_from_m8: 0  ← M8 sniper EMPTY (WS issue)
economics_gate_status: BLOCKED_NO_POSITIVE_GROSS
economics_blocker_class: MARKET_NO_POSITIVE_GROSS
```

### Gate failures (2 remaining)
| Failure | Root cause | Fix |
|---------|------------|-----|
| `STRICT_BRIDGE: graph_ready_from_m8=0` | M8 sniper EMPTY with Alchemy WS (WS log sub compat?) | Investigate sniper WS with Alchemy |
| `BLOCKED_NO_POSITIVE_GROSS` | No arb opportunity in current market with current 119-pool inventory | Market/time condition OR larger inventory |

---

## Session 2026-05-27 (Session 3): M8_STALE Fix + Gate Run

### Зроблено
- ✅ Orchestrator uses `scripts/sniper_smoke_run.py` + `--skip-preflight --skip-self-test`
- ✅ M8.1 rc=1 → soft-warn + continue (was abort)
- ✅ Pipeline ran: M8 (166 candidates), M8.1 (108 passes), Bridge (m8_stale=False!), M9 (9 sweeps, 1668 cycles, 203.4s/900s)
- ✅ DEV_REPORT_LATEST.md updated; check_repo_safety PASS

### Артефакти (2026-05-27T14:41:04Z)
`
generated_at_utc: 2026-05-27T14:41:04Z
sweeps_completed: 9, cycles_found: 1668, elapsed_s: 203.4, duration_fulfilled: False
qsr: 0.91, multicall_success_rate: 0.75, data_completeness: 0.92
bridge_source_metrics.m8_stale: False  ✅ FIRST TIME
bridge_source_metrics.graph_ready_from_m8: 14
cycles_positive_gross: 0, best_cycle_gross_bps: 0.0
toxic_route_rate: 1.0  ← needs pool_depth_probe --update-quarantine
`

### Gate failures (4 remaining after session 3)
| Failure | Root cause | Fix |
|---------|------------|-----|
| `duration_fulfilled=False` | scheduler exits at 203s vs 900s deadline | recycle on empty batch (fix 3) |
| `multicall_success_rate=0.75` | publicnode 429 throttling | scheduler recycle lowers RPC pressure |
| `data_completeness=0.92` | downstream of multicall 429s | same |
| `toxic_route_rate=1.0` | stale depth inventory | pool_depth_probe --update-quarantine |

---

## Sessions 2026-05-27 (1-2): Infrastructure Fixes

- ✅ `m9_bridge_build.py` accepts `--config` arg; orchestrator `PYTHONIOENCODING=utf-8`; M9 passes `--inventory` bridge path; bridge freshness guard
- ✅ Cost model: `estimated_cost_bps`, `cost_adjusted_net_bps`, `cost_adjusted_profit_usd` in top_opportunities; `cost_model_applied=false` → FAIL strict mode
- ✅ Multi-venue: Stage 4b quoteable DEX IDs only; symbol collision blocked; `m8_multi_venue_quoteable_count`

---

## Session 2026-05-26: DEX Coverage Gate PASS

- ✅ V4 hooks fix, sushiswap_v2 detected, quarantine 3→59 entries
- ✅ smoke29c: `toxic_rate=0.4183`, `cycles_positive_gross=38`, `best_cycle_gross_bps=+1.09`, EXIT 0
- ✅ strict-bridge gate PASS; 3/3 consecutive PASS runs → bridge unlock

---

## M8→M9 Adapter Coverage

- V4: M8 parses V4 events; routes in `m8_pending_routes`; P3 delivery requires M9 PoolManager StateView adapter
- V2/ve33: `getPair`, `getPool(bool)` selectors; `uniswap_v2`, `ve33`, `aerodrome_v2_stable` supported
- Curve: `_DEX_ID_TO_ADAPTER_TYPE["curve"] = "curve_stable"`; coin indices from adapter_metadata.yaml; 2 real pools configured
- Balancer: vault_address configured; pool_ids pending on-chain verification (Balancer API was unavailable)

---

## Current Blockers

1. ~~`multicall_success_rate < 0.90`~~ **RESOLVED** — publicnode, mc_rate=1.0 (smoke29c)
2. ~~3 consecutive all_pass runs for bridge unlock~~ **RESOLVED** — smoke23+24+25
3. ~~`toxic_route_rate=0.9894`~~ **RESOLVED** — quarantine 3→59; toxic_rate=0.4183
4. ~~`m8_stale=True`~~ **RESOLVED** — orchestrator now uses `scripts/sniper_smoke_run.py`
5. **RESOLVED**: orchestrator `--help` crash (→ Unicode fixed, session 5)
6. **RESOLVED**: `pool_depth_probe` fee=None crash (session 5)
7. **QUARANTINE EXPANDED** (59→60): `pool_depth_probe --update-quarantine` ran; runtime evidence pending (next full pipeline run)
8. `positive_cycles_with_m8_pool=0`; all current adapters are CPMM/CLMM with spreads ≤5 bps vs flat cost=11 bps; needs orthogonal pricing (stable curves) — **adapter slice 1 addresses this**
9. `router_sim` NOT_STARTED; `prequote_min_bps=-9999` smoke bypass; kill_switch=true
10. ~~Curve/Balancer adapters NOT YET wired~~ **RESOLVED** (Session 7): bridge_builder, quote_probe, raw_http_probe all wired; config populated with real Curve pools (Session 8)
11. **ACTIVE**: dRPC 429 throttling (qsr=0.20 in last online run); use Alchemy for next validation
12. **ACTIVE**: Balancer pool_ids not verified on-chain; `adapter_metadata.yaml` has vault_address + template but no real pool_ids
13. **ACTIVE**: M8 sniper WS incompatibility with Alchemy (graph_ready_from_m8=0 in Alchemy runs)

---

## Path to PASS (Next Steps)

`
[DONE]   M8_STALE resolved (m8_stale=False confirmed)
[DONE]   cost_model_applied=true, cost-adjusted fields populated
[DONE]   Priority scheduler recycle fix (session 4, needs runtime evidence)
[DONE]   pool_depth_probe --update-quarantine (quarantine 59→60, session 5)
[DONE]   orchestrator --help Unicode fix (session 5)
[DONE]   Adapter slice 1: Ve33StableAdapter, CurveStableAdapter, BalancerVaultAdapter, V4 hooks, fresh_window
[DONE]   Wire adapters: bridge_builder._DEX_ID_TO_ADAPTER_TYPE["curve"]="curve_stable"; quote_probe.py elif branches (Session 7)
[DONE]   Remove "balancer_stable"/"balancer_weighted" from _PENDING_ADAPTER_TYPES (Session 7)
[DONE]   config/adapter_metadata.yaml: 2 real Curve pools on Base (factory-stable-ng-47/48) (Session 8)
[DONE]   curve_stable enabled in exotic_base_anchor.yaml with real factory (Session 8)
[DONE]   economics_blocker_class: QSR check precedes positive_gross check (Session 8)
[NEXT_1] Use Alchemy RPC for next online validation: expect qsr≥0.8, Curve pools in cycles_by_adapter_family
[NEXT_2] Verify Balancer pool_ids on-chain via cast/web3; populate balancer.base.pools in adapter_metadata.yaml
[NEXT_3] Fix M8 sniper WS incompatibility with Alchemy so graph_ready_from_m8 > 0
[NEXT_4] ci_m9_productive_gate.py --strict-bridge → target GATE_EXIT=0
`

## Scope

M9 is a shadow scanner for multi-hop arbitrage cycles (length 3–4) on Base chain, built from M8.1 factory-verified inventory. Paper mode only. Rolling artifact: `data/runs/_rolling/m9_graph_latest.json`.

**runtime_gates thresholds**:
- `multicall_success_rate >= 0.90`
- `data_completeness >= 0.98`
- `unverified_active_routes == 0`
- `qsr >= 0.80`
- `quote_revert_rate < 0.05`
