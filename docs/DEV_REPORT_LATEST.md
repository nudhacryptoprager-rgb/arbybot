# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-04T09:26:39Z
run_timestamp_utc: 2026-07-04T09:26:39Z
goal_status: IN_PROGRESS
blocker_status_after: Raw factory log discovery broke fresh-selection zero; 9 fresh verified mirrors now exist; next blocker is quote_ready
docs_reread_confirmed: true
run_id: raw-factory-log-breakthrough-2026-07-05
mode: start.py -time_to_mirror --hot (partial) + start.py -mirror_recall_fast
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Implement raw factory log discovery to seed fresh_delta focus tokens before token-set filtering
goal_status: IN_PROGRESS
primary_blocker_of_session: quote_ready=0 despite selection_verified_fresh_total=9
blocker_status_before: selection_verified_fresh_total=0; tracked token set stale; factory logs filtered out
blocker_status_after: selection_verified_fresh_total=9; m9_target_ready=true; fresh_quote_candidate=9; quote_ready=0
close_allowed: true
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

## Next

- **Quote ready blocker**: 9 fresh mirrors exist but `quote_ready=0`. This is the new primary blocker.
- Investigate why fresh mirrors are not quote-ready: likely missing second venue, depth, or smoke quote path.
- Run M8.2 cross-dex expand / quote smoke on the 9 fresh tokens specifically.
- Recall SLA exceeded remains a production risk; optimize or split the hot lane.
- Do not run M9 shadow until `quote_ready > 0` and `cycles_at_floor > 0`.
- Update `Status_M9.md` only after full M9 admission evidence (quote_ready + capacity + cycles_at_floor).
