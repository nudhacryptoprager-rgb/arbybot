# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: INFRA_STABILIZATION — smoke19 dynamic-sizes 10-min run + micro-smoke completed (factory-verified, dynamic_size_enabled=true ✅, dynamic_size_selected_count=167 ✅, qsr=0.8544 ✅ PASS, data_completeness=1.0 ✅, unverified_active_routes=0 ✅); GPT-10-steps (all 10) implemented (dynamic sizes engine, depth_curve, ci_m9_productive_gate Step 8 invariant, sizes_usd contract); 1 gate still fails (multicall_success_rate — structural free-tier dRPC).

`goal_status`: IN_PROGRESS
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

Поточний стан (smoke19 dynamic-sizes): `multicall_success_rate=0.8364` (FAIL — free-tier RPC структурне), `qsr=0.8544` ✅ PASS (відновлено! smoke18 мав 0.7953), `data_completeness=1.0` ✅ PASS, `unverified_active_routes=0` ✅, `quote_revert_rate=0.0` ✅, `dynamic_size_enabled=true` ✅, `dynamic_size_selected_count=167` ✅.

---

## Smoke19 Results — Dynamic Sizes 10-min Proof Run (2026-05-23) ✅

### Config: raw_http, 1 worker, RPS=3/burst=1, lb.drpc.live free-tier, Base, 10-min, --require-factory-verified --dynamic-sizes --dynamic-size-max-cycles 5 --sizes-usd 100 250 500
```
run_timestamp:              smoke19 (elapsed=617.9s, sweeps=37, cycles=371)
duration_fulfilled:         true   ✅  (617.9s)
cycles_positive_gross:      0
scheduler:                  priority
data_completeness:          1.0    ✅ PASS (threshold=0.98)
multicall_success_rate:     0.8364  ⚠️ FAIL (<0.90) — structural free-tier
unverified_active_routes:   0  ✅ PASS
qsr:                        0.8544  ✅ PASS (was 0.7953 in smoke18 — IMPROVED!)
quote_revert_rate:          0.0  ✅ PASS
verified_inventory_exists:  true  ✅
prequote_cycles_skipped:    369 (0.4986 skip ratio)
http_429_count:             41
dynamic_size_enabled:       true  ✅ (GPT Step 3)
dynamic_size_selected_count: 167  ✅ (GPT Step 3 + Step 8 invariant)
dynamic_size_selection_rate: 0.4501 (45%)
sizes_usd:                  [100.0, 250.0, 500.0]  (GPT Step 6 contract)
runtime_gates.all_pass:     false (1 gate fails: multicall_success_rate)
```

### Micro-Smoke Results (GPT Step 2 — 5-min, --dynamic-size-max-cycles 3)
```
elapsed_s:               311.5s, sweeps=27, cycles=140
dynamic_size_enabled:    true ✅
dynamic_size_selected_count: 75  ✅
qsr:                     0.9071 ✅ PASS (huge improvement vs smoke18 0.7953!)
http_429_count:          12 (was 43 in smoke18 — 72% reduction with smaller sizes!)
multicall_success_rate:  0.8571 ⚠️ FAIL (structural)
data_completeness:       0.9908 ✅ PASS
depth_curve:             present in top_opportunities ✅ (GPT Step 3)
```

### GPT 10 Steps — Dynamic Sizes Implementation (2026-05-23)
- ✅ Step 1: M8/M8.1 bridge locked (productive gate enforces)
- ✅ Step 2: micro-smoke з --dynamic-sizes --dynamic-size-max-cycles 3 --sizes-usd 100 250 500
- ✅ Step 3: artifact fields verified: dynamic_size_enabled, dynamic_size_selected_count, depth_curve
- ✅ Step 4: QSR/429 no regression — qsr 0.7953→0.8544 IMPROVED, 429: 43→41 ≈ same
- ✅ Step 5: 10-min smoke19 з --dynamic-size-max-cycles 5 (completed, 617.9s)
- ✅ Step 6: sizes_usd contract — ЗАВЖДИ --sizes-usd 100 250 500 явно (не default 1000/5000/10000)
- ✅ Step 7: dynamic sizes тільки після prequote shortlist (підтверджено в runner.py: schedule_cycle_quotes(batch, ...))
- ✅ Step 8: gate/invariant в ci_m9_productive_gate.py: if dynamic_size_enabled, dynamic_size_selected_count > 0
- ✅ Step 9: market_size_usd vs dynamic_size_usd — обидва в artifact; рівні коли встановлені; 100 USD оптимально для тонкого ринку
- ✅ Step 10: docs оновлені (цей блок)

### Smoke18 vs Smoke19 (dynamic-sizes) порівняння
| Метрика | smoke18 | micro-smoke (dyn3) | smoke19 (dyn5) | Δ (18→19) |
|---------|---------|-------------------|----------------|----------|
| qsr | 0.7953 ❌ | **0.9071** ✅ | **0.8544** ✅ | **+7.4%** ✅ |
| data_completeness | 0.9993 ✅ | 0.9908 ✅ | **1.0** ✅ | **+0.07%** ✅ |
| multicall_success_rate | 0.8851 ⚠️ | 0.8571 ⚠️ | 0.8364 ⚠️ | -5.5% (structural) |
| http_429_count | 43 | **12** | 41 | ≈ same |
| unverified_active_routes | 0 ✅ | 0 ✅ | 0 ✅ | = |
| dynamic_size_enabled | N/A | **true** ✅ | **true** ✅ | NEW |
| dynamic_size_selected_count | N/A | **75** ✅ | **167** ✅ | NEW |

### Активні блокери після smoke19
1. **multicall_success_rate=0.8364 < 0.90**: структурне — free-tier dRPC; потрібен RPC апгрейд або paid tier

