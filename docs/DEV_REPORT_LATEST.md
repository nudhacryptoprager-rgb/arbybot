# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-04T07:49:00Z
goal_status: BLOCKED
blocker_status_after: UNIFIED_PIPELINE_CODE_READY__RUNTIME_NOT_VALIDATED
docs_reread_confirmed: true
run_id: m9-unified-pipeline-runtime-2026-06-04
mode: M9_UNIFIED_DATA_DRIVEN_PIPELINE
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Execute 10-step runtime validation (depth, bridge, diagnostic, soak, gate)
goal_status: BLOCKED
close_allowed: false
remaining_blockers: Dedicated HTTP RPC for sustained quote load; bridge toxic pool rate; QSR gate not met on latest soak
docs_reread_confirmed: true

## Runtime evidence (fresh)

| Artifact | run_timestamp / note | Key metrics |
|----------|----------------------|-------------|
| `m9_bridge_inventory_latest.json` | bridge rebuild 2026-06-04 | active=154, with_depth=136/154, `pool_quality_histogram`: QUARANTINED=128, DEPTH_OK=7, FACTORY_VERIFIED=19 |
| `m9_quote_route_diagnostic_latest.json` | productive lane | routes_probed=11, route_qsr=0.1818 |
| `m9_graph_latest.json` | verified soak | run_timestamp=2026-06-04T07:43:01Z, qsr=0.0769, runtime_gates.all_pass=false, depth_aware_known_rate=0.0 |
| `data/tmp/rpc_provider_ab_test_latest.json` | 2026-06-04 | publicnode archive_fail; dRPC 408 under burst |

## Commands executed

```powershell
py -3.11 scripts/run_m9_runtime_pipeline.py
$env:BASE_RPC='https://base-rpc.publicnode.com'
py -3.11 scripts/m9_enrich_bridge_depth.py --inventory data/runs/_rolling/m9_bridge_inventory_latest.json --verbose
py -3.11 -u scripts/m9_bridge_build.py --base-inv data/runs/_rolling/m9_bridge_inventory_latest.json ...
py -3.11 scripts/m9_quote_route_diagnostic.py --limit 50 --lane productive
py -3.11 scripts/rpc_provider_ab_test.py --route-limit 20
py -3.11 -m m9.graph_arb.runner --inventory data/tmp/m9_verified_inventory.json --duration-minutes 6 ...
py -3.11 scripts/ci_m9_productive_gate.py
```

## Decision

- **Code**: unified pipeline contracts landed (`pool_quality_state`, `core/provider_router.py`, scheduler budgets, layer telemetry).
- **Depth**: enrichment **succeeds on publicnode** (136/154 probed_ok); **fails on dRPC free tier** (408 timeouts).
- **QSR gate**: latest verified soak **does not PASS** (qsr=0.0769). Do not claim M9 REACHED.
- **Next**: set `BASE_RPC_PRIMARY` to paid dedicated endpoint; quarantine toxic bridge pools; re-soak ≥15m after RPC stable.
