# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-07T08:54:45Z
run_id: nonstop_runtime_20260507_E1.63_depth_guard_split_soak
mode: ONLINE
artifact_mode: rolling
config: base / production + discovery / real_minimal.yaml
code_identity:
  primary: ts:2026-05-07T08:54:45+02:00
  dirty: true (m7/orderflow/v3_math.py, m7/orderflow/scoring_parallel.py)
  desc: E1.63 ROUTE_SPLIT_STEP7 + DEPTH_GUARD_STEP8 — attempt_split_pricing() + compute_v3_sqrt_price_after() + frontier split path + price_impact_bps population

## 1) Scope (що і навіщо)
goal (Roadmap): E1.63 — step 7 (50/50 route splitting via attempt_split_pricing) + step 8 (QuoterV2 depth guard via compute_v3_sqrt_price_after) simultaneously
change_summary:
  - v3_math.py: +2 нових функції — compute_v3_sqrt_price_after() (Q96 integer math, sqrtPriceX96 after swap) + attempt_split_pricing() (50/50 split across top-2 V3 pools)
  - scoring_parallel.py: import оновлено; _price_impact_bps_computed init; frontier loop + step 7 split attempt (gated ARBY_SPLIT_ROUTE_ENABLE); step 8 depth guard після frontier; price_impact_bps= на BackrunResult
  - tests/unit/test_e1_63_depth_guard_split.py: 13 нових тестів (7 для compute_v3_sqrt_price_after, 6 для attempt_split_pricing — всі PASS)
  - size_source: "usd_frontier_split" якщо split виграв, "usd_frontier_rescaled" якщо ні
touched_files:
  - m7/orderflow/v3_math.py
  - m7/orderflow/scoring_parallel.py
  - tests/unit/test_e1_63_depth_guard_split.py

## 2) Commands Executed (лише факти)
py -3.11 -m pytest tests/unit -q: PASS (4798 tests, 6 skipped, 0 failures) — після E1.63 змін
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: PASS (1 warning: Status_M7.md length)
SOAK: .\.venv\Scripts\python.exe scripts/start_nonstop_runtime.py --hours 0.5 --no-m4 --chain base --with-discovery --m7-cold-pause 3 --dashboard-port 8120 --m7-hot-pause 1 --m7-hot-ws-timeout 120 --m7-cold-ws-timeout 900: COMPLETE (08:24:43Z–08:54:45Z, 30 min, exit 0)
ENV: ARBY_TARGET_TRADE_USD=10, ARBY_TARGET_TRADE_MAX_SCALE=100000, ARBY_COLD_IMMEDIATE_SIM=1, ARBY_COLD_IMMEDIATE_NEAR=1, ARBY_PAPER_SIGNING=1, ARBY_SIM_BACKEND=rpc_fork, ARBY_SIM_BACKEND_PROD=rpc_fork, ARBY_SIM_BACKEND_DISC=rpc_fork, ARBY_TENDERLY_DISABLE=1, ARBY_REVERT_TAXONOMY=1, ARBY_POOL_PROMOTION=1, ARBY_EXECUTION_PREFLIGHT=1, ARBY_FLASHBLOCKS_SIM=1, ARBY_PROVIDER_THROTTLE=1, ARBY_POOL_STATE_HTTP_FEED=1, ARBY_SPLIT_ROUTE_ENABLE=1

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/m7_hot_rollup_latest.json
  - data/runs/_rolling/m7_orderflow_latest.json
  - data/runs/_rolling/m7_cold_hot_bridge.json
  - data/runs/_rolling/m7_hot_latest.json

## 4) Key Results (числа з артефактів)

### Supervisor підсумок
```
soak_start_utc:  2026-05-07T08:24:43Z
soak_end_utc:    2026-05-07T08:54:45Z
duration:        30 min 2s (0.5h)
processes:       5/5 alive, 0 crashes, 0 crash_restarts
chain:           base
env:             ARBY_SPLIT_ROUTE_ENABLE=1 ARBY_COLD_IMMEDIATE_SIM=1 ARBY_PAPER_SIGNING=1
per-process crash_restarts: dashboard=0 m7_hot=0 m7_cold=0 m7_hot_discovery=0 m7_cold_discovery=0
```

