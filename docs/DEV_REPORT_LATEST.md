# DEV_REPORT_LATEST - M8 Phase 1 Complete / Steps 1-10 Done

goal_status: IN_PROGRESS  
`phase1_status`: REACHED  
`phase2_status`: NOT_STARTED  

## TL;DR (M8 Phase 1 — 2026-05-13, steps 1-10 implemented and verified)

Phase 1 foundation complete. All 10 team-lead review steps implemented and verified.
2h soak PASS. schema_revision bumped to phase1.2. 5318 unit tests pass.

```
=== M8 PHASE 1 STEPS 4-10 SUMMARY (2026-05-13) ===
Step 4+5: token0_symbol/token1_symbol/pair enrichment in recent_events (ERC20 on-demand, cached)
Step 6:   rpc_error_histogram — classifies 408_timeout/429_rate_limit/5xx_server/timeout/other
Step 7:   factory_breakdown — per-dex raw/parse_ok/errors/candidates counters in artifact
Step 8:   honeypot detector skeleton (KNOWN_SCAM→FAIL, KNOWN_LEGIT→PASS, else UNKNOWN)
          monitoring/sniper_honeypot.py — 18 tests — tests/unit/test_m8_sniper_honeypot.py
Step 9:   dry-run scoring placeholders in artifact:
          spread_bps/spread_usd/volume_usd/profit_usd=null, realizability_reason=PHASE1_NO_SCORING
          schema_revision: phase1.1 → phase1.2
Step 10:  2h soak PASS (see below)
unit tests: 5318 passed, 6 skipped, 0 failed (up from 5289)
```

```
=== M8 PHASE 1 — 2h SOAK (2026-05-13T19:54:57–21:54:59Z, 120min, Base) ===
chain:                 base (drpc)
factories:             4 (uniswap_v3, aerodrome_slipstream, aerodrome, pancakeswap_v3)
duration:              7202.7s  (240 cycles, poll_interval=30s, blocks_back=50)
schema_revision:       phase1.2
status:                ACTIVE  ✅
pool_creation_events_seen:     22
parse_ok:              22      ✅  (parse_failed=0)
snipe_candidates_total: 22     ✅
rpc_calls_made:        960
rpc_errors:            15      (1.56% — within 5% threshold)
rpc_error_histogram:   408_timeout=14, 5xx_server=1
factory_breakdown:
  uniswap_v3           raw=233  parse_ok=22  errors=7   candidates=22
  aerodrome_slipstream raw=233  parse_ok=0   errors=7   candidates=0
  aerodrome            raw=239  parse_ok=0   errors=1   candidates=0
  pancakeswap_v3       raw=240  parse_ok=0   errors=0   candidates=0
cycles_completed:      240     ✅
```

```
=== M8 PHASE 1 — 60min SOAK (reference, 2026-05-13T18:31–19:31Z) ===
parse_ok=7, parse_failed=0, candidates=7, cycles=120, rpc_error_rate=1.875%
schema_revision: phase1.1
```

```
=== M8 PHASE 1 GATE CHECK (FINAL) ===
offline smoke:         PASS ✅
Slipstream topic0:     VERIFIED ✅
10-min online smoke:   PASS ✅
60-min soak:           PASS ✅
2h soak:               PASS ✅
unit tests:            5318 passed, 6 skipped, 0 failed ✅
check_repo_safety:     PASS (1 warning) ✅
canonical rolling set: new_pool_sniper_latest.json registered ✅
```

## Archive

Historical M7 session reports (E1.81–E1.84) moved to archive/docs/DEV_REPORT_M7_history.md.
Current file intentionally contains only the active milestone (M8) report.


## TL;DR (M8 Phase 1 soak — 2026-05-13, 18:31–19:31Z)

60-хв listener-only soak для верифікації M8 Phase 1 foundation.
**Критерій: `parse_failed=0`, `snipe_candidates_total>0`, `status=ACTIVE`, `rpc_error_rate<5%`.**
Результат: PASS — 7 реальних UniswapV3 pool-creation events спарсовано без помилок, HexBytes
regression виявлено та виправлено в тій же сесії, усі unit-тести зелені (5289 passed).

```
=== M8 PHASE 1 LISTENER SOAK (2026-05-13T18:31:54–19:31:56Z, 60min, Base) ===
chain:                 base (drpc)
factories:             4 (uniswap_v3, aerodrome_slipstream, aerodrome, pancakeswap_v3)
duration:              3601.4s  (120 cycles, poll_interval=30s, blocks_back=50)
artifact:              data/runs/_rolling/new_pool_sniper_latest.json
schema_family:         m8_sniper
schema_revision:       phase1.1
status:                ACTIVE  ✅
pool_creation_events_seen:     7
parse_ok:              7       ✅  (parse_failed=0)
dedup_new:             7
filter_passed:         7
snipe_candidates_total: 7      ✅
rpc_calls_made:        480
rpc_errors:            9       (1.875% — drpc 408 timeouts, within 5% threshold)
cycles_completed:      120     ✅
generated_at_utc:      2026-05-13T17:31:56Z
```

```
=== M8 PHASE 1 REGRESSION BUG (FIXED THIS SESSION) ===
Bug:     parse_raw_log silently returned None for ALL real web3 v6 logs.
Root cause: web3 v6 eth.get_logs() returns HexBytes (bytes subclass) for
            topics/data/transactionHash. _strip_0x() called .lower() on bytes → AttributeError
            → except block returned None.  Symptom: events_seen>0, parse_ok=0, parse_failed=N.
Fix:     Added _normalize_raw_log() to convert bytes topics/data/transactionHash to
         0x-prefixed hex strings BEFORE any parser is called.
         Updated _strip_0x() to call .hex() on bytes input.
Verified: parse_ok=7, parse_failed=0 over 120 cycles / 60 minutes.
Tests:   TestParseRawLogHexBytesCompat (6 new tests) — all pass.
Files:   discovery/new_pool_listener.py
```

```
=== M8 PHASE 1 GATE CHECK ===
offline smoke:         PASS (schema_family=m8_sniper, reasons=[NO_EVENTS_YET]) ✅
Slipstream topic0:     VERIFIED (velodrome-finance/slipstream ICLFactory.sol PoolCreated event) ✅
topic0_verified:       uniswap_v3=true, aerodrome_slipstream=true,
                       aerodrome=unverified (topic0 known, verification_range_missing),
                       pancakeswap_v3=unverified (topic0 known, verification_range_missing)
                       (drpc returns 408 for eth_getLogs without topic0 filter — archive RPC needed
                        to confirm historic events; topic0 signatures are correct per ABI)
10-min online smoke:   PASS (parse_ok=1, candidates=1, status=ACTIVE) ✅
60-min soak:           PASS (parse_ok=7, candidates=7, rpc_error_rate=1.875%) ✅
unit tests:            5289 passed, 6 skipped, 0 failed ✅
canonical rolling set: new_pool_sniper_latest.json registered in
                       test_nonstop_loop_artifacts.py + test_orderflow_artifacts.py ✅
```


## Archive

Historical M7 session reports (E1.81�E1.84) moved to archive/docs/DEV_REPORT_M7_history.md.
Current file intentionally contains only the active milestone (M8) report.
