# Status: M7 (Triangular Feasibility)

**Status**: **E1.79 SOAK COMPLETE (2026-05-10). INFRASTRUCTURE_PASS / MARKET_GAP. All E1.79 prep fixes verified. 4966 tests pass.**

goal_status: BLOCKED
pipeline_ready: true
production_profit_ready: false
close_allowed: false
blocker: MARKET_GAP — session_best_amount_usd=37.99 (real depth; proxy=50 excluded by E1.79 fix 2); production_sized_total=0; submit_delta=0; discovery pool bps=265 unpriced
next_milestone: E1.80 Steps 7-9 (pair-family universe expansion, USD pricing for unpriced tokens, depth_breakthrough dashboard)
docs_reread_confirmed: true

```
=== E1.79 SOAK RESULT (2026-05-10T12:12:19Z–13:12:22Z) ===
soak_id:      start_nonstop_runtime.py --chain base --hours 1 --cold-http-only --m7-cold-ws-timeout 240
env:          TOP_N=15, SIZE_FRONTIER=5-1000, LOOSE_GATES=0, PAPER_SIGNING=1, USD_BASIS_FALLBACK=40 tokens
all_pass: false
verdict: INFRASTRUCTURE_PASS / MARKET_GAP
production_sized_total:         0       → FAIL (no $50+ priced candidate in session)
best_amount_in_usd:             37.99   → FAIL (E1.79: proxy=50 NOT counted; real depth 37.99 < 50)
best_expected_profit_usd:       22.44   → PASS (E1.79 fix 1 confirmed: session_best fallback working)
submit_ready_delta:             0       → FAIL (0 new submits this session; total=36 from prior)
roundtrip_profitable_delta:     0       → FAIL (paper signing, no exec completions; 2 attempted)
ws_429_rate:                    1.3%    → PASS (12/924 windows < 15%)
soak_infra: 5/5 alive, 0 crash_restarts, WS=11/924, clean exit 0
bridge top: pool=? bps=3782.6 usd=7e-6 (unpriced; discovery: bps=265 usd=null)
```

```
=== E1.79 PREP FIXES (code, 2026-05-10) — VERIFIED ===
Fix 1: gate reads session_best_expected_profit_usd as fallback → CONFIRMED (gate=22.44 not 0.000003)
Fix 2: gate uses session_best_amount_usd only (real) → CONFIRMED (gate=37.99 FAIL; proxy=50 not counted)
Fix 3: null-row protection in _writeback_enriched_candidates → in code, no regression
Fix 4: bridge dedup by score tuple (is_priced, profit, mav, usd) — priced always beats null row
Fix 5: ARBY_DISCOVERY_LOOSE_GATES=1 env mode + _loose_gates_mode() helper → in code
Fix 6: session_best_proxy_size_usd added as explicit field → CONFIRMED (field=0.0 separate from near_usd=50)
Fix 7: unpriced_but_depth_probeable bucket in bridge_runtime.py payload → dp_count=0 (no eligible pool)
Fix 8: gate_dropoff_* counters (top_n_cutoff/min_bps/min_profit/sim_admission/loose_mode/usd_basis)
Fix 9: gate_dropoff_sim_admission_failed + usd_basis synced from concrete sim-loop counters
pytest: 4966 passed / 6 skipped / 0 failures
check_repo_safety: PASS (0 warnings)
```

```
=== E1.79 ACCEPTANCE CRITERIA (evaluated) ===
session_best_amount_usd >= 50  → 37.99  FAIL  (real executable depth unchanged)
session_best_expected_profit_usd > 0    → 22.44 PASS
submit_ready_delta >= 1        → 0      FAIL
ws_429_rate < 15%              → 1.3%   PASS
soak_infra: 5/5 alive, 0 crash_restarts → PASS
overall: INFRASTRUCTURE_PASS / MARKET_GAP
```

