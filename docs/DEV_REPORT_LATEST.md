# DEV_REPORT_LATEST - E1.79 SOAK COMPLETE (INFRASTRUCTURE_PASS / MARKET_GAP)

## TL;DR (E1.79)

E1.79 SOAK COMPLETE. 1h soak finished 2026-05-10T13:12:22Z (clean exit 0). Gate: INFRASTRUCTURE_PASS / MARKET_GAP.

9 prep fixes implemented: gate profit fallback, proxy/real amount split, null-row protection, score-tuple dedup,
ARBY_DISCOVERY_LOOSE_GATES mode, unpriced bucket, gate_dropoff counters sync, 21 unit tests (4966 total).

Gate (strict):
  best_amount_in_usd:        37.99/50.0  FAIL (real depth unchanged; proxy=50.0 not counted in E1.79)
  best_expected_profit_usd:  22.44       PASS (pool 0xdc8f, session_best fallback working)
  submit_ready_delta:        0           FAIL (0 new submits in this session)
  ws_429_rate:               1.3%        PASS (12/924 windows, < 15%)
  production_sized_total:    0           FAIL (no $50+ priced candidate)
  roundtrip_profitable_delta: 0          FAIL (paper signing only)

Infra: 5/5 alive, 0 crash_restarts, 60 cold scan cycles, WS=11/924, clean exit 0

Goal delta vs E1.78: Fix 9 prep code changes verified working. E1.79 gate_profit_fallback: CONFIRMED (22.44 reads from session_best).
Blocker: MARKET_GAP — pool 0xdc8f real amount 37.99 USD, unpriced discovery pool bps=265 has no USD basis.

goal_status: BLOCKED
close_allowed: false
blocker_status_after: BLOCKED
blocker: MARKET_GAP (real depth 37.99 < 50 threshold; unpriced discovery pool bps=265 needs USD pricing)
docs_reread_confirmed: true

---

## E1.79 Soak (monitoring snapshots — bridge watcher, 3min interval)

| snap | time   | bridge_ts (UTC) | sb_amt | sb_proxy | sb_profit | ce_count | best_bps | WS     | 429_total |
|------|--------|-----------------|--------|----------|-----------|----------|----------|--------|-----------|
| 01   | 14:28  | 12:26:01        | 37.99  | 0.00     | 22.44     | 1        | 50.0     | 3/899  | 1         |
| 02   | 14:31  | 12:30:37        | 37.99  | 0.00     | 22.44     | 1        | 50.0     | 3/900  | 2         |
| 03   | 14:34  | 12:30:37        | 37.99  | 0.00     | 22.44     | 1        | 50.0     | 5/903  | 3         |
| 04   | 14:37  | 12:34:59        | 37.99  | 0.00     | 22.44     | 1        | 51.9     | 6/906  | 4         |
| 05   | 14:40  | 12:39:40        | 37.99  | 0.00     | 22.44     | 1        | 51.9     | 7/907  | 4         |
| 06   | 14:43  | 12:41:12        | 37.99  | 0.00     | 22.44     | 1        | 51.9     | 7/910  | 5         |
| 07   | 14:46  | 12:45:32        | 37.99  | 0.00     | 22.44     | 1        | 51.9     | 7/912  | 6         |
| 08   | 14:49  | 12:45:32        | 37.99  | 0.00     | 22.44     | 1        | 51.9     | 7/913  | 7         |
| 09   | 14:52  | 12:49:50        | 37.99  | 0.00     | 22.44     | 1        | 51.9     | 8/914  | 7         |
| final| 15:14  | 13:11:29        | 37.99  | 0.00     | 22.44     | 1        | 3782.6   | 11/924 | 12        |

session_best_amount_usd:          37.99 (real executable depth — E1.79 fix 2 confirmed: proxy NOT counted)
session_best_proxy_size_usd:      0.0   (new field from E1.79 fix 4; proxy=50 now separate)
session_best_near_usd (legacy):   50.0  (depth ladder proxy, informational only)
session_best_expected_profit_usd: 22.44 (E1.79 fix 1 confirmed: gate reads from session_best)
discovery bridge: bps=265 usd=null (high-spread pool found but unpriced — confirms USD pricing gap)

---

## E1.79 Prep Fixes Verification

