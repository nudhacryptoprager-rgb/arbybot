# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-07T06:33:37Z
run_id: nonstop_runtime_20260507_E1.61_usd_target_soak
mode: ONLINE
artifact_mode: rolling
config: base / production + discovery / real_minimal.yaml
code_identity:
  primary: ts:2026-05-07T06:33:37+02:00
  dirty: true (m7/orderflow/pricing.py, m7/orderflow/artifacts.py, m7/orderflow/scoring_parallel.py)
  desc: E1.61 SIZE_DUST_ROOT_CAUSE — opt-in USD-target rescale via ARBY_TARGET_TRADE_USD; size_source/size_normalization_source fields

## 1) Scope (що і навіщо)
goal (Roadmap): E1.61 — валідація USD-target rescale (ARBY_TARGET_TRADE_USD=10) у runtime; root cause size dust виявлено і зафіксовано
change_summary:
  - scoring_parallel.py: _usd_target_rescaled_size_wei() — opt-in rescale коли current_size_usd < target_usd
  - scoring_parallel.py: size_source="usd_target_rescaled" для rescaled кандидатів
  - contracts.py: size_normalization_source field на BackrunResult
  - artifacts.py: size_normalization_source проброшено у артефакти
  - E1.60 fixes (попередній commit): bridge no-overwrite, bridge_generation_status, scan timing, rate_metrics lifetime
touched_files:
  - m7/orderflow/scoring_parallel.py
  - m7/orderflow/pricing.py
  - m7/orderflow/artifacts.py
  - m7/orderflow/contracts.py

## 2) Commands Executed (лише факти)
py -3.11 -m pytest tests/unit -q: PASS (4775 tests, 6 skipped, 0 failures) — після E1.61 змін
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: PASS (1 warning: Status_M7.md 340 lines > 300 limit)
SOAK: py -3.11 scripts/start_nonstop_runtime.py --hours 0.25 --no-m4 --chain base --with-discovery --m7-cold-pause 3 --dashboard-port 8120 --m7-hot-pause 1 --m7-hot-ws-timeout 120 --m7-cold-ws-timeout 120: COMPLETE (06:18:35Z–06:33:37Z, 15 min exact, exit 0)
ENV: ARBY_TARGET_TRADE_USD=10, ARBY_TARGET_TRADE_MAX_SCALE=100000, ARBY_COLD_IMMEDIATE_SIM=1, ARBY_PAPER_SIGNING=1, ARBY_SIM_BACKEND=rpc_fork

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/m7_hot_rollup_latest.json
  - data/runs/_rolling/m7_orderflow_latest.json
  - data/runs/_rolling/m7_cold_hot_bridge.json
  - data/runs/_rolling/m7_hot_latest.json

## 4) Key Results (числа з артефактів)

### Supervisor підсумок
```
soak_start_utc:  2026-05-07T06:18:35Z
soak_end_utc:    2026-05-07T06:33:37Z
duration:        15 min 2s (exact per --hours 0.25)
processes:       5/5 alive, 0 crashes, 0 crash_restarts
chain:           base
env:             ARBY_TARGET_TRADE_USD=10 ARBY_TARGET_TRADE_MAX_SCALE=100000
```

### E1.61 Acceptance Criteria Matrix
```
size_source="usd_target_rescaled" appears in candidates: CONFIRMED ✓
  near_executable[0]: 0x6bb6a206/WETH size_source=usd_target_rescaled size_usd=1.453385
  near_executable[1]: 0xac73bece/WETH size_source=usd_target_rescaled size_usd=9.985034

size_usd_estimate raised from $0.000*** closer to $10: PARTIAL ✓
  token/WETH pairs: $1.45 and $9.99 (from dust ~$0.001)
  B3/USDC pairs: still $0.0 (oracle price for B3 unknown — rescale requires USD basis)

net_bps behavior at $10 size: REVEALED — route goes NEGATIVE
  near_exec[0]: net_bps=-5.5352  (was positive at dust size)
  near_exec[1]: net_bps=-5.9332  (was positive at dust size)
  Conclusion: low liquidity depth — route doesn't hold at $10; confirms issue #3 from reviewer
```

