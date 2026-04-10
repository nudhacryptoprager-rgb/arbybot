# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: ONLINE (M7.E1.10 -- discovery contour cleanup + 20m A/B cadence)
artifact_mode: rolling
config: config/onboard_base_discovery.yaml
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.E1.10 contour cleanup -- AMONGUS removed, structurally stronger pairs prioritized, hot fallback profile-aware, config contract + cross_dex policy tests

## Session Completion
session_goal: M7.E1.10 contour cleanup -- fix discovery config issues (dead AMONGUS slot, weak cross_dex contour, production-style hot fallback) per reviewer f5c8faa7, then run 20m A/B pair with cleaned contour.
goal_status: REACHED (contour cleaned, 7 new tests, 20m production 18:42-19:02Z + 20m discovery 19:03-19:23Z, both 0 events. Discovery hot correctly uses clean seed list. Per reviewer step 1: both empty + contour was the open question = no further runs justified this session.)
close_allowed: true
remaining_blockers: (1) market-window scarcity still active at 20m resolution post-contour-cleanup. (2) Per reviewer step 9: if next 20m A/B also zero after cleanup, return to code/config review.
evidence_session_run_dirs: [data/runs/_rolling/ -- 20m production 18:42-19:02Z + 20m discovery 19:03-19:23Z]
primary_blocker_of_session: discovery_contour_quality
blocker_status_before: ACTIVE (AMONGUS dead slot, weak cross_dex, production-style hot fallback)
blocker_status_after: RESOLVED (all 7 reviewer fixes applied, tested, CI green)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.10 = discovery contour cleanup per reviewer f5c8faa7 steps 2-7, then 20m A/B
change_summary:
  - config/onboard_base_discovery.yaml: Removed AMONGUS/WETH dead slot, reordered pairs (structurally stronger first, meme diagnostic_only)
  - m7/shared/constants.py: PREWARM_PAIRS_BASE_DISCOVERY updated to match (AMONGUS removed, new order)
  - scripts/m7a_orderflow_loop.py: _write_hot_artifact now accepts profile param, fallback uses get_prewarm_pairs(chain, profile) instead of HOT_WATCHLIST_PAIRS
  - tests/unit/test_e1_9_discovery_lane.py: 7 new tests (3 config contract, 2 cross_dex policy, 2 hot fallback profile-aware)
  - 20m production proof-run (18:42-19:02Z, 3/3 alive, 0 restarts, 0 events)
  - 20m discovery proof-run (19:03-19:23Z, 3/3 alive, 0 restarts, 0 events)
touched_files:
  - config/onboard_base_discovery.yaml
  - m7/shared/constants.py
  - scripts/m7a_orderflow_loop.py
  - tests/unit/test_e1_9_discovery_lane.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_e1_9_discovery_lane.py -v: PASS (41 passed, 0.69s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED, 3838 passed, 6 skipped, 101.66s)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.34 --chain base --m7-profile production --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (18:42-19:02Z, 3/3 alive, 0 restarts)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.34 --chain base --m7-profile discovery --no-m4 --dashboard-port 8100 --m7-hot-pause 1 --m7-cold-pause 5: PASS (19:03-19:23Z, 3/3 alive, 0 restarts)

## 3) Artifacts Attached

rolling:
  - data/runs/_rolling/m7_hot_latest.json (production, ts: 19:02:55Z)
  - data/runs/_rolling/m7_hot_latest_discovery.json (discovery, ts: 19:23:53Z)
  - data/runs/_rolling/m7_hot_rollup_latest.json (production, events_total: 290 cumulative)
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json (discovery, events_total: 0)
  - data/runs/_rolling/m7_orderflow_latest.json (production cold, snapshot_preserved)
  - data/runs/_rolling/m7_orderflow_latest_discovery.json (discovery cold, snapshot_preserved)

## 4) Key Results

### 4.1) Contour Cleanup (reviewer f5c8faa7, steps 2-7)

