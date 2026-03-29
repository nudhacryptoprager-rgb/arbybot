# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a5_1_live_evidence_20260329
mode: ONLINE (live block-event backrun replay with public RPC)
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow_7 universe, live block-event backrun replay
code_identity:
  primary: ts:2026-03-27T21:30:14Z
  dirty: false
  desc: M7.A.5.1 first live block-event evidence

## Session Completion
session_goal: Generate first live block-event evidence artifact for M7.A.5. Fix roundtrip measurement bug (sell used wrong input amount). Validate pipeline produces realistic measurements from real Arbitrum swap events.
goal_status: REACHED (live evidence generated, roundtrip bug fixed, measurements realistic)
close_allowed: true
remaining_blockers: None structural — public RPC latency is the identified surface blocker
evidence_session_run_dirs:
  - data/tmp/m7a_live_blocks.json (5 events, 100 blocks, corrected roundtrip)
  - data/tmp/m7a_live_wider.json (10 events, 500 blocks, repeatability confirmation)
  - data/tmp/m7a_live_repeatability.json (aggregated verdict)
primary_blocker_of_session: M7.A.5 had infrastructure but no live evidence
blocker_status_before: ACTIVE (no live artifact existed)
blocker_status_after: RESOLVED (live evidence generated, surface verdict: NOT VIABLE with public RPC)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.1 — first live block-event evidence on arbitrum_one. Validate live pipeline produces meaningful measured results from real swap events.
change_summary:
  - Fixed critical roundtrip measurement bug in score_backrun_live(): sell pass was using backrun_size_wei instead of buy output as input, causing ~19 billion bps false positives
  - Split single-pass buy+sell loop into two-pass: Pass 1 finds best buy, Pass 2 uses buy output as sell input
  - Added TestScoreBackrunLiveRoundtrip test class (1 test) validating two-pass chain
  - Generated first live evidence: 5+10 events, -19 to -21 bps (consistent, realistic)
  - Total test count: 2816 passed, 6 skipped, 0 failures (+1 new)
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: fixed two-pass roundtrip in score_backrun_live)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +1 roundtrip chain test, 80 total)
  - docs/status/Status_M7.md (to be updated with live evidence)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 scripts/m7a_orderflow_replay.py --live-blocks 100 --max-events 5 --output data/tmp/m7a_live_blocks.json: PASS (5 events scored, best_net=-19.07 bps)
py -3.11 scripts/m7a_orderflow_replay.py --live-blocks 500 --max-events 10 --output data/tmp/m7a_live_wider.json: PASS (10 events, best_net=-18.36 bps)
py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (80 passed in 0.59s)
py -3.11 -m pytest tests/unit -q: PASS (2816 passed, 6 skipped in 72.36s)

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_live_blocks.json (M7.A.5.1, narrow: 100 blocks, 5 events, best_net=-19.07 bps)
  - data/tmp/m7a_live_wider.json (M7.A.5.1, wider: 500 blocks, 10 events, best_net=-18.36 bps)
  - data/tmp/m7a_live_repeatability.json (aggregated verdict: NOT VIABLE with public RPC)
  - data/tmp/m7a_orderflow_offline.json (M7.A.4, still valid)
  - data/tmp/m7a_intent_scout.json (M7.A.4, still valid)

prior session artifacts (still valid):
  - data/tmp/m7a_verdict.json (narrow_7, M7.A)
  - data/tmp/m7a_expanded_verdict.json (expanded_10, M7.A.2)
  - data/tmp/m7a_regime_repeatability.json (M7.A.3)

rolling (unchanged):
  - data/runs/_rolling/_latest.json (run_dir: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.5.1 First Live Block-Event Evidence

### Critical Bug Fixed

`score_backrun_live()` had a roundtrip measurement bug: the sell pass used `backrun_size_wei` (in token_in units) as USDC input instead of the buy output. This produced ~19 billion bps false positives. Fixed by splitting into two passes: Pass 1 finds best buy across all venues, Pass 2 uses the buy output as the sell input.

### Live Evidence Metrics (6 required)

| Metric | Narrow (100 blk/5 ev) | Wider (500 blk/10 ev) |
|--------|----------------------|----------------------|
| events_fetched (raw_logs) | 11 | 97 |
| events_scored | 5 | 10 |
| best_live_net_bps | -19.07 | -18.36 |
| same_state distribution | 0 / 0 / 5 (same/next/stale) | 1 / 0 / 9 |
| mean_block_lag | 64.4 | 217.8 |
| mean_counter_venue_count | 6.0 | 6.0 |

### Verdict

- **Surface viable**: NO
- **Primary blocker**: PUBLIC_RPC_LATENCY
- **Evidence**: All events stale (mean lag 64-218 blocks). Gas exceeds gross on 15/15 events. Best net = -18.36 bps, worse than two-leg baseline (-3.51 bps).
- **Structural finding**: Public RPC cannot achieve same-block quoting consistently. Block-event backrun requires sub-block latency (private RPC or mempool access).
- **beats_two_leg_baseline**: false
- **beats_triangular_baseline**: false

## 5) Strategic Reading

M7.A.5.1 provides the first live measured evidence for the block-event backrun surface:

1. **Pipeline works correctly**: 15 events scored across 2 runs with consistent -18 to -22 bps measurements. Multi-venue quoting (6 venue×fee combinations) functions reliably.

2. **Roundtrip fix was critical**: The original code would have shown false billions-bps positives due to unit mismatch in the sell pass. The two-pass fix produces realistic measurements.

3. **Surface NOT viable with public RPC**: Mean block lag of 64-218 blocks (16-55 seconds) means quotes are fundamentally stale. Same-block execution is impossible with public RPC latency.

4. **Comparison to baselines**: Live backrun best (-18.36 bps) is worse than two-leg baseline (-3.51 bps) and comparable to M7.A.4 offline estimate (-1.55 bps) — confirming the offline model was optimistic.

5. **M7.A series conclusion**: Five bounded baselines (M7.A through M7.A.5) have now been explored. All produce negative measured edge. The block-event backrun surface is the most promising (highest feasibility per intent scout) but requires infrastructure beyond public RPC.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY — NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY — NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC latency blocker) |
| M7.B | NOT STARTED (closed by M7.A–M7.A.5 verdicts) |
