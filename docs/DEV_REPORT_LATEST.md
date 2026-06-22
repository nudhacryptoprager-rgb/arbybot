# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-22T10:35:00Z
goal_status: BLOCKED
blocker_status_after: M9_BLOCKED_BY_DEPTH_CAPACITY_NOT_METADATA
docs_reread_confirmed: true
run_id: m8-3-risk-registry-bridge-closure-2026-06-22
mode: M8_3_REGISTRY_REFRESH_AND_M9_CAPACITY_GATES
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Close risk-heuristic cleanup loop: green bridge tests, refreshed registry, no stale decimals blocker, capacity histogram after depth enrich.
goal_status: BLOCKED
close_allowed: true
remaining_blockers: M9 depth/capacity (`NO_QUOTEABLE_CYCLES`, `NO_ECON_CAPACITY_CYCLES`); Curve lane incomplete; stale shadow artifact.
primary_blocker_of_session: DEPTH_CAPACITY_FLOOR
blocker_status_before: RISK_HEURISTICS_CODE_FIXED_PENDING_REGISTRY_REFRESH
blocker_status_after: M9_BLOCKED_BY_DEPTH_CAPACITY_NOT_METADATA
docs_reread_confirmed: true

## Runtime evidence

| Artifact | Key metrics |
|----------|-------------|
| `data/runs/_rolling/m8_3_token_metadata_registry_latest.json` | `generated_at=2026-06-22T08:32:35Z`, `fee_on_transfer_suspected=1` (was 478 pre-fix) |
| `data/tmp/m8_3_acceptance_report_latest.json` | `goal_status=REACHED`, blockers `[]` |
| `data/tmp/m9_bridge_inventory_graph_handoff_latest.json` | `routes_decimals_unknown=0`, `m8_3_authority_applied=true`, `depth_known_rate=0.8286` |
| `data/tmp/m9_lane_acceptance_report_latest.json` | `m8_3_upstream=REACHED`, `DECIMALS_ENRICHMENT_REQUIRED` absent |
| `tests/unit/test_m9_bridge_builder.py` | 47 PASS |

## Commands executed

```powershell
py -3.11 -m pytest tests/unit/test_m8_3_token_risk_metadata.py tests/unit/test_m8_3_aggregator.py tests/unit/test_m9_bridge_builder.py tests/unit/test_m9_lane_acceptance_report.py -q
py -3.11 scripts/m8_3_token_metadata_registry_refresh.py --chain base --task-mode aggregated --with-dex-workers
py -3.11 scripts/m8_3_acceptance_report.py --strict
py -3.11 scripts/m9_bridge_build.py --graph-handoff-only --no-registry --metadata-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json --output data/tmp/m9_bridge_inventory_graph_handoff_latest.json
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m9_enrich_bridge_depth.py --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json --sleep-ms 150
py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json --m8-3-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json --shadow data/tmp/m9_graph_handoff_quote_validation_10m.json --rca data/tmp/m9_quote_lane_rca_graph_handoff_latest.json
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit
```

## Key results

- Risk registry noise: `FEE_ON_TRANSFER_SUSPECTED` **478 → 1** after PUSH4 heuristic + refresh.
- Bridge tests: **47/47 PASS** (Curve dedupe + productive admission).
- Lane acceptance: **no** `DECIMALS_ENRICHMENT_REQUIRED` when `m8_3_upstream=REACHED` and `routes_decimals_unknown=0`.
- Operator metrics: `active_factory_verified_routes` logged as primary; legacy `factory_verified_count` labeled base-inventory-only.
- M9 blockers remain capacity/depth: stale shadow `cycles_quoteable=0`, `ECON_RPC_QUOTES_ZERO`.

## Next owner
- `m9_curve_discovery.py` + indices probe; rebuild bridge.
- Fresh shadow only after capacity histogram shows enough routes `>= $180`.
- Use `econ_quote_success_rate`, not raw `qsr_econ`, when `cycles_quoteable=0`.