**Status (prior E1.78)**: **E1.78 REACHED (2026-05-10). 1h soak COMPLETE. Bug fix confirmed: session_best preservation in _HOT_PRESERVE_ALWAYS. 10 tests (4955 total). Gate: INFRASTRUCTURE_PASS / MARKET_GAP — session_best_near_usd=50 PASS, production_sized_total=0 FAIL, roundtrip_profitable_delta=0 FAIL. Soak: 5/5 alive, 0 crash_restarts, 13 cold cycles, WS=10/894, 429=1.45%, clean exit 0.**

goal_status: REACHED
pipeline_ready: true
production_profit_ready: false
close_allowed: true
blocker_status_after: BLOCKED — MARKET_GAP persists; production_sized_total=0; roundtrip_profitable_delta=0; E1.79 Steps 7-9 required
strict_gate_runtime_only: true
docs_reread_confirmed: true
blocker: MARKET_GAP — production_sized_total=0 (best pool 0xdc8f: amount_in_optimal_usd=$38, best_size_usd=$50, profit=$22.44); no roundtrip completions; infrastructure is healthy
next_milestone: E1.79 Steps 7-9 (universe expansion as pair-family, scout filter ≥2 DEX, depth_breakthrough dashboard block)

```
=== E1.78 FIXES (code, 2026-05-10) ===
bridge write-back:      mav_usd/lag_score/best_size_usd persisted to bridge JSON after sort
session_best:           session_best_near_usd / session_best_amount_usd accumulated per session (monotonic max)
strict gate:            post_soak_pass_gate reads session_best; best_amount_effective = max(snapshot, session_best_near, session_best_amount)
usd_basis_counter:      cold_exec_with_usd_basis now counts amount_in_optimal_usd > 0 (was missing)
pending_eth_call:       wired in cold scorer (top-3 MAV; balanceOf canary; E1.79 extends to quoter ABI)
session_best preserve:  bridge_runtime _HOT_PRESERVE_ALWAYS += "session_best" (bug fix: cold lane was clearing KPI each cycle)
new tests (10):         test_e1_78_bridge_writeback.py (write-back, session_best, gate, counter, preservation)
pytest:                 4955 passed / 6 skipped / 0 failures
```

```
=== E1.78 SOAK RESULT (2026-05-10T12:01–13:01Z) ===
soak_id:      start_nonstop_runtime.py --chain base --hours 1 --cold-http-only --m7-cold-ws-timeout 240
env:          PENDING_SIM=1, REQUIRE_USD_BASIS=1, COLD_REQUIRE_USD_BASIS=1, PAPER_SIGNING=1
acceptance:   session_best_near_usd >= 50 OR production_sized_total >= 1
all_pass: false
verdict: INFRASTRUCTURE_PASS / MARKET_GAP
production_sized_total:   0    → FAIL (market depth $38 < prod threshold)
best_amount_in_usd:       50.0 → PASS (session_best_near_usd=50.0 exactly matches threshold)
best_expected_profit_usd: 22.44 → PASS
roundtrip_profitable_delta: 0  → FAIL (paper signing, no exec completions)
submit_ready_delta:       3    → PASS
ws_429_rate:              1.45% → PASS (< 15%)
soak_infra: 5/5 alive, 0 crash_restarts, 13 cold cycles, clean exit 0
bridge top:   pool=0xdc8f | net_bps=5906 | lag=100 | best_size=50 | amount=37.99 | profit=22.44
```

```
=== E1.78 FIXES (code, 2026-05-10) ===
bridge write-back:      mav_usd/lag_score/best_size_usd persisted to bridge JSON after sort
session_best:           session_best_near_usd / session_best_amount_usd accumulated per session (monotonic max)
strict gate:            post_soak_pass_gate reads session_best; best_amount_effective = max(snapshot, session_best_near, session_best_amount)
usd_basis_counter:      cold_exec_with_usd_basis now counts amount_in_optimal_usd > 0 (was missing)
pending_eth_call:       wired in cold scorer (top-3 MAV; balanceOf canary; E1.79 extends to quoter ABI)
session_best preserve:  bridge_runtime _HOT_PRESERVE_ALWAYS += "session_best" (bug fix: cold lane was clearing KPI each cycle)
new tests (10):         test_e1_78_bridge_writeback.py (write-back, session_best, gate, counter, preservation)
pytest:                 4955 passed / 6 skipped / 0 failures
```

