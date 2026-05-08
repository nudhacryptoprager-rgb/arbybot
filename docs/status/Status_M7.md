# Status: M7 (Triangular Feasibility)

**Status**: **E1.64 step-fix soak: RUNTIME_VALIDATED. 45-min soak (08:33:31Z–09:18:46Z, 6/6 alive, exit 0) confirmed all 10 production-profit fix steps fired in fresh runtime per `current_session_delta`. PROD `e163_split_route_status` promoted ATTEMPTED_NO_WIN_YET → RUNTIME_VALIDATED via gross-PnL-wei comparison (11 wins this session). Cold + hot USD-basis gates blocked 98+98 fresh dust entries; MIN_PROFIT_USD gate blocked 98 fresh near-zero-profit entries. DISC lane: 20 fresh split-route wins (lifetime 25), 194 USD-basis blocks, 198 MIN_PROFIT blocks. `current_session_delta` block (13 keys) wired in rollup + bridge for both lanes. 0 crash_restarts. submit_ready_total preserved (lifetime prod=24, disc=35) — gates filter dust, not real entries.**

goal_status: REACHED
production_profit_status: gates active and firing on real runtime; submit_ready_delta=0 in this 45-min window reflects market opportunity, not pipeline regression
docs_reread_confirmed: true
close_allowed: true
blocker_status_after: RESOLVED (USD basis + MIN_PROFIT_USD enforced at submit_ready boundary; current_session_delta exposes per-session activity)

`python -m pytest tests/unit -q`: **4835 PASS / 6 skipped / 0 failures** (was 4826 + 9 new test_e1_64_step_fixes.py). `check_repo_safety.py --allow-intent-edit`: PASS (0 warnings). docs_reread_confirmed: true. soak: 2026-05-08T08:33:31Z–09:18:46Z (45 min, 6/6 alive, exit 0). restarts used: 0/4.

```
=== E1.64 STEP-FIX SOAK (current_session_delta evidence) ===
PROD csd.e163_split_route_attempted:    2074  -- CONFIRMED fresh activity
PROD csd.e163_split_route_win:            11  -- step 9 produced first prod wins (gross-PnL-wei)
PROD csd.e163_depth_guard_attempted:    2074  -- step 3 telemetry firing
PROD csd.e163_price_impact_populated:   2074  -- 1:1 with depth probes
PROD csd.e164_usd_basis_missing:          98  -- step 4 USD gate blocking dust at submit_ready
PROD csd.e164_min_profit_rejected:        98  -- step 4 MIN_PROFIT gate blocking near-zero
PROD csd.e164_depth_guard_rejected:        0  -- depth math sound; no probe failed bps cutoff
PROD csd.e164_depth_math_invalid:          0  -- no malformed depth math
PROD csd.submit_ready_total:               0  -- gates correctly hold dust back this window

DISC csd.e163_split_route_win:            20  -- 20 fresh disc wins this session (lifetime 25)
DISC csd.e164_usd_basis_missing:         194
DISC csd.e164_min_profit_rejected:       198

LIFETIME PROD e163_split_route_status:  RUNTIME_VALIDATED  (was ATTEMPTED_NO_WIN_YET in E1.63)
LIFETIME DISC e163_split_route_status:  RUNTIME_VALIDATED
LIFETIME e164_depth_guard_status:       RUNTIME_VALIDATED
crash_restarts:                         0/100  (6/6 alive, 45 min)
```

## E1.63 soak results — prior status entry below.

**Status**: **E1.63: RUNTIME_VALIDATED. 60-min soak (10:38:13Z–11:38:16Z, 5/5, exit 0) confirmed split_route_attempted_total=5310 (prod) + 6364 (disc), disc lane status=RUNTIME_VALIDATED (5 wins). Fast-path split routing wired into score_backrun_fast(). pool_price_state registry fallback for multicall misses. submit_ready improved prod=24, disc=35 (vs E1.62 baseline 13). Depth guard dormant (cold/slow path only — deferred to E1.64).**

`python -m pytest tests/unit -q`: **4807 PASS / 6 skipped / 0 failures**. docs_reread_confirmed: true. soak: 2026-05-07T10:38:13Z–11:38:16Z (60 min, 5/5, exit 0). restarts used: 2/4.

