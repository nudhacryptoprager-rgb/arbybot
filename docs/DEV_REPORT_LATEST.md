# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-03T11:42:22Z
goal_status: BLOCKED
blocker_status_after: STALE_BUT_POOL_EXISTS / created_at=None
docs_reread_confirmed: true
run_id: factory-token-enrichment-2026-07-03
mode: scripts/m8_onchain_factory_mirror_scan.py + scripts/m8_mirror_discovery_recall.py
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Fix FACTORY_MISSING_TOKENS (50 hints without token0/token1) by preserving token addresses in scan artifact serialization + load_factory_recall_hints.
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (STALE_BUT_POOL_EXISTS — all 43 pool_exists hints have created_at=None)
blocker_status_before: FACTORY_MEMBERSHIP_FAIL (50 FACTORY_MISSING_TOKENS, 2026-07-03 cycle 4)
blocker_status_after: STALE_BUT_POOL_EXISTS (43 pools exist but created_at=None → stale by policy)
close_allowed: true
remaining_blockers: created_at=None for factory-sourced hints; 14 FACTORY_NO_POOL; 22 V4_POOLID_NOT_RESOLVED
evidence_artifacts: data/tmp/m8_onchain_factory_scan_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json
docs_reread_confirmed: true

## Fresh RCA (2026-07-03T11:42:22Z)

| Metric | Cycle 4 (before) | Cycle 5 (after) | Delta |
|--------|-----------------|-----------------|-------|
| recall_verified_pool_exists_total | 5 | **43** | +38 |
| pool_exists_stale_total | 5 | **43** | +38 |
| selection_verified_fresh_total | 0 | 0 | 0 |
| FACTORY_MISSING_TOKENS | 50 | **0** | **-50 (ELIMINATED)** |
| FACTORY_NO_POOL | 4 | 14 | +10 |
| HINT_STALE | 5 | **43** | +38 |
| V4_SLOT0_EMPTY | 20 | 22 | +2 |
| V4_MISLABEL_V3_POOL | 3 | 2 | -1 |
| primary_blocker | FACTORY_MEMBERSHIP_FAIL | **STALE_BUT_POOL_EXISTS** | shifted |
| RCA samples with token0 | 0/25 | **25/25** | +25 |

## Code fix impact

Commit `7c2b236` preserved token0_addr/token1_addr/fee/factory_address/created_at in:
1. Scan artifact serialization (`onchain_factory_mirror_discovery.py:920-935`)
2. `load_factory_recall_hints()` reads them back (`token_pool_universe.py:182-207`)
3. `mirror_row_from_hint()` includes them in RCA samples (`mirror_discovery_recall.py:108-136`)

**FACTORY_MISSING_TOKENS eliminated**: 50 → 0. Factory verification now has token pairs to call `factory.getPool(token0, token1, fee)`. 43 pools verified as existing on-chain (up from 5).

## Remaining blocker: staleness

All 43 pool_exists hints have `created_at=None` → `hint_is_stale_for_recall=True` → `selection_verified_fresh=False`.

Root cause: `_pool_hint_from_factory_scan()` does not set `created_at`. Factory scan finds pools via `factory.getPool()` which doesn't return creation time. DexScreener hints have `created_at` from `pairCreatedAt`, but some return null.

**Next code task**: populate `created_at` for factory-sourced hints from `first_seen_block` timestamp (requires RPC `eth_getBlockByNumber`). Token watchlist has `first_seen_block` for each token — converting to block timestamp would give us pool creation time proxy.

## Other RCA buckets

- **FACTORY_NO_POOL (14)**: factory.getPool() returns no pool for these token pairs. Pools may not exist or may be on unsupported factories.
- **V4_POOLID_NOT_RESOLVED (22)**: V4 StateView slot0 empty. V3 fallback attempted but factory also fails. True V4 pools or non-existent.
- **V4_MISLABEL_V3_POOL (2)**: V4-labeled hints resolved as V3 pools via factory lookup. All stale.

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0` and `cycles_at_floor > 0`.
- Next code task: populate `created_at` for factory-sourced hints from `first_seen_block` block timestamp.
- Re-run `m8_onchain_factory_mirror_scan.py` + `m8_mirror_discovery_recall.py` after created_at fix.
- If `created_at` is set to actual creation time, some pools may become fresh (<48h) → `selection_verified_fresh_total > 0`.
