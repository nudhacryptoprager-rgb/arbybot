# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: ONLINE (M7.E1.2 Base hot blocker separation, April 7 21:38-21:41Z nonstop; single hot iteration at 21:36Z. M4/M5 rolling from ci_m5_gate_arbitrum_one_20260402_110313_968343, unchanged — M7-only session with --no-m4)
artifact_mode: rolling
config: config/onboard_base_profit.yaml (base, narrow contour)
code_identity:
  primary: ts:2026-04-07T21:41:43Z
  dirty: true
  desc: M7.E1.2 - separate Base hot blocker from cold gas blocker, fix Arbitrum contamination + stage_a_ms crash

## Session Completion
session_goal: M7.E1.2 - separate Base cold gas blocker from Base hot overlap/registry blocker; prove whether hot zero-hit is bridge/registry issue or gas shadow
goal_status: REACHED (Base hot lane is gas_economics_only blocked — 12/12 bridge-matching events gas-rejected, 0 scored positive. Arbitrum contamination eliminated. Hot lane now writes rollup after stage_a_ms fix.)
close_allowed: true
remaining_blockers: GAS_EXCEEDS_GROSS sole blocker on Base, both lanes. Best near-executable -2.20 bps (QWLA/WETH). L1 data 80% of gas. Flashblocks WS untested (separate subtask).
evidence_session_run_dirs: [data/runs/_rolling/ (m7_hot_rollup_latest.json ts=2026-04-07T21:41:43Z, m7_hot_latest.json ts=2026-04-07T21:41:43Z, m7_orderflow_latest.json ts=2026-04-07T21:41:02Z, m7_cold_hot_bridge.json ts=2026-04-07T21:41:43Z)]
primary_blocker_of_session: gas_economics — 12/12 bridge-matching hot events gas-rejected. blocker_class=gas_economics_only. 9/17 bridge families have hot events (event source NOT absent).
blocker_status_before: M7.E1.1 OPEN — hot artifacts showed Arbitrum contamination (false event_source_absence, hardcoded 0xd13040 pool, family_unresolved). Hot rollup silently not written (stage_a_ms KeyError).
blocker_status_after: M7.E1.2 OPEN — contamination eliminated, hot lane writes correctly, gas_economics_only confirmed with fresh chain-native traces.
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.2 = separate Base cold gas blocker from Base hot overlap/registry blocker
change_summary:
  - scripts/m7a_orderflow_loop.py: (1) Dynamic _TARGET_POOL from bridge_selected_at_assembly (A_cold_exec first, fallback, None). (2) Four event-to-bridge classification counters. (3) Three-way blocker_class. (4) families_with_any_hot_events across ALL bridge families.
  - m7/orderflow/mode_ws_live.py: Fixed KeyError 'stage_a_ms' — .get() instead of [] indexing in stage latency aggregation. This bug silently crashed every hot iteration.
  - tests/unit/test_47r_cross_artifact_contract.py: Updated _build_architecture_blocker_trace, tests for three-way classification, test_families_with_any_hot_events_uses_all_families.
  - tests/unit/test_e1_base_chain_aware.py: 3 new test classes (14 tests) — dynamic target pool selection, event-bridge classification, blocker classification. Source-level invariant: no hardcoded Arbitrum pool.
  - docs/status/Status_M7.md: Updated status line, M7.E1.2 subsection, Known Blockers, Next Steps.
  - docs/DEV_REPORT_LATEST.md: This file.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED — dynamic target pool, event counters, three-way blocker)
  - m7/orderflow/mode_ws_live.py (MODIFIED — stage_a_ms KeyError fix)
  - tests/unit/test_47r_cross_artifact_contract.py (MODIFIED — blocker classification tests)
  - tests/unit/test_e1_base_chain_aware.py (MODIFIED — 14 new E1.2 tests)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3718 passed, 6 skipped — 3702 + 16 new E1.2 tests)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED (pre-changes)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings, pre-changes)
py -3.11 scripts/m7a_orderflow_loop.py --lane hot --chain base --ws-blocks 3 --pause 0 --iterations 1: PASS (single hot iteration, rollup written at 21:36Z)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.05 --chain base --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (3 min, 3/3 alive, 0 restarts, clean shutdown at 21:41:47Z)

