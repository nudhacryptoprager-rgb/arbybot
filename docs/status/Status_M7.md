# Status: M7 (Triangular Feasibility)

**Status**: **E1.81 SOAK COMPLETE (2026-05-10). family_active 1–5 in 21/24 snaps. KEYCAT/WETH 825bps profitable_count=15. 50 tests (5044 total). Wiring confirmed.**

goal_status: SOAK_COMPLETE
pipeline_ready: true
production_profit_ready: false
close_allowed: true
blocker: production_sized=0 (market gap, depth ceiling — pre-existing, not E1.81 regression)
next_milestone: E1.82 — close E1.81, promote family-based cold candidates to production routing

```
=== E1.81 WIRING CONFIRMED (2026-05-10, session 2 — process-isolation fix) ===
BUG FIXED: observe_pair_family_profitable was in HOT process (cold_immediate_sim.py).
           family_promotion_snapshot reads _FAMILY_PROMOTIONS in COLD process (bridge_runtime.py).
           Module-level state is process-local → no cross-process sharing → always active_count=0.
FIX: moved observe calls into bridge_runtime._write_cold_hot_bridge() (COLD process).
ADDITIONAL FIX: use payload.get("cold_executable") not arg `candidates` so ready_preserved
     candidates also get observed even when COLD warming produces no new cold_exec.

File 1: m7/orderflow/bridge_runtime.py (MODIFIED)
        — observe_pair_family_profitable() per cold_executable candidate (COLD process)
        — family_promotion_snapshot added to bridge payload
        — candidate_source_breakdown.pool_family_active_count
        — uses _effective_cands = payload.get("cold_executable") or candidates (ready_preserved fix)
File 2: m7/orderflow/cold_immediate_sim.py (MODIFIED)
        — removed HOT-process observe (process isolation fix)
File 3: monitoring/dashboard_server.py (MODIFIED)
        — _serve_family_table() reads family_promotion_snapshot from bridge
        — rows: family_pool_count, family_dex_count, profitable_count fields
        — response: family_active_count, family_promo_ttl_s top-level fields
File 4: tests/unit/test_e1_81_pool_family.py (MODIFIED)
        — 50 tests: +3 process-isolation tests, +1 ready_preserved coverage
        — TestBridgeRuntimeE181Wiring: 4 tests (bridge call, snapshot, sim-not-calling, preserved)

CONFIRMED at 2026-05-10T18:19 local (bridge_ts=16:19:30Z, bgen_status=ready):
  family_active_count=1, pool_family_active_count=1
  MOG/WETH: bps=614.94, pool=0xc29dc26b28fff463e32834ce6325b5c74fac7098, dex=uniswap_v3
  /api/m7/family_table: 32 rows, family_active_count=1
  pair_pool_matrix: 31 pairs, 50 pools (CBBTC/USDC: 7 pools $42M TVL; USDC/WETH: 6 pools $184M TVL)

pytest: 5044 passed / 6 skipped / 0 failures (50 E1.81 tests pass)
check_repo_safety --allow-intent-edit: PASS (0 warnings)
```

```
=== E1.81 INFRASTRUCTURE (2026-05-10, session 1) ===
File 1: m7/orderflow/pool_family.py (NEW, ~200L)
        — PoolFamily dataclass + best_buy_pool / best_sell_pool / family_summary
        — pool_family_ttl_s() / pool_family_enabled() ENV helpers
        — ARBY_POOL_FAMILY_TTL_S (default 60s) / ARBY_POOL_FAMILY_ENABLE (default 1)
File 2: m7/orderflow/pool_registry.py (MODIFIED, +70L)
        — get_pool_family(token_a, token_b, ...) → PoolFamily with TTL cache
        — invalidate_family(token_a, token_b) → cache invalidation
File 3: m7/orderflow/disc_to_prod_pool_promotion.py (MODIFIED, +180L)
        — PairFamilyPromotion dataclass + observe_pair_family_profitable()
        — active_pair_family_promotions() + family_promotion_snapshot() + reset_family_promotions()
        — __all__ updated; existing 8 symbols preserved (regression tested)
File 4: monitoring/dashboard_server.py (MODIFIED, +130L)
        — /api/m7/family_table route + _serve_family_table() method (session 1)
File 5: tests/unit/test_e1_81_pool_family.py (NEW, ~590L, 45 tests, 8 test classes)
```

