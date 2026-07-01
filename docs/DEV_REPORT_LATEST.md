# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-30T08:49:52Z
goal_status: BLOCKED
blocker_status_after: SELECTION_VERIFIED_FRESH_ZERO
docs_reread_confirmed: true
run_id: mirror-recall-fast-split-runtime-2026-06-30
mode: start.py -mirror_recall_fast + downstream verify resume-from m8_onchain_factory_mirror_scan
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Fresh runtime proof for fast recall split (Contour A) and token-scoped downstream verify (Contour B); M9 shadow remains gated.
goal_status: BLOCKED
primary_blocker_of_session: selection_verified_fresh_total=0 (V4_POOLID_NOT_RESOLVED)
blocker_status_before: TIME_TO_MIRROR_PIPELINE_NEEDS_FAST_RECALL_SPLIT (code only)
blocker_status_after: SELECTION_VERIFIED_FRESH_ZERO / V4_POOLID_NOT_RESOLVED
close_allowed: true
remaining_blockers: v4 poolId resolution; stale hint refresh for selection admission
evidence_artifacts: data/tmp/m8_mirror_discovery_recall_latest.json, data/tmp/m8_time_to_mirror_step_timings_latest.json, data/tmp/m8_mirror_recall_verify_rca_latest.json, data/tmp/m8_existence_verify_subset.json
docs_reread_confirmed: true

## Contour A — mirror_recall_fast proof (alias normalization refresh)

| Check | Result |
|-------|--------|
| `start.py -mirror_recall_fast --force-rerun-steps` | exit **0**, elapsed **~46s** |
| recall_latency_s | **39.58** |
| recall_sla_pass | **true** |
| all_dex_mirrors_total | **80** |
| supported_mirrors_total | **80** (was **29**) |
| unknown_alias_mirrors_total | **0** (was **95**) |
| selection_verified_fresh_total | **0** |

## Contour B — downstream verify (existence subset only)

| Check | Result |
|-------|--------|
| `resume-from m8_onchain_factory_mirror_scan --force-rerun-steps` | exit **0**, elapsed **~32m** (includes cross_dex_expand) |
| onchain_factory_scan_s | **83.81** (27 tokens; prior full-universe ~792s) |
| m8_1_fresh_delta_s | **141.44** |
| verify_latency_s | **225.39** |
| verify_sla_pass | **true** (max 900s) |
| onchain verified_pools | **50** on **27** tokens |
| selection_verified_fresh_total | **0** (unchanged) |
| M9 narrow shadow | **not started** (--skip-shadow + admission gate) |

## Interpretation

Fast recall split works: DexScreener token-scoped recall completes in **~23s** on 713 tokens with **124** mirror candidates. Heavy RPC verification scoped to **27-token existence subset** completes in **~225s** vs **~18min** when coupled before recall on full universe.

Strategy blocker is no longer pipeline latency or alias width — admission width is now fully supported at recall (`80/80`). Remaining gap is **selection admission**: `V4_POOLID_NOT_RESOLVED` and stale hints. M9 correctly blocked until `selection_verified_fresh_total > 0`.

## Next

- Do not run M9 shadow until `selection_verified_fresh_total > 0` and fresh_long_tail quote-ready mirrors exist.
- Prioritize v4 poolId resolver + stale-hint refresh on existence_verify_queue (27 hints).
- Re-run `-mirror_recall_fast` on cadence; downstream verify only when `all_dex_mirrors_total > 0`.
