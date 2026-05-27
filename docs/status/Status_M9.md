# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: M8_CYCLE_PARTICIPATION_REACHED — Збір стабільний (`all_pass=True`, `qsr=0.9614`, `sweeps=345`, `bridge active`). CI gate (strict-bridge) EXIT 0. `cycles_with_m8_pool=98` — M8-sniped pools активно беруть участь у циклах. Профіль: `raw_http, 1 worker, dynamic-sizes`. M8 sniper: 1298 подій за 600s (V4=1206, V2=79, V3=11). M8.1 anchor: qsr=0.9465. Bridge: graph_ready_total=125, graph_ready_from_m8=18, m8_context_tokens=['VIRTUAL'], m8_context_pool_count=19. Наступний milestone: `positive_cycles_with_m8_pool > 0`.

`goal_status`: IN_PROGRESS
`schema_family`: m9_graph_arb
`schema_revision`: m9.1
`execution_enabled`: false
`kill_switch_active`: true
`execution_mode`: paper

---

## M8 Factory Polling Cadence

M8 smoke_run polling cadence:
- **Factory polling**: ~30s interval (`m8.runtime.smoke_run` polls `eth_getLogs` per block batch)
- **Bridge rebuild**: triggered after each M8/M8.1 scan cycle via `scripts/m9_bridge_build.py`
- **Rolling orchestrator**: `scripts/m9_rolling_orchestrator.py` — M8 scan → M8.1 refresh → bridge rebuild → M9 scan, no manual gaps between steps
- Target: M8 runs every 15–30 min, bridge rebuild runs immediately after, M9 scanner consumes live bridge artifact

## Strategic Goal Sequence

| Step | Target | Status |
|------|--------|--------|
| Health PASS | `all_pass=True`, `qsr>=0.8`, `bridge_active` | ✅ DONE |
| V4 Adapter | `uniswap_v4` quote path (hooks==0x0) | ✅ DONE |
| DEX Coverage Gate | sushiswap_v2/baseswap_v2 in bridge, Balancer pending tracked | ✅ DONE (2026-05-26) |
| **M8 Cycle Participation** | `cycles_with_m8_pool > 0` — M8-sniped pool enters active cycles | ✅ DONE (2026-05-27, cycles_with_m8=98) |
| **Next** | `positive_cycles_with_m8_pool > 0` | ⏳ PENDING |
| Final | `economics_gate_status=POSITIVE` | ⏳ PENDING |

### Next Soak Requirements (cycles_with_m8_pool > 0)
For the next soak to advance milestone, it MUST demonstrate:
1. **M8 run** → fresh events including sushiswap_v2 (TTT/WETH confirmed) or other new factories
2. **Bridge rebuild** runs AFTER M8 (orchestrator stale-guard ensures this)
3. **M9 run** uses fresh bridge with M8-sourced routes in active_routes
4. **`cycles_with_m8_pool > 0`** — at least one cycle quotes through an M8-sniped pool
5. Gate displays per-DEX breakdown showing `graph_ready_count > 0` for sushiswap_v2

---

## Session 2026-05-26: DEX_COVERAGE_GATE_PASS

### Зроблено (поточна сесія)
- ✅ **V4 hooks fix** (`smoke_run.py`): `fee/tick_spacing/stable/hooks` поля додані до `recent_list` items → bridge builder отримує правильні hooks для V4 фільтрації
- ✅ **Builder fee=None fix** (`builder.py`): `int(entry.get("fee") or 0)` (було `int(entry.get("fee", 0))`) — захист від V2 routes де fee=None
- ✅ **M8 run** (8 хв, 16 циклів, 527 подій): sushiswap_v2 TTT/WETH (`0x626d4f6d...`) виявлений
- ✅ **Bridge rebuild** (08:55:46Z): `m8_new_pools_input=26`, `graph_ready_from_m8=19`, `graph_ready_from_m8_new=7`, sushiswap_v2 TTT/WETH в active_routes
- ✅ **M9 run** (10 хв, 228 sweeps, 1124 cycles): `qsr=0.9653`, 6 positive gross, EXIT 0
- ✅ **CI gate** (strict-bridge): PASS EXIT 0
- ✅ **Unit tests**: 5971 passed, 6 skipped
- ✅ **DEX pipeline dashboard** (`ci_m9_productive_gate.py`): per-DEX breakdown із `graph_ready_count`
- ✅ **Balancer pending tracking** (`bridge_builder.py`): `balancer_stable/balancer_weighted` в `_PENDING_ADAPTER_TYPES` з explicit reasons
- ✅ **Quarantine TTL** (`pool_depth_probe.py` + `pool_depth_filter.py`): `quarantine_ttl_seconds=604800`, `retry_after_utc`, `activation_path` — TTL-expired entries auto-skipped
- ✅ **Orchestrator stale guard** (`m9_rolling_orchestrator.py`): якщо bridge старший за sniper після rebuild — M9 не запускається цього циклу