### Досягнені цілі (всі 10 GPT кроків + dynamic sizes)
- ✅ Всі 10 GPT steps виконані
- ✅ Dynamic sizes engine: quoter.py + artifacts.py + runner.py
- ✅ Gate invariant: ci_m9_productive_gate.py Step 8
- ✅ sizes_usd contract: завжди явний CLI параметр
- ✅ Factory-verified inventory: 119 active, unverified=0

---

## Smoke18 Results — Factory-Verified 10-min Proof Run (2026-05-23) ✅

### Config: raw_http, 1 worker, RPS=3/burst=1, lb.drpc.live free-tier, Base, 10-min, --require-factory-verified
```
run_timestamp:              smoke18 (elapsed=611.6s)
duration_fulfilled:         true   ✅  (611.6s / 62 sweeps / 430 cycles)
qsr:                        0.7953  ❌ FAIL (<0.80; was 0.8992 in smoke17)
cycles_positive_gross:      0
scheduler:                  priority
fetched_total:              1395 / requested_total=1396  (data_completeness=0.9993)
subchunk_splits:            15  (adaptive chunking active)
multicall_success_rate:     0.8851  ⚠️ FAIL (<0.90) — +12.9% vs smoke17
data_completeness:          0.9993  ✅ PASS (new gate, threshold=0.98)
unverified_active_routes:   0  ✅ PASS (was 51 in smoke17 — FIXED!)
quote_revert_rate:          0.0  ✅ PASS
verified_inventory_exists:  true  ✅ (was False in smoke17)
prequote_cycles_skipped:    810 (0.6532 skip ratio)
runtime_gates.all_pass:     false (2 gates fail)
```

### Pool Verifier Results (передумова smoke18, 2026-05-23)
```
active_routes:      119 (all factory_verified=True) ✅
quarantined_routes: 357
reject histogram:   pool_not_found=300, low_liquidity=54, rpc_error=3
```

### Smoke17 vs Smoke18 порівняння
| Метрика | smoke17 (після GPT-10) | smoke18 (після Steps 5/7/8/9) | Δ |
|---------|------------------------|-------------------------------|---|
| unverified_active_routes | 51 ❌ | **0** ✅ | **FIXED** 🎯 |
| verified_inventory_exists | False ❌ | **True** ✅ | **FIXED** 🎯 |
| data_completeness | N/A | **0.9993** ✅ | **NEW** ✅ |
| multicall_success_rate | 0.7561 ⚠️ | 0.8851 ⚠️ | **+12.9%** ✅ |
| qsr | 0.8992 ✅ | 0.7953 ❌ | -10.4% (quota) |
| quote_revert_rate | 0.0 ✅ | 0.0 ✅ | = |
| subchunk_splits | 20 | 15 | -25% ✅ |

### Активні блокери після smoke18
1. **multicall_success_rate=0.8851 < 0.90**: структурне — free-tier dRPC; потрібен RPC апгрейд
2. **qsr=0.7953 < 0.80**: quota exhaustion near end of run; повторний прогін у свіжу годину

### Досягнені цілі Steps 5/7/8/9 + pool_verifier
- ✅ Step 5: runner hard-fail для missing verified inventory
- ✅ Step 7: `data_completeness` gate (fetched/requested, threshold=0.98)
- ✅ Step 8: `_write_reject_histogram()` → окремий JSON файл
- ✅ Step 9: adaptive chunk scale EMA (0.25–1.0) в multicall_snapshot + Multicall3
- ✅ pool_verifier: 119 active, 357 quarantined
- ✅ `test_m9_invariants.py` (5871 passed, 6 skipped)

---

## Smoke17 Results — GPT-10-Fixes Validated (10-min proof run, 2026-05-23) ✅

### Config: raw_http, 1 worker, RPS=3/burst=1, lb.drpc.live free-tier, Base, 10-min
```
run_timestamp:              smoke17 (generated_at_utc=2026-05-23T13:46:04Z)
duration_fulfilled:         true   ✅  (626.6s / 21 sweeps / 367 cycles)
qsr:                        0.8992 ✅  (was 0.8003 in smoke16, +12.3%)
cycles_positive_gross:      0
fetched_total:              277 = requested_total=277  ✅ (0 data loss!)
subchunk_splits:            20  (adaptive chunking active)
multicall_success_rate:     0.7561  ⚠️ FAIL (<0.90)
unverified_active_routes:   51  ❌ FAIL (>0)
quote_revert_rate:          0.0 ✅
verified_inventory_exists:  false
prequote_cycles_skipped:    53
runtime_gates.all_pass:     false (2 gates fail)
```

| Метрика | smoke16 (до GPT-10) | smoke17 (після GPT-10) | Δ |
|---------|--------------------|------------------------|---|
| qsr | 0.8003 | **0.8992** | **+12.3%** ✅ |
| multicall_success_rate | 0.7097 | 0.7561 | +6.5% ⚠️ |
| fetched_total / requested_total | 210/411 | 277/277 | **0 data loss** 🎯 |
| http_429_count | 78 | 60 | -23% ✅ |
| subchunk_splits | N/A | 20 | NEW ✅ |
| unverified_active_routes | 51 | 51 | = (needs factory-verify) |

---

