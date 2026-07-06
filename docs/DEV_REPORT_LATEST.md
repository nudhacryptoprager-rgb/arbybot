# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-06T10:48:27.689861Z
run_timestamp_utc: 2026-07-06T10:48:27.689861Z
goal_status: BLOCKED
blocker_status_after: M9 admission blocked by second_venue_ready=0; fresh target discovery and quote readiness now proven in mirror_recall_fast
docs_reread_confirmed: true
run_id: m9-admission-anchor-constrained-2026-07-06
mode: start.py -mirror_recall_fast
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Implement anchor-constrained mirror recall so M9 admission gate can be evaluated on fresh anchor pairs with quote smoke
goal_status: BLOCKED
primary_blocker_of_session: second_venue_ready=0 despite selection_verified_fresh_total=30 and quote_ready_total=30
blocker_status_before: quote_ready=0 because mirror_recall_fast skipped quote smoke and fresh anchor pools from event stream lane were not feeding recall
blocker_status_after: quote_ready=30; m9_admission_ready=false only because every fresh token still has a single verified pool/venue
close_allowed: true
close_reason: BLOCKED — M9 admission requires second_venue_ready>0; current fresh tokens are single-venue only
remaining_blockers: second_venue_ready=0; second_pool_ready=0
evidence_session_run_dirs: data/runs/ci_m5_gate_arbitrum_one_20260706_124639_025704
evidence_artifacts: data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_event_stream_lane_latest.json, data/tmp/m8_mirror_recall_fresh_quote_smoke_latest.json

## Code changes

1. `m8/discovery/dexscreener_hints.py`:
   - Added `filter_anchor_mirror_pairs()` to keep only `fresh_token↔configured_anchor` DexScreener pairs and emit reject taxonomy.

2. `m8/discovery/mirror_discovery_recall.py`:
   - `run_mirror_discovery_recall()`: added `anchor_constrained` mode (scan only fresh targets, accept only anchor pairs), `run_quote_smoke` mode, and anchor-constrained metrics (`fresh_targets_scanned`, `dexscreener_pairs_seen`, `anchor_pairs_seen`).
   - Added `run_fresh_mirror_quote_smoke()` for lightweight quoter smoke on fresh candidates inside the recall step.
   - `_hint_to_smoke_route()` now includes `focus_token_address` and `focus_token_symbol` so `mirror_quote_smoke` recognizes same-pair routes.
   - Payload includes `second_pool_ready_total` and second-venue / second-pool readiness computed from verified pools.

3. `m8/discovery/token_pool_universe.py`:
   - `load_factory_recall_hints()` now ingests raw anchor-sided factory-log events from `m8_event_stream_lane_latest.json`, resolves block timestamps, and surfaces them as `factory_log` hints so `mirror_recall_fast` can see fresh anchor pools without running the heavy on-chain factory scan.

4. `scripts/m8_mirror_discovery_recall.py`:
   - Added `--anchor-constrained` and `--run-quote-smoke` CLI flags.

5. `start.py`:
   - `mirror_recall_fast` profile sets `anchor_constrained=True` and `run_quote_smoke=True`.
   - Recall command builder appends `--anchor-constrained` and `--run-quote-smoke` when profile flags are set.

6. `tests/unit/test_mirror_discovery_recall.py`:
   - Added tests for `filter_anchor_mirror_pairs()` reject taxonomy.

## Fresh runtime evidence (2026-07-06T10:48:27.689861Z)

| Metric | Value |
|--------|-------|
| all_dex_mirrors_total | 49 |
| supported_mirrors_total | 49 |
| recall_verified_pool_exists_total | 43 |
| selection_verified_fresh_total | 30 |
| fresh_target_ready_total | 30 |
| quote_ready_total | 30 |
| second_pool_ready_total | 0 |
| second_venue_ready_total | 0 |
| m9_target_ready | true |
| fresh_target_ready | true |
| m9_admission_ready | false |
| fresh_age_bucket_histogram | {1-6h: 30} |
| recall_latency_s | 152.19 |
| recall_sla_pass | true |
| fresh_quote_smoke | 30/30 QUOTE_OK_MIRROR_SMOKE |

## Interpretation

- Fresh target discovery works under anchor-constrained mode: 30 verified fresh mirrors, all 1–6 hours old.
- Quote smoke passes on all 30 fresh candidates (Uniswap V3 anchor pairs); V4 pairs still fail as expected.
- `m9_target_ready` / `fresh_target_ready` correctly signal fresh targets exist.
- `m9_admission_ready` correctly stays false because no focus token has a second verified pool or venue.
- `mirror_recall_fast` now completes under the 180s SLA.

## Pipeline

- `py -3.11 -m pytest -q`: 7035 passed, 19 skipped, 0 failed.
- `py -3.11 scripts/check_repo_safety.py`: PASS.
- `py -3.11 scripts/ci_full_pipeline.py --mode ci`: ALL REQUIRED GATES PASSED.

## Next

- Run cadence on `start.py -mirror_recall_fast` and `scripts/m8_event_stream_lane.py` to catch the moment when one of the 30 fresh tokens gets a second verified pool/venue.
- Do not run M9 shadow until `m9_admission_ready=true` (quote_ready>0 and second_venue_ready>0) and downstream capacity/cycles evidence exists.
- Consider moving DexScreener/wide recall to a warm/audit lane if hot SLA pressure returns.
- Update `Status_M9.md` with current blocker line.