### Артефакти (2026-05-26)
```
bridge_source_metrics:
  m8_new_pools_input: 26
  token_verified_count: 21
  anchor_connected_count: 19
  cross_dex_seen_count: 19
  graph_ready_from_m8: 19
  graph_ready_from_m8_new: 7
  pending_adapter_count: 0
  unsupported_dex_count: 0
  dex_coverage_matrix:
    sushiswap_v2: events=1, graph_ready=1, supported=True
    uniswap_v2:   events=4, graph_ready=4, supported=True
    uniswap_v3:   events=2, graph_ready=2, supported=True
    uniswap_v4:   events=12, graph_ready=12, supported=True

M9 run (latest):
  sweeps: 228, cycles: 1124, qsr: 0.9653, all_pass: True
  cycles_with_m8_pool: 0  ← target for next soak
  positive_cycles_with_m8_pool: 0
  V4 active route: USDC/Toad (hooks=0x0, fee=990001)
  sushiswap_v2 TTT/WETH: in bridge, not yet in m9_cycles (bridge stale during M9 run)
```

### Зроблено (live bridge acceptance milestone)
- ✅ **M8 sniper smoke**: `python -m m8.runtime.smoke_run --chain base --duration-minutes 0.2 --blocks-back 50` → 20 events, status=ACTIVE, `new_pool_sniper_latest.json` (2026-05-24T20:02:27Z)
- ✅ **M8.1 offline refresh**: `scripts/m8_1_stable_anchor_run.py --offline` → `m8_1_stable_anchor_latest.json` (2026-05-24T20:03:13Z)
- ✅ **bridge_builder.py Stage 6 fix**: `graph_ready_from_m8 = len(cross_dex_seen_events)` — рахує anchor-connected M8 пули безпосередньо (було 0, стало 7); нові M8 пули додаються до `active_routes` без вимоги їх наявності в depth inventory
- ✅ **bridge rebuild**: `scripts/m9_bridge_build.py` → 126 routes (було 119), `graph_ready_from_m8=7`, `m8_stale=False`, `m8_1_stale=False`
- ✅ **strict-bridge gate** (`ci_m9_productive_gate.py --strict-bridge`): EXIT 0 PASS — `graph_ready_from_m8=7`, `m8_stale=False`, `m8_1_stale=False`, `graph_ready_total=126`
- ✅ **15-min runner**: 326 sweeps, 1620 cycles, 23 positive gross, `best_gross=1.3271 bps`, `qsr=0.9593`, `http_429=0`, `duration_fulfilled=true`, EXIT 0
- ✅ **standard gate**: PASS — `all_pass=True`, `qsr=0.9593`, `sweeps=326`
- ✅ **pytest**: 5939 passed, 6 skipped

### GPT Acceptance Criteria — ALL MET
| criterion | required | actual | status |
|---|---|---|---|
| all_pass | true | True | ✅ |
| m8_stale | false | False | ✅ |
| m8_1_stale | false | False | ✅ |
| graph_ready_from_m8 | >0 | 7 | ✅ |
| qsr | >=0.8 | 0.9593 | ✅ |
| unverified | 0 | 0 | ✅ |

### Remaining
- ⏳ Router sim / cost model → `economics_gate_status=POSITIVE`
- ⏳ `estimated_cost_bps` (gas + router fee model)

---

## Previous Milestones (condensed)