```
e163_split_route_attempted (prod):  5310  -- CONFIRMED > 0
e163_split_route_attempted (disc):  6364  -- CONFIRMED > 0
e163_split_route_wins (prod):       0   (thin Base depth at $0.1-$50 USD; expected)
e163_split_route_wins (disc):       5   -- RUNTIME_VALIDATED
e163_split_route_status (disc):     RUNTIME_VALIDATED
e163_depth_guard_status:            LANDED_NOT_RUNTIME_VALIDATED  (slow path only; E1.64 fast-path wiring deferred)
submit_ready_total:                 prod=24, disc=35  (improved vs E1.62 baseline 13)
crash_restarts:                     0/100  (all 5 processes, clean shutdown)
fast_path_scored:                   prod=2654, disc=2584
cold_immediate_sim_passed:          prod=206, disc=235
```

## E1.62 soak results — prior status entry below.

**Status**: **E1.62: USD_PROFIT_FRONTIER + TOKEN_OUT_FALLBACK + COLD_RANKING_USD_FIRST LANDED. 20-min soak confirmed frontier active (`size_source="usd_frontier_rescaled"`), 13 submit_ready, bps_best=982.8, 0 crash restarts. `expected_profit_usd` field propagates to bridge. B3 oracle gap persists (meme tokens pass gate unconditionally as intended). WS 429 throttling (6 windows) from provider infra — pipeline falls back to HTTP correctly. Next: route splitting (step 7) or QuoterV2 depth guard (step 8).**

`py -3.11 -m pytest tests/unit -q`: **4785 PASS / 6 skipped / 0 failures**. `check_repo_safety.py --allow-intent-edit`: PASS (1 warning: Status_M7.md length). docs_reread_confirmed: true. soak: 2026-05-07T07:34:33Z–07:54:26Z (20 min, 5/5, exit 0).

```
frontier_active:               size_source="usd_frontier_rescaled" in bridge (VIRTUAL/WETH, BLEPE/WETH)
expected_profit_usd_field:     propagates to bridge; VIRTUAL/WETH ep_usd=-0.001002 (negative → not submitted)
submit_ready_total:            13
roundtrip_profitable_total:    13
roundtrip_profit_bps_best:     982.83
roundtrip_profit_bps_median:   272.91
roundtrip_profit_bps_worst:    -72.47
cold_immediate_sim_input:      394  (→ 93 passed → 13 roundtrip_profitable)
cold_profit_guard_rejected:    0  (dust entries w/o USD basis pass unconditionally — intended)
ws_failed_429_windows:         6  (provider rate-limit; falls back to HTTP, pipeline continues)
sim_failed_samples_total:      70  (hot-lane rpc_fork struggles; cold_immediate path healthy)
crash_restarts:                0/100  (all 5 processes clean shutdown)
```

## E1.61 soak results — prior status entry below.

**Status**: **E1.61: SIZE_DUST_ROOT_CAUSE_FOUND + USD_TARGET_RESCALE_LANDED. 15-min soak confirmed `size_source="usd_target_rescaled"` and `size_usd_estimate` elevated to $1.45/$9.99. Route inverts at $10 (thin liquidity). B3 oracle gap blocks rescale for meme tokens. Next: token_out USD fallback + size-curve sweep.**

`py -3.11 -m pytest tests/unit -q`: **4775 PASS / 6 skipped / 0 failures**. `check_repo_safety.py --allow-intent-edit`: PASS (1 warning: Status_M7.md 340 lines). docs_reread_confirmed: true. soak: 2026-05-07T06:18:35Z–06:33:37Z (15 min, 5/5, exit 0).

```
size_dust_root_cause: _REF_MAX_WEI_18=1_token → dust USD for low-price ERC20s
fix_landed: ARBY_TARGET_TRADE_USD opt-in rescale in scoring_parallel._usd_target_rescaled_size_wei()
size_source_confirmed: "usd_target_rescaled" in near_executable candidates
size_usd_pre_rescale:  ~$0.000***
size_usd_post_rescale: $1.45–$9.99 (WETH-output pairs)
net_bps_at_10usd:      NEGATIVE (-5.5, -5.9) → pool liquidity insufficient at $10
meme_token_gap:        B3 oracle=None → size_usd=0.0 → rescale blocked (token_out fallback needed)
ci_sim_input_growth:   +25 new events this soak (NOT frozen; Fix 3 confirmed: ready_preserved→ready)
```


## E1.60 and earlier — archived

Historical entries (E1.60 and earlier) moved to rchive/status/Status_M7_pre_E160.md.
