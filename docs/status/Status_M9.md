# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: SMOKE29C_QUARANTINE_EXPANSION_PASS — Bridge unlock MET (smoke23+24+25, 3/3 all_pass). smoke29c PASS (2026-05-24): productive lane, quarantine 59 entries, mc=1.0, qsr=0.9642, 0×429, depth_quarantine_skipped=57. toxic_rate 0.9894→0.4183 (×2.4 reduction). cycles_positive_gross=38 (first ever!). best_cycle_net_bps=+1.09. economics_gate_status=NEAR_MISS.

`goal_status`: M9_SMOKE29C_QUARANTINE_EXPANSION_PASS
`schema_family`: m9_graph_arb
`schema_revision`: m9.1
`execution_enabled`: false
`kill_switch_active`: true
`execution_mode`: paper

---

## Current Focus: Pool-Quality Gate (Before M8→M9 Bridge Expansion)

**Мета**: Перед розширенням через M8→M9 bridge — заблокувати TOXIC/thin пули від домінування `top_opportunities`. Factory_verified=True = пул існує, НЕ = достатня глибина.

### Зроблено (цей цикл — GPT 10 кроків)
- ✅ **Step 4**: `core/reject_reasons.py` — 3 нові enum members: `LOW_EFFECTIVE_DEPTH`, `TOXIC_PRICE_IMPACT`, `ASYMMETRIC_POOL_DEPTH`
- ✅ **Step 5**: `data/quarantine/m9_pool_depth_quarantine.json` — evidence-based карантин: AERO/TOSHI UV3-1% (real addr `0x7e904aaf...`, підтверджено on-chain); USDC/VIRTUAL (placeholders, потребує depth probe)
- ✅ **Step 2+3**: `m9/graph_arb/pool_depth_filter.py` — новий модуль: `load_quarantined_pool_addresses()`, `is_depth_sufficient()`; пропускає placeholder адреси
- ✅ **Step 2+3**: `m9/graph_arb/builder.py` — нові параметри: `exclude_pool_addresses`, `min_effective_depth_usd`, `lane` (`discovery` | `productive`)
- ✅ **Step 7**: `m9/graph_arb/artifacts.py` — новий блок `toxic_pool_families` (top-20 пулів з toxic cycles, sorted by cycle_count)
- ✅ **Step 8**: `m9/graph_arb/artifacts.py` — `_top_cycle_sort_key` оновлено: `(is_quoteable, is_not_toxic, gross_bps)` — toxic cycles більше не домінують `top_opportunities`
- ✅ **Step 1**: `m9/graph_arb/pool_depth_probe.py` — новий standalone utility для on-chain depth measurement ($100 quote probe → `effective_depth_usd`, `price_impact_at_100usd`)
- ✅ **Step 3**: `m9/graph_arb/runner.py` — нові CLI args: `--productive-lane`, `--pool-quarantine-path`, `--min-effective-depth-usd`; `pool_quality_lane` в `scan_scope` артефакту
- ✅ **Тести**: `test_m9_graph_builder.py` — `TestPoolDepthFilter` (8 тестів); `test_m9_invariants.py` — `TestToxicPoolFamiliesInvariant` (6), `TestPoolQualityLaneInvariant` (4)

### Pending
- ✅ **Step 9**: Smoke28 з `--productive-lane` — PASS: `elapsed_s=601.2`, `qsr=0.9985`, `mc=1.0`, `data_completeness=1.0`, `http_429_count=0`, `all_pass=true`
- ⏳ Розширити depth quarantine: smoke28 показав `toxic_pool_families` top candidates `AERO_USDC`, `AERO_WETH`, `EURC_USDC`, `EURC_WETH`; зараз виключено лише 1 pool address.
- ⏳ **Step 6**: Rebuild pair universe з M8/M8.1 (pool families з depth ≥ 2 DEX)
- ⏳ **Step 10**: Розширення discovery coverage (якщо після cleanup все ще немає позитивних)
- ⏳ Заповнити USDC/VIRTUAL placeholder адреси в quarantine через `pool_depth_probe`

---

## Policy: M9_INFRA_STABILIZATION_BEFORE_M8_BRIDGE

**Transition до M8/M8.1 інтеграції заморожено до стабільних proof-runs:**

- `runtime_gates.all_pass == True` в **3 consecutive** proof-runs (15+ хвилин кожен)
- Перевірка: `py -3.11 scripts/ci_m9_productive_gate.py` має вертати `EXIT 0`
- Мінімальні пороги (вбудовані в `runtime_gates`):
  - `multicall_success_rate >= 0.90`
  - `data_completeness >= 0.98`  ← NEW (Step 7)
  - `unverified_active_routes == 0`
  - `qsr >= 0.80`
  - `quote_revert_rate < 0.05`

