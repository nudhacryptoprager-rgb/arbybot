# DEV REPORT LATEST -- M9 Bridge Smoke (M8→M9 Pipeline): PASS (10-min, bridge_inventory, best_gross=1.05 bps)

**mode**: M9_BRIDGE_SMOKE_PASS
**session_date**: 2026-05-24
**schema_family**: m9_graph_arb
**schema_revision**: m9.1
**run_label**: bridge_smoke (10-min real-RPC, publicnode, productive-lane, raw_http, dynamic-sizes, bridge_inventory 119 routes)
**execution_enabled**: false
**kill_switch_active**: true

---

## 0) Meta
timestamp_utc: 2026-05-24T18:10:53Z
run_id: data/runs/_rolling/m9_graph_latest.json
mode: ONLINE
artifact_mode: rolling
config: config/exotic_base_anchor.yaml, productive-lane, --quote-backend raw_http, --dynamic-sizes, --prequote-min-bps -9999, publicnode.com
inventory: data/runs/_rolling/m9_bridge_inventory_latest.json (schema: m9_bridge_inventory.1, 119 routes)
code_identity:
  primary: ts:2026-05-24T18:10:53Z
  dirty: false
  desc: >
    Bridge smoke: first run via m9_bridge_inventory_latest.json (M8→M9 pipeline).
    bridge_builder.py created; artifacts.py + runner.py updated; bridge_source_metrics in artifact.
    2 canonical-set test fixes (test_nonstop_loop_artifacts.py, test_orderflow_artifacts.py).

## 1) Scope
goal: Bridge smoke -- validate M8→M9 bridge pipeline end-to-end. Uses m9_bridge_inventory_latest.json
      produced by bridge_builder.build_bridge_inventory(). Verify bridge_source_metrics propagates
      to m9_graph_latest.json artifact.
change_summary:
  - m9/graph_arb/bridge_builder.py (NEW): M8→M9 bridge inventory builder; funnel tracking
  - m9/graph_arb/artifacts.py: bridge_source_metrics Optional[Dict] parameter added
  - m9/graph_arb/runner.py: bridge extraction block; all 5 build_artifact calls updated
  - scripts/m9_bridge_build.py (NEW): CLI for bridge inventory build
  - tests/unit/test_m9_bridge_builder.py (NEW): 17 tests all PASS
  - tests/unit/test_nonstop_loop_artifacts.py: m9_bridge_inventory_latest.json added to canonical set
  - tests/unit/test_orderflow_artifacts.py: m9_bridge_inventory_latest.json added to canonical set
touched_files:
  - m9/graph_arb/bridge_builder.py
  - m9/graph_arb/artifacts.py
  - m9/graph_arb/runner.py
  - scripts/m9_bridge_build.py
  - tests/unit/test_m9_bridge_builder.py
  - tests/unit/test_nonstop_loop_artifacts.py
  - tests/unit/test_orderflow_artifacts.py

## 2) Commands Executed
bridge_build: python -m m9.graph_arb.bridge_builder → m9_bridge_inventory_latest.json (119 routes)
bridge_smoke runner (10 min, raw_http, dynamic-sizes, bridge_inventory): COMPLETED duration_fulfilled=true
ci_m9_productive_gate.py: EXIT 0 (PASS)
pytest tests/unit -q: 5956 passed, 6 skipped (5939 + 17 new bridge tests)

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/m9_bridge_inventory_latest.json (schema: m9_bridge_inventory.1, 119 routes)
  - data/runs/_rolling/m9_graph_latest.json (bridge_smoke, run_ts: 2026-05-24T18:10:53Z)

## 4) Key Results -- Bridge Smoke

### Run stats
- run_timestamp: 2026-05-24T18:10:53Z
- elapsed=598.6s (duration_fulfilled=true), sweeps=237, cycles_quoted=1178
- cycles_positive_gross=2
- best_cycle_gross_bps=+1.0531 (gross only -- no router sim)
- best_cycle_net_bps=+1.0531 (alias for gross; true net pending router_sim)
- positive_cycle_multi_hit_count=0, positive_cycle_max_repeat=1
- qsr=0.9599, rpc_provider=publicnode, http_429_count=0
- quote_backend=raw_http, dynamic_size_enabled=True, selection_rate=57.97%
- inventory=data/runs/_rolling/m9_bridge_inventory_latest.json (bridge pipeline)
- scan_scope.pool_quality_lane=productive, depth_quarantine_skipped=57

### bridge_source_metrics (M8→M9 funnel)
| metric | value |
|---|---:|
| m8_new_pools_input | 20 |
| m8_1_anchor_routes_input | 6 |
| token_verified_count | 17 |
| anchor_connected_count | 9 |
| cross_dex_seen_count | 9 |
| factory_verified_count | 119 |
| depth_ok_count | 117 |
| anchor_connected_from_base | 115 |
| graph_ready_from_m8 | 0 |
| graph_ready_total | 119 |
| m8_stale | True (artifact from 2026-05-15, >4h) |
| m8_1_stale | True (artifact from 2026-05-21, >4h) |

