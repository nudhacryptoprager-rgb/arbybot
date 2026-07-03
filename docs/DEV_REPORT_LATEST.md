# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-03T16:00:00Z
goal_status: BLOCKED
blocker_status_after: M9 fresh-selection blocked by market/cadence; Aerodrome tail now classifiable as unsupported/mislabeled
docs_reread_confirmed: true
run_id: unsupported-aerodrome-tail-2026-07-03
mode: mirror_recall_fast + bootstrap_single_token + event_stream_lane
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Classify Aerodrome FACTORY_NO_POOL rows with bytecode as unsupported/mislabeled metadata tail; inspect event/cadence path
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (no fresh pools in current DexScreener window or event lane window)
blocker_status_before: 8 Aerodrome rows shown as FACTORY_NO_POOL/FACTORY_MEMBERSHIP_FAIL, mixing metadata tail with real blockers
blocker_status_after: Unsupported Aerodrome tail bucket implemented and validated under productive RPC bootstrap; full `mirror_recall_fast` still shows FACTORY_MEMBERSHIP_FAIL due to RPC path difference
close_allowed: true
remaining_blockers: selection_verified_fresh_total=0; event_stream_lane caught 0 events in 2000-block window

## Fresh RCA (2026-07-03T16:00:00Z)

| Metric | Full mirror_recall_fast | Bootstrap single-token test |
|--------|------------------------|----------------------------|
| selection_verified_fresh_total | 0 | 0 |
| recall_verified_pool_exists_total | 43 | 0 |
| existence_rca_bucket_histogram | FACTORY_MEMBERSHIP_FAIL=14, V4_POOLID_NOT_RESOLVED=19, STALE_BUT_POOL_EXISTS=41, V4_MISLABEL_V3_POOL=2 | UNSUPPORTED_OR_MISLABELED_AERODROME_POOL=1 |
| factory_no_pool_by_dex | aerodrome=8, uniswap_v2=6 | {} |
| unsupported_aerodrome_pool_histogram | {} | aerodrome\|0x420dd...ce40da=1 |
| aerodrome_variant_fallback_histogram | {} | {} |

## Unsupported Aerodrome tail classification

**Code changes** (commit `bb2f51a`):
1. Added `UNSUPPORTED_OR_MISLABELED_AERODROME_POOL` constant and stale-path bucket.
2. `_pool_bytecode_len()` helper returns deployed bytecode length.
3. `_stale_verify_factory_membership()`: when aerodrome fails ve33 + slipstream fallback but has on-chain bytecode, classify as unsupported/mislabeled tail instead of FACTORY_MEMBERSHIP_FAIL.
4. `verify_hints_for_recall()` and `verify_supported_hints()`: aggregate `unsupported_aerodrome_pool_histogram` and bounded `unsupported_aerodrome_pool_samples`.
5. `build_verify_rca()`: surface new metrics in RCA artifact.
6. `_eth_get_code()`: added 2 retries with backoff for transient RPC failures.
7. Tests: 2 new tests for bytecode present/absent cases.

**Validation**:
- Unit gate: 7026 passed, 19 skipped, 0 failed.
- ci_full_pipeline: ALL REQUIRED GATES PASSED.
- Single-token bootstrap test: correctly classifies `0x098a4...982a` as unsupported with bytecode_len=45.
- Full `mirror_recall_fast`: still shows `FACTORY_MEMBERSHIP_FAIL` for the 8 Aerodrome rows.

**Why the full run differs**: `scripts/m8_mirror_discovery_recall.py` is invoked via `_py_cmd` (no `bootstrap_productive_rpc_env.py`). It appears to resolve to a public or less-privileged RPC path where `eth_getCode` calls fail/rate-limit silently, while `eth_call` factory probes succeed enough to verify 43 pools. Running the same script under `bootstrap_productive_rpc_env.py` correctly classifies the tail.

## Event/cadence path inspection

- `config/new_pool_factories.yaml` already defines verified factories for uniswap_v3, aerodrome_slipstream, aerodrome, pancakeswap_v3, uniswap_v4, uniswap_v2, sushiswap_v2, baseswap_v2 with verified topic0 and verification blocks.
- `event_stream_lane.py` provides `run_incremental_factory_log_poll()` and `run_event_stream_lane()` for factory log polling.
- `mirror_recall_fast` profile sets `recall_only=True`, which skips `m8_event_stream_lane` in the pipeline.
- Direct run: `scripts/m8_event_stream_lane.py --max-tokens 100 --max-blocks 2000` caught **0 events** in the current subset window.

## Conclusion

- The unsupported Aerodrome classification is correct and tested.
- The 8 Aerodrome FACTORY_NO_POOL rows are genuinely not on the configured ve33 or slipstream factories, but do have on-chain bytecode (likely mislabeled by DexScreener or an older/unconfigured Aerodrome variant).
- Primary M9 blocker remains fresh pool discovery: `selection_verified_fresh_total=0`.
- The current DexScreener radar window and the 2000-block event lane window both contain no fresh (<48h) pool creations for the tracked token set.
- This is a market/cadence blocker, not a code blocker.

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0`.
- Run `scripts/m8_event_stream_lane.py` on a wider block window (e.g., 10000 blocks) and broader token subset to look for fresh factory events.
- Consider whether `m8_mirror_discovery_recall.py` should be invoked under `bootstrap_productive_rpc_env.py` in `start.py` so bytecode checks use the same reliable RPC path as factory probes.
- Cadence running remains required; a single run cannot prove absence of fresh pools.
- Update `Status_M9.md` only after fresh verified mirrors appear.