### E1.60 Fix Validation (re-confirmed in this soak)
```
Fix 3 — bridge no-overwrite:      CONFIRMED ✓ bridge_generation_status="ready_preserved" at T+3min
Fix 4 — bridge_generation_status: CONFIRMED ✓ cycling: warming → ready_preserved → ready
Fix 7 — rate_metrics lifetime:    CONFIRMED ✓ submit_ready_total_lifetime=13
Fix 8 — cold scan timing:         CONFIRMED ✓ scan_duration=122s, pairs=38, pools=94
```

### Hot lane — session rate_metrics
```
session_elapsed_minutes:   13.154  (stopped at 15min wall-clock)
session_windows_seen:      8
submit_ready_delta:        0
cold_immediate_submit_ready_delta: 0
submit_ready_total_lifetime: 13
ci_lifetime:               13
rt_profitable_total_lifetime: 13
rt_attempted_total_lifetime:  81+
```

### Hot lane — lifetime rollup (end of soak)
```
events_seen_total:         2864  (+78 new this soak)
fast_path_scored_total:    1982  (+19 new)
cold_immediate_sim_input_total: 376  (+25 new — CI sim NOT frozen)
cold_immediate_sim_attempted:   363
cold_immediate_sim_passed:      92  (+10 new this soak)
cold_immediate_roundtrip_profitable: 13
submit_ready_total:        13
last_updated:              2026-05-07T06:33:37Z
```

### Bridge — final state (06:32:10Z)
```
bridge_generation_status:  ready  (cold scan completed fresh window)
cold_executable:           2  (B3/USDC, B3/USDC)
near_executable:           2  (0x6bb6a206/WETH, 0xac73bece/WETH)
cold scan:                 122s, 38 pairs, 94 pools
```

### USD-target rescale findings
```
B3/USDC candidates:
  size_source:               dynamic_bounded
  size_normalization_source: decimal_only
  size_usd_estimate:         0.0  ← B3 oracle price unknown; rescale blocked
  net_bps:                   2595.8716  ← high bps at dust size
  amount_in_wei:             1000000000000000000 (1e18 = 1 token = dust $)
  root cause:                _quote_implied_size_usd returns None for non-WETH/stable pairs
                             with no oracle → _usd_target_rescaled_size_wei skips

token/WETH near-exec candidates:
  size_source:               usd_target_rescaled  ✓
  size_usd_estimate:         $1.45 and $9.99  ✓
  net_bps:                   -5.5 and -5.9  ← route inverts at $10
  amount_in_wei:             ~1e23 wei (100000× rescale of 1e18)
  root cause of negative:    insufficient pool liquidity at $10 depth
```

### E1.60 Fix Validation Matrix
```
Fix 4 — bridge_generation_status field:     CONFIRMED ✓
  observed: bridge.bridge_generation_status = "warming" (both segments)
  expected: present; "ready"/"warming"/"ready_preserved"/"empty_market"

Fix 7 — rate_metrics lifetime totals:       CONFIRMED ✓
  observed: submit_ready_total_lifetime=13, cold_immediate_submit_ready_total_lifetime=13
  expected: fields present in rate_metrics block

Fix 8 — cold lane scan timing fields:       CONFIRMED ✓
  observed: full_universe_scan_started_at=2026-05-06T09:01:33Z
            full_universe_scan_ended_at=2026-05-06T09:02:17Z
            full_universe_scan_duration_s=44.0
            pairs_scanned=4 / pools_scanned=15
  expected: fields present in cold lane m7_loop_context

Fix 3 — bridge no-overwrite on cold restart: NOT EXERCISED
  reason: cold scan completed in 44s (4 pairs, 15 pools only)
          bridge never reached "ready" state → restart scenario not triggered
  status: code implemented, unit tests pass; soak too short for full universe scan

Fix 2 — cold_immediate_sim docstring:       CONFIRMED ✓ (investigative)
  finding: no 1e18 default in code; uses entry.get("amount_in_wei") or 0
           STF reverts caused by unfunded Hardhat account, not synthetic amount
```

### Hot lane — session rate_metrics (seg-2, 09:01:33Z–09:03:27Z)
```
session_elapsed_minutes:           11.634  (cumulative from rollup baseline)
session_windows_seen:              7
roundtrip_attempted_delta:         0
roundtrip_profitable_delta:        0
scoring_blackhole_windows_delta:   1
submit_ready_delta:                0
cold_immediate_submit_ready_delta: 0
submit_ready_total_lifetime:       13
cold_immediate_submit_ready_total_lifetime: 13
rt_profitable_total_lifetime:      13
rt_attempted_total_lifetime:       81
lifetime_profitable_rate_per_hour: 0.0  (lifetime accumulated from prior soak)
rate_basis:                        current_worker_session_delta
```