| Step | Fix | Evidence |
|------|-----|----------|
| #2 | Remove AMONGUS/WETH (not in core_tokens.yaml) | Removed from config + PREWARM_PAIRS. Config contract test PASS |
| #3 | Mark meme families as diagnostic_only | DEGEN/BRETT/TOSHI (cross_dex_expected=1) after structurally stronger pairs. Cross_dex policy test PASS |
| #4 | Prioritize structurally stronger pairs | AERO/USDC, AERO/WETH, cbBTC/USDC, cbBTC/WETH now before meme families |
| #5 | Hot fallback promoted_watchlist profile-aware | _write_hot_artifact(profile=) uses get_prewarm_pairs(chain, profile). Signature + source test PASS |
| #6 | Config contract test | 3 tests: discovery tokens in core_tokens, prewarm tokens in core_tokens, production tokens valid |
| #7 | Cross-dex policy test | 2 tests: low cross_dex documented as diagnostic, structurally strong pairs present |

### 4.2) 20m A/B Proof-Run (April 10, 18:42-19:23 UTC -- post-contour-cleanup)

| Metric | Production (20m) | Discovery (20m) |
|--------|------------------|------------------|
| Run window | 18:42-19:02Z | 19:03-19:23Z |
| Supervisor | 3/3 alive, 0 restarts | 3/3 alive, 0 restarts |
| Session events | 0 | 0 |
| Hot watchlist source | promoted (cold-derived) | seed_only (clean contour) |
| Hot watchlist has AMONGUS | yes (old promoted data) | NO (correctly removed) |
| signal_counts present | true | true |
| snapshot_preserved | true | true |
| Namespace isolation | confirmed | confirmed |

**Discovery hot fallback confirmed clean**: seed list = [USDC/DAI, USDC/USDT, WETH/USDC, AERO/USDC, AERO/WETH, cbBTC/USDC, cbBTC/WETH, DEGEN/WETH, BRETT/WETH, TOSHI/WETH] -- no AMONGUS, structurally stronger pairs first.

### 4.3) Test Results

- 3838 passed, 6 skipped (up from 3831 in prior E1.10 session, +7 new tests)
- New tests: TestE110ConfigContract (3), TestE110CrossDexPolicy (2), TestE110HotFallbackProfileAware (2)

## 5) Strategic Reading

1. **Contour cleanup resolves reviewer's primary concern**: discovery config was structurally weak (dead AMONGUS slot, no core_tokens enforcement, production-style hot fallback). All 7 fixes applied and tested.
2. **Post-cleanup 20m A/B still zero**: market-window scarcity persists after contour cleanup. This confirms scarcity is market-driven, not contour-driven.
3. **Per reviewer step 1 cadence rule**: 20m production + 20m discovery executed. Both empty + contour cleanup was the open question. No further runs justified this session.
4. **Per reviewer step 9**: if next session's 20m A/B also zero, return to code/config review (not more runs). If 2-3 sessions still zero, then modest discovery expansion or OP Mainnet comparative pilot (step 10).
5. **Discovery hot fallback fix immediately visible**: discovery seed list now correctly shows clean contour without AMONGUS, with structurally stronger pairs (AERO, cbBTC) before diagnostic meme families.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (production canonical, discovery _discovery namespace)
runtime artifacts not committed: OK
docs_reread_confirmed: true

## 6) Blocker Classification

code_blocker: NONE (contour cleanup RESOLVED this session)
infra_blocker: NONE
market_window_scarcity: CONFIRMED (post-cleanup 20m A/B still 0 events at 18:42-19:23Z)

## 6.1) Blockers / Risks
- **market_window_scarcity** (CONFIRMED): 0 events across 20m production + 20m discovery post-contour-cleanup. Total evidence now: E1.9.2 (9 short runs, 0), E1.10 prior (2 x 1h, 0), E1.10 post-cleanup (2 x 20m, 0).
- Discovery scoreboard still empty (0 families -- needs events to populate)
- Per reviewer step 9: if next 20m A/B also zero, work returns to code/config review
- Per reviewer step 10: if 2-3 sessions fail, modest discovery expansion or OP Mainnet pilot
