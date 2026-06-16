# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Reporting split:** M8.2 gates → `scripts/m8_2_acceptance_report.py` + [Status_M8_2.md](Status_M8_2.md). M9 gates → `scripts/m9_lane_acceptance_report.py`.

**Current runtime line:** **M9_POST_M82_TWO_PHASE_SHADOW / QUOTE_LIVENESS_PARTIAL / SANITY_IMPROVED_NOT_ZERO / ECONOMICS_NOT_PROVEN**

```text
M9_POST_M82_TWO_PHASE_SHADOW (2026-06-16, after DexScreener-first two-phase M8.2 refresh):
  duration_fulfilled=true
  run_timestamp=2026-06-16T08:59:32Z
  elapsed_s=569
  bridge=m9_bridge_inventory_graph_handoff_latest.json (graph_ready_total=210)
  cycles_found=808
  cycles_quoteable=73
  cycles_positive_gross=0
  cycle_reject_histogram=STABLE_VALUE_RATIO_OUTLIER:246 NEGATIVE_GROSS:73 CYCLE_QUOTE_FAILED:33 AMOUNT_CONTINUITY_VIOLATION:7 QUOTE_FAILED:2
  m8_stale=true (sniper not refreshed this session)
  primary_blocker=NO_POSITIVE_GROSS + residual sanity rejects
  upstream=M8.2 handoff_ready=true after fresh hints+expansion (verified_yield=37)
```

Prior verification shadow (2026-06-15, pre-M8.2-two-phase):

```text
M9_VERIFICATION_SHADOW_COMPLETED (post-fix reshadow, 2026-06-15):
  duration_fulfilled=true
  runner_outcome=COMPLETED
  bridge=m9_bridge_inventory_graph_handoff_latest.json (canonical)
  graph_ready_total=324
  active_routes=208 (curve_stable=22 promoted to active)
  curve_active_promoted_count=22
  depth_known_rate=0.1538 (target >=0.8 not met)
  decimals_unknown=~175/219 routes
  m8_stale=true (sniper age ~4h; refresh before production-grade repeat)
  m8_direct_routes_in_bridge=82
  cycles_found=840
  cycles_quoteable=452 (was 0 pre-fix)
  cycles_positive_gross=0
  cycles_with_m8_pool=140
  cycles_with_direct_sniper_pool=0
  cross_mechanic_cycles_quoteable=32
  cycle_reject_histogram=NEGATIVE_GROSS:452 STABLE_VALUE_RATIO_OUTLIER:315 CYCLE_QUOTE_FAILED:65
  stable_value_ratio_outlier_legs=2 (RCA sample; histogram still 315)
  primary_blocker=NO_POSITIVE_GROSS + residual sanity rejects at sub-$1 sizing
  primary_next_owner=depth/decimals enrichment + curve/maverick adapter RCA
  next_evidence=data/tmp/m9_quote_lane_rca_graph_handoff_latest.json
  m9_blockers=NO_POSITIVE_GROSS,QSR_ECON_ZERO
```

Prior pre-fix shadow (superseded):

```text
M9_SANITY_BLOCKED / FRESH_M8_TO_M9_SHADOW_COMPLETED:
  cycles_found=980
  cycles_quoteable=0
  cycle_reject_histogram=STABLE_VALUE_RATIO_OUTLIER:980
```

| Layer | Status | Source |
|-------|--------|--------|
| M8 / M8.1 upstream | **REACHED** | [Status_M8.md](Status_M8.md), [Status_M8_1.md](Status_M8_1.md) |
| M8.2 handoff | **REACHED** (`graph_topology`) | [Status_M8_2.md](Status_M8_2.md) |
| M8.2 2-leg mirror quote | **BLOCKED** (`mirror_quote_ready=0`) | M8.2 only |
| M9 economics | **NOT_PROVEN** (`cycles_positive_gross=0`) | this file |

```text
M9_QUOTE_LIVENESS: PARTIAL (cycles_quoteable=452, qsr_liveness=0.0 dynamic-size subset)
M9_SANITY_STATUS: IMPROVED_NOT_ZERO (STABLE_VALUE_RATIO_OUTLIER 980→315; P0 fix partially runtime-validated)
M9_ECONOMICS_STATUS: NOT_PROVEN (cycles_positive_gross=0)
M8_FRESH_PARTICIPATION: PROVEN_IN_GRAPH (cycles_with_m8_pool=140) QUOTEABLE_PARTIAL (cross_mechanic_quoteable=32)
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

py -3.11 scripts/m9_enrich_bridge_decimals.py --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json

py -3.11 scripts/m9_enrich_bridge_depth.py --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json --sleep-ms 150

py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json --shadow data/tmp/m9_graph_handoff_quote_validation_10m.json --rca data/tmp/m9_quote_lane_rca_graph_handoff_latest.json
```
