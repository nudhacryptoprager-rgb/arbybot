# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-03T13:05:00Z
goal_status: BLOCKED
blocker_status_after: STALE_BUT_POOL_EXISTS / Aerodrome factory_address missing
docs_reread_confirmed: true
run_id: rca-breakdown-2026-07-03
mode: scripts/m8_onchain_factory_mirror_scan.py + scripts/m8_mirror_discovery_recall.py
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Add per-dex/per-factory RCA breakdown for FACTORY_NO_POOL + DexScreener null-age audit
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (STALE_BUT_POOL_EXISTS + Aerodrome factory_address="" for DexScreener hints)
blocker_status_before: STALE_BUT_POOL_EXISTS / created_at enriched (cycle 6)
blocker_status_after: STALE_BUT_POOL_EXISTS + RCA shows Aerodrome factory_address="" as root cause for 8 FACTORY_NO_POOL
close_allowed: true
remaining_blockers: Aerodrome factory_address not populated for DexScreener hints; all pools >48h; 4 DexScreener null-age hints
evidence_artifacts: data/tmp/m8_onchain_factory_scan_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json
docs_reread_confirmed: true

## Fresh RCA (2026-07-03T13:05:00Z)

### Overall metrics

| Metric | Value |
|--------|-------|
| selection_verified_fresh_total | 0 |
| recall_verified_pool_exists_total | 43 |
| pool_exists_stale_total | 43 |
| primary_blocker_recall | STALE_BUT_POOL_EXISTS |

### FACTORY_NO_POOL breakdown (new RCA)

| dex_id | count | root cause |
|--------|-------|------------|
| aerodrome | 8 | factory_address="" — DexScreener hints not enriched with Aerodrome factory |
| uniswap_v2 | 7 | factory=0x8909dc15e4 set but getPool returns no pool |

| factory_address (prefix) | count | note |
|--------------------------|-------|------|
| (empty) | 4 | Aerodrome DexScreener hints — no factory |
| 0x8909dc15e4 | 7 | Uniswap V2 factory — pool may not exist |
| 0x420dd381b3 | 4 | Unknown factory |

### factory_no_pool_samples (first 5)

All 8 Aerodrome samples have `factory_address=""`, `fee=null`, `source=dexscreener`. This means DexScreener-sourced Aerodrome hints are not getting factory_address populated during hint creation. The `resolve_aerodrome_dex_variant()` resolver classifies the variant but doesn't set the factory address.

Uniswap V2 samples have `factory_address="0x8909dc15e4..."`, `created_at_source="first_seen_block_proxy"`. Factory is set but getPool returns no pool — likely the pool doesn't exist on this factory.

### DexScreener null-age histogram (new RCA)

| dex_id | null_age_count |
|--------|----------------|
| aerodrome | 4 |

4 DexScreener aerodrome hints have `created_at=None` (pairCreatedAt is null in DexScreener API response).

## Code changes

Commit `c0a34f5`:
1. `mirror_recall_verify.py`: `verify_hints_for_recall()` — added `factory_no_pool_by_dex`, `factory_no_pool_by_factory`, `factory_no_pool_samples`, `dex_null_age_histogram` to metrics
2. `mirror_discovery_recall.py`: `verify_supported_hints()` — same aggregation in the other entry point; `build_verify_rca()` — propagated new keys to RCA report
3. `tests/unit/test_mirror_recall_verify.py` — 2 new tests: FACTORY_NO_POOL aggregation, dex_null_age histogram

## Root cause analysis

**Aerodrome FACTORY_NO_POOL (8 hints)**: DexScreener-sourced Aerodrome hints have `factory_address=""`. The `_pair_to_hint()` function in `dexscreener_hints.py` doesn't set `factory_address` for Aerodrome. The `resolve_aerodrome_dex_variant()` resolver determines the variant (ve33/slipstream/stable) but the factory address for each variant is not looked up from config.

**Next code task**: In `dexscreener_hints.py` or `_pair_to_hint()`, after Aerodrome variant resolution, set `factory_address` from `config/exotic_base_anchor.yaml` dexes section. Aerodrome has different factories for ve33, slipstream, and stable variants.

**uniswap_v2 FACTORY_NO_POOL (7 hints)**: Factory address is set but getPool returns no pool. These pools may genuinely not exist on the Uniswap V2 factory, or the factory address may be wrong for Base chain.

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0` and `cycles_at_floor > 0`.
- Next code task: populate `factory_address` for DexScreener Aerodrome hints from config after variant resolution.
- Re-run scan + recall after factory_address fix to see if FACTORY_NO_POOL for Aerodrome drops.
- Cadence running still needed for fresh (<48h) pool discovery.
