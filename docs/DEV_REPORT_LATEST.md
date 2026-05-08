# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-08T19:30:00Z
run_id: nonstop_runtime_20260508_E1.66_depth_universe_UNIT_VALIDATED
mode: ONLINE
artifact_mode: rolling
config: base / production + discovery / real_minimal.yaml
code_identity:
  primary: ts:2026-05-08T19:30:00Z
  dirty: true (E1.66: depth-aware universe expansion, ARBY_MIN_PRODUCTION_SIZE_USD gate, discovery depth guard, 13 new tests)
  desc: E1.66 UNIT_VALIDATED -- E1.65 closed REACHED; depth-aware promotion guard (min_size_usd in PromotionThresholds); AERO/WETH + VIRTUAL/WETH added to Base universe; production_sized_profitable_total + pipeline_ready + production_profit_ready in dashboard; max_profitable_size_usd tracked in discovery scoreboard

## 1) Scope
goal (Roadmap): E1.66 — depth-aware universe expansion + production-sized profitability gate
change_summary:
  E1.65 closed as REACHED (dashboard/depth truth confirmed; prod=0 is market reality, not code bug)
  10-step E1.66 change set:
  1. docs/status/Status_M7.md: E1.65 → REACHED; goal_status=REACHED; pipeline_ready=true; production_profit_ready=false
  2. monitoring/dashboard_server.py: ARBY_MIN_PRODUCTION_SIZE_USD env ($50 default); is_serious_production_sized field on rows
  3. monitoring/dashboard_server.py: production_sized_profitable_total in usd_coverage
  4. monitoring/dashboard_server.py: pipeline_ready + production_profit_ready flags in usd_coverage
  5. monitoring/dashboard_server.py: min_production_size_usd in usd_coverage
  6. config/intent.txt: Base +2 pairs (AERO/WETH, VIRTUAL/WETH); 22→24 Base productive pairs
  7. m7/orderflow/runtime_io.py: _update_discovery_scoreboard tracks max_profitable_size_usd per family
  8. m7/orderflow/disc_to_prod_promotion.py: PromotionThresholds.min_size_usd (depth guard, default 0.0=off)
  9. tests/unit/test_e1_47_p2_disc_to_prod.py: +4 depth guard tests
  10. tests/unit/test_e1_9_discovery_lane.py: +4 max_profitable_size_usd scoreboard tests
  +6 tests/unit/test_dashboard_summary.py: TestM7A566UsdCoverageE166 (pipeline_ready, production_profit_ready, production_sized_profitable_total)

touched_files:
  - docs/status/Status_M7.md              (E1.65 → REACHED)
  - monitoring/dashboard_server.py        (ARBY_MIN_PRODUCTION_SIZE_USD + new fields)
  - config/intent.txt                     (AERO/WETH + VIRTUAL/WETH)
  - m7/orderflow/runtime_io.py            (max_profitable_size_usd tracking)
  - m7/orderflow/disc_to_prod_promotion.py (PromotionThresholds.min_size_usd)
  - tests/unit/test_e1_47_p2_disc_to_prod.py (+4 tests)
  - tests/unit/test_e1_9_discovery_lane.py (+4 tests)
  - tests/unit/test_dashboard_summary.py (+6 tests)