## 4.1) Theoretical Net Profit
```
theoretical_net_profit:
  mode: paper_simulated
  note: No new submit_ready events this soak; near_exec routes inverted at $10 size
  lifetime_basis: submit_ready_total_lifetime=13, rt_profitable_total=13 (from prior sessions)
  gross_pnl_usdc: not computed (no new candidates cleared sim this soak)
  disclaimer: "Theoretical profit based on simulated execution. No real trades were executed."
```

## 5) Contract Checks
```
status/reasons consistency:          OK (no errors in soak windows)
rolling discipline (3 files only):   OK (m7_hot_rollup_latest, m7_hot_latest, m7_orderflow_latest)
v2.x provenance contract:            OK
runtime artifacts not committed:     OK
pytest:                              4775 PASS / 6 skipped / 0 failures
safety:                              PASS (1 warning: Status_M7.md 340 lines)
```

## 6) Blocker Classification
```
code_blocker:             LOW  (4775 pytest PASS, no crashes in 15min soak)
data_collection_blocker:  LOW  (ci_input growing +25 new; bridge cycling ready/ready_preserved)
market_window_blocker:    HIGH  (routes invert at $10; B3 bps=2595 but oracle price unknown → rescale blocked)
```

## 6.1) Blockers / Risks
1. **USD rescale blocked for meme tokens (B3/FUN/etc)**: `_quote_implied_size_usd` returns None when neither token is WETH/stable and oracle is silent. `_usd_target_rescaled_size_wei` requires `current_size_usd > 0`. B3/USDC shows `size_usd=0.0` despite USDC being a stable — root cause: token_in=B3 (unknown price), oracle lookup fails. The USDC coarse fallback only triggers when `token_in` is stablecoin. Fix: use `token_out` USD estimate when `token_in` price unavailable.
2. **Route depth insufficient at $10**: near_exec token/WETH routes go negative at $10 rescale. Pool liquidity too thin. Need size-curve sweep (reviewer issue #4) to find max viable size before slippage inverts the route.
3. **CI sim STF reverts**: rpc_fork uses unfunded Hardhat account. ~100% STF revert rate for CI sim. Need Fix 6 (funded address).
4. **B3/USDC `amount_in_wei=1e18` baseline**: 1 token of a near-worthless meme coin ≈ dust USD. High bps on dust is economically meaningless without absolute USD profit gate.

## 7) E1.61 Execution Map
```
pytest:        4775 PASS / 6 skipped — DONE
safety:        PASS (1 warn) — DONE
usd_rescale:   landed behind ARBY_TARGET_TRADE_USD — DONE
soak 15min:    COMPLETE (06:18:35Z–06:33:37Z) — DONE
size_source:   "usd_target_rescaled" confirmed in near_exec — DONE
size_usd rise: $1.45 and $9.99 for WETH-output pairs — DONE
net_bps check: negative at $10 → route depth issue confirmed — DONE
meme tokens:   B3 oracle=None → rescale blocked; needs token_out fallback — IDENTIFIED
next steps:    size-curve sweep (issue #4), token_out USD fallback (issue #5), min_profit_usd gate (issue #6)
```

## 8) What I need from Lead now
```
request_1: Confirm next priority — (a) token_out USD fallback for meme tokens or (b) size-curve sweep first
request_2: Confirm whether B3/USDC at 2595bps dust size should be treated as a valid candidate or filtered by min_profit_usd gate
request_3: Fix 6 (funded rpc_fork wallet) timeline — CI sim STF blocks submit_ready growth
```

## Session Completion
```
session_goal: E1.61 USD-target rescale — pytest, safety, 15min soak validation
goal_status: REACHED — all acceptance criteria met or root-caused
close_allowed: true
remaining_blockers: meme token oracle gap (B3 rescale), route depth at $10, CI sim STF
evidence_session_run_dirs: data/runs/_rolling/ (m7_hot_rollup_latest.json last_updated=2026-05-07T06:33:37Z)
primary_blocker_of_session: route inverts at $10 for WETH-output pairs; B3 oracle unknown
blocker_status_before: size_dust unknown (E1.60)
blocker_status_after: root cause confirmed; usd_rescale active; route depth + oracle gap are next fixes
docs_reread_confirmed: true
```
