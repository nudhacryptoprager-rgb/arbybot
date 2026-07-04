# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-04T09:26:39Z
run_timestamp_utc: 2026-07-04T09:26:39Z
goal_status: BLOCKED
blocker_status_after: M9 fresh-selection blocked by market/cadence; rolling scanner refreshed but M7 hot rollup remains stale
docs_reread_confirmed: true
run_id: canonical-scanner-mirror-recall-fast-2026-07-04
mode: start.py multi-chain scanner + start.py -mirror_recall_fast
config: config/real_minimal.yaml,config/onboard_zksync_candidate.yaml,config/onboard_base_stage2.yaml,config/onboard_mantle_stage2.yaml,config/onboard_linea_stage1.yaml,config/onboard_scroll_stage1.yaml

## Session Completion
session_goal: Refresh rolling artifacts via canonical scanner and M8 mirror_recall_fast; restore dashboard-visible operational state
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (no fresh pools in DexScreener or 10000-block event lane window)
blocker_status_before: Dashboard /api/summary stale (2026-05-12); M8 unsupported Aerodrome tail classifiable but not surfaced in full mirror_recall_fast due to RPC path
blocker_status_after: Canonical scanner refreshed long_scan_latest.json and run_summary_latest.json (2026-07-04T09:26:39Z); mirror_recall_fast re-run; dashboard /api/summary still stale because it reads m7_hot_rollup_latest.json (2026-06-01)
close_allowed: true
remaining_blockers: selection_verified_fresh_total=0; m7_hot_rollup_latest.json stale; no fresh factory events in 10000-block window
evidence_artifacts: data/runs/_rolling/long_scan_latest.json, data/runs/_rolling/run_summary_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json, data/tmp/m8_event_stream_lane_latest.json

## Canonical multi-chain scanner results (2026-07-04T09:26:39Z)

| Chain | Runs | PASS | NO_DATA | INFRA_FAIL | Signals | Net USDC | Notes |
|-------|------|------|---------|------------|---------|----------|-------|
| arbitrum_one | 3 | 3 | 0 | 0 | 36 | $96.36 | Only signal-producing chain |
| base | 2 | 0 | 2 | 0 | 0 | $0.00 | NO_DATA |
| zksync | 2 | 0 | 0 | 2 | 0 | $0.00 | INFRA_FAIL |
| mantle | 2 | 0 | 0 | 2 | 0 | $0.00 | INFRA_FAIL |
| linea | 2 | 0 | 0 | 2 | 0 | $0.00 | INFRA_FAIL |
| scroll | 2 | 0 | 0 | 2 | 0 | $0.00 | Accepted fail |
| **Total** | **13** | **3** | **2** | **8** | **36** | **$96.36** | Profitable RTs: 0 |

Warnings:
- CHAIN_ALL_POSITIVE [arbitrum_one]: 3 runs all PASS — check if data quality is real.
- STATIC_PROBE_PATH [arbitrum_one]: same top pairs across last 3 runs — apparent stability may reflect narrow probe config, not market health.

## M8 event lane results

- 10000 blocks / 713 tokens / Base chain: **0 factory events** caught.
- 2000 blocks / 100 tokens / Base chain: **0 factory events** caught.
- Conclusion: no fresh pool creations in the tracked token set for the last ~10000 blocks (~3.5h on Base).

## M8 mirror_recall_fast results (latest run)

- all_dex_mirrors_total=75, supported=75, pool_exists=45, selection_fresh=0, stale_backlog=45.
- existence_rca_bucket_histogram: FACTORY_MEMBERSHIP_FAIL=14, V4_POOLID_NOT_RESOLVED=16, STALE_BUT_POOL_EXISTS=43, V4_MISLABEL_V3_POOL=2.
- factory_no_pool_by_dex: aerodrome=9, uniswap_v2=5.
- unsupported_aerodrome_pool_histogram: {} in full run (single-token bootstrap test confirms classification works with productive RPC).
- Primary blocker: selection_blocked_stale.
- recall_sla_gate: blocked (latency_s=293.53 > max_s=180).

## Dashboard state

- Dashboard server alive at http://127.0.0.1:8099.
- `/api/summary` still reports 2026-05-12 timestamp and `is_fresh=false` because it reads `data/runs/_rolling/m7_hot_rollup_latest.json` (last write 2026-06-01).
- The canonical multi-chain scanner updates `long_scan_latest.json` and `run_summary_latest.json`, not `m7_hot_rollup_latest.json`.
- `/api/m8/current` and `/api/m9/current` returned empty `timestamp`/`is_fresh`/`staleness_reason` after `mirror_recall_fast`; likely waiting for `-m8_m9` pipeline artifacts or a dashboard refresh.

## Code changes this session

- Commit `2dc2045`: `_eth_get_code` retry/backoff for transient RPC failures.
- Worktree clean.

## Next

- Do not claim M9 REACHED: `selection_verified_fresh_total=0` and no fresh factory events.
- To refresh dashboard `/api/summary`, the M7 hot runtime/soak must be run (produces `m7_hot_rollup_latest.json`). The multi-chain scanner is not the right tool for that panel.
- Continue cadence running; a single 10000-block window cannot prove absence of fresh pools.
- Update `Status_M9.md` only after `selection_verified_fresh_total > 0` and `fresh_long_tail_quote_ready > 0`.
