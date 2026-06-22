# Status: M8.3 Token Metadata Registry & Decimals Service

**Status**: **M8_3_STRICT_PASS / AUTHORITY_WIRED / RISK_HEURISTICS_CODE_FIXED**

```text
goal_status: REACHED (m8_3_acceptance_report.py --strict)
registry_refresh: fee_on_transfer_suspected collapsed after PUSH4 heuristic fix
risk_heuristics: PUSH4-aware; no transfer/transferFrom in fee-on-transfer flag
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
goal_status: REACHED (m8_3_acceptance_report.py --strict)
registry_refresh: fee_on_transfer_suspected collapsed after PUSH4 heuristic fix
bridge_consumption: m8_3_authority_applied, routes_decimals_unknown=0 on graph-handoff rebuild
```

`execution_enabled`: false  
`kill_switch_active`: true
