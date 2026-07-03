# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-03T12:19:59Z
goal_status: BLOCKED
blocker_status_after: STALE_BUT_POOL_EXISTS / all pools >48h old
docs_reread_confirmed: true
run_id: created-at-proxy-2026-07-03
mode: scripts/m8_onchain_factory_mirror_scan.py + scripts/m8_mirror_discovery_recall.py
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Resolve created_at=None for factory-sourced hints via first_seen_block proxy to unblock STALE_BUT_POOL_EXISTS.
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (all 40 pool_exists hints have created_at from 2026-06-07, which is >48h → genuinely stale)
blocker_status_before: STALE_BUT_POOL_EXISTS / created_at=None (43 hints, 2026-07-03 cycle 5)
blocker_status_after: STALE_BUT_POOL_EXISTS / created_at=2026-06-07 (40 hints, all >7d old)
close_allowed: true
remaining_blockers: all discovered pools are genuinely >48h old; DexScreener hints with created_at=null (53 unknown age); 17 FACTORY_NO_POOL; 22 V4_POOLID_NOT_RESOLVED
evidence_artifacts: data/tmp/m8_onchain_factory_scan_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json
docs_reread_confirmed: true

## Fresh RCA (2026-07-03T12:19:59Z)

| Metric | Cycle 5 (before) | Cycle 6 (after) | Delta |
|--------|-----------------|-----------------|-------|
| created_at_non_null (scan) | 0/50 | **50/50** | +50 (ENRICHED) |
| recall_verified_pool_exists | 43 | 40 | -3 (different scan run) |
| pool_exists_stale | 43 | 40 | -3 |
| selection_verified_fresh | 0 | 0 | 0 |
| mirror_age_bucket: unknown | 53 | **53** | 0 (DexScreener nulls) |
| mirror_age_bucket: >7d | 26 | **26** | 0 (factory hints enriched) |
| FACTORY_NO_POOL | 14 | 17 | +3 |
| V4_SLOT0_EMPTY | 22 | 22 | 0 |
| primary_blocker | STALE_BUT_POOL_EXISTS (created_at=None) | **STALE_BUT_POOL_EXISTS (all >7d)** | shifted from code to market |

## Code fix impact

Commit `9814245` added:
1. `_resolve_block_timestamps()` — batch eth_getBlockByNumber → ISO timestamp
2. `_enrich_hints_from_subset()` — resolves first_seen_block → created_at proxy
3. `created_at_source=first_seen_block_proxy` provenance marker
4. dotenv loading in resolver for direct script execution

**created_at enrichment works**: 50/50 factory scan pools now have `created_at` from block timestamps. All pools date to `2026-06-07` (~26 days ago), which is >48h → correctly classified as stale by `hint_is_stale_for_recall`.

## Root cause analysis: why selection_verified_fresh_total=0

This is now a **market condition**, not a code bug:
1. **Factory scan tokens** (376 with first_seen_block) all have blocks from `2026-06-07` — these are not fresh tokens. The pending queue's `first_seen_block` values are all ~26 days old.
2. **DexScreener hints** (53 with unknown age) have `created_at=null` from DexScreener API (pairCreatedAt is null for some pairs).
3. **No fresh (<48h) pool creation** has been detected in the current token universe.

The code path is now correct:
- token0/token1 preserved (commit 7c2b236) ✓
- created_at enriched from first_seen_block (commit 9814245) ✓
- V3 fallback for V4-mislabeled hints (commit 692b470) ✓
- Pool existence verified via factory membership ✓

**Fresh pools require fresh market activity**: new pair creation events on Base within the last 48h. The pipeline needs to run on cadence (e.g., every few hours) to catch fresh pair creations as they happen.

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0` and `cycles_at_floor > 0`.
- The code path is now complete for factory-sourced hint enrichment. Admission requires fresh market data (<48h pool creations).
- Run `-mirror_recall_fast` on cadence to catch fresh pair creations.
- Consider: DexScreener hints with `created_at=null` — investigate if DexScreener API provides alternative creation time fields, or if block-based enrichment applies to DexScreener-sourced hints too.
- 17 FACTORY_NO_POOL: token pairs not found on any factory — may be Aerodrome pools (Aerodrome uses its own factory, not in standard factory list).
- 22 V4_POOLID_NOT_RESOLVED: true V4 pools with empty StateView slot0 or non-existent pools.