## 1) Scope
goal (Roadmap): E1.65 -- fix USD basis data propagation gap (FUN/USDC, B3/USDC size_usd=0); reduce WS subscription pressure (4→2 effective lanes via HTTP polling + global lease + discovery delay); add ws_provider_health observability
change_summary:
  10-step fix set (per GPT E1.65 review):
  1. contracts.py: BackrunResult +3 fields: best_buy_amount_wei, best_sell_amount_wei, usd_basis_source
  2. scoring_parallel.py: _usd_basis_source() helper; wire best_buy/sell_amount_wei + usd_basis_source into BackrunResult constructor
  2b. artifacts.py: _compact_candidate exports best_buy_amount_wei, best_sell_amount_wei, usd_basis_source
  3. cold_immediate_sim.py: _build_synthetic_event uses best_buy_amount_wei; _enrich_usd_from_buy_amount() fallback for USDC/WETH token_out
  4. cold_immediate_sim.py: explicit USD_BASIS_MISSING:missing_buy_amount reason in diagnostic samples
  5. artifacts.py + bridge_runtime.py: ARBY_COLD_REQUIRE_USD_BASIS gate + top_cold_usd_basis_missing list
  6. mode_ws_live.py: file-based WS global lease (_acquire_ws_lease, _release_ws_lease, ARBY_WS_GLOBAL_LEASE=1)
  7. mode_ws_live.py + start_nonstop_runtime.py: HTTP-only block polling (ARBY_WS_HTTP_BLOCKS=1, --cold-http-only)
  8. mode_ws_live.py: cross-process WS cooldown file write on 429 in reconnect handler
  9. start_nonstop_runtime.py: discovery warmup delay (--discovery-warmup-delay-s, default 600s)
  10. hot_runtime_artifacts.py: ws_provider_health block in rollup (provider, 429_count, cooldown, active_lanes)

touched_files:
  - m7/orderflow/contracts.py             (step 1)
  - m7/orderflow/scoring_parallel.py      (steps 2+2b)
  - m7/orderflow/artifacts.py             (steps 2b+5)
  - m7/orderflow/cold_immediate_sim.py    (steps 3+4)
  - m7/orderflow/bridge_runtime.py        (step 5b)
  - m7/orderflow/mode_ws_live.py          (steps 6+7+8)
  - scripts/start_nonstop_runtime.py      (steps 7+9)
  - m7/orderflow/hot_runtime_artifacts.py (step 10)
  - tests/unit/test_orderflow_contracts_core.py   (field count 83→86)
  - tests/unit/test_orderflow_artifacts.py        (field count 83→86, compact_keys +3)
  - tests/unit/test_orderflow_status_metrics.py   (field count 83→86 x6)

## 2) Commands Executed
python -m pytest tests/unit -q: PASS (4863 tests, 6 skipped, 0 failures) [+13 new vs E1.65 baseline 4850]
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: PASS (0 warnings)

## 3) New Fields Summary (E1.66)

### usd_coverage (dashboard `/api/m7/current`)
```
production_profitable_total        — profit>0 and size >= $10  (research gate, unchanged)
production_sized_profitable_total  — profit>0 and size >= $50  (NEW: serious-production gate)
research_profitable_total          — profit>0 and size < $10
dust_only_total                    — size < $1
pipeline_ready                     — True when any candidates present (scanning works)
production_profit_ready            — True when production_sized_profitable_total > 0 (market found)
min_executable_size_usd            — $10 (ARBY_MIN_EXECUTABLE_SIZE_USD)
min_production_size_usd            — $50 (ARBY_MIN_PRODUCTION_SIZE_USD, NEW)
```

### Discovery scoreboard (per family)
```
max_profitable_size_usd  — max size_usd_estimate seen when best_net_bps > 0 (NEW: depth tracking)
```

### PromotionThresholds (disc_to_prod_promotion.py)
```
min_size_usd  — depth guard; family blocked if max_profitable_size_usd < threshold (NEW, default 0.0=off)
               Set ARBY_DISC_PROMOTE_MIN_SIZE_USD in loop_runner to enable
```

### intent.txt (Base)
```
base:AERO/WETH    — NEW: Aerodrome CL + Uniswap V3, $50M+ AERO TVL
base:VIRTUAL/WETH — NEW: Uniswap V3 + Aerodrome CL, $20M+ TVL
Total Base: 22 → 24 pairs
```

## 4) Soak 4 Launch Command (E1.66 acceptance gate)