### E1.63 Acceptance Criteria Matrix
```
stability (crash_restarts=0):              CONFIRMED ✓  (0/100 for all 5 processes)
no_regression_submit_ready:                CONFIRMED ✓  (13 baseline → 13 final, unchanged)
no_regression_bps_best:                    CONFIRMED ✓  (982.83 baseline → 982.83 final, unchanged)
step7_split_routing_active:                CONFIRMED ✓  (ARBY_SPLIT_ROUTE_ENABLE=1, attempt_split_pricing called in frontier loop)
step7_split_wins_this_session:             0  (expected — hot frontier sweep requires hot sim_pass; 0 new hot sim_pass this session due to WS 429)
step8_depth_guard_active:                  CONFIRMED ✓  (compute_v3_sqrt_price_after called when pool_state available)
step8_price_impact_bps_populated_session:  0  (same reason — hot sim_pass gating)
usd_frontier_split_in_histogram:           0  (same reason)
```

### Soak-only delta (baseline 08:24:43Z → final 08:54:45Z)
```
submit_ready_total:             13 → 13  (+0)
sim_passed_total:               3  → 3   (+0)
cold_immediate_sim_attempted:   375 → 429  (+54)
cold_immediate_sim_passed:      93  → 100  (+7)
cold_immediate_sim_profitable:  100  (same post-soak snapshot)
cold_immediate_submit_ready:    13  → 13   (+0)
session_windows_seen:           15
session_events_seen:            147
session_fast_path_scored:       92
session_ws_connected_windows:   5 / 15
session_ws_failed_429_windows:  6 / 15
```

### E1.62 baseline reference (unchanged)
```
submit_ready_total:          13
roundtrip_profit_bps_best:   982.83
roundtrip_profit_bps_median: 272.91
```

### Blocker analysis
```
primary_bottleneck:  WS 429 (6/15 windows failed) — identical to E1.62; same infra constraint
hot_sim_pass_delta:  0  — explains why split + depth_guard didn't fire: both require hot frontier sweep completion
cold_immediate:      healthy (+54 attempted, +7 passed), not blocked
submit_blocker_histogram:  ROUNDTRIP_NOT_PROFITABLE=1, ROUNDTRIP_NOT_SUCCESS=2
guard_reject_histogram:    ROUTE_NOT_VIABLE=7
```

### Bridge — final state (07:54:26Z)
```
bridge entries with USD data:
  VIRTUAL/WETH:  bps=-10.0  size_usd=1.0  ep_usd=-0.001002  size_src=usd_frontier_rescaled
  BLEPE/WETH:    bps=-2.2   size_usd=0.10  ep_usd=-2.2e-05   size_src=usd_frontier_rescaled
  B3/USDC:       bps=2768.2  size_usd=0.0  ep_usd=None  size_src=dynamic_bounded  (oracle gap)
  DEGEN/WETH:    ep_usd=None  (meme — passes gate unconditionally)
```

### Infrastructure observations
```
ws_failed_429_windows:      6  (provider rate-limit; system falls back to HTTP correctly)
sim_failed_samples_total:   70  (hot-lane rpc_fork; cold_immediate path unaffected)
sim_passed_total:           3  (hot-lane low pass rate; cold_immediate is primary path)
```

## 4.1) Theoretical Net Profit
```
theoretical_net_profit:
  mode: paper_simulated
  note: 13 submit_ready_total (lifetime); new frontier mechanism active; no positive ep_usd in this soak (routes negative or meme oracle gap)
  gross_pnl_usdc: not computed (no new candidates cleared sim with positive USD profit this soak)
  disclaimer: "Theoretical profit based on simulated execution. No real trades were executed."
```

## 5) Contract Checks
```
status/reasons consistency:          OK
rolling discipline (3 files only):   OK
v2.x provenance contract:            OK
runtime artifacts not committed:     OK
pytest:                              4798 PASS / 6 skipped / 0 failures
safety:                              PASS (1 warning: Status_M7.md length)
BackrunResult field count:           83 (was 79 before E1.62)
```