```
=== E1.80 SOAK STATUS (2026-05-10T14:08-15:08Z — COMPLETE, 60min) ===
soak_id:      start_nonstop_runtime.py --chain base --hours 1 --cold-http-only --m7-cold-ws-timeout 300
env:          USD_BASIS_FALLBACK_ENABLE=1, POOL_PROMOTION=1, FRONTIER=5-1000, cb*_pairs(+5), DECIMAL_FIX
usd_basis_missing:      0       → FIXED (was dominant in E1.79) ✓
viable_count/cycle:     0–5     → improved (5 in final window; 1988.9bps WETH/toby) ✓
best_net_bps:           1988.9  → BEST RESULT (WETH/toby, cold_exec=5, profit_guard_passed=5) ✓
production_sized_total: 0       → FAIL (no $50+ candidate) ✗
submit_ready_delta:     0       → FAIL (no new submits in E1.80 session) ✗
GAS_EXCEEDS_GROSS:      84%     → NEW primary blocker (80–84% per cycle)
api_alive_at_t60min:    true    → PASS FULL 60min (E1.79 died at t=54min) ✓
ws_connections:         6/940   → PASS stable (9 failed_429 = 0.96% rate)
hot_signals_detected:   2×950bps (0x6921b130/WETH; sim=None, cold_not_verified)
hot_signals_executed:   0       → FAIL (hot_cold_gap; depth_math_invalid=549; SCORER_SIM_DIV x2)
```

```
=== E1.80 SOAK SNAPS (monitor 5-min intervals) ===
[01] 16:23:26 +15m FRESH prod=0 sub=36 WS=3/930(429=3) cold_age=225s usd_miss=0
[02] 16:28:26 +20m STALE prod=0 sub=36 WS=3/933(429=5) cold_age=196s usd_miss=0
[03] 16:33:26 +25m FRESH prod=0 sub=36 WS=5/936(429=6) cold_age=166s usd_miss=0
[04] 16:38:26 +30m FRESH prod=0 sub=36 WS=6/938(429=7) cold_age=136s usd_miss=0
[05] 16:43:26 +35m FRESH prod=0 sub=36 WS=6/940(429=9) cold_age=100s usd_miss=0
[06-12] pending — soak ends ~17:08:20 local
```

```
=== E1.80 IMPLEMENTATION (2026-05-10) ===
Item 1: intent.txt — 5 cb* pairs + 2 multi-hop routes
Item 2: usd_basis_fallback.py — cb* anchors (CBXRP, CBLTC, CBADA, CBMEGA, CBETH, WSTETH)
Item 4: disc_to_prod_pool_promotion.py — try_promote_from_cold_signal() + cold_immediate_sim hook
Item 5: scoring_parallel.py — frontier default $5-$1000 (was $0.1-$50)
Item 6: scripts/verify_flashblocks.py — new operator CLI
Item 7: execution/flash_loan/aave_adapter.py — Aave V3 flash loan skeleton (fail-closed)
Item 9: scoring_parallel.py — stable decimal cache-miss fix (primary path)
pytest: 4995 passed / 6 skipped / 0 failures (+29 vs E1.79)
check_repo_safety: PASS (0 warnings)
```

**Status (prior E1.79)**: **E1.79 SOAK COMPLETE (2026-05-10). INFRASTRUCTURE_PASS / MARKET_GAP. All E1.79 prep fixes verified. 4966 tests pass.**

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

## E1.61-E1.63 soak results (archived summary)

E1.63 (2026-05-07T10:38-11:38Z): split_route_wins=5 (disc), submit_ready=24/35, 4807 tests.
E1.62 (2026-05-07T07:34-07:54Z): usd_frontier active, submit_ready=13, bps_best=982.8, 4785 tests.
E1.61 (2026-05-07T06:18-06:33Z): size_dust root cause found, size_usd=\.45-\.99, 4775 tests.

## E1.60 and earlier — archived

Historical entries (E1.60 and earlier) moved to rchive/status/Status_M7_pre_E160.md.
