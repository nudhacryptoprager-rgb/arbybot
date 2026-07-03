# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-03T10:38:37Z
goal_status: BLOCKED
blocker_status_after: SELECTION_VERIFIED_FRESH_ZERO / FACTORY_MEMBERSHIP_FAIL
docs_reread_confirmed: true
run_id: mirror-recall-fast-v4-fallback-2026-07-03
mode: start.py -mirror_recall_fast --force-rerun-steps
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Fresh runtime validation of V4 poolId resolver V3 fallback patch (commit 692b470); selection_verified_fresh_total > 0 or fresh BLOCKED RCA.
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (FACTORY_MEMBERSHIP_FAIL + stale-only)
blocker_status_before: V4_POOLID_NOT_RESOLVED (24 hints, 2026-06-30 RCA)
blocker_status_after: FACTORY_MEMBERSHIP_FAIL (54 hints) + V4_POOLID_NOT_RESOLVED (20 hints) + stale-only (5 pool_exists_stale)
close_allowed: true
remaining_blockers: factory membership fail for onchain_factory hints; stale-only pool_exists; V4 slot0 empty for true V4 pools
evidence_artifacts: data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json, data/tmp/m8_2_acceptance_report_latest.json, data/tmp/m8_3_acceptance_report_latest.json
docs_reread_confirmed: true

## Fresh RCA (2026-07-03T10:38:37Z)

| Metric | Before (2026-06-30) | After (2026-07-03) | Delta |
|--------|--------------------|--------------------|-------|
| recall_verified_pool_exists_total | 2 | 5 | +3 |
| pool_exists_stale_total | 2 | 5 | +3 |
| selection_verified_fresh_total | 0 | 0 | 0 |
| V4_SLOT0_EMPTY | 24 | 20 | -4 |
| V4_MISLABEL_V3_POOL | 0 | 3 | +3 (new bucket) |
| FACTORY_MISSING_TOKENS | 50 | 50 | 0 |
| FACTORY_NO_POOL | 4 | 4 | 0 |
| HINT_STALE | 2 | 5 | +3 |
| primary_blocker_recall | V4_POOLID_NOT_RESOLVED | FACTORY_MEMBERSHIP_FAIL | shifted |

## V3 fallback impact

Code fix (commit `692b470`) resolved 3 V4-mislabeled hints as `V4_MISLABEL_V3_POOL` via V3 factory lookup. These pools exist on-chain but are stale (>48h), so they count as `pool_exists_stale` not `selection_verified_fresh`.

V4_POOLID_NOT_RESOLVED decreased from 24 to 20 — the remaining 20 are likely true V4 pools (StateView slot0 genuinely empty) or non-existent pools.

## Primary blocker analysis

`selection_verified_fresh_total=0` persists because:

1. **FACTORY_MEMBERSHIP_FAIL (54 hints)**: factory.getPool() cannot find these pools. 50 have no token addresses (`FACTORY_MISSING_TOKENS`), 4 have tokens but factory returns no pool (`FACTORY_NO_POOL`). These are onchain_factory-sourced hints without populated token0/token1.
2. **V4_POOLID_NOT_RESOLVED (20 hints)**: V4 StateView slot0 empty. V3 fallback attempted but factory also fails. Likely true V4 pools with uninitialized state or non-existent pools.
3. **Stale-only (5 pool_exists_stale)**: Pools exist on-chain but created >48h ago. Not selection-fresh by policy.

No fresh (<48h) DexScreener hints with valid pool existence were found in this run.

## M8.2/M8.3 acceptance

| Gate | Status | Key metrics |
|------|--------|-------------|
| M8.2 | BLOCKED | mirror_quote_ready_tokens=13, handoff_ready=implied, blockers: EXTERNAL_HINTS_STALE, HINTS_STALE, SUBGRAPH_READY_LOW |
| M8.3 | REACHED | token_task_funnel: 109/109 completed, pool_identity_cycle_rate=1.0 |

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0` and `cycles_at_floor > 0`.
- Next code task: populate `token0/token1` for onchain_factory hints (54 hints blocked by FACTORY_MISSING_TOKENS/FACTORY_NO_POOL).
- Re-run `-mirror_recall_fast` after token population fix.
- Stale-only pools (5) require fresh market activity (new pair creation <48h) — not a code fix.
