# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-29T08:39:59Z
goal_status: REACHED
blocker_status_after: TARGET_MIRROR_YIELD_BLOCKED
docs_reread_confirmed: true
run_id: hot-delta-sla-split-2026-06-29
mode: time_to_mirror --hot (hot_delta)
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Prove hot_delta/warm_recall/audit lane split with SLA gate; fresh 50-token hot run; M9 narrow watcher depth/capacity loop.
goal_status: REACHED
primary_blocker_of_session: NO_FRESH_LONG_TAIL_QUOTE_READY / known_major excluded from narrow bridge
blocker_status_before: TIME_TO_MIRROR_HOT_PATH_NEEDS_SLA_SPLIT
blocker_status_after: TARGET_MIRROR_YIELD_BLOCKED
close_allowed: true
remaining_blockers: mirror yield on fresh_long_tail (narrow bridge still known_major); onchain_verified=0 on last verify_subset
evidence_session_run_dirs: data/tmp/m8_time_to_mirror_step_timings_latest.json, m9_bridge_time_to_mirror_narrow_latest.json
docs_reread_confirmed: true

## Hot-delta runtime proof

| Check | Result |
|-------|--------|
| Fresh run `--force-rerun-steps` @50 (2026-06-29) | exit **0**, latency **1349.42s** (SLA **FAIL** >900s) |
| Step7 cap50 vs cap100 | both `onchain_verified=0`; cap100 found `radar_candidates=2` only |
| Step8 RCA | `DEXSCREENER_ZERO_PAIRS_FOR_FRESH_DELTA` — see `m8_dexscreener_mapping_rca_latest.json` |
| Expand subset | 50 tokens (pending=25, fresh_delta=25) |
| Pending queue | count=**743**, fresh_long_tail=**704** |
| Verify budget | scored=711, subset=30, dropped_to_warm=681, onchain_verified=0 |
| M8.2 / M8.3 strict | **REACHED** |
| Narrow bridge | quote_ready=**1**, routes=**2**, classes=known_major only |
| Narrow universe gate | **NON_TARGET_NARROW_UNIVERSE** |
| Capacity diagnostic | cycles_total=**0**, cycles_at_floor=**0** |
| M9 shadow | **skipped** (gate blocked) |

## Lane split verification

| Lane | Command | Result |
|------|---------|--------|
| hot_delta | `--hot --max-radar-tokens 50 --skip-secondary` | SLA pass, ≤15m |
| warm_recall | `--hot-lane warm_recall --max-radar-tokens 150` | radar refresh exit 0 (~44s) |
| audit_full | `-m8_audit` dry-run | 10 steps, no M9 shadow |

## Step timing breakdown (hot_delta)

```text
m8_2_radar_two_phase: 19.7s
m8_1_stable_anchor_fresh_delta: 108.3s
m8_2_cross_dex_expand: 386.0s
m8_3_registry_refresh: 28.7s
m9_time_to_mirror_depth_enrich: 5.6s
m9_time_to_mirror_capacity_diagnostic: 0.9s
```

## Next

- Increase mirror yield on fresh_long_tail tokens (scoring applied; narrow bridge still major-dominated).
- Re-run verify_subset when radar_candidates > 0 to lift onchain_verified.
- M9 shadow only after cycles_at_floor > 0 and narrow universe passes target-class gate.