Поточний стан (smoke25 15-min soak, 2026-05-23): **ALL 5 GATES PASS** — `mc_rate=1.0` ✅, `qsr=0.9779` ✅, `data_completeness=1.0` ✅, `unverified_active_routes=0` ✅, `quote_revert_rate=0.0` ✅, `http_429/408/5xx=0`. **3/3 consecutive all_pass runs achieved** (smoke23+smoke24+smoke25 all PASS). **M8→M9 bridge unlock condition MET.** Policy gate satisfied.

---

## Smoke25 Results — 3/3 ALL_PASS — M8→M9 Bridge Unlock (2026-05-23) ✅ (5/5 gates)

### Config: `config/exotic_base_anchor.yaml`, `--prequote-min-bps -9999` (bypass), `--dynamic-sizes`, `dynamic_size_max_cycles=3`, raw_http, 1 worker, publicnode.com, Base, 15-min
```
elapsed_s:                    900.2  (duration_fulfilled=true ✅)
sweeps_completed:             450
cycles_found:                 4483
cycles_quoteable:             4384
cycles_positive_gross:        0    (flat market, expected)
run_timestamp:                2026-05-23T19:21:47Z

# runtime_gates — ALL PASS (3rd consecutive — bridge unlock)
multicall_success_rate:       1.0     ✅ PASS (≥0.90)
data_completeness:            1.0     ✅ PASS (≥0.98)
unverified_active_routes:     0       ✅ PASS
qsr:                          0.9779  ✅ PASS (≥0.80)
quote_revert_rate:            0.0     ✅ PASS (<0.05)
all_pass:                     true    ✅ 3/3 CONSECUTIVE

# infra — zero errors
rpc_provider:                 publicnode
http_429_count:               0
http_408_count:               0
http_5xx_count:               0
actual_http_calls:            7626

# dynamic_size telemetry
dynamic_size_enabled:         true   ✅
dynamic_size_selected_count:  1329
dynamic_size_selection_rate:  0.2965  (~30%)

# prequote funnel (bypass mode)
prequote_cycles_skipped:      17   (0.38% — non-V3/zero-price pools only)
prequote_min_bps:             -9999 (bypass for smoke validation)

# rejects
cycle_reject_histogram:
  NEGATIVE_GROSS:             4384  (97.8%, flat market)
  CYCLE_QUOTE_FAILED:         99    (2.2% failure rate)
```

### Verdict
- ✅ **3/3 CONSECUTIVE ALL-PASS** — policy gate satisfied
- ✅ **M8→M9 bridge unlock condition MET** — `py -3.11 scripts/ci_m9_productive_gate.py` EXIT 0
- ✅ **Zero infra errors** across 7626 HTTP calls (publicnode.com, zero rate limiting)
- ✅ **Stable QSR trend**: smoke23=0.9742, smoke24=0.9766, smoke25=0.9779 (improving)
- ✅ **mc_rate=1.0 stable** across all 3 runs
- Ready for M8/M8.1 → M9 bridge integration review

### Artifacts
- `data/runs/_rolling/m9_graph_latest.json` (rolling, run_ts: 2026-05-23T19:21:47Z)
- `data/tmp/smoke25_log.txt`

---

## Smoke23 Results — First ALL_PASS 15-min Soak (2026-05-23) ✅ (5/5 gates)

### Config: `config/exotic_base_anchor.yaml`, `--prequote-min-bps -9999` (bypass), `--dynamic-sizes`, `dynamic_size_max_cycles=3`, raw_http, 1 worker, publicnode.com, Base, 15-min
```
elapsed_s:                    900.7  (duration_fulfilled=true ✅)
sweeps_completed:             452
cycles_found:                 2248
cycles_quoteable:             2190
cycles_positive_gross:        0    (flat market, expected)
best_cycle_net_bps:           0.0
sizes_usd:                    [100, 250, 500] (from config scan_params)

# runtime_gates — ALL PASS (first time ever)
multicall_success_rate:       1.0     ✅ PASS (≥0.90)  — P0 RESOLVED
data_completeness:            1.0     ✅ PASS (≥0.98)
unverified_active_routes:     0       ✅ PASS
qsr:                          0.9742  ✅ PASS (≥0.80)
quote_revert_rate:            0.0     ✅ PASS (<0.05)
all_pass:                     true    ✅ FIRST TIME

# infra — zero errors
rpc_provider:                 publicnode
http_429_count:               0       (was 44 artifact / 715 raw in smoke20)
http_408_count:               0       (was many in smoke21e)
http_5xx_count:               0
actual_http_calls:            4645
blocked_by_breaker:           0

# dynamic_size telemetry
dynamic_size_enabled:         true   ✅
dynamic_size_selected_count:  1321
dynamic_size_selection_rate:  0.5876  (~59%)
sizes_usd_source:             config.scan_params  ✅

# prequote funnel (bypass mode)
prequote_cycles_skipped:      12   (0.53% — non-V3/zero-price pools only)
prequote_min_bps:             -9999 (bypass for smoke validation)

# rejects
cycle_reject_histogram:
  NEGATIVE_GROSS:             2190  (97.4%, flat market)
  CYCLE_QUOTE_FAILED:         58    (2.6% failure rate, vs 12.6% in smoke20)
```