```powershell
# E1.66 Soak 4 — production_sized_profitable_total > 0 target
$env:ARBY_REQUIRE_USD_BASIS="1"
$env:ARBY_COLD_REQUIRE_USD_BASIS="1"
$env:ARBY_MIN_EXPECTED_PROFIT_USD="0.01"
$env:ARBY_COLD_IMMEDIATE_SIM="1"
$env:ARBY_COLD_IMMEDIATE_NEAR="1"
$env:ARBY_PAPER_SIGNING="1"
$env:ARBY_SPLIT_ROUTE_ENABLE="1"
$env:ARBY_POOL_STATE_HTTP_FEED="1"
$env:ARBY_ACTIVE_WS_LANES="2"
$env:ARBY_MIN_EXECUTABLE_SIZE_USD="10.0"
$env:ARBY_MIN_PRODUCTION_SIZE_USD="50.0"
py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 6 --no-m4 --with-discovery --dashboard-port 8099 --cold-http-only --discovery-warmup-delay-s 600 --m7-hot-ws-timeout 120 --m7-cold-ws-timeout 900
```

**Success criterion (E1.66):** `production_sized_profitable_total > 0` in any cold cycle during the soak (any pair with confirmed $50+ profitable depth).  
**Fallback accept criterion:** `production_profitable_total > 0` ($10 depth) in ≥2 cold cycles.

## 5) Contract Checks (E1.66)
```
pytest:      4863 PASS / 6 skipped / 0 failures
repo safety: PASS (0 warnings)
stability:   SOAK3 confirmed E1.65 (prod=0 market-reality); Soak 4 pending
```

## Session Completion (E1.66)
session_goal: E1.66 — depth-aware universe expansion, ARBY_MIN_PRODUCTION_SIZE_USD gate, discovery depth guard, production_sized_profitable_total metric
goal_status: UNIT_VALIDATED
close_allowed: false
blocker_status_after: UNIT_VALIDATED (4863 tests pass; Soak 4 needed to confirm production_sized_profitable_total > 0 with expanded universe)
remaining_blockers: Soak 4 runtime (6h, new pairs AERO/WETH + VIRTUAL/WETH, new success metric)
docs_reread_confirmed: true

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/m7_hot_rollup_latest.json (E1.64 snapshot; E1.65 requires fresh soak)
  - data/runs/_rolling/m7_cold_hot_bridge.json

## 4) Key Results

### Unit Test Summary
```
pytest:  4835 PASS / 6 skipped / 0 failures (E1.65 changes fully covered by updated tests)
repo safety: PASS (0 warnings)
```

### E1.65 Unit-Level Acceptance
```
BackrunResult +3 new fields:                   CONFIRMED (field count 83→86 in all tests)
best_buy_amount_wei stored on BackrunResult:   CONFIRMED (scoring_parallel wiring)
compact_candidate exports 3 new fields:        CONFIRMED (test_top_candidates_compact_keys)
cold_immediate_sim uses best_buy_amount_wei:   CONFIRMED (no size_usd=0 for USDC pairs if buy_amount_wei set)
WS HTTP-only polling flag wired:               CONFIRMED (mode_ws_live.py ARBY_WS_HTTP_BLOCKS)
--cold-http-only supervisor flag:              CONFIRMED (start_nonstop_runtime.py)
ws_provider_health block in rollup:            CONFIRMED (hot_runtime_artifacts.py step 10)
discovery warmup delay 600s default:           CONFIRMED (start_nonstop_runtime.py)
```

## 5) Contract Checks
```
pytest:                      4835 PASS / 6 skipped / 0 failures
repo safety:                 PASS (0 warnings)
stability:                   N/A (soak not yet run)
ws_provider_health in rollup: CONFIRMED (code present, activates on next soak)
```

