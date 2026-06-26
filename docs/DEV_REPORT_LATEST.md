# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-25T21:51:22Z
goal_status: REACHED
blocker_status_after: DIAGNOSTIC_NO_POSITIVE_GROSS
docs_reread_confirmed: true
run_id: time-to-mirror-full-rerun-2026-06-25
mode: time_to_mirror
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Close time_to_mirror control-plane runtime proof (mirror RPC/heartbeat, queue v2, narrow diagnostic shadow, fail-marker hygiene).
goal_status: REACHED
primary_blocker_of_session: stale_heartbeat_900s on m8_mirror_quote_reprobe
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
close_allowed: true
remaining_blockers: route provenance mass-fill re-expand in progress after registry/watchlist merge fix
evidence_session_run_dirs: n/a (rolling/tmp artifacts)
docs_reread_confirmed: true

## Control-plane / mirror quote

| Check | Result |
|-------|--------|
| Resume `m8_mirror_quote_reprobe` | exit **0**, productive RPC, checkpoint alive |
| `m8_second_pool_verify` | exit **2** (`no_quote_ready`, allowed) |
| Separate checkpoints | `m8_mirror_quote_reprobe_progress.json` (210 routes, quote_ok=81) + `m8_second_pool_verify_progress.json` |
| `start_pipeline_latest.fail` after success | **absent** (cleared on `.done`) |
| Full rerun `--force-rerun-steps` @100 | **done** `2026-06-25T21:51:22Z` |

## Time-to-mirror lane artifacts

| Artifact | Result |
|----------|--------|
| Pending queue | `m8_time_to_mirror_pending_queue_v2`, count=743, top `priority_score=35.0` |
| SLA export | `mirror_quote_ready_tokens=4`, reprobe exit 0 / verify exit 2 preserved |
| M8.2 strict | **REACHED** |
| M8.3 strict | **REACHED** |
| Narrow M9 shadow | `duration_fulfilled=true`, cycles_found=1039, cycles_quoteable=200, cycles_positive_gross=0 |
| Narrow lane status | `diagnostic_lane_status=DIAGNOSTIC_NO_POSITIVE_GROSS` (not production profit claim) |
| NALI RCA | `no_active_liquidity_rca.leg_failures_total=741` (top dex: maverick_v2) |

## Route provenance (step 7)

Full rerun initially left `token_class=None` on 516/517 routes (watchlist/registry key mismatch).
Follow-up code fix: `_merge_registry_provenance_map`, `first_block` mapping, focus-token attach.
Re-expand started to refresh `m8_cross_dex_expansion_latest.json`.

## Operational notes

- Do **not** claim production economics from narrow shadow (`quote_size_truth` ~$0.05 diagnostic floor).
- Do **not** run full `m8_m9` until time_to_mirror lane stable at desired token cap.
- Duplicate `start.py` processes were deduped; keep single orchestrator per lane.

## Next

- Confirm post-fix expansion: majority of `routes_admitted` carry `token_class` + `refresh_lane`.
- Re-export pending queue if watchlist `first_block` backfill changes top rows.
- Patient lane / production bridge remain separate tracks.
