# Status: M7 (Triangular Feasibility)

**Status**: **E1.63: ROUTE_SPLIT_STEP7 + DEPTH_GUARD_STEP8 LANDED. 30-min soak (08:24:43Z–08:54:45Z, 5/5, exit 0) confirmed zero crash_restarts, no regression (submit_ready=13, bps_best=982.83 unchanged). New features stable but dormant (WS 429 limited hot sim_pass to 0 new events in session). Cold immediate path: +54 sim_attempted, +7 sim_passed during soak. `usd_frontier_split` and `price_impact_bps` fields inactive this window (hot frontier sweep requires hot sim_pass to fire). Both features are strictly additive/gated and never killed the pipeline.**

`py -3.11 -m pytest tests/unit -q`: **4798 PASS / 6 skipped / 0 failures** (+13 new E1.63 tests). `check_repo_safety.py --allow-intent-edit`: PASS (1 warning: Status_M7.md length). docs_reread_confirmed: true. soak: 2026-05-07T08:24:43Z–08:54:45Z (30 min, 5/5, exit 0).

```
E1.63_step7_split_routing:   ARBY_SPLIT_ROUTE_ENABLE=1 active; attempt_split_pricing() called in frontier loop
E1.63_step8_depth_guard:     compute_v3_sqrt_price_after() always called when pool_state has sqrt_price_x96
usd_frontier_split_wins:     0  (no hot frontier sweep completed — requires hot sim_pass which was 0 in session)
price_impact_bps_populated:  0  (same reason — hot path did not reach BackrunResult constructor in session)
submit_ready_total:          13  (unchanged vs E1.62 baseline — no regression)
bps_best:                    982.83  (unchanged vs E1.62 baseline)
cold_immediate_sim delta:    +54 attempted / +7 passed in soak
crash_restarts:              0/100  (all 5 processes, clean shutdown)
session_ws_connected_windows: 5/15  (WS 429 still main bottleneck, identical to E1.62)
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