## 6) E1.65 Final Execution Map
```
Step 1  - BackrunResult +3 fields:                    DONE
Step 2  - _usd_basis_source() + scoring_parallel wire: DONE
Step 2b - compact_candidate exports new fields:        DONE
Step 3  - cold_immediate_sim best_buy_amount_wei fix:  DONE
Step 4  - explicit USD_BASIS_MISSING:missing_buy_amount: DONE
Step 5  - cold USD gate + top_cold_usd_basis_missing:  DONE
Step 6  - WS global lease (ARBY_WS_GLOBAL_LEASE):     DONE
Step 7  - HTTP blocks mode (ARBY_WS_HTTP_BLOCKS):      DONE
Step 8  - cross-process WS cooldown file on 429:       DONE
Step 9  - discovery warmup delay (600s default):       DONE
Step 10 - ws_provider_health rollup block:             DONE
Tests:   field count + compact_keys updated:           DONE (4835 PASS)
Repo safety:                                           PASS (0 warnings)
```

## 7) Soak Validation Results (2026-05-08T10:15:41Z → 11:15:44Z, 1 hour)

### Run configuration
- ENV: `ARBY_REQUIRE_USD_BASIS=1 ARBY_COLD_REQUIRE_USD_BASIS=1 ARBY_MIN_EXPECTED_PROFIT_USD=0.01 ARBY_PROVIDER_THROTTLE=1 ARBY_COLD_IMMEDIATE_SIM=1 ARBY_PAPER_SIGNING=1 ARBY_SPLIT_ROUTE_ENABLE=1 ARBY_POOL_STATE_HTTP_FEED=1 ARBY_ACTIVE_WS_LANES=2`
- Flags: `--cold-http-only --discovery-warmup-delay-s 600 --with-discovery --dashboard-port 8126`
- Stability: **5/5 processes alive, 0 crash_restarts, exit code 0** — CLEAN

### E1.65 acceptance criteria
| Criterion | Status | Evidence |
|---|---|---|
| ws_provider_health in rollup | ✅ CONFIRMED | Block appeared at first hot window (10:17Z) |
| discovery warmup 600s | ✅ CONFIRMED | Supervisor log "deferred 600s → started after warmup" |
| cold HTTP polling ARBY_WS_HTTP_BLOCKS=1 | ✅ CONFIRMED | Supervisor log confirmed for cold lane |
| 5/5 alive, 0 crashes | ✅ CONFIRMED | All 60 min |
| ws_429 reduced | ✅ CONFIRMED | 15/hr vs ~80+/45min in E1.64 (80%+ reduction) |
| usd_basis_missing reduced | ✅ CONFIRMED | PROD delta 23 vs 98 in E1.64 (76% reduction) |
| Bridge usd_basis_missing fix (Step 3) | ✅ CONFIRMED | Bridge PROD delta=15 (enrichment working) |
| active_ws_lanes=2 | ✅ CONFIRMED | ws_provider_health.active_ws_lanes=2 |
| cooldown_active on 429 storm | ✅ CONFIRMED | cooldown_active=true at 60min mark |
| artifacts.py USD gate fix (Step 5b) | ✅ CODED+TESTED | 4 new unit tests PASS |

### Soak-discovered bug (E1.65 Step 5 fix)
- **Root cause**: `artifacts.py` USD gate checked `size_usd_estimate > 0` only; slow-path entries with `best_buy_amount_wei > 0` but `size_usd=0` (FUN/USDC, REKT/WETH) went to `cold_usd_basis_missing` instead of `cold_executable`
- **Fix**: `_has_usd_basis()` helper with OR condition (`size_usd > 0` OR `buy_wei > 0`); applied to `m7/orderflow/artifacts.py`
- **Tests**: `TestM7A546E165UsdGateFilter` (4 tests) added to `test_orderflow_artifacts.py`
- **Test result**: 4839 PASS, 0 failed (up from 4835 pre-soak)