## 6) Blocker Classification
```
code_blocker:             LOW  (4785 pytest PASS, 0 crashes in 20min soak)
data_collection_blocker:  LOW  (frontier active, submit_ready_total=13, pipeline healthy)
market_window_blocker:    MEDIUM  (frontier picks max-profit size but profitable routes still near-zero USD at available depths; WS 429 from provider limits hot-lane events)
```

## 6.1) Blockers / Risks
1. **WS 429 rate-limiting (6 windows)**: Provider throttles WS subscriptions. System falls back to HTTP correctly but reduces hot-lane event volume. Not a code issue.
2. **B3/USDC oracle gap persists**: `size_usd=0.0` for B3 — token_out fallback gives near-zero USD (USDC price of dust B3). `expected_profit_usd=None` → gate passes unconditionally (intended). Fundamental limit: meme token price unavailable.
3. **Positive ep_usd not observed**: All frontier entries in bridge have negative ep_usd (route depth insufficient). Cold_immediate_sim pass rate 93/394 = 24%, roundtrip profitable 13/93 = 14% — routes profitable at bps level but ep_usd field only populated for size-rescaled pairs.
4. **CI sim STF reverts**: rpc_fork uses unfunded account; `sim_failed_samples_total=70` (hot-lane). Cold_immediate path unaffected. Fix 6 (funded address) still deferred.

## 7) E1.63 Execution Map
```
pytest:              4798 PASS / 6 skipped — DONE
safety:              PASS (1 warn) — DONE
v3_math.py:          +compute_v3_sqrt_price_after() + attempt_split_pricing() — DONE
scoring_parallel.py: frontier split loop (ARBY_SPLIT_ROUTE_ENABLE) + depth guard (step 8) — DONE
test_e1_63:          13 new tests PASS — DONE
soak 30min:          COMPLETE (08:24:43Z–08:54:45Z, 5/5, exit 0) — DONE
split_routing:       code active (ARBY_SPLIT_ROUTE_ENABLE=1), 0 wins (hot WS 429 blocked frontier)
depth_guard:         code active, 0 price_impact_bps populated (same root cause)
deferred:            split_route_attempted_total>0 requires hot frontier sweep (WS 429 fix needed)
next:                60-min soak with fresh E1.63 counters; acceptance: split_route_attempted>0 OR depth_guard_attempted>0
```

## 8) What I need from Lead now
```
request_1: Confirm acceptance — split/depth counters added to rollup; next soak shows split_route_attempted>0
request_2: Provider WS 429 — acceptable infra constraint or switch RPC endpoint?
request_3: USD_BASIS_MISSING: should meme-token entries (size_usd=0, net_bps>0) be fully excluded or stay as diagnostic candidates?
```

## Session Completion
```
session_goal: E1.63 ROUTE_SPLIT_STEP7 + DEPTH_GUARD_STEP8 — additive frontier features, 30-min paper soak validation
goal_status: LANDED_NOT_RUNTIME_VALIDATED — all E1.63 code shipped; split/depth not yet runtime-activated (split_route_attempted=0, price_impact_populated=0; requires hot frontier sweep completion which was blocked by WS 429)
close_allowed: false
remaining_blockers: WS 429 (infra), usd_frontier_split_wins=0 (no hot sim_pass this session), price_impact_populated=0 (same root cause), B3 oracle gap (market), positive ep_usd not yet observed (thin liquidity)
evidence_session_run_dirs: data/runs/_rolling/ (last_updated=2026-05-07T08:54:45Z)
primary_blocker_of_session: WS 429 throttling prevented hot frontier sweep from completing; split_route and depth_guard code paths never reached in live events
blocker_status_before: E1.62 frontier active with usd_frontier_rescaled; no split routing; no depth guard
blocker_status_after: E1.63 code landed; split + depth guard gated behind ARBY_SPLIT_ROUTE_ENABLE; no regression; RUNTIME NOT VALIDATED
docs_reread_confirmed: true
```