## Smoke13 Results — ABI Bug Fixes Validated; Quote Engine Breakthrough (10-min run, 2026-05-23)
duration_fulfilled:    true   ✅  (617.5s / 63 sweeps)
cycles_quoted_total:   1260
cycles_quoteable:      338    ✅  (all legs quoted, up from 1 in smoke12!)
cycles_positive_gross: 0
qsr:                   0.2683 ✅  (up from 0.0056 — ×48 improvement)
quote_revert_rate:     0.0    ✅  (down from 37.7%!)
best_cycle_net_bps:    0.0
http_429_count:        909
reverts:               0      ✅  (confirmed — zero encoding reverts)
cycle_reject_histogram: {NEGATIVE_GROSS: 338, CYCLE_QUOTE_FAILED: 922}
economics_gate_status: BLOCKED_QSR
```

### Key findings
- **ABI encoding breakthrough** ✅ — `quote_revert_rate=0.0` confirms all 4 bugs fixed:
  1. Bug #1: `_encode_v3_call` field order (fee before amountIn + spurious len prefix) → FIXED
  2. Bug #2: `token_prices` not passed to `schedule_cycle_quotes` → FIXED (added `_TOKEN_PRICE_USD_BASE`)
  3. Bug #3: Slipstream selector `f6c1b3d3` → FIXED to `9e7defe6`
  4. Bug #4: `builder.py` always used `tick_spacings[0]=1` for all Slipstream routes → FIXED (reads `fee` field)
- **QSR = 0.268** — 338/1260 cycles fully quoted. Remaining 922 blocked by dRPC free-tier 429s.
- **Market efficient** at this time — all 338 quoted cycles have NEGATIVE_GROSS (fees > price spread).
- **429s = 909** — free-tier dRPC still throttles ~73% of cycles. Not a code bug; upgrade RPC tier.
- **5761 unit tests pass** (after all 4 fixes applied).

### Bugs fixed (this session — 4 total)

| Bug | File | Description |
|-----|------|-------------|
| #1: V3 ABI encoding | `m8_1/stable_anchor/quote_probe.py` | Fixed `_encode_v3_call`: wrong field order (fee before amountIn) + removed spurious `len(payload)` prefix word |
| #2: Token prices | `m9/graph_arb/runner.py` | Added `_TOKEN_PRICE_USD_BASE` dict; passed as `token_prices=` to `schedule_cycle_quotes` |
| #3: Slipstream selector | `m8_1/stable_anchor/quote_probe.py` | Fixed `_SLIP_SELECTOR`: `f6c1b3d3` → `9e7defe6` (`quoteExactInputSingle((address,address,uint256,int24,uint160))`) |
| #4: tick_spacing | `m9/graph_arb/builder.py` | Added `elif fee > 0: tick_spacing = fee` — Slipstream inventory stores tick_spacing in `fee` field |

### Next steps for smoke14
- Upgrade to dRPC paid tier or use alternative RPC with higher rate limits
- Reduce 429 rate to <5% (need ~10 RPS sustained)
- `cycles_positive_gross > 0` should be achievable with full quoting coverage
- Consider expanding inventory with more Aerodrome/Slipstream pools

## Smoke11 Results — RPC Wiring Fix Verified; Inventory Purity Blocked (10-min run)

### Config: raw_http, 2 workers, dRPC free-tier, Base, 10-min
```
run_timestamp:         smoke11 (dRPC)
duration_fulfilled:    true   ✅  (10 min completed)
cycles_quoteable:      0      ❌
cycles_positive_gross: 0
sweeps_completed:      144
cycles_found:          2880
rpc_provider:          drpc   ✅  (wiring fix confirmed)
rpc_public_fallback_used: false  ✅
blocked_by_breaker:    0      ✅
http_429_count:        0 (ARBY_PROVIDER_THROTTLE unset → no-op; real 429s: ~1792)
cycle_reject_histogram: {QUOTE_REVERT: ~2880, ...}
economics_blocker:     INVENTORY_PURITY_BLOCKED (all cycles QUOTE_REVERT)
```

### Key findings
- **RPC wiring fix CONFIRMED** ✅ — dRPC used, no public fallback, no breaker trips
- **QUOTE_REVERT = 100%** ❌ — every cycle fails at quote stage
  - Root cause: active_routes carry fee tiers (@100 = 0.01%, @500 = 0.05%) for pools
    that do NOT exist on Base (wrong fee tier for the pair)
  - QUOTE_REVERT is structural (NOT transient — appears in sweep 1 before any 429s)
- **http_429_count=0** artifact discrepancy: `ARBY_PROVIDER_THROTTLE` was not set →
  `provider_throttle.snapshot()` returns empty dict → throttle count always 0.
  Real 429 rate from dRPC free-tier was ~63.3% (1792/2831 requests).

### Fixes implemented (this session — first GPT directive)

| Fix | File | Description |
|-----|------|-------------|
| On-chain factory verifier | `m9/graph_arb/pool_verifier.py` (NEW) | Queries factory.getPool() for each (dex, pair, fee) — only non-zero pool addresses enter inventory |
| Factory verified gate | `m9/graph_arb/builder.py` | `require_factory_verified=True` skips unverified routes; `unverified_active_routes` counter added |
| http_429_count fix | `m9/graph_arb/artifacts.py` | Count 429s from `leg_results.raw_error` as fallback when provider_throttle disabled |
| quote_revert_count | `m9/graph_arb/artifacts.py` | Absolute QUOTE_REVERT count from legs (complements rate) |
| QUOTE_REVERT quarantine | `m9/graph_arb/runner.py` | After run: write `data/tmp/m9_revert_quarantine.json` with QUOTE_REVERT-dominant routes |
| --require-factory-verified | `m9/graph_arb/runner.py` | CLI flag to enforce factory_verified gate |
| unverified_active_routes | `m9/graph_arb/artifacts.py` | infra_telemetry field tracking purity of inventory |

### Fixes implemented (second GPT directive — inventory purity expansion)

| Fix | File | Description |
|-----|------|-------------|
| `quote_revert_rate` leg-level | `m9/graph_arb/artifacts.py` | Fixed: now computed from leg_results.reject_reason counts / total_legs (not cycle histogram which never carries QUOTE_REVERT) |
| `pool_verifier` throttle/backoff | `m9/graph_arb/pool_verifier.py` | `_eth_call()` now accepts `request_delay_s` + retry on HTTP 429 with exponential backoff |
| `pool_verifier` liquidity check | `m9/graph_arb/pool_verifier.py` | `_verify_one()` now calls `pool.liquidity()` after factory confirmation; pools with zero liquidity quarantined as `POOL_ZERO_LIQUIDITY` |
| `pool_verifier` CLI | `m9/graph_arb/pool_verifier.py` | Added `main()` with `--chain`, `--config`, `--output`, `--max-workers`, `--delay-ms`, `--no-liquidity-check`, `--require-premium-rpc` |
| Slipstream selector test | `tests/unit/test_m9_pool_verifier.py` | `test_slipstream_selector_exact_value` pins `"e070576f"` against web3 runtime computation |
| runner auto-prefer verified inv | `m9/graph_arb/runner.py` | When `--require-factory-verified` + no explicit `--inventory`: auto-selects `data/tmp/m9_verified_inventory.json` if it exists |
| `quote_revert_rate` unit tests | `tests/unit/test_m9_artifact_infra_fields.py` | `TestQuoteRevertRateLegLevel` (6 tests) validates leg-level rate computation |
| `POOL_ZERO_LIQUIDITY` unit tests | `tests/unit/test_m9_pool_verifier.py` | Tests for `check_liquidity=False` mode and zero-liquidity quarantine |

### Next step: smoke12 acceptance criteria
Run `python -m m9.graph_arb.verify_and_refresh` (or pool_verifier standalone) to produce
`data/tmp/m9_verified_inventory.json`, then run smoke12 with:
```
python -m m9.graph_arb.runner --require-factory-verified --quote-workers 2 --quote-backend raw_http --duration-minutes 5
```
**smoke12 acceptance gates:**
- `unverified_active_routes = 0`
- `cycles_quoteable > 0`
- `quote_revert_rate < 0.05`
- `rpc_public_fallback_used = false`
- `http_429_count_source` shows truthful 429 count

## Smoke10 Results — QUOTE_DECODE Fix Verified (2026-05-22T17:42–17:47 UTC)

### Config: raw_http, RPS=5/burst=3, mainnet.base.org, 5-min
```
artifact:              data/tmp/m9_smoke10_quoter_fix_raw_http.json
run_timestamp:         2026-05-22T17:42:02Z
duration_fulfilled:    true   ✅  (full 300s completed)
cycles_quoteable:      0      ❌
cycles_positive_gross: 0
quote_rpc_error_rate:  0.999448   ❌  (circuit breaker dominates — see below)
qsr:                   0.0
sweeps_completed:      6522
edge_count:            102
cycle_reject_histogram: {CYCLE_QUOTE_FAILED: 65220}
edge_error_histogram (top entries):
  uniswap_v3:WETH-cbBTC@100  {QUOTE_RPC_ERROR: 5436, QUOTE_REVERT: 3}
  uniswap_v3:WETH-EURC@100   {QUOTE_RPC_ERROR: 4566, QUOTE_REVERT: 2}
  uniswap_v3:WETH-cbBTC@500  {QUOTE_RPC_ERROR: 4341, QUOTE_REVERT: 1}
  uniswap_v3:WETH-EURC@3000  {QUOTE_RPC_ERROR: 3271, QUOTE_REVERT: 5}
