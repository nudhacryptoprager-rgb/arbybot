# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-16T10:17:48Z
goal_status: BLOCKED
blocker_status_after: M9_ECON_SIZE_ATTEMPTED__MARKET_NO_POSITIVE_GROSS
docs_reread_confirmed: true
run_id: m9-econ-size-shadow-2026-06-16
mode: M9_ECONOMICS_SIZE_VALIDATION
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Unify economics floor sizing, attempt economics-size quotes, and determine whether zero gross is market or instrumentation.
goal_status: BLOCKED
close_allowed: true
remaining_blockers: `cycles_positive_gross=0` at `$180` economics size with `qsr_econ=0.9144`; `depth_known_rate=0.1489`; `routes_decimals_unknown=146`; `m8_stale=true`.
primary_blocker_of_session: NO_POSITIVE_GROSS
blocker_status_before: ECON_SIZE_NOT_ATTEMPTED_FOR_CURRENT_COST_PROFILE
blocker_status_after: MARKET_NO_POSITIVE_GROSS
docs_reread_confirmed: true

## Runtime evidence

| Artifact | Key metrics |
|----------|-------------|
| `data/tmp/m9_graph_handoff_quote_validation_10m.json` | `run_timestamp=2026-06-16T10:07:43Z`, `duration_fulfilled=true`, `econ_quote_attempts=514`, `qsr_econ=0.9144`, `cycles_quoteable=102`, `cycles_positive_gross=0` |
| `data/tmp/m9_bridge_inventory_graph_handoff_latest.json` | `graph_ready_total=210`, `depth_known_rate=0.1489`, `routes_decimals_unknown=146` |
| `data/tmp/m9_lane_acceptance_report_latest.json` | `m8_2_upstream=REACHED`, `m9_blockers=['NO_POSITIVE_GROSS']` |
| `data/runs/_rolling/m8_external_pool_hints_latest.json` | DexScreener-first two-phase, `verified_yield=37`, `radar_fast_tokens=753` |
| `data/runs/_rolling/m8_cross_dex_expansion_latest.json` | `routes_admitted=676`, `handoff_ready=true` |

## Commands executed

```powershell
py -3.11 scripts/check_repo_safety.py
py -3.11 -m pytest tests/unit/test_per_dex_sizing.py tests/unit/test_m9_depth_aware_sizing.py tests/unit/test_m9_graph_artifact.py tests/unit/test_m9_quote_lane_rca.py -q
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m9_enrich_bridge_decimals.py --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m9_enrich_bridge_depth.py --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json --force-reprobe --sleep-ms 80
$env:ARBY_M9_CYCLE_LENGTHS='2,3,4'
$env:ARBY_BRIDGE_SHADOW_SKIP_CYCLE_GATE='1'
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 -u -m m9.graph_arb.runner --chain base --config config/exotic_base_anchor.yaml --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json --duration-minutes 10 --productive-lane --require-factory-verified --quote-backend raw_http --quote-workers 1 --max-cycles-per-sweep 20 --artifact-path data/tmp/m9_graph_handoff_quote_validation_10m.json
py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json --shadow data/tmp/m9_graph_handoff_quote_validation_10m.json --rca data/tmp/m9_quote_lane_rca_graph_handoff_latest.json
```

## Key results

Code fixes landed:
- `productive_cycle_size_usd_cap()` now uses `economic_size_floor_usd()` (default `$180`) for unknown-depth distinct cycles.
- `quote_size_truth` exposes `attempted_size_usd_histogram`, `selected_size_usd_histogram`, `below_econ_quote_attempts`.
- `loss_reason_histogram` no longer marks zero/sanity-suppressed cycles as `POSITIVE`.

Economics-size shadow (10m):

| Metric | Before fix | After fix |
|--------|------------|-----------|
| `economic_size_floor_usd` | 180.0 | 180.0 |
| `econ_quote_attempts` | 0 | **514** |
| `qsr_econ` | 0.0 | **0.9144** |
| `attempted sizes` | liveness/mixed | **$180 only** |
| `cycles_quoteable` | 73 | 102 |
| `cycles_positive_gross` | 0 | 0 |
| Verdict | ECONOMICS_NOT_PROVEN | **MARKET_NO_POSITIVE_GROSS** |

Interpretation: zero gross is now a defensible market verdict at economics size, not an instrumentation gap. Residual quality blockers: low depth coverage, high decimals-unknown count, stale M8 sniper.

## Next owner
- Raise `depth_known_rate` toward `>=0.5` interim / `>=0.8` production.
- Reduce `routes_decimals_unknown` before claiming production-grade economics.
- Refresh M8/M8.1 artifacts before next long shadow or spread_lifetime run.
