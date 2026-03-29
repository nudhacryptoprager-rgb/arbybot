# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: ci_m5_gate_arbitrum_one_20260327_222948_123275
mode: OFFLINE + INTENT_SCOUT
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow_7 universe, orderflow replay, intent surface scout
code_identity:
  primary: ts:2026-03-27T21:30:14Z
  dirty: false
  desc: M7.A.4 orderflow-driven backrun/replay hypothesis

## Session Completion
session_goal: Implement M7.A.4 orderflow-driven backrun/replay hypothesis — shift from static AMM triangular scanning to event-driven orderflow replay and intent/auction surface scouting.
goal_status: REACHED
close_allowed: true
remaining_blockers: none
evidence_session_run_dirs:
  - data/tmp/m7a_orderflow_offline.json (5 fixture events, offline replay)
  - data/tmp/m7a_intent_scout.json (4 surface assessments)
primary_blocker_of_session: M7.A.4 orderflow pipeline not yet implemented
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.4 — orderflow-driven backrun/replay hypothesis. Edge may emerge from event-driven orderflow replay and auction/intent surfaces rather than static AMM triangular state.
change_summary:
  - Created scripts/m7a_orderflow_replay.py (~600 lines): full event-driven replay pipeline
  - OrderflowEvent (15 fields), BackrunResult (17 fields), IntentSurfaceAssessment (16 fields)
  - 5 canonical fixture events covering different tokens/sizes/impacts/DEXes
  - Event classification: classify_event_backrun_type() (impact-based), classify_event_viability() (size/impact gates)
  - Offline scoring: estimate_backrun_gross_bps() (capture_rate * competition_decay), gas/fee estimation
  - Online scoring: live RPC quotes across known DEXes using existing adapter infrastructure
  - Intent scout: 4 surface assessments (MEV-Share, UniswapX, CoW, block event backrun)
  - CLI: --offline, --replay <file>, --online, --intent-scout (mutually exclusive)
  - 58 new contract tests in tests/unit/test_orderflow_contracts.py
  - Total test count: 2794 passed, 6 skipped, 0 failures (+58 new)
touched_files:
  - scripts/m7a_orderflow_replay.py (NEW)
  - tests/unit/test_orderflow_contracts.py (NEW)
  - docs/status/Status_M7.md (updated with M7.A.4 section)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 scripts/m7a_orderflow_replay.py --offline --output data/tmp/m7a_orderflow_offline.json: PASS (5 events, 0 viable, best_net=-1.5537 bps)
py -3.11 scripts/m7a_orderflow_replay.py --intent-scout --output data/tmp/m7a_intent_scout.json: PASS (4 surfaces, best_near_term=block_event_backrun)
py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -v --tb=short: PASS (58 passed in 0.43s)
py -3.11 -m pytest tests/unit -q: PASS (2794 passed, 6 skipped)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/ci_docs_consistency.py --verbose: PASS (all docs consistent)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all 7 gates green)

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_orderflow_offline.json (5 fixture events, offline replay, best_net=-1.5537 bps)
  - data/tmp/m7a_intent_scout.json (4 surface assessments, best_near_term=block_event_backrun)

prior session artifacts (still valid, not overwritten):
  - data/tmp/m7a_verdict.json (narrow_7, 4-block verdict from M7.A)
  - data/tmp/m7a_expanded_verdict.json (expanded_10, 3-block verdict from M7.A.2)
  - data/tmp/m7a_regime_repeatability.json (M7.A.3 regime aggregation)

rolling (unchanged):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.4 Orderflow-Driven Backrun/Replay

### New Infrastructure