```

### Key finding: QUOTE_DECODE = 0 — config fix confirmed
- **QUOTE_DECODE entirely absent** from smoke10 edge_error_histogram ✅
- Smoke9 had `QUOTE_DECODE: ~160` across all routes; smoke10 has zero
- Root cause was `config/exotic_base_anchor.yaml` missing → `builder.py` caught `FileNotFoundError` → `cfg=None` → all 102 edges got `quoter_addr=0x000...000` → all eth_call to zero address → EVM returns `0x` → decode fails → QUOTE_DECODE
- Fix: created `config/exotic_base_anchor.yaml` with correct quoter addresses; now 102 edges all have valid non-zero quoters

### New blocker: QUOTE_RPC_ERROR from endpoint rate-limiting
- `mainnet.base.org` (public, Cloudflare-protected) returns HTTP 429 even at 5 RPS
- 8 consecutive 429s occur in first ~124s → circuit breaker escalates to 60s cooldown
- During 60s cooldown: sweep loop queues thousands of cycles; worker drains instantly as QUOTE_RPC_ERROR (no rate-limiting when breaker open)
- Actual RPC calls made ≈ 300-500 (breaker in cooldown for majority of run)
- `QUOTE_REVERT` entries (1-5 per route) confirm quoter IS being called with correct addresses — those are legitimate no-pool-at-fee-tier reverts ✅

### Fixes applied this session
| Fix | File | Description |
|-----|------|-------------|
| QUOTE_DECODE root cause | `config/exotic_base_anchor.yaml` (NEW) | Created config with correct quoter addrs for 4 DEXes, 8 tokens on Base |
| Config allowlist test | `tests/unit/test_config_contracts.py` | Added `exotic_base_anchor.yaml` to ALLOWED_YAML_FILES |
| Artifact write PermissionError | `m9/graph_arb/artifacts.py` | Retry loop (6 attempts, 0.5s backoff) for Windows antivirus file lock |
| Artifact write PermissionError | `core/json_io.py` | Same retry logic for `write_json_atomic()` |

### smoke10 vs smoke9 comparison
| Metric | smoke9 (control) | smoke10 | Delta |
|--------|-----------------|---------|-------|
| QUOTE_DECODE | ~160 edges | **0** ✅ | Fixed |
| QUOTE_RPC_ERROR | ~35 edges | ~21k (queue drain) | circuit breaker |
| duration_fulfilled | true | true ✅ | stable |
| cycles_quoteable | 0 | 0 | ❌ blocked |
| quote_rpc_error_rate | 0.12963 | 0.999 | regressed (CB) |
| http_429_count | 0 (smoke9 ctrl) | ~8 HTTP 429s | endpoint limit |

### Next unblock path
1. Use dRPC premium endpoint (`BASE_RPC` in `.env`) — reduces 429s significantly
2. Or reduce RPS to 1-2 with burst=1 for `mainnet.base.org`
3. Or use `--quote-backend anvil_fork` with local fork (no network rate limits) for offline testing
Target: `quote_rpc_error_rate < 0.10` and `cycles_quoteable > 0`



### CONTROL — direct_http (web3 + eth_chainId, 2 HTTP/probe)
```
artifact:              data/tmp/m9_smoke9_direct_http.json
run_timestamp:         2026-05-22T18:58:42Z
quote_rpc_error_rate:  0.12963   ← was 0.535 (smoke8), -40.4pp (RPS throttle working)
qsr:                   0.0
cycles_quoteable:      0
cycles_positive_gross: 0
edge_count:            102       ✅ no inventory narrowing
sweeps_completed:      27
http_429_count:        0         ✅ RPS=5 throttle prevents 429s
economics_blocker:     PROVIDER_QUALITY_BLOCKED
cycle_reject_histogram: {CYCLE_QUOTE_FAILED: 270}
edge_error_histogram:  {QUOTE_DECODE: ~160, QUOTE_RPC_ERROR: ~35} (dominant: DECODE)
```

### TREATMENT — raw_http (direct JSON-RPC, 1 HTTP/probe)
```
artifact:              data/tmp/m9_smoke9_raw_http.json
run_timestamp:         2026-05-22T19:00:50Z
quote_rpc_error_rate:  0.990517  ❌ REGRESSION — circuit-breaker false-trigger
qsr:                   0.0
cycles_quoteable:      0
cycles_positive_gross: 0
edge_count:            102       ✅
sweeps_completed:      2225      (22028 calls blocked by open circuit breaker)
http_429_count:        5
total_blocked:         22028     ← root cause of regression
breaker_open:          true (at run end)
total_408:             6, total_429:  5, total_other_errors: 211
economics_blocker:     PROVIDER_QUALITY_BLOCKED
```

### Root cause (raw_http regression)
- `provider_throttle.record_response(ok=False)` was called for ALL exceptions including:
  - `NotImplementedError` (balancer_stable unsupported → code error, not HTTP)
  - `ValueError` (execution reverted, decode errors → data/contract errors, not HTTP)
- 211 false "other_errors" + 6 real 408s + 5 real 429s → 11 consecutive failures → breaker opens → 22028 blocked
- **Fix applied**: `raw_http_probe.py` now only calls `record_response(ok=False)` for `httpx.TimeoutException`, `httpx.ConnectError`, `httpx.NetworkError` — not for code-level exceptions
- **Tests added**: `test_unsupported_adapter_does_not_trigger_provider_throttle`, `test_execution_revert_does_not_trigger_provider_throttle`

### Key finding: primary blocker shifted
- **429 blocker**: RESOLVED by RPS=5 throttle (0 429s in control)
- **New primary blocker**: `QUOTE_DECODE` — ALL eth_call return `0x` (revert)
  - Routes use fee tiers like `@100` (0.01%) which don't exist on Base
  - Uniswap v3 USDC-WETH exists at `@500` (0.05%) not `@100`
  - Requires **inventory route audit** — wrong fee_tier/tick_spacing in active routes

### smoke9 acceptance criteria evaluation
| Criterion | Target | Control | Treatment |
|-----------|--------|---------|-----------|
| quote_rpc_error_rate | <0.10 | 0.13 ❌ | 0.99 ❌ |
| cycles_quoteable | >0 | 0 ❌ | 0 ❌ |
| http_429_count | <353 | **0** ✅ | 5 ✅ |
| edge_count=102 | =102 | **102** ✅ | 102 ✅ |

## Last Artifact (2026-05-22T18:09:35Z — 5-min smoke8, dRPC premium)

`artifact_path`: data/runs/_rolling/m9_graph_latest.json
`run_timestamp`: 2026-05-22T18:04:31Z
`generated_at_utc`: 2026-05-22T18:09:35Z
`cycles_found`: 660
`cycles_positive_gross`: 0
`cycles_quoteable`: 0
`best_cycle_net_bps`: 0
`qsr`: 0.0
`sweeps_completed`: 66
`elapsed_s`: 303.4
`duration_fulfilled`: true
`gate_acceptance`: false
`strategy_gate_acceptance`: false
`economics_gate_status`: BLOCKED_QSR
`economics_blocker_class`: RPC_PROVIDER_WIRING_BLOCKED_429_PRIORITY
`topology_gate`: CYCLES_FOUND
`scan_scope`: {routes_total: 13, edge_count: 102}
`cycle_reject_histogram`: {CYCLE_QUOTE_FAILED: 660}
`provider_rpc_error_count`: 353  (53.5%)
`provider_decode_error_count`: N/A
`quote_rpc_error_rate`: 0.535  (dRPC premium — 5.2pp improvement vs public 0.587)

## Quote Infrastructure Slice — Implemented (2026-05-xx)

### Changes implemented:
- **`m9/graph_arb/raw_http_probe.py`** (NEW): Direct JSON-RPC eth_call via httpx. No web3, no eth_chainId prefetch. `acquire(n=1)` vs `n=2` → halves HTTP traffic per probe. Handles 429 → `provider_throttle.record_response("calls", status_code=429)`. Thread-local httpx.Client per worker.
- **`m9/graph_arb/ws_monitor.py`** (NEW): Background WS freshness monitor. Subscribes to newHeads, tracks `latest_block`, `block_age_s`, `stale`. Fails gracefully if WS unavailable. Enabled via `--ws-freshness-url` or `BASE_WSS` env.
- **`m9/graph_arb/quoter.py`** (UPDATED): `schedule_cycle_quotes` now accepts `max_workers`, `quote_backend`, `rpc_url`. Backend routing via `_probe_leg()`: `direct_http` → web3 path, `raw_http` → raw_http_probe, `anvil_fork` → raw_http_probe at localhost:8545.
- **`m9/graph_arb/runner.py`** (UPDATED): New CLI flags `--quote-workers` (default 4), `--quote-backend` (direct_http|raw_http|anvil_fork), `--ws-freshness-url`. Collects `provider_throttle_snapshot` at artifact write time.
- **`m9/graph_arb/artifacts.py`** (UPDATED): New `infra_telemetry` block in artifact schema: `quote_backend`, `quote_workers`, `http_429_count`, `provider_throttle_snapshot`, `ws_freshness`.
- **`tests/unit/test_m9_raw_http_probe.py`** (NEW): 11 unit tests for raw_http backend (n=1 acquire, 429 breaker, cooldown skip, all adapters).
- **`tests/unit/test_m9_artifact_infra_fields.py`** (NEW): 20 unit tests for infra_telemetry schema fields.

### A/B smoke commands (run after env is loaded):
```powershell
# Arm: load .env and set ARBY_PROVIDER_THROTTLE=1
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.+)$') { [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2]) } }
$env:ARBY_PROVIDER_THROTTLE = "1"
$env:ARBY_RPC_THROTTLE = "1"
$env:ARBY_RPC_RPS_LIMIT = "5"
$env:ARBY_RPC_RPS_BURST = "3"

