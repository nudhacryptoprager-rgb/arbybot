# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-04T09:26:39Z
run_timestamp_utc: 2026-07-04T09:26:39Z
goal_status: BLOCKED
blocker_status_after: M9 admission blocked by quote_ready=0 / second_venue_ready=0; fresh target discovery now clearly separated from admission
docs_reread_confirmed: true
run_id: m9-admission-semantics-2026-07-06
mode: start.py -mirror_recall_fast, start.py -time_to_mirror --hot (partial)
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Distinguish fresh target discovery from M9 admission; add quote-ready / second-venue / TTL metrics and gates
goal_status: BLOCKED
primary_blocker_of_session: quote_ready=0 and second_venue_ready=0 despite selection_verified_fresh_total=8
blocker_status_before: m9_target_ready=true conflated fresh target existence with admission readiness; quote_ready_queue included non-quote-ready fresh tokens
blocker_status_after: m9_admission_ready=false explicit; quote_ready_queue now only quote-smoke-OK hints; fresh_age_bucket_histogram tracks TTL
close_allowed: true
close_reason: BLOCKED — M9 admission requires quote_ready>0 and second_venue_ready>0; current fresh tokens are single-venue only
remaining_blockers: quote_ready=0; second_venue_ready=0; recall SLA exceeded (367.39s > 180s); time_to_mirror hot lane times out at cross_dex_expand
evidence_artifacts: data/tmp/m8_mirror_discovery_recall_latest.json (2026-07-06T08:42:37Z), data/tmp/m8_event_stream_lane_latest.json, data/tmp/m8_token_watchlist_latest.json, data/tmp/m8_2_acceptance_report_latest.json

## Code changes

1. `m8/discovery/mirror_discovery_recall.py`:
   - `run_mirror_selection_pass()`: added `fresh_target_ready`, `m9_admission_ready`, `second_venue_ready_count`, `selection_stages.second_venue_ready`.
   - Main recall payload: added `fresh_target_ready_total`, `quote_ready_total`, `second_venue_ready_total`, `fresh_target_ready`, `m9_admission_ready`, `fresh_age_bucket_histogram`.
   - `write_mirror_queue_artifacts()`: quote-ready queue now contains only hints with `hint_status` starting with `QUOTE` or `QUOTE_SMOKE_OK`.
   - `evaluate_m9_admission_gate()`: now requires `selection_verified_fresh_total>0 AND quote_ready_total>0 AND second_venue_ready_total>0`.
   - `_fresh_age_bucket()`: buckets `<1h`, `1-6h`, `6-24h`, `24-48h`, `expired`.

2. `tests/unit/test_mirror_discovery_recall.py`:
   - `test_quote_ready_queue_contains_only_quote_smoke_ok_hints`
   - `test_m9_admission_gate_blocks_without_quote_ready`
   - `test_m9_admission_gate_blocks_without_second_venue`
   - `test_m9_admission_gate_opens_with_quote_and_second_venue`

## Fresh runtime evidence (2026-07-06T08:42:37Z)

| Metric | Value |
|--------|-------|
| all_dex_mirrors_total | 88 |
| supported_mirrors_total | 88 |
| recall_verified_pool_exists_total | 52 |
| selection_verified_fresh_total | 8 |
| fresh_target_ready_total | 8 |
| quote_ready_total | 0 |
| second_venue_ready_total | 0 |
| m9_target_ready | true (fresh target exists) |
| fresh_target_ready | true |
| m9_admission_ready | false |
| fresh_age_bucket_histogram | {6-24h: 6, 24-48h: 2} |
| recall_sla | exceeded (367.39s > 180s) |

## Interpretation

- Fresh target discovery works: 8 verified fresh mirrors.
- These tokens are 6–48 hours old and currently have only one verified pool each.
- Quote readiness and M9 admission require a second venue; none exists yet.
- `m9_target_ready` now correctly signals fresh targets exist, while `m9_admission_ready` correctly stays false.

## Pipeline issues

- `start.py -time_to_mirror --hot --force-rerun-steps` times out after 30 minutes at `m8_2_cross_dex_expand`.
- `start.py -mirror_recall_fast` completes but exceeds 180s SLA (367.39s).
- Hot lane needs SLA split: raw logs + pending reprobe in hot lane; DexScreener/wide recall in warm/audit lane.

## Next

- Run cadence on `mirror_recall_fast` and event lane to catch the moment when one of the 8 tokens gets a second pool.
- Do not run M9 shadow until `m9_admission_ready=true` (quote_ready>0 and second_venue_ready>0) and downstream capacity/cycles evidence exists.
- Optimize or split hot lane to meet SLA.
- Update `Status_M9.md` with current blocker line.
