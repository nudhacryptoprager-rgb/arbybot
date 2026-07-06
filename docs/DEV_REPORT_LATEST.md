# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-04T09:26:39Z
run_timestamp_utc: 2026-07-04T09:26:39Z
goal_status: BLOCKED
blocker_status_after: Raw factory log discovery broke fresh-selection zero; 9 fresh verified mirrors now exist; blocked on quote_ready=0
docs_reread_confirmed: true
run_id: raw-factory-log-breakthrough-2026-07-05
mode: start.py -time_to_mirror --hot (partial) + start.py -mirror_recall_fast
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Implement raw factory log discovery to seed fresh_delta focus tokens before token-set filtering
goal_status: BLOCKED
primary_blocker_of_session: quote_ready=0 despite selection_verified_fresh_total=9
blocker_status_before: selection_verified_fresh_total=0; tracked token set stale; factory logs filtered out
blocker_status_after: selection_verified_fresh_total=9; m9_target_ready=true; fresh_quote_candidate=9; quote_ready=0
close_allowed: true
close_reason: BLOCKED — session reached a real downstream blocker (quote_ready=0); fix requires separate quote smoke / second venue / depth RCA
remaining_blockers: quote_ready=0; recall SLA exceeded (320.75s > 180s); M9 shadow still blocked until cycles_at_floor > 0
evidence_artifacts: data/tmp/m8_event_stream_lane_latest.json, data/tmp/m8_token_watchlist_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json

## Breakthrough: raw factory log discovery

Implemented `scan_raw_factory_logs_for_anchor_pools()` in `m8/discovery/onchain_factory_mirror_discovery.py`:
- Scans factory PairCreated/PoolCreated logs without token-set filter.
- Matches events where exactly one side is a known anchor (WETH, USDC, USDbC, cbBTC, ...).
- The non-anchor token becomes the focus token.
- V4 66-char poolIds are skipped (not EVM pool addresses).
- Events are merged into watchlist with `refresh_lane=fresh_delta_lane`, `token_class=fresh_long_tail`, `source=raw_factory_log`, `first_seen_block`.

Wired into `m8/discovery/event_stream_lane.py`:
- `run_incremental_factory_log_poll()` now runs both token-scoped and raw anchor-side polls.
- New metrics: `raw_factory_logs_fetched`, `raw_anchor_pools_seen`, `raw_factory_new_focus_tokens_total`.
- Existing `fresh_factory_event_hints_total` now counts both modes.

Added unit tests in `tests/unit/test_onchain_factory_mirror_discovery.py`:
- `test_raw_factory_log_discovers_anchor_sided_untracked_token`
- `test_raw_factory_log_skips_non_anchor_pairs`
- `test_raw_factory_log_skips_v4_pool_id`

## Runtime evidence (2026-07-05)

### Event stream lane (hot_delta, 500 blocks)
- `raw_factory_logs_fetched`: 9
- `raw_anchor_pools_seen`: 9
- `raw_factory_new_focus_tokens_total`: 9
- `fresh_factory_event_hints_total`: 9
- 9 brand-new focus tokens added to watchlist with blocks 48225736–48226053

### mirror_recall_fast after raw discovery
- all_dex_mirrors_total=81, supported=81
- recall_verified_pool_exists_total=51
- pool_exists_stale=42
- selection_verified_fresh_total=9
- fresh_enough=9
- fresh_quote_candidate=9
- quote_ready=0
- m9_target_ready=true
- verify_rca_primary_blocker=selection_blocked_stale (legacy label from stale path; fresh path has 9 selected)

### RCA
- existence_rca_bucket_histogram: FACTORY_MEMBERSHIP_FAIL=15, V4_POOLID_NOT_RESOLVED=15, STALE_BUT_POOL_EXISTS=40, V4_MISLABEL_V3_POOL=2
- stale_recall_bucket_histogram: STALE_POOL_NOT_FOUND=30, STALE_BUT_POOL_EXISTS=42
- reject_reason_histogram: FACTORY_NO_POOL=15, V4_SLOT0_EMPTY=15, HINT_STALE=42

## Quote-ready RCA (2026-07-06)

- `m8_mirror_quote_ready_queue_latest.json` contains 9 hints (the raw-factory tokens), but their `source` is `dexscreener` because the verified recall artifact stamped DexScreener as the discovery authority after the watchlist seed.
- `m8_second_pool_transition_subset.json`: 50 tokens, all `same_pair_mirror_topology_fallback`, `transitions_1_to_2=0`, market state `MARKET_NO_1_TO_2_TRANSITION`.
- `m8_second_pool_verify_progress.json`: processed 0 routes, exit class `no_quote_ready`.
- `m8_mirror_quote_reprobe_progress.json`: processed 10 routes, quote_ok=0, quote_fail=10, exit class `no_quote_ready`.
- `m8_2_acceptance_report_latest.json`: `handoff_ready=true`, `mirror_quote_ready_tokens=13`, but strict `goal_status=BLOCKED` with blockers:
  - `EXPANSION_FRESHNESS_ORDER_VIOLATION`
  - `EXTERNAL_HINTS_STALE`
  - `HINTS_STALE`
  - `SUBGRAPH_READY_LOW`

### Root cause

The 9 fresh tokens were discovered at pool creation (blocks 48225736–48226053). Each currently has **exactly one verified pool** (the one from the factory log). Mirror readiness and M9 admission require a **second venue** for the same token pair. The cross-dex expand / second-pool transition step reports `MARKET_NO_1_TO_2_TRANSITION` because these brand-new tokens have not yet been listed on a second DEX.

This is a **market/cadence blocker**, not a code bug: the system now discovers fresh tokens correctly, but must wait (or run cadence) for a second pool to appear.

## Next

- Run `mirror_recall_fast` / `time_to_mirror --hot` on cadence to catch the moment when one of the 9 tokens gets a second pool.
- Do not run M9 shadow until `quote_ready > 0` and `cycles_at_floor > 0`.
- Recall SLA exceeded remains a production risk; optimize or split the hot lane.
- Update `Status_M9.md` only after full M9 admission evidence (quote_ready + capacity + cycles_at_floor).