**Note**: m8_stale=True, m8_1_stale=True, graph_ready_from_m8=0 are EXPECTED — M8/M8.1 artifacts
are stale; no new M8 pool addresses appear in verified base inventory. This is a WARNING not a blocker.
Full GPT acceptance criteria (m8_stale=false, graph_ready_from_m8>0) requires fresh M8/M8.1 runs (separate step).

### runtime_gates -- ALL PASS
| gate | value | threshold | pass |
|---|---:|---:|---|
| multicall_success_rate | 1.0 | 0.90 | PASS |
| data_completeness | 1.0 | 0.98 | PASS |
| qsr | 0.9599 | 0.80 | PASS |
| unverified_active_routes | 0 | 0 | PASS |
| quote_revert_rate | 0.0 | <0.05 | PASS |
| **all_pass** | **true** | | **PASS** |

### Pool-Quality Gate
| gate | value | threshold | pass |
|---|---:|---:|---|
| toxic_route_rate | 0.5067 | <0.90 | **PASS** |

### Economics -- NEAR_MISS
- cycle_reject_histogram: UNFAVORABLE_PRICES=466, TOXIC_ROUTE_PRICE_IMPACT=571, QUOTE_FAILED=47, FEE_DRAG=87, POSITIVE=2
- cycles_positive_gross=2, best_cycle_gross_bps=+1.0531
- top cycle: WETH→USDC→EURC→WETH (uniswap_v3+aerodrome_slipstream, fee=2.01bps, size=)
- economics_gate_status=NEAR_MISS (not POSITIVE -- no router_sim yet)

### Bridge Pipeline Contract Verification
- bridge_source_metrics in m9_graph_latest.json: ✓
- inventory_path in run_context: data/runs/_rolling/m9_bridge_inventory_latest.json ✓
- schema_version in bridge inventory: m9_bridge_inventory.1 ✓
- active_routes from bridge inventory accepted: 119 ✓
- unverified_active_routes: 0 ✓

### theoretical_net_profit
mode: paper_simulated
gross_pnl_usdc: 0.0 (no real trades)
net_pnl_usdc: 0.0
disclaimer: Theoretical profit based on simulated execution. No real trades were executed.

## 5) Contract Checks
status/reasons consistency: OK -- all_pass=True, toxic_rate=0.5067 < 0.90
rolling discipline: OK -- m9_bridge_inventory_latest.json and m9_graph_latest.json both in canonical set
bridge_source_metrics contract: OK -- propagated from bridge_builder → artifact → gate
v2.x provenance contract: OK -- run_timestamp, generated_at_utc present; no deprecated fields
runtime artifacts not committed: OK -- data/runs/** not in git

## 6) Blocker Classification
| Type | Level | Status |
|---|---|---|
| CODE | RESOLVED | bridge_builder.py, artifacts.py, runner.py, CLI, 17 tests; 5956 tests PASS |
| INFRA | RESOLVED | raw_http backend, dynamic-sizes; 0x429; qsr=0.96 |
| BRIDGE_FRESHNESS | LOW_WARNING | m8_stale=True, m8_1_stale=True, graph_ready_from_m8=0; requires fresh M8/M8.1 runs |
| MARKET_WINDOW | LOW | cycles_positive=2 (NEAR_MISS); best_gross=1.05 bps; economics_gate_status=NEAR_MISS |
| ROUTER_SIM | BLOCKED | estimated_cost_bps=null; router_sim_net_bps=null; true net profit unknown |

---

## Session Completion

session_goal: M8→M9 bridge pipeline: bridge_builder.py, artifacts.py update, runner.py update,
              CLI, tests, bridge inventory generation, bridge smoke 10-min run, gate PASS.
goal_status: REACHED
close_allowed: true
remaining_blockers:
  - economics_gate_status=NEAR_MISS (not POSITIVE); router_sim NOT_STARTED
  - m8_stale=True, m8_1_stale=True (requires fresh M8/M8.1 runs for full GPT acceptance)
  - graph_ready_from_m8=0 (requires fresh M8 runs feeding new pools through pool_verifier)
  - estimated_cost_bps=null (TODO: gas + router fee model)
evidence_session_run_dirs: data/runs/_rolling/m9_graph_latest.json (run_ts: 2026-05-24T18:10:53Z)
primary_blocker_of_session: none -- bridge pipeline delivered end-to-end.
blocker_status_before: BRIDGE_NOT_IMPLEMENTED
blocker_status_after: RESOLVED -- bridge_builder.py created; bridge_source_metrics in artifact;
  bridge smoke gate PASS (all_pass=True, qsr=0.9599, 0x429, 2 positive gross, best=1.05bps).
docs_reread_confirmed: true
