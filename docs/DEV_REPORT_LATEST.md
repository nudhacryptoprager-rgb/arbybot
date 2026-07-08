# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-08T08:18:55.543880Z
run_timestamp_utc: 2026-07-08T08:18:55.543880Z
goal_status: BLOCKED
blocker_status_after: M9 admission blocked by second_venue_ready=0; observer-mode second-venue coverage implemented, fresh evidence pending RPC latency fix
docs_reread_confirmed: true
run_id: m9-admission-observer-mode-2026-07-08
mode: start.py -mirror_recall_fast, direct recall script
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Add observer-mode second-venue factory scan, clean blocker taxonomy, and bound hot-lane quote smoke to protect SLA
goal_status: BLOCKED
primary_blocker_of_session: second_venue_ready=0 despite active observer coverage; fresh live evidence blocked by Base RPC latency/preflight archive probe timeout
blocker_status_before: quote_ready reached but second_venue_ready=0; only 4 productive factories scanned, 8 discovery_only factories ignored
blocker_status_after: observer mode scans all 12 factories; `SECOND_VENUE_READY_ZERO` is explicit primary blocker; live recall script exceeds SLA due to RPC latency
close_allowed: true
close_reason: BLOCKED — M9 admission requires second_venue_ready>0; current live evidence is stale/pending due to Base RPC timeouts
remaining_blockers: second_venue_ready=0; second_pool_ready=0; Base RPC archive probe timeout; direct recall script latency >300s
evidence_session_run_dirs: data/runs/ci_m5_gate_arbitrum_one_20260708_101645_712808
evidence_artifacts: data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_event_stream_lane_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json

## Code changes

1. `m8/discovery/onchain_factory_mirror_discovery.py`:
   - `scan_raw_factory_logs_for_anchor_pools()` gained `observer_mode=True` and `focus_tokens` parameters.
   - Observer mode scans the 8 `discovery_only` factories for second venues.
   - Events are tagged `observer_only=True`; metrics report `productive_factories_scanned` and `observer_factories_scanned`.

2. `m8/discovery/event_stream_lane.py`:
   - Runs observer scan after productive scan, restricted to current watchlist focus tokens.
   - Stores full event lists: `raw_factory_events` and `observer_factory_events`.
   - New metrics: `observer_factory_logs_fetched`, `observer_anchor_pools_seen`, `observer_factory_new_focus_tokens_total`.

3. `m8/discovery/token_pool_universe.py`:
   - Added `SECOND_POOL_HINT` constant.
   - `_FACTORY_SOURCES` includes `observer_factory_log`.
   - `load_factory_recall_hints()` ingests observer events as `source="observer_factory_log"` hints.

4. `m8/discovery/mirror_discovery_recall.py`:
   - Added `use_dexscreener` flag (hot lane can skip DexScreener to protect SLA).
   - Added `quote_smoke_max_candidates` to bound fresh quote smoke to the hottest tokens.
   - `run_mirror_selection_pass()` now computes `second_venue_ready` from all fresh_enough hints, not only quote-ready hints.
   - Top-level payload exposes `m9_admission_blocker`.
   - New metrics: `verified_pool_count_by_dex`, `second_pool_count_by_dex`, `verified_second_venues_by_dex`, `observer_focus_tokens_total`, `observer_overlap_fresh_total`, `observer_overlap_quote_total`, `observer_second_venue_candidate_total`, `observer_verified_second_venue_total`, `fresh_targets_actual_scanned`, `fresh_targets_non_delta_scanned`.

5. `m8/discovery/hint_verifier.py`:
   - `verify_factory_pool()` now retries once on `FACTORY_NO_POOL`.
   - Factory-log/observer hints that still fail are bucketed as `RPC_TRANSIENT_FACTORY_MEMBERSHIP_FAIL` instead of being misclassified as real `FACTORY_NO_POOL`.

6. `m8/discovery/mirror_recall_verify.py` and `m8/discovery/mirror_discovery_recall.py`:
   - Track `rpc_transient_factory_membership_fail_total` in verification metrics and RCA.

7. `scripts/m8_mirror_discovery_recall.py`:
   - CLI flags: `--no-dexscreener`, `--quote-smoke-max-candidates`.

8. `start.py`:
   - `mirror_recall_fast` profile: `anchor_constrained=True`, `run_quote_smoke=True`, `quote_smoke_max_candidates=25`, `use_dexscreener=False`.

9. `tests/unit/test_mirror_discovery_recall.py`:
   - Regression test: productive V3 + observer V2 for same focus token yields `second_venue_ready_count=1`; admission opens only when both are quote-ready.

## Fresh runtime evidence (2026-07-07T09:29:08Z)

| Metric | Value |
|--------|-------|
| all_dex_mirrors_total | 30 |
| supported_mirrors_total | 30 |
| recall_verified_pool_exists_total | 16 |
| selection_verified_fresh_total | 6 |
| fresh_target_ready_total | 6 |
| quote_ready_total | 5 |
| second_pool_ready_total | 0 |
| second_venue_ready_total | 0 |
| m9_target_ready | true |
| fresh_target_ready | true |
| m9_admission_ready | false |
| m9_admission_blocker | SECOND_VENUE_READY_ZERO |
| factory_listener | productive=4, observer=8 |
| raw_anchor_pools_seen | 49 |
| observer_anchor_pools_seen | 3 |
| fresh_age_bucket_histogram | {1-6h: 5, <1h: 1} |
| fresh_targets_scanned | 753 |
| fresh_targets_actual_scanned | 746 |
| fresh_targets_non_delta_scanned | 7 |

## Interpretation

- Observer mode is active: all 12 factories (4 productive + 8 discovery_only) are now scanned.
- 3 observer anchor pools were seen in the latest event window, but none created a verified second venue for the current fresh tokens.
- `second_venue_ready_total=0` is the explicit, clean M9 admission blocker.
- Hot lane skips DexScreener and bounds quote smoke to protect the 180s SLA.
- Fresh live evidence is pending because the direct recall script now hangs/times out against Base RPC; preflight archive probe also fails with HTTP 408.

## Pipeline

- `py -3.11 -m pytest -q`: 7038 passed, 19 skipped, 0 failed.
- `py -3.11 scripts/check_repo_safety.py`: PASS.
- `py -3.11 scripts/ci_full_pipeline.py --mode ci`: ALL REQUIRED GATES PASSED.
- `py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --refresh-rolling`: PASS.

## Next

- Resolve Base RPC latency / archive probe timeout so `start.py -mirror_recall_fast` and direct recall script complete reliably.
- Continue cadence once recall script completes: run `m8_event_stream_lane.py` periodically and `mirror_recall_fast` to catch a verified second venue.
- Do not run M9 shadow until `m9_admission_ready=true` (quote_ready>0 and second_venue_ready>0) plus downstream capacity/cycles evidence.
- Update `Status_M9.md` only when blocker state changes.