### Fixes validated in this run
1. ✅ **CONFIG_ERROR gate**: `--no-prequote` + duration≥5 → EXIT_CONFIG_ERROR (prevents multicall bypass)
2. ✅ **http_408/500/5xx telemetry**: counters in `infra_telemetry` (all zero this run)
3. ✅ **5xx circuit breaker**: `ProviderThrottle` now tracks and soft-breaks on HTTP 5xx
4. ✅ **Scheduler prequote-skip demotion**: `record_prequote_skips()` prevents starvation
5. ✅ **RPC fix**: publicnode.com (zero 429/408/5xx, vs dRPC free-tier storm)

### Verdict
- ✅ **FIRST ALL-PASS RUN** — all 5 runtime_gates satisfied simultaneously
- ✅ **P0 blocker RESOLVED** — mc_rate=1.0 (publicnode.com, no rate limiting)
- ✅ **Scheduler starvation bug fixed** — 11 prequote-skips total (was 5/5 every sweep)
- ✅ **Zero infra errors** across 4645 HTTP calls
- ✅ **5883/5883 unit tests pass** (including new test_5xx_opens_breaker)
- 1/3 consecutive all_pass runs achieved for M8→M9 bridge unlock

### Artifacts
- `data/runs/_rolling/m9_graph_latest.json` (rolling)
- `data/tmp/smoke23_log.txt`

---

## Smoke27 Results — Economics RCA + publicnode (2026-05-24) ✅ (5/5 gates)

### Config: `config/exotic_base_anchor.yaml`, `--prequote-min-bps -9999`, `--require-factory-verified`, `--dynamic-sizes`, raw_http, 1 worker, publicnode.com, Base, 15-min
```
elapsed_s:                    898.0  (duration_fulfilled=true ✅)
sweeps_completed:             412
cycles_found:                 4099   (cycles_quoteable=4007, QUOTE_FAILED=92)
cycles_positive_gross:        0

# runtime_gates — ALL PASS
multicall_success_rate:       1.0     ✅ (≥0.90)
data_completeness:            1.0     ✅ (≥0.98)
qsr:                          0.9776  ✅ (≥0.80)
unverified_active_routes:     0       ✅
quote_revert_rate:            0.0     ✅ (<0.05)
all_pass:                     true    ✅

# infra — zero errors
rpc_provider:                 publicnode
http_429_count:               0

# economics RCA — new fields (GPT fix steps 3+5)
loss_reason_histogram:        {TOXIC_ROUTE_PRICE_IMPACT: 4007}  (100% of cycles)
toxic_route_rate:             1.0
factory_verified:             True  (all top_opportunities)
top_opp.spread_bps:           -9176.6  (AERO/TOSHI/WETH/USDC)
median_gross_bps:             -9991.2
```

### Verdict
- ✅ **ALL 5 GATES PASS** — ci_m9_productive_gate.py EXIT 0
- ✅ **0 HTTP 429** — publicnode.com confirmed clean
- ✅ **factory_verified=True** in ALL top_opportunities (GPT fix step 3)
- ✅ **TOXIC_ROUTE_PRICE_IMPACT** classifies 100% of cycles (GPT fix step 5)
- ✅ **Economics RCA confirmed on-chain**: AERO/TOSHI UV3-1% pool (0x7e904aaf),
  liquidity=8.57e+20 (89× thinner than TOSHI/WETH), 91% price impact at $100.
  Cause: pool thinness (NOT code/infrastructure).

---

## Smoke29c Results — Quarantine Expansion PASS (2026-05-24) ✅ (5/5 gates + toxic_rate PASS)

