# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-03T13:45:00Z
goal_status: BLOCKED
blocker_status_after: STALE_BUT_POOL_EXISTS / Aerodrome variant misclassification
docs_reread_confirmed: true
run_id: aerodrome-factory-fix-2026-07-03
mode: scripts/m8_onchain_factory_mirror_scan.py + scripts/m8_mirror_discovery_recall.py
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Populate factory_address from config for DexScreener Aerodrome hints after variant resolution
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (STALE_BUT_POOL_EXISTS + Aerodrome getPool returns no pool despite correct factory_address)
blocker_status_before: Aerodrome FACTORY_NO_POOL with factory_address="" (cycle 8)
blocker_status_after: Aerodrome FACTORY_NO_POOL with factory_address="0x420dd381b3" (correct ve33 factory, but getPool still returns no pool)
close_allowed: true
remaining_blockers: Aerodrome variant misclassification (ve33 vs slipstream); all pools >48h; 4 DexScreener null-age hints
evidence_artifacts: data/tmp/m8_onchain_factory_scan_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json
docs_reread_confirmed: true

## Fresh RCA (2026-07-03T13:45:00Z)

### Factory_address fix impact

| Metric | Before (cycle 8) | After (cycle 9) | Delta |
|--------|-----------------|-----------------|-------|
| Aerodrome factory_address | "" (empty) | **0x420dd381b3** | **FIXED** |
| factory_no_pool_by_factory: (empty) | 4 | **0** | -4 (eliminated) |
| factory_no_pool_by_dex: aerodrome | 8 | 8 | 0 (still FACTORY_NO_POOL) |
| factory_no_pool_by_dex: uniswap_v2 | 7 | 9 | +2 |
| recall_verified_pool_exists | 43 | 41 | -2 |
| selection_verified_fresh | 0 | 0 | 0 |

### Root cause shift

Factory_address is now correctly populated from config (`0x420dd381b31aef6683db6b902084cb0ffece40da` for ve33/stable). The `unknown`/empty factory bucket is eliminated. However, `FACTORY_NO_POOL` persists for 8 Aerodrome hints because `factory.getPool(token0, token1, fee)` on the ve33 factory returns no pool.

**Hypothesis**: These 8 pools are actually Slipstream pools (concentrated liquidity) misclassified as ve33 by `resolve_aerodrome_dex_variant()`. The resolver uses DexScreener `labels` and `type` fields, but these pairs have no labels → default to ve33. Slipstream pools use a different factory (`0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a`) and different getPool method signature.

**Evidence**: All 8 Aerodrome FACTORY_NO_POOL samples have:
- `dex_id=aerodrome` (ve33 default)
- `raw_dex_id=aerodrome`
- `factory_address=0x420dd381b3` (ve33 factory)
- `fee=None` (ve33 doesn't use fee, but slipstream does)
- No labels in DexScreener data

## Code changes

Commit `c53b78a`:
1. `dexscreener_hints.py`: After variant resolution, look up `factory_address` from `cfg["dexes"][dex_id]["factory"]` and set on PoolHint
2. `tests/unit/test_m8_external_pool_hints.py`: 4 new tests (ve33, slipstream, stable, missing config)

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0` and `cycles_at_floor > 0`.
- Next investigation: Aerodrome variant resolution accuracy — try slipstream factory for pools where ve33 getPool fails. This could be a fallback chain (try ve33 first, then slipstream).
- Alternative: query pool contract directly to determine pool type (Aerodrome pools have different contract interfaces for ve33 vs slipstream).
- Cadence running still needed for fresh (<48h) pool discovery.