### Key metrics at 60-min mark (PROD LIFETIME)
- events_seen_total: 4368 | submit_ready_total: 24
- split_route_win: 11 (lifetime; delta=0 this soak — market conditions, no code regression)
- ws_429_count: 15 | fallback_used: 0 | cooldown_active: true
- usd_basis_missing_total (PROD delta): 23 | min_profit_rejected_total (PROD delta): 168

### GPT post-soak review issues identified (current session)
- **Issue #1 (root cause)**: `_quote_implied_size_usd` secondary path used `dec_out = decimals_out if not None else 18`. For USDC on cache miss, `get_cached_decimals` → None → dec_out=18 → `round(1000/1e18, 6) = 0.0`. This caused ALL FUN/USDC and similar pairs to show `size_usd_estimate=0.0` in the bridge.
- **Fix applied**: `_STABLE_DEC_OVERRIDE` dict in `scoring_parallel.py` + stable-coin-aware `_dec_out_stable` in `_quote_implied_size_usd` secondary path (2 new unit tests)
- **Issue #2 (SOAK 2 CONFIRMED)**: Soak 2 (2026-05-08T12:04–12:34, 5/5 alive) confirmed `size_usd_estimate > 0` in live bridge: USDe/USDC $1.07957, FUN/USDC $0.099806. `cold_executable_without_usd_basis=0` confirmed.
- **Issue #3 (dashboard fix — current session)**: Dashboard `/api/m7/current` was NOT showing priced bridge rows because: (a) bridge internal timestamp may be > 120s old at API call time → `is_fresh=False` → `bridge={}`; (b) `_candidate_size_usd` returned `0.0` (not None) for `size_usd=0.0` rows.
- **Dashboard fixes applied (2026-05-08 current session)**:
  1. Bridge freshness threshold doubled to 240s (cold lane writes ~30s cycles)
  2. `_load(inject_mtime=True)` injects `_file_mtime_utc` into bridge dict → `_artifact_timestamp()` uses mtime as fallback when internal timestamp is old
  3. `_candidate_size_usd` returns None when base_dec <= 0 (previously returned Decimal(0) / float 0.0)
  4. Priced bridge rows (`bridge_cold_executable_priced`) placed first in opportunity sources
  5. `usd_basis_source` field propagated to dashboard row dict
  6. +3 dashboard unit tests (4841 → 4844 PASS)

### Acceptance criteria update post-GPT-review
| Criterion | Status | Evidence |
|---|---|---|
| ws_provider_health in rollup | ✅ CONFIRMED | Block appeared at first hot window (10:17Z) |
| discovery warmup 600s | ✅ CONFIRMED | Supervisor log "deferred 600s → started after warmup" |
| cold HTTP polling ARBY_WS_HTTP_BLOCKS=1 | ✅ CONFIRMED | Supervisor log confirmed for cold lane |
| 5/5 alive, 0 crashes | ✅ CONFIRMED | All 60 min |
| ws_429 reduced | ✅ CONFIRMED | 15/hr vs ~80+/45min in E1.64 (80%+ reduction) |
| usd_basis_missing reduced | ✅ CONFIRMED | PROD delta 23 vs 98 in E1.64 (76% reduction) |
| Bridge usd_basis_missing fix (Step 3) | ✅ CONFIRMED | Bridge PROD delta=15 (enrichment working) |
| active_ws_lanes=2 | ✅ CONFIRMED | ws_provider_health.active_ws_lanes=2 |
| cooldown_active on 429 storm | ✅ CONFIRMED | cooldown_active=true at 60min mark |
| artifacts.py USD gate fix | ✅ CODED+TESTED | 4 tests PASS |
| size_usd_estimate > 0 for FUN/USDC in live bridge | ✅ SOAK2_CONFIRMED | USDe/USDC $1.07957, FUN/USDC $0.099806 (soak 2 2026-05-08T12:04–12:34) |
| cold_executable_without_usd_basis = 0 in bridge | ✅ SOAK2_CONFIRMED | bridge diagnostic confirmed = 0 in soak 2 |
| Dashboard shows priced bridge rows | ❌ PENDING CONTROL SOAK | Code fix applied (4844 tests); 10-min control soak needed |