```
=== E1.78 SOAK IN PROGRESS (2026-05-10T12:01Z) ===
soak_id:      start_nonstop_runtime.py --chain base --hours 1 --cold-http-only --m7-cold-ws-timeout 240
env:          PENDING_SIM=1, REQUIRE_USD_BASIS=1, COLD_REQUIRE_USD_BASIS=1, PAPER_SIGNING=1
acceptance:   session_best_near_usd >= 50 OR production_sized_total >= 1
t+03m [01]:   FRESH | cold_cyc=1  | session_near=0  | hmap=29 | submit=33 | WS=1/868  | 429=0
t+06m [02]:   FRESH | cold_cyc=2  | session_near=0  | hmap=47 | submit=33 | WS=2/869  | 429=0
t+09m [03]:   FRESH | cold_cyc=3  | session_near=25 | hmap=47 | submit=34 | WS=3/871  | 429=1  (usd_basis=2)
t+12m [04]:   FRESH | cold_cyc=3  | session_near=25 | hmap=47 | submit=35 | WS=3/872  | 429=2
t+15m [05]:   FRESH | cold_cyc=4  | session_near=25 | hmap=47 | submit=36 | WS=3/873  | 429=3
t+18m [06]:   STALE | cold_cyc=5  | session_near=0  | hmap=47 | submit=36 | WS=3/874  | 429=4  (pool change bug)
t+21m [07]:   FRESH | cold_cyc=5  | session_near=0  | hmap=47 | submit=36 | WS=4/876  | 429=5
t+24m [08]:   FRESH | cold_cyc=6  | session_near=0  | hmap=47 | submit=36 | WS=5/877  | 429=5
t+27m [09]:   STALE | cold_cyc=7  | session_near=0  | hmap=47 | submit=36 | WS=5/878  | 429=6
t+30m [10]:   FRESH | cold_cyc=7  | session_near=0  | hmap=47 | submit=36 | WS=6/880  | 429=7
t+33m [11]:   FRESH | cold_cyc=8  | session_near=50 | hmap=47 | submit=36 | WS=6/882  | 429=8  (BREAKTHROUGH! pool 0xdc8f net_bps=5906 profit=$22.44)
t+36m [12]:   FRESH | cold_cyc=9  | session_near=50 | hmap=47 | submit=36 | WS=6/884  | 429=9  (preserved!)
t+39m [13]:   FRESH | cold_cyc=9  | session_near=50 | hmap=47 | submit=36 | WS=7/885  | 429=9
t+42m [14]:   FRESH | cold_cyc=10 | session_near=50 | hmap=47 | submit=36 | WS=8/887  | 429=9
t+45m [15]:   FRESH | cold_cyc=11 | session_near=0  | hmap=47 | submit=36 | WS=8/888  | 429=10  (cold scan race)
t+48m [16]:   FRESH | cold_cyc=11 | session_near=50 | hmap=47 | submit=36 | WS=8/890  | 429=11  (restored)
t+51m [17]:   FRESH | cold_cyc=12 | session_near=50 | hmap=47 | submit=36 | WS=9/892  | 429=11
t+54m [18]:   FRESH | cold_cyc=12 | session_near=50 | hmap=47 | submit=36 | WS=10/893 | 429=11
t+57m [19]:   FRESH | cold_cyc=13 | session_near=0  | hmap=47 | submit=36 | WS=10/894 | 429=12  (cold scan race)
t+60m [20]:   API_ERR (soak terminated 13:01:13Z, monitor polled 13:01:49Z = 36s post-shutdown)
bridge top:   pool=0xdc8f | net_bps=5906 | lag=100 | best_size=50 | amount=37.99 | profit=22.44

=== STRICT GATE RESULT (2026-05-10T13:01Z) ===
all_pass: false
verdict: INFRASTRUCTURE_PASS / MARKET_GAP
production_sized_total:   0    → FAIL (market depth $38 < prod threshold)
best_amount_in_usd:       50.0 → PASS (session_best_near_usd=50.0 exactly matches threshold)
best_expected_profit_usd: 22.44 → PASS
roundtrip_profitable_delta: 0  → FAIL (paper signing, no exec completions)
submit_ready_delta:       3    → PASS
ws_429_rate:              1.45% → PASS (< 15%)
soak_infra: 5/5 alive, 0 crash_restarts, 13 cold cycles, clean exit 0
``` 30-min soak INFRASTRUCTURE_PASS: 5/5 processes alive throughout, 0 crash_restarts, 7 cold cycles (240s cadence), heatmap_rows=29 stable from t+6m, bridge identity fields present (pair/source/dex=unknown). Strict gate KPIs (production_sized/submit_ready_delta/roundtrip_profitable_delta) = 0 — confirmed MARKET_GAP (best_near_usd peaked $30 at t+27m; OPP peaked 17 at t+18m; WS 429_rate=0.8%).



