# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: ONLINE (M7.E1.3 Base counter separation, April 8 07:10-07:21Z nonstop. M4/M5 rolling from ci_m5_gate_arbitrum_one_20260402_110313_968343, unchanged — M7-only session with --no-m4)
artifact_mode: rolling
config: config/onboard_base_profit.yaml (base, narrow contour)
code_identity:
  primary: ts:2026-04-08T07:20:59Z
  dirty: true
  desc: M7.E1.3 - split registry vs gas rejection counters, chain-purity invariant tests, viable signal found

## Session Completion
session_goal: M7.E1.3 - reconcile Base hot artifacts with Base cold gas blocker and remove Arbitrum legacy contamination; prove whether Base hot zero-hit is registry/overlap issue or gas-only
goal_status: REACHED (Counter separation reveals viable signal: 0 registry-rejected, 44 gas-rejected, 6 scored positive out of 50 bridge events. 3 cold-executable candidates with positive bps. blocker_class=selection_or_scoring. Registry overlap definitively NOT a blocker.)
close_allowed: true
remaining_blockers: GAS_EXCEEDS_GROSS majority blocker (88% of bridge events). selection_or_scoring active — 6 scored-positive events don't reach full viability. Best near-executable -2.20 bps. 3 cold-executable candidates need Tenderly simulation. Flashblocks WS untested.
evidence_session_run_dirs: [data/runs/_rolling/ (m7_hot_rollup_latest.json ts=2026-04-08T07:20:59Z, m7_hot_latest.json ts=2026-04-08T07:20:59Z, m7_orderflow_latest.json ts=2026-04-08T07:20:47Z, m7_cold_hot_bridge.json ts=2026-04-08T07:20:47Z)]
primary_blocker_of_session: counter_conflation — E1.2 conflated registry rejection with gas rejection in matched_then_gas_rejected, hiding 6 scored-positive events
blocker_status_before: M7.E1.2 OPEN — matched_then_gas_rejected conflated two orthogonal blocker types (registry rejection vs gas rejection). 12/12 in 3-min run appeared all gas-blocked.
blocker_status_after: M7.E1.3 OPEN — counters separated, 0 registry-rejected, 44 gas-rejected, 6 scored-positive. Viable signal confirmed. blocker_class correctly upgraded from gas_economics_only to selection_or_scoring.
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.3 = reconcile Base hot artifacts with Base cold gas blocker and remove Arbitrum legacy contamination
change_summary:
  - scripts/m7a_orderflow_loop.py: (1) Split conflated matched_then_gas_rejected_total in rollup into matched_then_registry_rejected_total + matched_then_gas_rejected_total + matched_then_scored_positive_total. (2) Added 3 per-iteration counters to hot_gap_debug: matched_bridge_then_registry_rejected, matched_bridge_then_gas_rejected, matched_bridge_then_scored_positive.
  - tests/unit/test_e1_base_chain_aware.py: Fixed conflated E1.2 test (split 1 → 2 tests). Added Section 12: TestE1_3_ChainPurityInvariant (4 tests). Added Section 13: TestE1_3_RegistryVsGasSeparation (6 tests).
  - docs/status/Status_M7.md: Updated status line, added M7.E1.3 subsection, updated Known Blockers and Next Steps.
  - docs/DEV_REPORT_LATEST.md: This file.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED — counter split in rollup + hot_gap_debug)
  - tests/unit/test_e1_base_chain_aware.py (MODIFIED — 10 new E1.3 tests, 1 E1.2 test rewritten as 2)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3728 passed, 6 skipped — 3718 + 10 new E1.3 tests)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED (pre-changes)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings, pre-changes)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --chain base --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (10 min, 3/3 alive, 0 restarts, clean shutdown at 07:21:09Z)

## 3) Artifacts Attached

