# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-08T08:18:55
run_timestamp_utc: 2026-07-08T08:18:55
goal_status: BLOCKED
blocker_status_after: M9 admission blocked by QUOTE_READY_SECOND_VENUE_ZERO; second venue exists but is not quote-ready on the same focus token
docs_reread_confirmed: true
run_id: m9-admission-second-venue-quote-readiness-2026-07-09
mode: start.py -mirror_recall_fast
config: config/exotic_base_anchor.yaml
rolling_run_dir: data/runs/ci_m5_gate_arbitrum_one_20260708_101645_712808
runtime_evidence_timestamp_utc: 2026-07-09T08:27:04Z

## Session Completion
session_goal: Validate observer-mode second-venue recall and enforce strict M9 admission semantics
goal_status: BLOCKED
primary_blocker_of_session: QUOTE_READY_SECOND_VENUE_ZERO
blocker_status_before: observer mode implemented, but canonical start.py failed on a top-level m9_admission_blocker UnboundLocalError and prior evidence still claimed RPC/preflight latency
blocker_status_after: canonical mirror_recall_fast completes under SLA; one fresh second venue is verified; no focus token has quote-ready pools on two venues
close_allowed: true
close_reason: BLOCKED - M9 admission requires a same-focus token with quote-ready pools on at least two DEX venues
remaining_blockers: quote_ready_second_venue_total=0; second venue quote smoke fails on the observer leg; M9 shadow remains NOT_STARTED
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

## Fresh runtime evidence

| Metric | Value |
|--------|-------|
| run_timestamp | 2026-07-09T08:27:04Z |
| all_dex_mirrors_total | 52 |
| supported_mirrors_total | 52 |
| recall_verified_pool_exists_total | 48 |
| selection_verified_fresh_total | 21 |
| fresh_quote_candidate_total | 21 |
| quote_ready_total | 17 |
| second_pool_ready_total | 1 |
| second_venue_ready_total | 1 |
| quote_ready_second_venue_total | 0 |
| m9_admission_ready | false |
| m9_admission_blocker | QUOTE_READY_SECOND_VENUE_ZERO |
| verified_pool_count_by_dex | {uniswap_v3: 45, uniswap_v2: 3} |
| second_pool_count_by_dex | {uniswap_v2: 1} |
| verified_second_venues_by_dex | {uniswap_v3: 1, uniswap_v2: 1} |
| observer_focus_tokens_total | 3 |
| observer_overlap_fresh_total | 1 |
| observer_overlap_quote_total | 0 |
| observer_verified_second_venue_total | 1 |
| rpc_transient_factory_membership_fail_total | 0 |
| recall_latency_s | 78.56 |
| recall_sla_pass | true |

## Interpretation

- Base RPC preflight is not the current blocker: archive probe PASS, recall completed.
- Observer mode produced a real fresh second venue for token `0xa5d6...d94`.
- That token has verified `uniswap_v3` + `uniswap_v2` pools, but neither leg reached `QUOTE_SMOKE_OK`.
- Other tokens are quote-ready on `uniswap_v3`, but they do not have a quote-ready second venue.
- Therefore M9 admission correctly remains closed.

## Pipeline

- `py -3.11 -m pytest tests/unit/test_mirror_discovery_recall.py tests/unit/test_mirror_recall_verify.py -q`: 29 passed.
- `py -3.11 scripts/check_rpc_endpoints.py --chain base --ws-timeout 15`: PASS.
- `py -3.11 start.py -mirror_recall_fast --force-rerun-steps --no-dashboard`: PASS, recall SLA PASS.

## Next

- RCA the fresh second venue token `0xa5d6f9d4803bceb6fd4444e2e55a82d4bab94d94`.
- Determine why its `uniswap_v3` and `uniswap_v2` pools remain `HINT_FACTORY_VERIFIED` instead of `QUOTE_SMOKE_OK`.
- Fix V2 observer quote smoke path if the failure is adapter/quoter metadata, or keep cadence if the failure is true zero reserves/no quote.
- Do not run M9 shadow until `quote_ready_second_venue_total>0`.
