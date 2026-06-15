# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Reporting split:** M8.2 gates → `scripts/m8_2_acceptance_report.py` + [Status_M8_2.md](Status_M8_2.md). M9 gates → `scripts/m9_lane_acceptance_report.py`.

**Current runtime line:** **M8_2_GRAPH_HANDOFF_REACHED / M9_QUOTE_LIVENESS_PROVEN / M9_ECONOMICS_BLOCKED_BY_VALUE_RATIO_RCA**

```text
M9_QUOTE_LIVENESS_PROVEN / M9_ECONOMICS_BLOCKED_BY_VALUE_RATIO_RCA:
  duration_fulfilled=true
  runner_outcome=COMPLETED
  cycles_found=1776
  cycles_quoteable=1776
  qsr=1.0
  qsr_econ=0.0
  sizes_usd=[25,100,250,500]
  cycles_positive_gross=0
  economics_status=NOT_PROVEN
  next_owner=leg amount continuity + Curve/Maverick value-ratio RCA
  next_evidence=data/tmp/m9_graph_handoff_quote_validation_10m.json
```

| Layer | Status | Source |
|-------|--------|--------|
| M8 / M8.1 upstream | **REACHED** | [Status_M8.md](Status_M8.md), [Status_M8_1.md](Status_M8_1.md) |
| M8.2 handoff | **REACHED** (`graph_topology`) | [Status_M8_2.md](Status_M8_2.md) |
| M8.2 2-leg mirror quote | **BLOCKED** (`mirror_quote_ready=0`) | M8.2 only |
| M9 economics | **NOT_PROVEN** (`cycles_positive_gross=0`) | this file |

```text
M8_2_UPSTREAM_READY: true
M9_ECONOMICS_STATUS: NOT_PROVEN
M9_QUOTE_LIVENESS: PROVEN (qsr=1.0, cycles_quoteable=1776)
```

## Graph-handoff topology RCA

Full expansion (`routes_admitted=471`) contains **3/4-leg cycles** in discovery lane (see `m9_graph_topology_diagnostic.py --expansion ... --bridge ...`). Prior `--graph-handoff-only` selection dropped closure edges → bridge showed `cycles_3_4=0` while full expansion did not.

**Fix in progress:** cycle-preserving `select_graph_handoff_universe_routes()`, node canonicalization (`WETH`/`0x420000`), placeholder `T` symbol repair, expansion-vs-bridge comparison in topology diagnostic.

Required evidence: `data/tmp/m9_graph_topology_diagnostic_latest.json` with `expansion_vs_bridge` block.

## Precise claims

```text
M8.2 handoff readiness:     REACHED (graph_topology)
M8.2 economics/quote:       out of scope
M9 economics:               NOT_PROVEN
```

Do **not** claim profit-ready until `cycles_quoteable > 0` and depth/sizing RCA passes.

## Canonical commands

```powershell
py -3.11 scripts/m9_bridge_build.py --graph-handoff-only --no-registry --output data/tmp/m9_bridge_inventory_graph_handoff_latest.json

py -3.11 scripts/m9_graph_topology_diagnostic.py `
  --expansion data/runs/_rolling/m8_cross_dex_expansion_latest.json `
  --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json `
  --cycle-lengths 2,3,4

$env:ARBY_M9_CYCLE_LENGTHS='2,3,4'
$env:ARBY_BRIDGE_SHADOW_SKIP_CYCLE_GATE='1'
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 -u -m m9.graph_arb.runner --chain base --config config/exotic_base_anchor.yaml --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json --duration-minutes 10 --productive-lane --require-factory-verified --quote-backend raw_http --quote-workers 1 --max-cycles-per-sweep 20 --artifact-path data/tmp/m9_graph_handoff_quote_validation_10m.json

py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json --shadow data/tmp/m9_graph_handoff_quote_validation_10m.json
```