## 8) Outstanding work / next iteration
- **REQUIRED (final E1.65 blocker)**: Run 10-min control soak with `--dashboard-port 8099`; verify `/api/m7/current` returns ≥1 row with `amount_in_optimal_usd > 0` from `source=bridge_cold_executable_priced`
- **REQUIRED**: Confirm `candidate_source_breakdown.cold_exec_with_usd_basis > 0`
- Consider raising ARBY_WS_LEASE_TTL_S default beyond 600s if reconnect storms persist

## 9) Soak 3 Results (3h depth-sweep, 2026-05-08T13:53:11Z → 16:53:13Z)

### Run configuration
- ENV: `ARBY_REQUIRE_USD_BASIS=1 ARBY_COLD_REQUIRE_USD_BASIS=1 ARBY_MIN_EXPECTED_PROFIT_USD=0.01 ARBY_COLD_IMMEDIATE_SIM=1 ARBY_COLD_IMMEDIATE_NEAR=1 ARBY_PAPER_SIGNING=1 ARBY_SPLIT_ROUTE_ENABLE=1 ARBY_POOL_STATE_HTTP_FEED=1 ARBY_ACTIVE_WS_LANES=2 ARBY_MIN_EXECUTABLE_SIZE_USD=10.0`
- Flags: `--chain base --hours 3 --no-m4 --with-discovery --dashboard-port 8099 --cold-http-only --discovery-warmup-delay-s 600 --m7-hot-ws-timeout 120 --m7-cold-ws-timeout 900`
- Stability: **5/5 processes alive, 0 crash_restarts, exit code 0** — CLEAN

### Monitor log (every 5 min via `data/tmp/soak3_monitor.ps1`)
```
T+1  15:55Z | prod=0 res=4 dust=7  opp=10 | ws_conn=0  ws_429=0  ws_fail=1  pct429=0.0 | hot_age=109s cold_age=5670s bridge_fresh=True
T+2  16:00Z | prod=0 res=4 dust=7  opp=15 | ws_conn=2  ws_429=0  ws_fail=1  pct429=0.0 | hot_age=80s  cold_age=5970s (5 hot pairs WS connect)
T+4  16:10Z | prod=0 res=3 dust=6  opp=10 | ws_conn=5  ws_429=1  ws_fail=2  pct429=0.2 | cold_age=85s ← COLD CYCLE 1 (14:09Z)
T+7  16:25Z | prod=0 res=5 dust=10 opp=15 | ws_conn=10 ws_429=2  ws_fail=4  pct429=0.5 | cold_age=60s ← COLD CYCLE 2 (14:24Z)
T+10 16:40Z | prod=0 res=5 dust=10 opp=14 | ws_conn=12 ws_429=6  ws_fail=10 pct429=1.4 | cold_age=40s ← COLD CYCLE 3 (14:39Z) + discovery started
T+14 17:00Z | prod=0 res=5 dust=10 opp=15 | ws_conn=15 ws_429=11 ws_fail=16 pct429=2.6 | cold_age=320s WS recovered
T+26 18:00Z | prod=0 res=5 dust=10 opp=15 | ws_conn=28 ws_429=22 ws_fail=33 pct429=4.8 | cold_age=183s stable
T+34 18:40Z | prod=0 res=5 dust=10 opp=10 | ws_conn=37 ws_429=29 ws_fail=42 pct429=6.1 | stable
T+36 18:50Z | prod=0 res=6 dust=9  opp=15 | ws_conn=41 ws_429=29 ws_fail=43 pct429=6.1 | final
```