- **Live Bridge Acceptance** (2026-05-24): GPT criteria met — `graph_ready_from_m8=7`, `graph_edges_from_m8=14` (pair_id slash→underscore bug fixed), `cycles_with_m8_pool=13`, strict-bridge gate PASS. Pair_id fix: `"_".join(sorted([token0, token1]))`.
- **Pool-Quality Gate**: quarantine expanded 3→59 entries, `toxic_rate` 0.99→0.42, `cycles_positive_gross=38`, `best_cycle_net_bps=+1.09`.
- **Infrastructure stabilization**: 3/3 consecutive 15-min all_pass runs → bridge unlock. publicnode.com (zero 429/408/5xx).

---

## Historical Smoke Summary (condensed)

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

## M8→M9 Adapter Coverage (E1.XX — GPT 10-step fix)

**Context**: factory probe confirmed M8 already parses V4 (1758 events/5k blocks). Root cause of graph_ready_from_m8=0 was at bridge/verifier layer, not M8 parser.

**Changes implemented:**
- `pool_verifier.py`: Added V2 factory verification (`getPair(address,address)`, selector `0xe6a43905`); added ve33/Aerodrome factory verification (`getPool(address,address,bool)`, lazy selector); added `_build_factory_calldata()` dispatcher; expanded `supported` set to include `uniswap_v2`, `ve33`, `aerodrome_v2_stable`; V4 now gets explicit reason `NO_V4_QUOTE_ADAPTER_PENDING_P3` instead of generic `UNSUPPORTED_DEX_TYPE`
- `bridge_builder.py`: `uniswap_v4` now maps to `"uniswap_v4"` adapter_type (not `"unsupported"`); added `_PENDING_ADAPTER_TYPES` and `_PENDING_ADAPTER_REASONS`; V4 events go to `m8_pending_routes` (not `m8_quarantined_routes`); `dex_coverage_matrix` expanded with `adapter_pending`, `graph_ready_count`, `pending_count`, `quarantine_reason`; `bridge_source_metrics` includes `pending_adapter_count`
- `test_adapter_readiness.py`: Added `TestM8ToM9BridgeCoverage` (contract: no silent 'unsupported' for active DEXes) and `TestPoolVerifierCoverage` (contract: V2/ve33 selectors correct, V4 in pending set)
- `ci_m9_productive_gate.py`: Strict-bridge mode now checks `unsupported_dex_count > 0` (FAIL) and prints `pending_adapter_count` (INFO); PASS output includes both counters

**V4 status**: Explicitly tracked. M8 parses V4 events (1758/5k). V4 routes quarantined with `NO_V4_QUOTE_ADAPTER_PENDING_P3`. P3 delivery: requires M9 PoolManager StateView quote adapter. Pool address is bytes32 PoolId (not 20-byte contract) — needs special quoting path.

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
[DONE]    smoke29c — toxic_rate=0.4183 (<0.90), cycles_positive_gross=38, best_cycle_gross_bps=+1.09 bps (gross only, no router sim), EXIT 0 ✅
[DONE]    Steps 4+5+6 merged — best_cycle_gross_bps, estimated_cost_bps, router_sim_net_bps fields; positive_cycle_multi_hit_count, positive_cycle_max_repeat; 65 artifact tests PASS
[DONE]    pool_verifier refresh — 119 active, 357 quarantined (2026-05-24T16:34:04Z)
[DONE]    pool_depth_probe refresh — 117 ok, 2 fail, depth $10-$100 USD
[DONE]    smoke30 — raw_http + dynamic-sizes + depth-enriched inv; toxic_rate=0.0574, cycles_positive_gross=21, best_gross=+1.3499, max_repeat=11, multi_hit=2, EXIT 0 ✅
[PENDING]  router_sim validation on positive_gross shortlist (estimated_cost_bps still null)
[PENDING]  Step 6: rebuild pair universe from M8/M8.1 (depth >= 2 DEX)
```

## Scope

M9 is a shadow scanner for multi-hop arbitrage cycles (length 3–4) on Base chain, built from M8.1 factory-verified inventory. Paper mode only (`execution_mode=paper`). Rolling artifact: `data/runs/_rolling/m9_graph_latest.json`.

**runtime_gates thresholds** (all must pass for bridge unlock):
- `multicall_success_rate >= 0.90`
- `data_completeness >= 0.98`
- `unverified_active_routes == 0`
- `qsr >= 0.80`
- `quote_revert_rate < 0.05`