| Component | Description |
|-----------|-------------|
| `scripts/m7a_orderflow_replay.py` | Event-driven replay pipeline (~600 lines) |
| `OrderflowEvent` | 15-field event model (event_id, type, chain, block, tokens, amounts, dex, pool, impact) |
| `BackrunResult` | 17-field backrun scoring output (net_bps, reject_reason, viable, candidate_path) |
| `IntentSurfaceAssessment` | 16-field feasibility assessment (surface_type, feasibility_score, execution_model) |
| 5 fixture events | USDC→WETH, WETH→USDC, ARB→USDC, WBTC→USDC, USDT→USDC on arbitrum_one |
| 7 reject reasons | BELOW_MIN_SIZE, BELOW_MIN_IMPACT, SLIPPAGE_EXCEEDS_GROSS, GAS_EXCEEDS_GROSS, FEE_EXCEEDS_NET, ROUTE_NOT_VIABLE, NO_COUNTER_VENUE |
| 4 intent surfaces | mev_share_backrun, uniswapx_filler, cow_solver, block_event_backrun |

### Offline Replay Evidence (5 fixture events)

| Metric | Value |
|--------|-------|
| Events scored | 5 |
| Viable count | 0 |
| Best net (bps) | **-1.5537** |
| Worst net (bps) | -7.55 |
| Mean net (bps) | -4.37 |
| Reject: SLIPPAGE_EXCEEDS_GROSS | 4 |
| Reject: GAS_EXCEEDS_GROSS | 1 |
| beats_triangular_baseline (-14.16 bps) | **true** |
| beats_two_leg_baseline (-3.5062 bps) | **false** |

### Intent/Auction Surface Scout

| Surface | Feasibility | Key advantage | Key risk |
|---------|-------------|---------------|----------|
| MEV-Share backrun | medium | Structured API, proven economics | High competition |
| UniswapX filler | medium | Intent-based, Dutch auction | Private inventory needed |
| CoW solver | low | Batch optimization | Complex competition |
| Block event backrun | **high** | Reuses existing adapters | Block event parsing needed |

### New Tests Added (58 contract tests)

| Class | Tests | What it locks |
|-------|-------|--------------|
| TestOrderflowEventSchema | 6 | Schema validity, field types, canonical event types |
| TestBackrunResultSchema | 3 | Defaults, artifact fields, reject reasons |
| TestIntentSurfaceSchema | 3 | Surface count, canonical surfaces, assessment keys |
| TestFixtureEvents | 9 | Count, types, chains, unique IDs, positive amounts |
| TestEventClassification | 7 | High/low impact, boundary, viability rejections |
| TestBackrunScoring | 11 | Gross/gas proportionality, offline rejection, net calculation |
| TestIntentScout | 7 | Assessment count, surfaces, feasibility scores |
| TestReplayArtifactSchema | 8 | Hypothesis field, baselines, reject histogram, JSON serializable |
| TestBackwardCompatibility | 4 | M7.A imports, two-leg/triangular baselines |

## 5) Strategic Reading

M7.A.4 shifts the search from passive triangular pool-state scanning to event-driven orderflow surfaces. Key findings:

1. **Offline backrun estimates are better than triangular**: Best net -1.55 bps (orderflow) vs -14.16 bps (triangular). The event-driven frame produces estimates closer to two-leg baseline (-3.51 bps) even with conservative default capture_rate (0.3) and competition_decay (0.5).

2. **Still does not beat two-leg baseline offline**: The theoretical offline estimates are inherently conservative — real backrun profitability depends on live event timing, MEV competition dynamics, and same-block execution probability, none testable offline.

3. **Block event backrun is highest-feasibility next surface**: It reuses existing arbitrum_one adapter infrastructure, requires only block event parsing and post-event quoting—no new chain, capital, or protocol integration. This is the logical next step if M7.A continues.

4. **MEV-Share and UniswapX have medium feasibility**: Both require external protocol integration (Flashbots API, UniswapX RFQ system) but have proven economics in production. CoW is lowest feasibility due to complex solver competition.

**M7.A.4 is a closed bounded baseline** for offline-estimated event-driven backrun replay. The intent scout maps the orderflow/auction surface landscape and identifies the highest-ROI path forward.

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
| M7.B | NOT STARTED (closed by M7.A–M7.A.4 verdicts) |
