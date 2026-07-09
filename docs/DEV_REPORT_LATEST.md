# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-08T08:18:55
run_timestamp_utc: 2026-07-08T08:18:55
goal_status: BLOCKED
blocker_status_after: M9 admission blocked by selection freshness; latest mirror_recall_fast sees only stale observer/factory-log pools
docs_reread_confirmed: true
run_id: m9-admission-stale-observer-backlog-2026-07-09
mode: start.py -mirror_recall_fast
config: config/exotic_base_anchor.yaml
rolling_run_dir: data/runs/ci_m5_gate_arbitrum_one_20260708_101645_712808
runtime_evidence_timestamp_utc: 2026-07-09T10:21:55Z

## Session Completion
session_goal: Validate observer-mode second-venue recall, enforce strict M9 admission semantics, and audit the current M8->M9 funnel freshness
goal_status: BLOCKED
primary_blocker_of_session: SELECTION_VERIFIED_FRESH_ZERO / selection_blocked_stale
blocker_status_before: observer mode implemented, but canonical start.py failed on a top-level m9_admission_blocker UnboundLocalError and prior evidence still claimed RPC/preflight latency
blocker_status_after: canonical mirror_recall_fast completes under SLA; prior second-venue evidence aged out; no selection-fresh mirrors remain in the current bundle
close_allowed: true
close_reason: BLOCKED - M9 admission requires selection-fresh mirrors before quote-ready second-venue admission can be evaluated
remaining_blockers: selection_verified_fresh_total=0; event_stream artifact is stale; quote_ready_second_venue_total=0; M9 shadow remains NOT_STARTED
evidence_session_run_dirs: data/runs/ci_m5_gate_arbitrum_one_20260708_101645_712808
evidence_artifacts: data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_selection_latest.json, data/tmp/m8_time_to_mirror_step_timings_latest.json

## Code changes

1. `m8/discovery/mirror_discovery_recall.py`:
   - Fixed top-level `m9_admission_blocker` ordering bug (`m9_blocker` is computed before payload construction).
   - Restored separate `aerodrome_variant_fallback_histogram` and `unsupported_aerodrome_pool_histogram` counters.
   - Tightened M9 admission: it now requires `quote_ready_second_venue_total>0`, not merely `quote_ready_total>0` and `second_venue_ready_total>0` on different tokens.
   - Added top-level `quote_ready_second_venue_total` and `rpc_transient_factory_membership_fail_total`.

2. `tests/unit/test_mirror_discovery_recall.py`:
   - Added regression coverage for top-level `m9_admission_blocker`.
   - Extended second-venue test so one quote-ready venue is not enough; admission opens only when the same focus token has two quote-ready venues.
   - Isolated selection/quote-smoke helper tests to `tmp_path` so unit tests no longer overwrite canonical runtime artifacts.

## Fresh runtime evidence

| Metric | Value |
|--------|-------|
| run_timestamp | 2026-07-09T10:21:55Z |
| all_dex_mirrors_total | 52 |
| supported_mirrors_total | 52 |
| recall_verified_pool_exists_total | 50 |
| selection_verified_fresh_total | 0 |
| fresh_quote_candidate_total | 0 |
| quote_ready_total | 0 |
| second_pool_ready_total | 0 |
| second_venue_ready_total | 0 |
| quote_ready_second_venue_total | 0 |
| m9_admission_ready | false |
| m9_admission_blocker | NONE |
| verify_rca_primary_blocker | selection_blocked_stale |
| verified_pool_count_by_dex | {uniswap_v3: 47, uniswap_v2: 3} |
| second_pool_count_by_dex | {} |
| verified_second_venues_by_dex | {} |
| observer_focus_tokens_total | 3 |
| observer_overlap_fresh_total | 0 |
| observer_overlap_quote_total | 0 |
| observer_verified_second_venue_total | 0 |
| rpc_transient_factory_membership_fail_total | 2 |
| pool_exists_stale_total | 50 |
| event_stream_generated_at | 2026-07-07T09:23:55Z |
| recall_latency_s | 75.19 |
| recall_sla_pass | true |

## Interpretation

- Base RPC preflight is not the current blocker: archive probe PASS, recall completed.
- The current event-stream artifact is stale (`2026-07-07T09:23:55Z`), so mirror_recall_fast only replays aged factory-log pools.
- All 52 mirrors are now in the `1-7d` age bucket; 50 pools still exist, but 0 are selection-fresh.
- The previous observer second-venue token (`0xa5d6...d94`) is useful RCA evidence, not current admission evidence.
- Therefore a full M8 hot refresh is required before evaluating M9 admission again.

## Pipeline

- `py -3.11 -m pytest tests/unit/test_mirror_discovery_recall.py tests/unit/test_mirror_recall_verify.py -q`: 29 passed.
- `py -3.11 scripts/check_rpc_endpoints.py --chain base --ws-timeout 15`: PASS.
- `py -3.11 start.py -mirror_recall_fast --force-rerun-steps --no-dashboard`: PASS, recall SLA PASS (`75.19s`).

## Next

- Run a canonical upstream M8 refresh starting from `m8_event_stream_lane` before another recall/selection decision.
- Add quote-smoke provenance and per-token `quote_ready_second_venue` reject breakdown.
- RCA stale second-venue token `0xa5d6f9d4803bceb6fd4444e2e55a82d4bab94d94` as a diagnostic sample, not as current admission evidence.
- Do not run M9 shadow until a coherent fresh bundle has `quote_ready_second_venue_total>0`.
