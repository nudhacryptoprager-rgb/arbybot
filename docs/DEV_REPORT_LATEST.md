# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-29T15:00:00Z
run_id: m7a5_2_alchemy_revalidation
mode: ONLINE (live block-event backrun replay with Alchemy RPC)
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow_7 universe, live block-event backrun replay
code_identity:
  primary: ts:2026-03-29T15:00:00Z
  dirty: false
  desc: M7.A.5.2 Alchemy RPC revalidation

## Session Completion
session_goal: Revalidate M7.A.5 block-event backrun with Alchemy RPC to determine if provider latency materially reduces block lag and improves economics.
goal_status: REACHED (Alchemy revalidation completed, hypothesis rejected — lag unchanged)
close_allowed: true
remaining_blockers: None — both RPC paths now closed
evidence_session_run_dirs:
  - data/tmp/m7a_live_alchemy_narrow.json (20 events, 100 blocks, Alchemy RPC)
primary_blocker_of_session: M7.A.5.1 only proved NOT VIABLE with public RPC path, Alchemy path untested
blocker_status_before: ACTIVE (Alchemy path not evaluated)
blocker_status_after: RESOLVED (Alchemy evidence confirms same stale-lag regime, both paths closed)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.2 — Alchemy RPC revalidation of block-event backrun on arbitrum_one.
change_summary:
  - Replaced get_rpc_url() with resolve_rpc_http() in --live-blocks path for provider provenance
  - Added 4 provenance fields to artifact: rpc_provider, rpc_source, resolved_rpc_host, fallback_used
  - Added low-lag subset metrics: events_scored_low_lag, best_live_net_bps_low_lag
  - Chunked fetch_recent_swap_events into 10-block windows (Alchemy free-tier limit)
  - 5 new contract tests in TestProviderProvenance class
  - Total test count: 2821 passed, 6 skipped, 0 failures (+5 new)
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: provider provenance, chunked getLogs, low-lag metrics)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +5 provenance tests, 85 total)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.2 section added)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 scripts/m7a_orderflow_replay.py --live-blocks 100 --max-events 20 --output data/tmp/m7a_live_alchemy_narrow.json: PASS (20 events, provider=alchemy, best_net=-19.49 bps)
py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (85 passed in 0.43s)
py -3.11 -m pytest tests/unit -q: PASS (2821 passed, 6 skipped in 48.99s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all required gates passed)

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_live_alchemy_narrow.json (M7.A.5.2, Alchemy: 100 blocks, 20 events, best_net=-19.49 bps)

prior session artifacts (still valid, for comparison):
  - data/tmp/m7a_live_blocks.json (M7.A.5.1, public RPC: 100 blocks, 5 events)
  - data/tmp/m7a_live_wider.json (M7.A.5.1, public RPC: 500 blocks, 10 events)
  - data/tmp/m7a_live_repeatability.json (M7.A.5.1 aggregated verdict)

rolling (unchanged):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.5.2 Alchemy Revalidation

### Provider Provenance (new)

| Field | Value |
|-------|-------|
| rpc_provider | alchemy |
| rpc_source | alchemy_api_key |
| resolved_rpc_host | arb-mainnet.g.alchemy.com |
| fallback_used | false |

### Public vs Alchemy Comparison

| Metric | Public (M7.A.5.1 wider) | Alchemy (M7.A.5.2) |
|--------|------------------------|-----------------------------|
| rpc_provider | public | **alchemy** |
| events_scored | 10 | 20 |
| best_live_net_bps | -18.36 | **-19.49** |
| mean_live_net_bps | -20.75 | -21.88 |
| viable_count | 0 | 0 |
| same_block_count | 1 | **0** |
| next_block_count | 0 | 0 |
| stale_count | 9 | **20** |
| mean_block_lag | 217.8 | **59.55** |
| events_scored_low_lag | — | **0** |
| best_live_net_bps_low_lag | — | **None** |

### Verdict

- **Surface viable**: NO
- **Alchemy improves latency**: NO (all 20 events stale, zero low-lag)
- **Primary blocker**: SEQUENTIAL_SCAN_ARCHITECTURE (not RPC provider latency)
- **Evidence**: Alchemy resolves correctly but the fetch→normalize→quote pipeline introduces inherent lag
- **Decision gate**: Wider scan NOT warranted (lag stayed in stale regime)
- **beats_two_leg_baseline**: false

## 5) Strategic Reading

M7.A.5.2 closes the Alchemy RPC branch:

1. **Provider provenance works**: Artifact machine-readably records which RPC provider was used.

2. **Alchemy does NOT reduce lag**: All 20 events stale (mean lag 59.55 blocks). Zero same_block or next_block.

3. **Bottleneck is architecture, not provider**: Sequential fetch→normalize→quote pipeline is structural.

4. **Both RPC paths now closed**: Public (M7.A.5.1) and Alchemy (M7.A.5.2) both show stale-only events.

5. **M7.A series fully concluded**: Six baselines explored. No path to M7.B graduation.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY — NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY — NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC) |
| M7.A.5.2 | **LIVE EVIDENCE: NOT VIABLE** (Alchemy RPC — stale lag unchanged) |
| M7.B | NOT STARTED (closed by M7.A–M7.A.5.2 verdicts) |
