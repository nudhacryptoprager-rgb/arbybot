# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Reporting split:** M8.2 gates → `scripts/m8_2_acceptance_report.py` + [Status_M8_2.md](Status_M8_2.md). M9 gates → `scripts/m9_lane_acceptance_report.py`.

**Current runtime line:** **M8_2_GRAPH_HANDOFF_REACHED / M9_QUOTE_VALIDATION_BLOCKED**

| Layer | Status | Source |
|-------|--------|--------|
| M8 / M8.1 upstream | **REACHED** | [Status_M8.md](Status_M8.md), [Status_M8_1.md](Status_M8_1.md) |
| M8.2 handoff | **REACHED** (`graph_topology`) | [Status_M8_2.md](Status_M8_2.md) |
| M8.2 2-leg mirror quote | **BLOCKED** (`mirror_quote_ready=0`) | M8.2 only |
| M9 economics | **NOT_EVALUATED_AFTER_GRAPH_HANDOFF** | this file |

```text
M8_2_UPSTREAM_READY: true
M9_ECONOMICS_STATUS: NOT_EVALUATED_AFTER_GRAPH_HANDOFF
```

## Graph-handoff quote validation (2026-06-15, widened universe)

| Step | Result |
|------|--------|
| Expansion handoff funnel | `graph_handoff_universe_routes=69`, `cycle_potential=69` |
| Bridge `--graph-handoff-only --no-registry` | `graph_ready_total=66`, `active_routes=66`, `m8_2_handoff_lane=graph_topology` |
| M9 shadow inventory | `data/tmp/m9_bridge_inventory_graph_handoff_latest.json` |
| M9 quote validation run | `data/tmp/m9_graph_handoff_quote_validation_10m.json` |
| `cycles_found` / `cycles_quoteable` | **0** / **0** (12 tokens in graph, 10 M8-sniper edges) |
| `m9_quote_validation_blockers` | **`UPSTREAM_OK_BUT_NO_CYCLES`** |

**Interpretation:** M8.2 handoff succeeded and universe widened **6 → 66** active bridge routes. M9 graph cycle builder still finds **no closable cycles** — next RCA is **M9 graph builder / productive-lane edge admission**, not M8.2 rollback.

**Next action:** widen graph-handoff universe further (`cross_anchor` still 0); if cycles remain 0 at 66 routes, fix M9 cycle builder edge wiring from expansion routes.

## Precise claims

```text
M8.2 handoff readiness:     REACHED (graph_topology)
M8.2 economics/quote:       out of scope
M9 economics:               NOT_PROVEN
```

Do **not** claim profit-ready until `cycles_quoteable > 0` and depth/sizing RCA passes.

## Next steps (M9-owned)

1. If `cycles_found=0`: widen graph handoff universe (`cross_anchor`, more tokens) — M8.2 expansion rerun
2. If `cycles_found>0` but `cycles_quoteable=0`: RCA `QUOTE_REVERT`, `NO_DEPTH`
3. If `cycles_quoteable>0`: depth/sizing/economics gate

## Canonical commands

```powershell
py -3.11 scripts/m9_bridge_build.py --graph-handoff-only --no-registry --output data/tmp/m9_bridge_inventory_graph_handoff_latest.json

$env:ARBY_BRIDGE_SHADOW_SKIP_CYCLE_GATE='1'
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 -u -m m9.graph_arb.runner --chain base --config config/exotic_base_anchor.yaml --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json --duration-minutes 10 --productive-lane --require-factory-verified --quote-backend raw_http --quote-workers 1 --max-cycles-per-sweep 20 --artifact-path data/tmp/m9_graph_handoff_quote_validation_10m.json

py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json --shadow data/tmp/m9_graph_handoff_quote_validation_10m.json
```