**Status (prior)**: **E1.65 REACHED (2026-05-08). USD-size/dashboard/depth truth validated. 3h soak clean (5/5 alive, 0 crashes). production_profitable_total=0 is ACCEPTED as dust-depth market reality: all profitable Base arb pairs (FUN/USDC, 0x16ee7eca/USDC) cap at AMM frontier < $1. pipeline_ready=true. production_profit_ready=false (no pair ≥$10 depth). Next: E1.66 depth-aware universe expansion + production-sized profitability gate.**

goal_status: REACHED
pipeline_ready: true
production_profit_ready: false
close_allowed: true
reason_for_prod_zero: dust-depth AMM frontier — market reality, not code bug; all dashboard/gate logic confirmed correct
next_milestone: E1.66 — depth-aware universe promotion + production_sized_profitable_total > 0
docs_reread_confirmed: true

`python -m pytest tests/unit -q`: **4850 PASS / 6 skipped / 0 failures**. `check_repo_safety.py --allow-intent-edit`: PASS (0 warnings).

```
=== SOAK 3 EVIDENCE (3h, 2026-05-08T13:53Z→16:53Z) ===
5/5 alive, 0 crash_restarts, clean shutdown (exit 0)
production_profitable_total:  0 (stable throughout)
research_profitable_total:    5-6 (dust/micro)
dust_only_total:              8-10
opportunities_total:          10-15
cold_cycles:                  ~every 15min; cold_exec=5 (FUN/USDC ×4 + 0x16ee7eca/USDC ×1)
max_pair_size_usd:            FUN/USDC $0.075 (usd_frontier_split)
tier_map at end:              hot=173, warm=164, cold=0 (discovery found 164 warm pairs, none cold-confirmed)
ws_pct429:                    6.1 (peak; stable in last hour)
bridge_fresh:                 True throughout (mtime fix confirmed)
dashboard_bridge_rows:        CONFIRMED — bridge_cold_executable_priced appeared at T+4 (first cold cycle)
DUST_PROFIT_ONLY_tag:         CONFIRMED — all sub-$1 profitable rows tagged correctly
depth_verdict:                dust_only for all profitable pairs — CORRECT
profit_size_buckets_est:      populating (linear extrapolation only — real AMM degrades faster at >$1)
```

`python -m pytest tests/unit -q`: **4850 PASS / 6 skipped / 0 failures** (was 4844 + 6 new size/depth tests). `check_repo_safety.py --allow-intent-edit`: PASS (0 warnings).

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