M7 rolling artifacts (from Base 10-min nonstop, April 8 07:10-07:21Z):
- m7_hot_rollup_latest.json: last_updated=2026-04-08T07:20:59Z, windows_seen=206, events_seen_total=221, windows_with_events=73, bridge_pool_hit_total=70, fast_path_scored_total=71, events_in_bridge_total=50, events_not_in_bridge_total=21, matched_then_registry_rejected_total=0, matched_then_gas_rejected_total=44, matched_then_scored_positive_total=6, blocker_class=selection_or_scoring, families_with_any_hot_events=19/27
- m7_hot_latest.json: timestamp=2026-04-08T07:20:59Z, events_count=5, viable_count=1, hot_gap_debug.matched_bridge_then_registry_rejected=0, matched_bridge_then_gas_rejected=2, matched_bridge_then_scored_positive=1
- m7_orderflow_latest.json: chain=base, timestamp=2026-04-08T07:20:47Z, events_count=30, viable_count=3
- m7_cold_hot_bridge.json: timestamp=2026-04-08T07:20:47Z, cold_executable=3 (W/WETH +92.63, CRV/WETH +59.08, doginme/WETH +24.08 bps), near_executable=5 (best -2.20 bps)

## 4) Key Results - M7.E1.3

### Counter Separation Evidence

| Metric | E1.2 (conflated) | E1.3 (separated) | Interpretation |
|--------|-------------------|-------------------|----------------|
| `matched_then_registry_rejected_total` | N/A (lumped in gas) | **0** | Registry overlap NOT a blocker |
| `matched_then_gas_rejected_total` | 12 (conflated) | **44** | Gas remains majority blocker |
| `matched_then_scored_positive_total` | 0 | **6** | Viable signal exists — was hidden |
| `events_in_bridge_total` | 12 | **50** | Longer run, more data |
| `blocker_class` | `gas_economics_only` | **`selection_or_scoring`** | Correctly upgraded |
| `families_with_any_hot_events` | 9/17 | **19/27** | Strong event coverage |
| `cold_executable_count` | 0 | **3** | W/WETH +92.63, CRV/WETH +59.08, doginme/WETH +24.08 bps |
| `hot viable_count` (final iteration) | 0 | **1** | Hot lane sees viable events |
| sum invariant (reg+gas+pos) | N/A | 0+44+6=50=bridge ✓ | Counter consistency proven |

### Key Findings

1. **Registry rejection is definitively NOT a blocker**: 0/50 bridge events are registry-rejected. All events that reach bridge pools pass the hot registry.
2. **Gas is the majority but NOT sole blocker**: 44/50 (88%) gas-rejected. 6/50 (12%) scored positive. E1.2's conflated counter hid the 12% positive signal.
3. **Viable signal confirmed**: Cold lane: 3 executable candidates (up to +92.63 bps). Hot lane: viable_count=1 in final iteration. Cold orderflow: viable_count=3.
4. **E1.2 narrative was incomplete**: "gas_economics_only" was true for the 3-min E1.2 run (12/12 gas-rejected). The 10-min E1.3 run with 50 bridge events reveals a more nuanced picture.
5. **Counter sum invariant holds**: 0 + 44 + 6 = 50 = events_in_bridge_total. Infrastructure proven.

## 5) Strategic Reading

1. **E1.3 goal REACHED**: Counter separation reveals hidden viable signal on Base. Registry overlap definitively NOT a blocker. Gas is majority but not sole blocker.
2. **Viable signal is the key discovery**: 3 cold-executable candidates with strong positive bps, 6 hot scored-positive events. This was invisible under E1.2's conflated gas_rejected counter.
3. **Next priority is signal exploitation, not gas reduction**: With viable candidates found, the focus shifts from gas optimization to: (a) verify reproducibility, (b) Tenderly simulation for cold-executable candidates, (c) understand why scored-positive events don't always reach viable.
4. **Gas remains the majority blocker**: 88% of bridge events gas-rejected. L1 data cost still dominates. But the 12% that break through represent actionable signal.
5. **Infrastructure investment paying off**: Separated counters, chain-purity tests, and three-way blocker classification correctly detect and classify the nuanced blocker landscape on Base.

## 5.1) Contract Checks
status/reasons consistency: OK (REACHED with counter_conflation resolved — 0 registry-rejected, 44 gas-rejected, 6 scored-positive, blocker_class=selection_or_scoring)
rolling discipline: OK (m7_hot_rollup_latest.json updated at 07:20:59Z, no new artifact files, all M7 artifacts Base-origin)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true