## 3) Artifacts Attached

M7 rolling artifacts (from Base nonstop + single hot iteration, April 7 21:36-21:41Z):
- m7_hot_rollup_latest.json: last_updated=2026-04-07T21:41:43Z, windows_seen=185, events_seen_total=116, windows_with_events=52, bridge_pool_hit_total=16, fast_path_scored_total=19, events_in_bridge_total=12, events_not_in_bridge_total=7, matched_then_gas_rejected_total=12, matched_then_scored_positive_total=0, blocker_class=gas_economics_only, families_with_any_hot_events=9/17
- m7_hot_latest.json: timestamp=2026-04-07T21:41:43Z, events_count=1, viable_count=0, not_in_hot_registry_count=0
- m7_orderflow_latest.json: chain=base, timestamp=2026-04-07T21:41:02Z
- m7_cold_hot_bridge.json: timestamp=2026-04-07T21:41:43Z, bridge_selected_count=20, hot_overlap_count=5

## 4) Key Results - M7.E1.2

### Blocker Separation Evidence

| Metric | E1.1 (pre-fix) | E1.2 (post-fix) | Interpretation |
|--------|----------------|------------------|----------------|
| `blocker_class` | `event_source_absence` | **`gas_economics_only`** | E1.1 was FALSE — Arbitrum contamination |
| `families_with_any_hot_events` | 0 | **9/17** | Events reach bridge families |
| `exact_pool_trace.pool_address` | `0xd13040...` (Arbitrum) | **`0x6f79e0...`** (Base) | Contamination eliminated |
| `exact_family_trace.family` | `family_unresolved` | **resolved** | PTT lookup works on Base |
| `events_in_bridge_total` | N/A | **12** | NEW counter |
| `matched_then_gas_rejected_total` | N/A | **12** (all) | All bridge-matching events gas-killed |
| `matched_then_scored_positive_total` | N/A | **0** | Zero make it through gas |
| hot rollup written? | NO | **YES** | `stage_a_ms` fix |

### Root Causes Found

1. **Hardcoded Arbitrum pool** (`_TARGET_POOL = 0xd13040...`): All trace diagnostics chain-foreign on Base. `exact_pool_trace` always `not_in_bridge`. `exact_family_trace` always `family_unresolved`. `families_with_any_hot_events` checked only the unresolved family → 0 → false `event_source_absence`.
2. **`stage_a_ms` KeyError**: `mode_ws_live.py` used `dict["stage_a_ms"]` instead of `.get()`. When live results lacked the key, every hot iteration crashed — caught by outer try/except, loop retried but never reached `_update_hot_rollup()`. Supervisor showed 3/3 alive (process didn't exit).
3. **Single-family event check**: Old code checked events only at the target family. On Base with dynamic families, most events hit different families. New code checks ALL bridge families cumulatively.

## 5) Strategic Reading

1. **E1.2 goal REACHED**: Base hot lane is cleanly proven gas_economics_only. Arbitrum contamination eliminated. Hot rollup now reliably written.
2. **Both lanes converge**: Cold lane (E1.1): 26/30 GAS_EXCEEDS_GROSS. Hot lane (E1.2): 12/12 bridge-matching events gas-rejected. Same blocker, independently proven.
3. **Gas frontier unchanged at -2.20 bps**: The blocker is economic, not architectural. L1 data cost (80%) remains the target for optimization.
4. **Hot lane infrastructure now reliable**: `stage_a_ms` fix + dynamic target pool + three-way blocker classification means future Base runs produce accurate chain-native diagnostics.
5. **Next logical step**: Gas economics optimization (Flashblocks for sub-block delivery, L1 data cost reduction, gas_floor_bps tuning) — not architecture changes.

## 5.1) Contract Checks
status/reasons consistency: OK (REACHED with gas_economics — 12/12 bridge-matching events gas-rejected, blocker_class=gas_economics_only)
rolling discipline: OK (m7_hot_rollup_latest.json updated at 21:41:43Z, no new artifact files, all M7 artifacts Base-origin)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
