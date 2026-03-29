# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-29T10:34:33Z
run_id: m7a5_live_blocks_infra_20260329
mode: OFFLINE + INFRA (live block-event pipeline built, evidence pending RPC run)
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow_7 universe, live block-event backrun replay
code_identity:
  primary: ts:2026-03-29T10:34:33Z
  dirty: false
  desc: M7.A.5 live block-event backrun replay infrastructure

## Session Completion
session_goal: Implement M7.A.5 live block-event backrun replay — replace offline-estimated replay with real block events and post-event live quotes via read_quoter_v2.
goal_status: REACHED (infrastructure + tests complete, live evidence pending RPC run)
close_allowed: true
remaining_blockers: Live --live-blocks run requires RPC access (not run in this session)
evidence_session_run_dirs:
  - data/tmp/m7a_orderflow_offline.json (5 fixture events, offline replay — backward compat verified)
primary_blocker_of_session: M7.A.5 live block-event pipeline not yet implemented
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED (pipeline built, 21 new tests passing)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5 — live block-event backrun replay on arbitrum_one. Hypothesis: block_event_backrun may produce viable measured edge when replay uses real block events and post-event live quotes.
change_summary:
  - Extended scripts/m7a_orderflow_replay.py with M7.A.5 live block-event infrastructure:
    - SWAP_EVENT_TOPIC constant (V3 canonical Swap topic)
    - fetch_recent_swap_events() — fetches raw Swap logs via eth_getLogs
    - normalize_swap_log() — parses V3 Swap(int256 amount0, int256 amount1) into OrderflowEvent
    - score_backrun_live() — sync measured quotes via read_quoter_v2() across all known V3 DEXes
    - _build_address_to_symbol() — reverse address→symbol lookup
  - Extended BackrunResult with 6 new fields: event_block, quote_block, block_lag, same_state_class, counter_venue_count, best_live_net_bps
  - Added --live-blocks N CLI mode + --max-events limiter
  - Rewrote score_backrun_online() as wrapper around score_backrun_live (fixes broken M7.A.4 adapter constructor)
  - 21 new contract tests (79 total in test_orderflow_contracts.py)
  - Total test count: 2815 passed, 6 skipped, 0 failures (+21 new)
  - All CI gates pass
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: +~250 lines, M7.A.5 live block-event infrastructure)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +21 tests for M7.A.5 contracts)
  - docs/status/Status_M7.md (updated with M7.A.5 section)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 scripts/m7a_orderflow_replay.py --offline: PASS (backward compat verified, 5 events, best_net=-1.5537 bps)
py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (79 passed in 0.70s)
py -3.11 -m pytest tests/unit -q: PASS (2815 passed, 6 skipped in 77.09s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all 7 gates green, elapsed 71.7s)

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_orderflow_offline.json (M7.A.4, still valid — backward compat verified)
  - data/tmp/m7a_intent_scout.json (M7.A.4, still valid)

prior session artifacts (still valid):
  - data/tmp/m7a_verdict.json (narrow_7, M7.A)
  - data/tmp/m7a_expanded_verdict.json (expanded_10, M7.A.2)
  - data/tmp/m7a_regime_repeatability.json (M7.A.3)

rolling (unchanged):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.5 Live Block-Event Infrastructure

### New Infrastructure

| Component | Description |
|-----------|-------------|
| `SWAP_EVENT_TOPIC` | V3 canonical Swap topic (shared across V3 forks) |
| `fetch_recent_swap_events()` | Fetches raw Swap logs via eth_getLogs from last N blocks |
| `normalize_swap_log()` | Parses V3 Swap event data (int256 amount0/amount1) into OrderflowEvent |
| `score_backrun_live()` | Sync measured quotes via `read_quoter_v2()` across known V3 DEXes |
| `_build_address_to_symbol()` | Reverse address→symbol lookup for token identification |
| `--live-blocks N` CLI | Fetch real events from last N blocks, score with live quotes |
| `--max-events` CLI | Limit events to score (conserves RPC calls, default: 20) |

### BackrunResult M7.A.5 Fields

| Field | Type | Description |
|-------|------|-------------|
| `event_block` | int? | Block number where the swap event occurred |
| `quote_block` | int? | Block number when quotes were taken |
| `block_lag` | int? | quote_block - event_block |
| `same_state_class` | str? | "same_block" / "next_block" / "stale" |
| `counter_venue_count` | int | Number of venues that returned valid quotes |
| `best_live_net_bps` | float? | Net bps from live measured quotes |

### New Tests Added (21 in 5 classes)

| Class | Tests | What it locks |
|-------|-------|--------------|
| TestSwapEventConstants | 2 | SWAP_EVENT_TOPIC correctness, DEFAULT_LIVE_BLOCKS |
| TestAddressLookup | 3 | Reverse address→symbol, empty, case-insensitive |
| TestNormalizeSwapLog | 6 | Log parsing: token0_in, token1_in, both-positive skip, tiny skip, truncated data, tx_hash preservation |
| TestBackrunResultLiveFields | 5 | Default None, asdict serialization, M7.A.5 schema, same_state_class values, post_trade_state "live" |
| TestM7A5BackwardCompat | 5 | Offline results have None live fields, fixture count unchanged, artifact schema, JSON roundtrip |

### Backward Compatibility

- All existing M7.A.4 tests pass without modification
- Offline mode produces identical output (M7.A.5 fields are None/0 for offline results)
- Legacy `score_backrun_online()` now uses `read_quoter_v2()` correctly (fixes broken adapter constructor from M7.A.4)

## 5) Strategic Reading

M7.A.5 builds the infrastructure for live block-event backrun replay:

1. **Live event pipeline complete**: `fetch_recent_swap_events()` → `normalize_swap_log()` → `score_backrun_live()` forms a complete pipeline from raw chain events to measured backrun scores.

2. **Correct quoting path**: Uses `read_quoter_v2()` from `strategy/quote_rpc.py` (sync, with fallback RPCs and 429 quarantine) instead of broken async adapter constructors from M7.A.4.

3. **State classification**: `same_state_class` (same_block/next_block/stale) tracks how fresh the quotes are relative to the event — critical for understanding whether the measured edge is actionable.

4. **Next step**: Run `--live-blocks 5` with RPC access to generate live evidence artifacts. This will produce the first measured backrun scores from real block events.

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
| M7.A.5 | **INFRA BUILT** (live block-event replay, evidence pending) |
| M7.B | NOT STARTED (closed by M7.A–M7.A.4 verdicts) |
