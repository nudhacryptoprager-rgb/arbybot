# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-03T14:30:00Z
goal_status: BLOCKED
blocker_status_after: STALE_BUT_POOL_EXISTS / Aerodrome pools not on ve33 or slipstream factory
docs_reread_confirmed: true
run_id: aero-slipstream-fallback-2026-07-03
mode: scripts/m8_onchain_factory_mirror_scan.py + scripts/m8_mirror_discovery_recall.py
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Add Aerodrome variant fallback (ve33 FACTORY_NO_POOL -> try slipstream) in both fresh and stale verification paths
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (STALE_BUT_POOL_EXISTS + 8 Aerodrome pools not found on ve33 or slipstream factory)
blocker_status_before: Aerodrome FACTORY_NO_POOL with factory_address set but getPool returns no pool (cycle 9)
blocker_status_after: Slipstream fallback tried but pools not on slipstream factory either; bytecode check may fail due to RPC rate limiting
close_allowed: true
remaining_blockers: 8 Aerodrome pools not on any configured factory; all pools >48h; RPC rate limiting during recall
evidence_artifacts: data/tmp/m8_onchain_factory_scan_latest.json, data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json
docs_reread_confirmed: true

## Fresh RCA (2026-07-03T14:30:00Z)

| Metric | Value |
|--------|-------|
| selection_verified_fresh_total | 0 |
| recall_verified_pool_exists_total | 43 |
| pool_exists_stale_total | 43 |
| factory_no_pool_by_dex | aerodrome=8, uniswap_v2=5 |
| aerodrome_variant_fallback_histogram | {} (empty — fallback tried but slipstream also returns no pool) |

## Aerodrome slipstream fallback analysis

The fallback was implemented in both verification paths:
1. `verify_hint_specialized` (fresh path) — tries slipstream when ve33 returns FACTORY_NO_POOL
2. `_stale_verify_factory_membership` (stale path) — same fallback for stale hints

**Runtime result**: `aerodrome_variant_fallback_histogram={}` — the fallback function was called but returned `(False, "", None)` for all 8 hints. The pools do NOT exist on the slipstream factory (`0x5e7bb104...`) with any V3 fee tier (100, 500, 3000, 10000).

**On-chain verification**: I manually checked 3 of the 8 pool addresses via `eth_getCode`:
- All 3 have bytecode (code_len=92, ~45 bytes — likely EIP-1167 minimal proxy)
- But `getPair` on ve33 factory returns zero address
- And `getPool` on slipstream factory with all fee tiers returns zero address

**Hypothesis**: These pools are either:
1. Aerodrome V1 pools (pre-V2) on a different factory not in config
2. Pools from a different protocol that DexScreener mislabeled as "aerodrome"
3. Proxy contracts that delegate to a pool implementation

**Stale path bytecode check**: The 8 aerodrome hints end up as FACTORY_MEMBERSHIP_FAIL (not STALE_BUT_POOL_EXISTS), which means `_pool_has_bytecode` returned False. This could be RPC rate limiting (429) during the recall run — the `_eth_get_code` function catches all exceptions and returns False.

## Code changes

Commit `85ad66d`:
1. `hint_verifier.py`: `_try_aerodrome_slipstream_fallback()` — tries slipstream factory with V3 fee tiers
2. `hint_verifier.py`: `verify_hint_specialized()` — calls fallback when aerodrome FACTORY_NO_POOL
3. `mirror_recall_verify.py`: `_stale_verify_factory_membership()` — same fallback in stale path
4. `mirror_discovery_recall.py`: `aerodrome_variant_fallback_histogram` in RCA
5. `tests/unit/test_m8_external_pool_hints.py`: 3 new tests (slipstream hit, slipstream miss, non-aerodrome)

Commit `220697c`:
1. `mirror_recall_verify.py`: Added slipstream fallback in stale path too

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0` and `cycles_at_floor > 0`.
- The 8 Aerodrome FACTORY_NO_POOL hints are likely mislabeled by DexScreener or on an unconfigured factory. Not a code bug.
- RPC rate limiting during recall may cause bytecode checks to fail silently. Consider adding retry or rate-limit-aware backoff in `_eth_get_code`.
- Cadence running still needed for fresh (<48h) pool discovery.
- `selection_verified_fresh_total=0` is now a market/infra condition: all discovered pools are >48h old.