### Config: `config/exotic_base_anchor.yaml`, `--prequote-min-bps -9999`, `--productive-lane`, `--pool-quarantine-path data/quarantine/m9_pool_depth_quarantine.json` (59 entries), `--min-effective-depth-usd 1000`, raw_http, 1 worker, publicnode.com, Base, 15-min
```
elapsed_s:                    901.8  (duration_fulfilled=true ✅)
sweeps_completed:             292
cycles_found:                 1453   (cycles_positive_gross=38, CYCLE_QUOTE_FAILED=52)
cycles_positive_gross:        38     ✅ (was 0 in smoke28! first positive_gross in M9)
best_cycle_net_bps:           +1.0854 ✅ (was 0.0 in smoke28! first positive net in M9)

# runtime_gates — ALL PASS
multicall_success_rate:       1.0     ✅ (≥0.90)
data_completeness:            1.0     ✅ (≥0.98)
unverified_active_routes:     0       ✅
qsr:                          0.9642  ✅ (≥0.80)
quote_revert_rate:            0.0     ✅ (<0.05)
all_pass:                     true    ✅

# pool-quality gate
toxic_route_rate:             0.4183  ✅ (<0.90 threshold)   ← was 0.9894 in smoke28!
depth_quarantine_skipped:     57      ✅   ← was 1 in smoke28!

# economics
economics_gate_status:        NEAR_MISS   ← was BLOCKED_NO_POSITIVE_GROSS!
cycle_reject_histogram:       NEGATIVE_GROSS=1363, POSITIVE_GROSS=38, CYCLE_QUOTE_FAILED=52
loss_reason_histogram:        TOXIC=586, UNFAVORABLE_PRICES=596, FEE_DRAG=181, POSITIVE=38

# infra — zero errors
rpc_provider:                 publicnode
http_429_count:               0       (was 49 mc_429 in smoke29b with dRPC free-tier)
```

### Pool Depth Probe (ran before smoke29c)
- ok=117, fail=2 (aerodrome non-CL, no QuoterV2), toxic=36, low_depth=21
- Quarantine expanded: 3 → 59 entries (+56 new: AERO/EURC, AERO/USDC, AERO/WETH, EURC/USDC, EURC/WETH, TOSHI/WETH, VIRTUAL/WETH, LBTC/WETH, cbBTC/WETH, USDC/WETH (some), etc.)
- Key fix: `pool_depth_probe.py` now injects `quoter_addr` from config dexes block (was 100% NO_QUOTER before fix)

### Smoke28 vs Smoke29c
| Metric | smoke28 | smoke29c |
|---|---|---|
| quarantine entries | 3 | **59** (+56) |
| depth_quarantine_skipped | 1 | **57** |
| toxic_route_rate | 0.9894 | **0.4183** (×2.4 reduction) |
| cycles_positive_gross | 0 | **38** ✅ |
| best_cycle_net_bps | 0.0 | **+1.0854** ✅ |
| economics_gate_status | BLOCKED_NO_POSITIVE_GROSS | **NEAR_MISS** ✅ |
| all_pass | true | true ✅ |

### Verdict
- ✅ **ALL 5 RUNTIME GATES PASS** + toxic_rate gate PASS
- ✅ **First cycles_positive_gross=38 in M9** — quarantine removing toxic pools unblocked near-breakeven cycles
- ✅ **best_cycle_net_bps=+1.09** — not profitable after gas/slippage yet, but positive gross confirmed
- ✅ **0×429** publicnode.com confirmed (vs dRPC free-tier 49×mc_429 in smoke29b)
- ✅ **5928 unit tests pass** (+9 new tests vs smoke28 session)
- ci_m9_productive_gate.py → EXIT 0

---

## Historical Smoke Summary (condensed)

| Run | Date | Dur | Sweeps | Cycles | qsr | multicall_sr | unverified | d_complete | all_pass | RPC |
|-----|------|-----|--------|--------|-----|-------------|------------|------------|----------|-----|
| **smoke29c** | 2026-05-24 | 15m | 292 | 1453 | 0.9642✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ | publicnode — **quarantine expansion, toxic_rate=0.42, 38 positive_gross** |
| **smoke28** | 2026-05-24 | 10m | 266 | 2648 | 0.9985✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ | publicnode — **productive lane, gate validated** |
| **smoke27** | 2026-05-24 | 15m | 412 | 4099 | 0.9776✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ | publicnode — **RCA complete** |
| **smoke26** | 2026-05-24 | 15m | 76 | 669 | 0.8744✅ | 0.6826❌ | 0✅ | 0.92❌ | ❌ | drpc-free (71×429) |
| **smoke25** | 2026-05-23 | 15m | 450 | 4483 | 0.9779✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ | publicnode — **3/3 UNLOCK** |
| **smoke24** | 2026-05-23 | 15m | 451 | 4485 | 0.9766✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ | publicnode |
| **smoke23** | 2026-05-23 | 15m | 452 | 2248 | 0.9742✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ | publicnode |
| **smoke20** | 2026-05-23 | 15m | 83 | 420 | 0.8738✅ | 0.8716❌ | 0✅ | 0.9991✅ | ❌ | drpc-free |
| smoke19 | 2026-05-23 | 10m | 37 | 371 | 0.8544✅ | 0.8364❌ | 0✅ | 1.0✅ | ❌ | drpc-free |
| smoke18 | 2026-05-23 | 10m | 62 | 430 | 0.7953❌ | 0.8851❌ | 0✅ | 0.9993✅ | ❌ | drpc-free |
| smoke17 | 2026-05-23 | 10m | 21 | 367 | 0.8992✅ | 0.7561❌ | 51❌ | n/a | ❌ | drpc-free |
| smoke13 | 2026-05-23 | 10m | 63 | 1260 | 0.2683❌ | n/a | n/a | n/a | ❌ | drpc-free |

