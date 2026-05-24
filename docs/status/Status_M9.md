# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: ALL_PASS_SMOKE25_PUBLICNODE_RPC — **3/3 consecutive all_pass runs achieved** (smoke23+smoke24+smoke25); qsr=0.9779 ✅, mc_rate=1.0 ✅, data_completeness=1.0 ✅, unverified=0 ✅, quote_revert_rate=0.0 ✅, http_429/408/5xx=0. **M8→M9 bridge unlock condition MET.** Policy gate satisfied — ready for M8/M8.1 integration review.

`goal_status`: BRIDGE_UNLOCK_CONDITION_MET
`schema_family`: m9_graph_arb
`schema_revision`: m9.1
`execution_enabled`: false
`kill_switch_active`: true
`execution_mode`: paper

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

## Smoke20 Results — Dynamic Sizes 15-min Real-RPC Soak (2026-05-23) ✅ (4/5 gates)

### Config: `config/exotic_base_anchor.yaml` + `scan_params.sizes_usd=[100,250,500]` (config-locked), `dynamic_size_max_cycles=3`, raw_http, 1 worker, RPS=3/burst=1, lb.drpc.live free-tier, Base, 15-min
```
run_timestamp:                smoke20 (elapsed=917.1s / 900s requested)
duration_fulfilled:           true   ✅
sweeps_completed:             83
cycles_found:                 420
cycles_quoteable:             367
cycles_positive_gross:        0      (flat market, expected)
cycles_router_sim_eligible:   0
best_cycle_net_bps:           0.0
sizes_usd:                    [100, 250, 500]   ✅ (from config scan_params)

# runtime_gates
multicall_success_rate:       0.8716  ❌ FAIL (<0.90)  — structural free-tier dRPC
data_completeness:            0.9991  ✅ PASS (>=0.98)
unverified_active_routes:     0       ✅ PASS
qsr:                          0.8738  ✅ PASS (>=0.80)
quote_revert_rate:            0.0     ✅ PASS
all_pass:                     false

# dynamic_size telemetry (key feature)
dynamic_size_enabled:           true   ✅
dynamic_size_selected_count:    224    (+57 vs smoke19)
dynamic_size_selection_rate:    0.5333 (~53%)
verified_inventory_exists:      true

# prequote funnel
prequote_cycles_skipped:        410
prequote_skip_ratio:            0.494   (~49% pre-filter efficiency)

# infra
rpc_provider:                   drpc (free tier, chain_env_BASE_RPC)
actual_http_calls:              1498
http_429_count (artifact):      44
http_429 (raw log):             715  (retries amplify)
multicall_stats:                attempted=218, success=190, http_429=99, retry=71, subchunk_splits=26
blocked_by_breaker:             0  (breaker held)

# rejects
cycle_reject_histogram:
  NEGATIVE_GROSS:               367  (88%, flat market)
  CYCLE_QUOTE_FAILED:           53   (12%, 429 propagation)
```

### Verdict
- ✅ **Dynamic sizes engine works** (selected_count=224, selection_rate=0.53, config-locked sizes confirmed)
- ✅ **QSR improved** from 0.8544 → 0.8738
- ✅ **Code-level invariants all pass** (4/5 runtime_gates)
- ❌ **multicall_success_rate=0.8716** still structurally below 0.90 due to free-tier dRPC 429-storm
- **Path to PASS**: upgrade dRPC tier or rotate to a second RPC endpoint; same blocker as smoke19

### Artifacts
- `data/runs/_rolling/m9_graph_latest.json` (rolling)
- `data/tmp/smoke20_log.txt` (2.2 MB raw log)
- `/memories/repo/M9_smoke20_audit.md` (audit notes)

---

## Historical Smoke Summary (condensed)