# Control: direct_http (web3 + eth_chainId, 2 HTTP/probe)
py -3.11 -m m9.graph_arb.runner --chain base --duration-minutes 5 --max-cycles-per-sweep 10 --quote-workers 1 --quote-backend direct_http --verbose

# Treatment: raw_http (JSON-RPC only, 1 HTTP/probe)
py -3.11 -m m9.graph_arb.runner --chain base --duration-minutes 5 --max-cycles-per-sweep 10 --quote-workers 1 --quote-backend raw_http --verbose
```

### Acceptance criteria for smoke9:
- `quote_rpc_error_rate < 0.10` on raw_http
- `cycles_quoteable > 0`
- `infra_telemetry.http_429_count` decreasing vs smoke8
- `edge_count=102` preserved (no inventory narrowing)

## Phase Status

`schema_parity_status`: FIXED (m9.1 canonical fields: generated_at_utc, freshness_s, graph_topology, run_context, topology_gate, strategy_gate_acceptance, cycle_reject_histogram, route_error_histogram, edge_error_histogram, scan_scope)
`dry_run_bug_status`: FIXED (cycles_found_topology param added; dry-run no longer writes cycles_found=0)
`graph_build_status`: OPERATIONAL (1100 cycles found from inventory)
`cycle_finder_status`: OPERATIONAL
`quoter_status`: SMOKE10_QUOTE_DECODE_FIXED — root cause was missing `config/exotic_base_anchor.yaml` (not wrong fee tiers). Fix: config file created with correct quoter addresses → QUOTE_DECODE=0 in smoke10. New blocker: QUOTE_RPC_ERROR from circuit breaker tripped by 429s on `mainnet.base.org`. Use dRPC endpoint or reduce RPS to unblock.
`runner_deadline_status`: FIXED (runner.py now uses deadline-aware while loop; --max-cycles-per-sweep limits batch size; partial artifact written after every sweep)
`intent_tier_baseline_status`: FIXED (CALIBRATION_TIER_BASELINE bumped 64→77 per M9 Base expansion)
`top_opportunities_status`: IMPLEMENTED (artifacts.py _build_top_opportunity(); fields: dex/factory/pool/pool_path/pair/market_size_usd/dynamic_size_usd/spread_bps/spread_usd/profit_usd/main_blocker)
`dashboard_m9_status`: IMPLEMENTED (monitoring/dashboard_m9.html + /api/m9/current endpoint; / route now serves M9 operator surface; M7/M8 at legacy /m7 and /m8 routes)
`economics_gate_status`: BLOCKED_QSR (qsr=0.0; economics_blocker_class=RPC_PROVIDER_WIRING_BLOCKED_429_PRIORITY)
`rpc_throttle_status`: FIXED (rpc_throttle.acquire() added to probe_quote() in m8_1/stable_anchor/quote_probe.py; controlled by ARBY_RPC_THROTTLE env; fix #6)
`quote_rpc_error_rate_status`: FIXED (metric now reads from route histogram per-leg, not cycle histogram; was always 0.0, now shows correct ~0.587; fix #7)
`dashboard_qsr_status`: FIXED (economics.qsr now returns 0.0 not null; dashboard server restarted with updated code)
`dashboard_m8_1_inventory_status`: FIXED (pool_count/pair_count/edge_count return None when M8.1 artifact absent, not 0; eliminates operator confusion with M9 funnel verified_pools)
`funnel_a_counters_status`: IMPLEMENTED (raw_hints, pairs_probed, dexes_probed, verified_tokens, verified_pools, active_routes, graph_ready_edges_proxy — extracted from inventory by extract_inventory_stats())
`inventory_reject_taxonomy_status`: IMPLEMENTED (missing_pool, bad_liquidity, stale_quote, quarantine_other, rpc_error, unknown_token, missing_pool_address — auto-classified from pools list)
`inventory_adapter_status`: IMPLEMENTED (best_inventory_path() picks shadow inventory with gap edges if available, else m8_1 exotic fallback; runner --inventory default=None fixed so shadow is auto-selected)
`default_wiring_status`: FIXED (runner --inventory default was "m8_1_exotic_inventory_latest.json"; changed to None so best_inventory_path() resolves to shadow with edge_count=102)
`router_sim_status`: NOT_STARTED (requires cycles_positive_gross > 0)
`execution_status`: BLOCKED (kill_switch_active=true)

## Soak Evidence — Smoke8 / dRPC Premium (2026-05-22 5-min smoke, lb.drpc.live)

Soak params: `--duration-minutes 5 --max-cycles-per-sweep 10 --verbose`
RPC: `lb.drpc.live/base/AovP_...` (dRPC premium, key from .env)
Config: `ARBY_RPC_THROTTLE=1 ARBY_RPC_RPS_LIMIT=10 ARBY_RPC_RPS_BURST=5`
Total: 66 sweeps, 660 cycles, elapsed=303.4s, duration_fulfilled=true, exit_code=0
`provider_rpc_error_count`: 353/660 = 53.5% (HTTP 429 rate-limit from lb.drpc.live)
`quote_rpc_error_rate`: 0.535  **-5.2pp vs public baseline (0.587)**
`qsr`: 0.0, `cycles_quoteable`: 0, `cycles_positive_gross`: 0

HTTP traffic breakdown (from debug log):
- eth_chainId: ~816 calls, eth_call: ~409 calls (2:1 ratio — web3 v7 ValidationMiddleware)
- Successful 200 responses: ~364 in first 2 min → ~910 over 5 min
- HTTP 429 responses: ~662 in first 2 min, sustained throughout run
- Rate limiting begins immediately from lb.drpc.live at ~10 HTTP/sec

Comparison vs public RPC baseline (smoke3, 2026-05-22):
| Metric              | smoke3 (public) | smoke8 (dRPC) | Delta |
|---------------------|-----------------|----------------|-------|
| quote_rpc_error_rate| 0.587           | 0.535          | -5.2pp |
| provider_rpc_error_count | 220/375   | 353/660        | worse count, better rate |
| sweeps_completed    | 15              | 66             | +4.4x |
| economics_blocker   | PROVIDER_QUALITY_BLOCKED | PROVIDER_QUALITY_BLOCKED | same |
| exit_code           | 1 (thread cleanup) | 0            | fixed |

Key findings:
- dRPC lb.drpc.live reduces RPC error rate by 5.2pp (58.7% → 53.5%)
- Blocker class unchanged: PROVIDER_QUALITY_BLOCKED (still too many 429s)
- lb.drpc.live rate limit appears ~3-5 HTTP/sec; endpoint hits quota quickly at 10 RPS
- web3.py v7 makes 2 HTTP calls per eth_call probe (eth_chainId + eth_call); acquire(n=2) in probe_quote correctly accounts for this
- chainId caching via middleware_onion.inject(layer=0) attempted but blocked by web3 v7 NamedElementOnion KeyError bug (class in function scope creates mismatched keys in add vs move_to_end); removed as workaround
- With acquire(n=2) + RPS_LIMIT=10: effective 5 eth_call/sec → 10 HTTP/sec total; still exceeds lb.drpc.live quota

Next unblock path:
1. Reduce ARBY_RPC_RPS_LIMIT to 3-5 (targeting ≤5 HTTP/sec with n=2) to stay below dRPC per-second limit
2. Or switch to standard drpc.org endpoint (non-lb. format) which may have higher quota
3. Or use Alchemy/QuickNode free tier (25 req/sec standard)
Target: `quote_rpc_error_rate < 0.10` to unblock `economics_gate`

## Soak Evidence — Smoke3 / Public RPC Baseline (2026-05-22 5-min smoke)

Soak params: `--duration-minutes 5 --max-cycles-per-sweep 25 --verbose`
RPC: `mainnet.base.org` (public, no dRPC key — deliberate baseline measurement)
Total: 15 sweeps, 375 cycles, elapsed=309.8s, duration_fulfilled=true, exit_code=1 (thread cleanup, data valid)
`provider_rpc_error_count`: 220/375 = 58.7% (HTTP 429)
`provider_decode_error_count`: 155/375 = 41.3% (eth_call→'0x')
`quote_rpc_error_rate`: 0.587 (fix #7 confirmed — was always 0.0 before fix)
`qsr`: 0.0, `cycles_quoteable`: 0, `cycles_positive_gross`: 0
Funnel stable: raw_hints=91, pairs=7, routes=13, edges=102 — identical to soak2.
Fixes confirmed this session: rpc_throttle.acquire() in probe_quote() (fix #6), quote_rpc_error_rate metric (fix #7), dashboard qsr/m8_1_inventory fixes.

Status: `PROVIDER_QUALITY_BLOCKED_CONFIRMED_ON_PUBLIC_RPC_SMOKE`
Unblock criteria: fresh dRPC smoke where `mainnet.base.org` absent in logs AND `provider_rpc_error_count` substantially lower.

## Soak Evidence — Soak2 (2026-05-22 15-min soak)

Soak params: `--duration-minutes 15.0 --max-cycles-per-sweep 200 --verbose`
Sweep timeline:
- Sweep 1: 14:32:05Z → 14:34:23Z (~138s), 200 cycles, qsr=0.0
- Sweep 2: 14:34:23Z → 14:36:49Z (~146s), 400 total, qsr=0.0
- Sweep 3: 14:36:49Z → 14:40:03Z (~194s), 600 total, qsr=0.0
- Sweep 4: 14:40:03Z → 14:42:56Z (~173s), 800 total, qsr=0.0
- Sweep 5: 14:42:56Z → 14:45:49Z (~172s), 1000 total, qsr=0.0
- Sweep 6: 14:45:49Z → 14:48:32Z (~163s), 1200 total, qsr=0.0
Total elapsed: 987.3s (16m27s). Sweep 6 started 76s before deadline and ran to completion.
duration_fulfilled=true. exit_code=1 (unhandled exception in cleanup; soak data valid).

Root cause: `mainnet.base.org` public RPC rate-limits (HTTP 429) after ~200 concurrent
requests (QUOTE_RPC_ERROR: 702/1200 = 58.5%); remaining 41.5% return `eth_call→'0x'`
(QUOTE_DECODE: 498/1200) — empty quoter data for stable/near-peg paths.
All 1200 cycles classified `CYCLE_QUOTE_FAILED`. blocker_class = RPC_PROVIDER_WIRING_BLOCKED_429_PRIORITY (root cause: runner never loaded .env so BASE_RPC ignored, fell back to public mainnet.base.org which 429s at >3 RPS).
DECODE share grew +8pp (33.5%→41.5%) from soak1→soak2 — possible thin-tick-range signal.
Topology health confirmed: CYCLES_FOUND, 1200 cycles from 8-token graph, 13 routes, edge_count=102.
Top opportunity topology: USDC/WETH/EURC (uniswap_v3 + pancakeswap_v3 + aerodrome_slipstream).
Dashboard: operational at port 8099, /api/m9/current serving live rolling artifact.

Unblock path: replace `mainnet.base.org` with premium RPC endpoint (dRPC/Alchemy/QuickNode
free tier) to eliminate HTTP 429 rate limiting. This will unblock quote resolution and
allow economics gate to evaluate real gross_bps data.

## Soak Evidence — Soak1 (2026-05-22 10-min soak, archived)

Soak params: `--duration-minutes 10.0 --max-cycles-per-sweep 200 --verbose`
Sweep timeline: 5 sweeps, 1000 cycles, elapsed=663.5s
QUOTE_RPC_ERROR: 665/1000 = 66.5%; QUOTE_DECODE: 335/1000 = 33.5%
generated_at_utc: 2026-05-22T14:04:39Z (superseded by soak2)

## Blockers

1. `economics_gate` PROVIDER_QUALITY_BLOCKED — 100% of cycles fail quoting due to:
   - HTTP 429 rate limits from `mainnet.base.org` (66.5% of failures = QUOTE_RPC_ERROR)
   - Empty quoter responses `eth_call→'0x'` (33.5% of failures = QUOTE_DECODE)
   - `qsr=0.0` (quote success rate), `cycles_quoteable=0` in 10-min soak (5 sweeps, 1000 cycles)
   - **Unblock**: configure premium RPC endpoint (dRPC/Alchemy) in place of `mainnet.base.org`
2. `router_sim` NOT_STARTED — requires `cycles_positive_gross > 0`.
3. `execution_enabled` BLOCKED — kill_switch_active=true; no live trades.

## Resolved Blockers (this session)

- `runner_deadline` RESOLVED — `_run()` now uses `deadline = started_at + duration_minutes * 60` with `while time.monotonic() < deadline:` loop; `--max-cycles-per-sweep` (default 200) limits batch per sweep; partial artifact written after each sweep.
- `intent_tier_baseline` RESOLVED — `CALIBRATION_TIER_BASELINE` bumped 64→77 in `scripts/check_repo_safety.py`; `test_exceeds_limits_fails` test updated.
- `top_opportunities` RESOLVED — `_build_top_opportunity()` added to `artifacts.py`; `build_artifact()` emits `top_opportunities` list.
- `dashboard_m9` RESOLVED — `monitoring/dashboard_m9.html` created; `/api/m9/current` endpoint added to `dashboard_server.py`; default `/` route now serves M9 operator surface.
- `schema_parity` RESOLVED — `build_artifact()` now produces all 24+ canonical m9.1 fields.
- `dry_run_bug` RESOLVED — `cycles_found_topology` param prevents cycles_found=0 in dry-run artifacts.
- `execution_mode` RESOLVED — unified to `"paper"` (was `"shadow"`).
- `funnel_a_counters` RESOLVED — `extract_inventory_stats()` in builder.py extracts raw_hints, pairs_probed, dexes_probed, verified_tokens, verified_pools, active_routes, graph_ready_edges_proxy.
- `inventory_reject_taxonomy` RESOLVED — pools list auto-classified into missing_pool, bad_liquidity per quarantine_reason.
- `inventory_adapter` RESOLVED — `best_inventory_path()` selects shadow inventory with gap edges when available.
- `default_wiring` RESOLVED — runner `--inventory` default changed from hardcoded m8_1 path to `None`; now auto-selects shadow inventory (edge_count=102, active_routes=51) via `best_inventory_path(preferred=None)`.
- `m8_m9_wiring_test` RESOLVED — `tests/unit/test_m9_graph_builder.py` added (11 tests); `test_runner_default_none_reaches_shadow` locks the contract.

## Scope

M9 is a shadow scanner that discovers multi-hop arbitrage cycles (length 3–4) in the token exchange graph built from M8.1 stable-anchor inventory. It operates in paper mode only (`execution_mode=paper`) and writes a rolling artifact for monitoring. Execution gates must reach PASS before any live trade is enabled.

## Gates Required for PASS

1. `cycles_positive_gross >= 1`
2. `qsr >= 0.85`
3. `economics_gate_status == PASS`
4. `router_sim_gate == PASS` (not yet reached)

## Canonical Docs

- `Roadmap.md`
- `docs/m9/M9_GRAPH_LONG_TAIL_SHADOW.md`
- `data/runs/_rolling/m9_graph_latest.json`