Key milestones:
- smoke13: ABI encoding fixed, quote_revert_rate=0 (was 37.7%)
- smoke17: GPT-10 steps (prequote funnel, scheduler, multicall adaptive), qsr=0.8992
- smoke18: pool_verifier run → unverified_active_routes=0, factory_verified=true
- smoke19–20: dynamic sizes engine, config-locked scan_params
- smoke23–25: publicnode RPC → mc_rate=1.0, 3/3 consecutive PASS → bridge unlock
- smoke26: drpc free-tier (provider regression demo) — mc_rate=0.68, 71×429, GATE FAIL

---

## Current Blockers

1. ~~**P0**: `multicall_success_rate < 0.90`~~ **RESOLVED** — publicnode.com RPC, mc_rate=1.0.
2. ~~**P1**: Need 3 consecutive 15-min all_pass runs for bridge unlock~~ **RESOLVED** — smoke23+smoke24+smoke25 all PASS (3/3). Bridge unlock condition MET.
3. ~~**P2**: `toxic_route_rate=0.9894`~~ **RESOLVED** — quarantine expansion 3→59 entries; toxic_rate=0.4183 (smoke29c). Pool depth probe on-chain confirmed 36 TOXIC + 21 LOW_DEPTH pools.
4. `cycles_positive_gross=38, economics_gate_status=NEAR_MISS` — 38 positive gross cycles found, but best_net=+1.09 bps (fees/gas not cleared). Pool universe may need further refinement.
5. `router_sim` NOT_STARTED — requires confirmed positive_gross shortlist.
6. `execution_kill_switch` — `kill_switch_active=true`, no live trades (paper only).
7. `prequote_min_bps=-9999` used for smoke runs (bypass). Future runs should progressively tighten threshold.

## Path to PASS

```
[DONE]    smoke23 — all_pass=True (1/3 consecutive)
[DONE]    smoke24 — all_pass=True (2/3 consecutive)
[DONE]    smoke25 — all_pass=True (3/3 consecutive)  ← M8→M9 bridge unlock condition MET
  ↓ Proof: py -3.11 scripts/ci_m9_productive_gate.py → EXIT 0  ✅
[UNLOCKED] M8/M8.1 → M9 bridge transition — policy gate satisfied
[DONE]    smoke28 — productive lane PASS (2026-05-24): quarantine_skipped=1, top_opp -9040→-18 bps ✅
[DONE]    pool_depth_probe run — ok=117/119, toxic=36, low_depth=21 ✅
[DONE]    quarantine expansion — 3→59 entries (+56 on-chain confirmed) ✅
[DONE]    smoke29c — toxic_rate=0.4183 (<0.90), cycles_positive_gross=38, best_net=+1.09 bps, EXIT 0 ✅
[PENDING]  Tighten quarantine further — ~42% toxic cycles remain (more AERO/USDC UV3 variants)
[PENDING]  Step 6: rebuild pair universe from M8/M8.1 (depth ≥ 2 DEX)
[PENDING]  router_sim validation on positive_gross shortlist
```

## Scope

M9 is a shadow scanner for multi-hop arbitrage cycles (length 3–4) on Base chain, built from M8.1 factory-verified inventory. Paper mode only (`execution_mode=paper`). Rolling artifact: `data/runs/_rolling/m9_graph_latest.json`.

**runtime_gates thresholds** (all must pass for bridge unlock):
- `multicall_success_rate >= 0.90`
- `data_completeness >= 0.98`
- `unverified_active_routes == 0`
- `qsr >= 0.80`
- `quote_revert_rate < 0.05`
