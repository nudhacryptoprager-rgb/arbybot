# Status: M8.3 Token Metadata Registry & Decimals Service

**Status**: **M8_3_STRICT_PASS / UPSTREAM_METADATA_READY**

```text
goal_status: REACHED (m8_3_acceptance_report.py --strict, 2026-06-24)
curve_handoff: m9_curve_pool_indices → coin_indices via m8/metadata/curve_indices.py
dex_route_metadata: cycle_participating ready_rate=1.0, pool_identity_cycle_rate=1.0
primary_blocker_resolved: Curve coin_indices not propagated (was 0.2222 ready)
```

```text
scope: token decimals/symbol/name validation for M9 economics
truth_boundary: on-chain verified metadata required for economics-grade
downstream_blocker_if_fail: UPSTREAM_M8_3_NOT_READY
```

**Reporting split:** M8.3 gates → `scripts/m8_3_acceptance_report.py --strict`. M9 must not re-claim economics until M8.3 strict acceptance passes.

## Layer placement

```text
M8 sniper
→ M8.1 anchor/metadata probe
→ M8.2 cross-DEX expansion / radar / graph handoff
→ M8.3 token metadata registry / decimals validation
→ M9 quote / depth / sizing / economics
```

M8.3 does **not** discover pools, mirror quote, or compute profit. It is the **single authority** for token metadata after M8.2 handoff. Bridge/M9 must consume registry only; legacy decimals paths are missing-only fallback and must not overwrite `m8_3_*` provenance.

## Scope boundaries

```text
M8.2 handoff readiness:     REACHED (unchanged — see Status_M8_2.md)
M8.2 economics/metadata:    out of scope (M8.3 owns metadata normalization)
M8.3 economics-grade truth: on-chain ERC20 or core config only
M9 economics:               blocked until M8.3 strict acceptance PASS
```

## Canonical rolling artifact

- `data/runs/_rolling/m8_3_token_metadata_registry_latest.json`

Schema: `m8_3_token_metadata_registry_v2` (v1 accepted for read). Sections: `token_registry`, `dex_route_metadata`, `task_funnel`, `per_dex_worker_metrics`, `authority_contract`.

## Aggregated metadata authority (M8_3_AGGREGATED_METADATA_AUTHORITY)

```text
m8/metadata/aggregator.py     root scheduler + merge (sole writer)
m8/metadata/registry.py       token_registry writer (decimals authority)
m8/metadata/dex/*.py          per-DEX route/pool metadata workers (no token write)
```

Refresh:

```powershell
py -3.11 scripts/m8_3_token_metadata_registry_refresh.py --chain base --task-mode aggregated --with-dex-workers
```

## Resolution precedence

1. core config / known anchors
2. M8 sniper ERC20
3. M8.1 / M8.2 artifact route metadata
4. prior registry cache
5. on-chain ERC20 / multicall
6. external hints (hint-only, not economics-grade)
7. unresolved (`DECIMALS_UNRESOLVED`, `ERC20_DECIMALS_REVERT`, `DECIMALS_CONFLICT`)

## Strict acceptance gates

- `cycle_participating_decimals_known_rate >= 0.95` (economics-grade legs)
- `decimals_conflict_count = 0`
- `economics_grade_missing_for_capacity_routes = 0`

## Operator commands

```powershell
py -3.11 scripts/m8_3_token_metadata_registry_refresh.py --chain base

py -3.11 scripts/m8_3_acceptance_report.py --strict

py -3.11 scripts/m9_bridge_build.py `
  --graph-handoff-only --no-registry `
  --metadata-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json `
  --output data/tmp/m9_bridge_inventory_graph_handoff_latest.json

# Optional missing-only fallback (does not overwrite M8.3 provenance):
py -3.11 scripts/m9_enrich_bridge_decimals.py `
  --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json `
  --metadata-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json `
  --legacy-missing-only-fallback
```

## Current evidence line

```text
goal_status: REACHED (m8_3_acceptance_report.py --strict, 2026-06-24)
cycle_participating_dex_route_metadata_ready_rate: 1.0
pool_identity_verified_rate (cycle): 1.0
dex_routes_ready: 52/52 (pre graph-handoff rebuild registry)
curve_indices_source: m9_curve_pool_indices_latest.json via enrich_curve_routes
bridge_consumption: m8_3_authority_applied, routes_decimals_unknown=0
```

`execution_enabled`: false  
`kill_switch_active`: true

## Negative-cache / repeated-probe audit

```text
audit_verdict: M8.3 strict remains REACHED
primary_debt: unresolved NON_ERC20 / failed ERC20 rows are not yet a durable negative cache
strict_scope: out-of-cycle NON_ERC20 does not block M8.3
operational_risk: repeated refresh can re-probe the same non-economics-grade addresses
```

M8.3 is now the correct metadata authority for M9, but the next optimization should
persist non-economics-grade failures with a TTL and reason code. This must be a
metadata-cache optimization only: it must not hide cycle-participating routes from
acceptance, and it must not overwrite valid `m8_3_*` provenance.

Required follow-up:

```text
negative_cache_key: chain + token_address + code_hash
negative_cache_values: NON_ERC20 / NO_CODE / ERC20_DECIMALS_REVERT / PROBE_CAP_EXHAUSTED
refresh_policy: skip until TTL expires unless code_hash changes or route becomes cycle/econ-capacity participating
```
