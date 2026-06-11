# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-11T16:27:36Z
goal_status: BLOCKED
blocker_status_after: M8_2_RUNTIME_PARTIAL_REACHED__QUALITY_NOT_READY
docs_reread_confirmed: true
run_id: m8-2-runtime-audit-2026-06-11
mode: M8_2_RUNTIME_AUDIT
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Audit M8.2 after M8/M8.1 upstream closure and identify blockers before claiming branch readiness.
goal_status: BLOCKED
close_allowed: true
remaining_blockers: M8.2 finds and forwards routes, but `subgraph_ready_tokens=1`, `verified_second_pool_count=5`, external hints are stale vs fresh sniper, and no fresh M9 economics proof exists after this M8.2 run.
primary_blocker_of_session: M8_2_QUALITY_AND_HANDOFF_NOT_100_PERCENT
blocker_status_before: ACTIVE
blocker_status_after: BLOCKED
docs_reread_confirmed: true

## Runtime evidence

| Artifact | Key metrics |
|----------|-------------|
| `data/runs/_rolling/new_pool_sniper_latest.json` | `status=ACTIVE`, `recent_events=278`, `generated_at_utc=2026-06-11T16:06:29Z`, `rpc_errors=0` |
| `data/runs/_rolling/m8_1_stable_anchor_latest.json` | candidates=3228, passes=351, qsr=1.0 |
| `data/runs/_rolling/m8_pending_pairs.json` | `generated_at_utc=2026-06-11T16:12:16Z`, tokens=701 |
| `data/runs/_rolling/m8_external_pool_hints_latest.json` | `generated_at_utc=2026-06-11T07:50:18Z`, verified_second_pool_count=162, stale vs fresh sniper |
| `data/runs/_rolling/m8_cross_dex_expansion_latest.json` | `generated_at_utc=2026-06-11T16:25:44Z`, tokens_in=701, routes_admitted=1025, multi_venue_tokens=14 |
| `data/tmp/m9_bridge_inventory_shadow_latest.json` | `generated_at_utc=2026-06-11T16:27:36Z`, graph_ready_total=1130, graph_ready_from_expansion=817, active_routes=950 |
| `data/tmp/m9_lane_acceptance_report_latest.json` | M8/M8.1 fresh, M8.2 visible, M9 blockers remain |

## Commands executed

```powershell
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m8_cross_dex_expand.py --chain base --config config/exotic_base_anchor.yaml --input data/runs/_rolling/m8_pending_pairs.json --expansion-mode token_neighborhood --external-hints data/runs/_rolling/m8_external_pool_hints_latest.json --output data/runs/_rolling/m8_cross_dex_expansion_latest.json --verbose

py -3.11 -u scripts/m9_bridge_build.py --config config/exotic_base_anchor.yaml --registry data/runs/_rolling/m8_pending_pairs.json --include-expansion-duplicates-for-shadow --output data/tmp/m9_bridge_inventory_shadow_latest.json

py -3.11 scripts/m9_lane_acceptance_report.py
```

## Key results

M8.2 is no longer the old "2 routes / BASEAI only" state. It now expands the fresh M8 registry into a large M8-derived universe:

| Metric | Value |
|--------|------:|
| `tokens_in` / `m8_tokens_in` | 701 / 701 |
| `routes_admitted_count` | 1025 |
| `hint_tokens_matched` | 774 |
| `multi_venue_tokens` | 14 |
| `connector_routes_count` | 67 |
| `subgraph_ready_tokens` | 1 |
| `verified_second_pool_count` | 5 |
| `external_hints_enabled` | true |

DEX coverage in M8.2:

| DEX | Routes |
|-----|-------:|
| uniswap_v4 | 678 |
| maverick_v2 | 143 |
| balancer_vault | 94 |
| uniswap_v2 | 61 |
| uniswap_v3 | 36 |
| curve_stable | 9 |
| aerodrome | 2 |
| pancakeswap_v3 | 2 |

Distinct-pricing lane report at route level:

| Adapter | Discovered | Verified | Admitted | Quoteable |
|---------|-----------:|---------:|---------:|----------:|
| curve_stable | 9 | 9 | 9 | 9 |
| balancer_vault | 94 | 94 | 94 | 79 |
| maverick_v2 | 143 | 143 | 143 | 90 |

Bridge handoff after M8.2:

| Metric | Value |
|--------|------:|
| `graph_ready_total` | 1130 |
| `graph_ready_from_m8` | 196 |
| `graph_ready_from_expansion` | 817 |
| `active_routes` | 950 |
| `canonical_routes_count` | 1016 |
| `routes_rejected_not_m8_derived` | 94 |
| `m8_stale` / `m8_1_stale` | false / false |

## Audit conclusion

M8.2 is **runtime-partial reached**: it consumes fresh M8 registry data, uses external hints, includes distinct-pricing DEX lanes, and passes a large M8-derived route set into bridge.

M8.2 is **not 100% ready** because readiness should mean not only "many routes", but "enough verified, cross-DEX, connector-complete, economics-eligible subgraphs for M9". Current blockers:

1. `subgraph_ready_tokens=1` is too low for production-quality M9 search.
2. `verified_second_pool_count=5` is borderline and should be raised before claiming strong M8.2 coverage.
3. External hints are stale relative to the fresh sniper run (`07:50` vs `16:06`).
4. M8.2 logs still show resolver attempts with partial/symbol-like token identifiers such as `0x420000` / `0x833589`; these must not reach pair resolution.
5. `connector_routes_count=67`, but only one token becomes subgraph-ready, so connector synthesis is not yet reliably converting coverage into usable topology.
6. Route-level quoteability for Balancer/Maverick exists, but cycle-level economics remains unproven downstream.

## Decision

- M8: REACHED for upstream runtime.
- M8.1: REACHED for upstream quote-probe role.
- M8.2: PARTIAL_REACHED, but BLOCKED for 100% readiness.
- M9 economics: BLOCKED and not part of this closure.

Do not run a long economics soak as the next action. First refresh hints after fresh M8, repair M8.2 token identity/connector readiness, and prove `subgraph_ready_tokens` plus `verified_second_pool_count` improve in the expansion artifact.