| Fix | Description | Status |
|-----|-------------|--------|
| Fix 1 | gate reads session_best_expected_profit_usd fallback | CONFIRMED (gate shows 22.44 from session_best) |
| Fix 2 | gate uses session_best_amount_usd only (real) | CONFIRMED (proxy=50 not counted; gate shows 37.99 FAIL) |
| Fix 3 | null-row protection in _writeback_enriched_candidates | in code (no regression) |
| Fix 4 | session_best_proxy_size_usd explicit field | CONFIRMED (field=0.0 in bridge, proxy=50 stays in near_usd) |
| Fix 5 | ARBY_DISCOVERY_LOOSE_GATES mode | in code (not triggered; loose_gates=0 in soak) |
| Fix 6 | unpriced_but_depth_probeable bucket | dp_count=0 (no eligible unpriced pool crossed threshold) |
| Fix 7 | dedup by score tuple | in code (no regression) |
| Fix 8 | gate_dropoff_* counters declared | in code |
| Fix 9 | gate_dropoff_sim_admission/usd_basis synced | in code |
| Tests | 21 tests (4966 total) | PASS (21 passed in 0.34s) |

---

## Changed Files (E1.79)

| File | Kind | Notes |
|---|---|---|
| m7/orderflow/cold_immediate_sim.py | edit | null-row protect, LOOSE_GATES, gate_dropoff counters, proxy/real split |
| m7/orderflow/bridge_runtime.py | edit | score-tuple dedup, unpriced_but_depth_probeable bucket |
| scripts/post_soak_pass_gate.py | edit | gate profit fallback, proxy exclusion from amount check |
| tests/unit/test_e1_78_bridge_writeback.py | edit | 21 tests (was 10), 5 new test classes |
| docs/status/Status_M7.md | edit | E1.79 IN_PROGRESS → soak result |

---

## E1.78 Soak (archived)

Prior soak finished 2026-05-10T11:01:13Z. Gate: INFRASTRUCTURE_PASS / MARKET_GAP.
session_best_near_usd=50.0 PASS / session_best_amount_usd=37.99 FAIL / profit=22.44 PASS / submit_delta=3 PASS.
Infra: 5/5 alive, 0 crash_restarts, 13 cold cycles, WS=10/894, clean exit 0.

---

## Session Completion

goal_status: BLOCKED (MARKET_GAP)
close_allowed: false
test_count: 4966 passed / 6 skipped / 0 failures
docs_reread_confirmed: true

---

## Changed Files

| File | Kind | Notes |
|---|---|---|
| m7/orderflow/cold_immediate_sim.py | edit | _writeback_enriched_candidates() + pending_eth_call |
| m7/orderflow/bridge_runtime.py | edit | cold_exec_with_usd_basis + session_best in _HOT_PRESERVE_ALWAYS |
| scripts/post_soak_pass_gate.py | edit | reads session_best; best_amount_effective |
| tests/unit/test_e1_78_bridge_writeback.py | new | 10 tests |
| docs/status/Status_M7.md | edit | E1.78 REACHED + full soak table + gate result |

---

## E1.78 Soak (20 snapshots x 3min = 60min)

| snap | time | cold_cyc | session_near | notes |
|------|------|----------|-------------|-------|
| 01 | +3m  | 1  | 0  | startup |
| 02 | +6m  | 2  | 0  | |
| 03 | +9m  | 3  | 25 | pool 0x9dcbb8 net_bps=1636 |
| 04 | +12m | 3  | 25 | |
| 05 | +15m | 4  | 25 | |
| 06 | +18m | 5  | 0  | cold scan race window |
| 07 | +21m | 5  | 0  | pool changed to 0xabc net_bps=50 |
| 08 | +24m | 6  | 0  | |
| 09 | +27m | 7  | 0  | |
| 10 | +30m | 7  | 0  | |
| 11 | +33m | 8  | 50 | BREAKTHROUGH pool 0xdc8f net_bps=5906 profit=22.44 |
| 12 | +36m | 9  | 50 | preserved |
| 13 | +39m | 9  | 50 | |
| 14 | +42m | 10 | 50 | WS=8/887 |
| 15 | +45m | 11 | 0  | cold scan race |
| 16 | +48m | 11 | 50 | restored by hot lane |
| 17 | +51m | 12 | 50 | WS=9/892 |
| 18 | +54m | 12 | 50 | WS=10/893 |
| 19 | +57m | 13 | 0  | cold scan race |
| 20 | +60m | -  | -  | API_ERR soak terminated 36s before poll |

session_best_near_usd: 50.0 (best_size_usd pool 0xdc8f)
session_best_amount_usd: 37.99
session_best_expected_profit_usd: 22.44

---

## Session Completion

goal_status: REACHED
close_allowed: true
test_count: 4955 passed / 6 skipped / 0 failures
docs_reread_confirmed: true