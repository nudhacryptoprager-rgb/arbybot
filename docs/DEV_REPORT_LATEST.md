# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-04T09:26:39Z
run_timestamp_utc: 2026-07-04T09:26:39Z
goal_status: BLOCKED
blocker_status_after: Fresh-delta admission still blocked; raw factory event discovery needed to find new long-tail tokens
docs_reread_confirmed: true
run_id: time-to-mirror-hot-delta-2026-07-04
mode: start.py -time_to_mirror --hot, start.py -mirror_recall_fast
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Run focused hot-delta time-to-mirror lane and mirror_recall_fast to isolate fresh-delta blocker
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0
blocker_status_before: M8/M9 artifacts stale; unsupported Aerodrome tail classifiable but not surfaced; dashboard /api/summary stale
blocker_status_after: Hot-delta lane partial run revealed factory_log events exist but are filtered out by token+anchor filter; mirror_recall_fast still selection_fresh=0; recall SLA exceeded
close_allowed: true
remaining_blockers: selection_verified_fresh_total=0; no fresh factory events match tracked token set; M7 hot rollup stale
evidence_artifacts: data/tmp/m8_event_stream_lane_latest.json, data/tmp/m8_onchain_factory_scan_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json, data/tmp/m8_time_to_mirror_sla_latest.json

## Commands executed

```powershell
py -3.11 scripts/check_rpc_endpoints.py --chain base --ws-timeout 15
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m8_event_stream_lane.py --chain base --max-tokens 713 --max-blocks 10000
py -3.11 start.py --config-list config/real_minimal.yaml,config/onboard_zksync_candidate.yaml,config/onboard_base_stage2.yaml,config/onboard_mantle_stage2.yaml,config/onboard_linea_stage1.yaml,config/onboard_scroll_stage1.yaml --accepted-fail-chains scroll --max-fail-chains 5 --hours 0.10 --cycles 1 --sleep-seconds 0 --coverage-workers 2 --no-dashboard --prune-keep 200 --summary-file data/runs/_rolling/long_scan_latest.json
py -3.11 start.py -time_to_mirror --hot --no-dashboard --skip-shadow --force-rerun-steps
py -3.11 start.py -mirror_recall_fast --no-dashboard --force-rerun-steps
```

## Key findings from hot-delta lane

### Event stream lane (500-block window, 50 tokens)
- `logs_fetched`: 13
- `pools_matched`: 0
- `block_window`: 501
- `rpc_lane_primary_source`: public_fallback

### On-chain factory scan (5001-block window, 50 tokens)
- `factory_scan`: tokens=50, pools_found=50 (all existing/old pools)
- `factory_log_scan`: logs_fetched=105, pools_matched=0
- All discovered pools have `created_at` ~2026-06-07 and `first_seen_block` ~47M
- Current head ~48.1M, so these pools are ~500k blocks old

### Interpretation
Factory logs contain events (13 in 500 blocks, 105 in 5000 blocks), but **zero match the current tracked-token + anchor filter**. The tracked token set is stale and does not include tokens that are launching new pools. The system needs **raw factory event discovery first, token filtering second** to find fresh long-tail tokens.

## mirror_recall_fast results (latest run)

- all_dex_mirrors_total=74, supported=74, pool_exists=43, selection_fresh=0, stale_backlog=43
- existence_rca_bucket_histogram: FACTORY_MEMBERSHIP_FAIL=14, V4_POOLID_NOT_RESOLVED=16, STALE_BUT_POOL_EXISTS=43, V4_MISLABEL_V3_POOL=2
- factory_no_pool_by_dex: aerodrome=9, uniswap_v2=5
- unsupported_aerodrome_pool_histogram: {} (RPC path issue in full run)
- recall_sla_gate: blocked (296.47s > 180s)
- selection_verified_fresh_total=0

## Multi-chain scanner results

- 13 runs, PASS=3, NO_DATA=2, INFRA_FAIL=8
- Signals only on arbitrum_one: 36 signals, net USDC $96.36
- Profitable roundtrips: 0
- Base: NO_DATA

## Dashboard state

- `/api/summary` still stale (2026-05-12) because it reads `m7_hot_rollup_latest.json` (2026-06-01).
- `/api/m8/current` and `/api/m9/current` return empty freshness fields.

## Breakthrough path

The next code change should be a **raw factory log scanner** that:
1. Scans factory PairCreated/PoolCreated logs without filtering by existing token set.
2. Identifies new pools where one side is a known anchor (WETH, USDC, USDbC, cbBTC) and the other side is a new/untracked token.
3. Adds new focus tokens to the watchlist with `refresh_lane=fresh_delta_lane`.
4. Emits metric `fresh_factory_event_hints_total`.

Without this, the system only re-verifies old pools for old tokens and cannot discover fresh long-tail mirrors.

## Next

- Implement raw factory log discovery in `m8/discovery/onchain_factory_mirror_discovery.py`.
- Add `fresh_factory_event_hints_total` to event_stream_lane and onchain_factory_scan artifacts.
- Re-run `start.py -time_to_mirror --hot` after implementation.
- Do not run M9 shadow until `selection_verified_fresh_total > 0`.
- Update `Status_M9.md` only after fresh verified mirrors appear.