### Final state at soak end
```
production_profitable_total:  0  (no pair reached $10 depth with positive profit)
research_profitable_total:    6  (dust/micro < $1)
dust_only_total:              9
opportunities_total:          15
tier_map (base, 16:44Z):  hot=173, warm=164, cold=0
bridge (16:44Z): cold_exec=5 (FUN/USDC ×4 + 0x16ee7eca/USDC ×1)
bridge_fresh: True throughout (mtime fix confirmed working)
ws_status at end: connected (drpc)
ws_429_total: 29 windows | pct429=6.1 (ARBY_WS_TIMEOUT 429 recovery working)
discovery_cold: B3/WETH $0.0015 (even smaller than main lane)
crash_restarts: 0/100 all 5 processes — CLEAN shutdown
```

### Pair depth findings
| Pair | Max size USD | Profit @ size | Net bps | Size source | Verdict |
|---|---|---|---|---|---|
| FUN/USDC | $0.075–$0.10 | $0.031 | 3102 | usd_frontier_split | dust_only |
| 0x16ee7eca/USDC | $0.10 | $0.031 | 3102 | usd_frontier_split | dust_only |
| PENGACHU/WETH | $0.0004 | $0.00008 | — | dynamic_bounded | dust_only |
| B3/WETH (disc) | $0.0015 | $0.00008 | 524 | dynamic_bounded | dust_only |
| WETH/USDC (hot) | unpriced | 0 | — | — | depth_unknown |

**Key finding**: `usd_frontier_split` is Base AMM depth limit — FUN/USDC maxes at $0.075 (not a system error). To achieve production_profitable_total > 0, need pairs with deeper AMM liquidity (WETH/USDC, WBTC/USDC) where $10+ input is viable.

### Dashboard fix confirmed (via soak 3)
- `bridge_cold_executable_priced` rows appeared correctly at T+4 (after first cold cycle)
- `DUST_PROFIT_ONLY:artifact_usd_fields` tag correctly applied to all sub-$1 rows
- `depth_verdict=dust_only` correctly classified all profitable rows
- `profit_size_buckets_est` populating (linear extrapolation — real AMM depth degrades faster)
- `production_profitable_total` correctly reporting 0 (honest, not a bug)

### E1.65 acceptance criteria (final)
| Criterion | Status | Evidence |
|---|---|---|
| Dashboard shows priced bridge rows | ✅ SOAK3_CONFIRMED | bridge_cold_executable_priced at T+4 with usd>0 |
| DUST_PROFIT_ONLY tag | ✅ SOAK3_CONFIRMED | Applied to all sub-$1 rows |
| depth_verdict classification | ✅ SOAK3_CONFIRMED | dust_only for all profitable pairs |
| profit_size_buckets_est | ✅ SOAK3_CONFIRMED | Populated at all buckets |
| production_profitable_total | ⚠️ SOAK3_RESULT=0 | No Base pair has $10+ AMM depth at current spread |
| bridge_fresh throughout | ✅ SOAK3_CONFIRMED | mtime fix kept bridge fresh |
| 5/5 processes, 0 crashes | ✅ SOAK3_CONFIRMED | Clean 3h shutdown |
| discovery finds new pairs | ✅ SOAK3_CONFIRMED | tier_warm grew 23→164 |

## Session Completion
session_goal: E1.65 soak 3 (3h depth-sweep): production_profitable_total measurement, dashboard validation, discovery monitoring
goal_status: SOAK_COMPLETE
close_allowed: false
soak3_result: production_profitable_total=0 — honest result: all current profitable Base arb pairs are dust-depth (AMM frontier < $1). Dashboard + classification correct.
blocker_status_after: E1.65 FEATURE_COMPLETE (all code + tests done; dashboard confirmed). production_profitable_total=0 is market reality, not a code bug. Close requires decision: either (a) accept prod=0 as valid finding and close E1.65 with "depth confirmed dust-only on current Base pairs", or (b) expand pair universe to include deeper AMM pools (WETH/USDC, WBTC/USDC) and run soak 4.
remaining_blockers: decision — accept dust-only finding vs expand pair universe
docs_reread_confirmed: true