| Run | Date | Dur | Sweeps | Cycles | qsr | multicall_sr | unverified | d_complete | all_pass |
|-----|------|-----|--------|--------|-----|-------------|------------|------------|----------|
| **smoke25** | 2026-05-23 | 15m | 450 | 4483 | 0.9779✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ | **3/3 UNLOCK** |
| **smoke24** | 2026-05-23 | 15m | 451 | 4485 | 0.9766✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ |
| **smoke23** | 2026-05-23 | 15m | 452 | 2248 | 0.9742✅ | 1.0✅ | 0✅ | 1.0✅ | ✅ |
| **smoke20** | 2026-05-23 | 15m | 83 | 420 | 0.8738✅ | 0.8716❌ | 0✅ | 0.9991✅ | ❌ |
| smoke19 | 2026-05-23 | 10m | 37 | 371 | 0.8544✅ | 0.8364❌ | 0✅ | 1.0✅ | ❌ |
| smoke18 | 2026-05-23 | 10m | 62 | 430 | 0.7953❌ | 0.8851❌ | 0✅ | 0.9993✅ | ❌ |
| smoke17 | 2026-05-23 | 10m | 21 | 367 | 0.8992✅ | 0.7561❌ | 51❌ | n/a | ❌ |
| smoke13 | 2026-05-23 | 10m | 63 | 1260 | 0.2683❌ | n/a | n/a | n/a | ❌ |

Key milestones:
- smoke13: ABI encoding fixed, quote_revert_rate=0 (was 37.7%)
- smoke17: GPT-10 steps (prequote funnel, scheduler, multicall adaptive), qsr=0.8992
- smoke18: pool_verifier run → unverified_active_routes=0, factory_verified=true
- smoke19: dynamic sizes engine (selected_count=167, selection_rate=45%)
- smoke20: config-locked scan_params, selected_count=224, selection_rate=53%, qsr improved

---

## Current Blockers

1. ~~**P0**: `multicall_success_rate < 0.90`~~ **RESOLVED** — publicnode.com RPC, mc_rate=1.0.
2. ~~**P1**: Need 3 consecutive 15-min all_pass runs for bridge unlock~~ **RESOLVED** — smoke23+smoke24+smoke25 all PASS (3/3). Bridge unlock condition MET.
3. `cycles_positive_gross=0` — flat market; no arb signal at $100-500 sizes on Base. Expected until market conditions change.
4. `router_sim` NOT_STARTED — requires positive_gross shortlist.
5. `execution_kill_switch` — `kill_switch_active=true`, no live trades (paper only).
6. `prequote_min_bps=-9999` used for smoke23/24/25 (bypass). Future runs should progressively tighten threshold.

## Path to PASS

```
[DONE]    smoke23 — all_pass=True (1/3 consecutive)
[DONE]    smoke24 — all_pass=True (2/3 consecutive)
[DONE]    smoke25 — all_pass=True (3/3 consecutive)  ← M8→M9 bridge unlock condition MET
  ↓ Proof: py -3.11 scripts/ci_m9_productive_gate.py → EXIT 0  ✅
[UNLOCKED] M8/M8.1 → M9 bridge transition — policy gate satisfied
```

**Next proof-run command:**
```powershell
$env:BASE_RPC="https://base-rpc.publicnode.com"
$env:ARBY_REQUIRE_FACTORY_VERIFIED="1"
py -3.11 -m m9.graph_arb.runner `
  --chain base --config config/exotic_base_anchor.yaml `
  --duration-minutes 15 --max-cycles-per-sweep 5 `
  --quote-workers 1 --quote-backend raw_http `
  --scheduler priority --require-factory-verified `
  --dynamic-sizes --dynamic-size-max-cycles 3 `
  --prequote-min-bps -9999 `
  --artifact-path data/runs/_rolling/m9_graph_latest.json
```

## Scope

M9 is a shadow scanner for multi-hop arbitrage cycles (length 3–4) on Base chain, built from M8.1 factory-verified inventory. Paper mode only (`execution_mode=paper`). Rolling artifact: `data/runs/_rolling/m9_graph_latest.json`.

**runtime_gates thresholds** (all must pass for bridge unlock):
- `multicall_success_rate >= 0.90`
- `data_completeness >= 0.98`
- `unverified_active_routes == 0`
- `qsr >= 0.80`
- `quote_revert_rate < 0.05`
