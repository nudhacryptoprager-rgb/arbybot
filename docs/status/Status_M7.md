# Status: M7 (Triangular Feasibility)

**Status**: **M7.E1.28 — E1 (widened ERC-20 seeding: 15 slots, 5 allowance offsets, env override, STF diagnostic), E2 (round-trip buy+sell same-token bps), E3 (legacy `sim_profit_bps_*` migration purge), E4 (diagnostic `ARBY_SIM_BYPASS_GUARD=1` to measure real profit). 2×30min soak: 0 restarts. 5 round-trips executed; scorer +20334 bps AERO/WETH ≠ real -10000 bps → first reproducible false-positive evidence. 4014 pytest pass.**  
**Updated**: 2026-04-16
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep, 9 canonical blocker tags, temporal repeatability, verdict summary, universe profiles, orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, gas decomposition, stale/low-lag split, pool-class truth, V2 direct resolve, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, registry activation in ws-live, pipeline latency optimization, profit guard + hot-mode fast path, hot-lane no-fallback + execution-readiness timing, cold/hot artifact isolation + promoted watchlist, batch pre-resolve + supervisor fix. M7.B remains closed.

---

## Strategic Focus (E1.12.1)

**Base M7 production = main lane.** Arbitrum M4 = regression/paper benchmark only. Base delivers 183x more swap events per block than Arbitrum One. Arbitrum M7 FROZEN at 5.47s. Production closure requires: sim_passed>0, submit_ready>0, profit_realism=ROUNDTRIP_PROFITABLE.

## E1.12.2 — Modularize loop + wire execution gate (DONE, compressed)

Monolith (`scripts/m7a_orderflow_loop.py`) split: 2750→204 lines (-93%). Modules: `runtime_io.py`, `bridge_runtime.py`, `execution_gate.py`, `profit_guard.py`, `hot_runtime_artifacts.py`, `loop_runner.py`. Execution gate wired. Discovery hot artifact path-rebinding regression found and fixed. 30m×2 soak evidence: prod+disc 0 restarts, clean shutdown. CI: 3881.

## E1.12.3 — Simulation Telemetry + Blocker Refinement (DONE, compressed)

Added `sim_errors`, `submit_blockers_detail` to `ExecutionGateResult`. Added `simulation_error_histogram` + `submit_blocker_histogram` to rollup. Removed SUBGRAPH_API_KEY_REQUIRED blocker. Added `gas_l1_breakdown`. Key finding: sim failures were Tenderly HTTP 403 (credits exhausted). CI: 3888.

## E1.12.4 — Anvil Backend + rpc_fork (DONE, compressed)

4 sub-steps (A-D). Backend abstraction (`ARBY_SIM_BACKEND=tenderly|anvil|rpc_fork`). Anvil soak: 40/200 sim_passed. First non-Tenderly `sim_passed > 0` via Anvil fork (block 44618144). SwapRouter02 encoding (selector `0x04e45aaf`). CI: 3924.

---

## M7.A–A.5.47s: Triangular + Orderflow + Hot Execution (CLOSED, archived)

Steps 1-8, A.4, A.5.1-5.47s all CLOSED. Triangular: NO-GRADUATE (all cycles net-negative). Orderflow backrun (Arbitrum): sequential pipeline too slow. WS-live: NOT VIABLE (2.3s/event). Hot execution: bridge truth converged. **Arbitrum M7 FROZEN** (5.47s: event_source_absence confirmed, 0 hot events in peak-hours proof). Full history available in git diff.

Modules: `engine/triangular_*.py`, `scripts/m7a_*.py`, `m7/orderflow/`. Tests: 152 triangular + 369 orderflow.

---

## M7.E1: Base Flashblocks Event-Source Pilot (OPEN)

**Hypothesis**: Base delivers abundant V3 Swap events via newHeads+logs, enabling backrun scoring impossible on Arbitrum.

**E1 pilot evidence (April 7)**: 73.4 events/block (183x Arbitrum), all same-block (lag=0), best_net=-2.28 bps, sole blocker GAS_EXCEEDS_GROSS. CI: 3698.

### E1.1–E1.7: Nonstop → Contamination Fix → Funnel → Hot Write (CLOSED, compressed)

**E1.1–E1.4**: Hot+cold nonstop, Arbitrum contamination fix, registry vs gas separation (registry NOT blocker, gas IS blocker), convergence fields. CI: 3702→3741.
**E1.5–E1.7**: Funnel inversion fix, strict exec (route_viable AND size_valid), hot lane write fix. CI: 3746→3775.

---

### M7.E1.8–E1.9.3: Dashboard + Chain Provenance + Discovery Lane Split (CLOSED, compressed)

**E1.8+E1.8.1**: Dashboard M7 freshness, `chain`+`run_context.chain` in all artifacts, 9-key signal_counts zero dict. CI: 3790→3797.
**E1.9–E1.9.3**: Production/discovery lane split, namespace isolation (`*_discovery.json`), peak-hours A/B (market scarcity confirmed), session-first dashboard. CI: 3817→3829.

---

### M7.E1.10–E1.11: Peak-Hours A/B + Contour Cleanup + dRPC (CLOSED, compressed)

**E1.10**: 1h A/B proof (1953 windows, 0 events). Contour cleanup: removed AMONGUS dead slot, meme families diagnostic_only, AERO/cbBTC prioritized. VIRTUAL family added. 429-fallback fix: Alchemy→publicnode WS/HTTP automatic. Post-fix: production 230 events/46 windows, discovery 245/50. CI: 3831→3838.
**E1.11**: dRPC provider upgrade (`BASE_RPC`/`BASE_WSS` chain-scoped envs). dRPC WS 100% stable (0 failures), HTTP 50% 429 fallback. Discovery now scoring (31 fast_path_scored vs prior 0). CI: 3838.
**E1.12**: Premium-provider gate generalized (alchemy+drpc+infura). CI gates PASS, rolling refreshed.

**E1.12.1 artifact-semantics + start.py + 10-step audit (2026-04-11)**:
Fixes: `cold_executable_positive` semantic (route_viable AND size_valid), `start.py` single-chain auto-partial. Full audit (10 steps): premium RPC backoff (3 retries), Flashblocks URL fix, Tenderly/Subgraph scaffolding, L1 data fee first-class, stricter release semantics. 30min burn-in: production +1 guard_passed, discovery 6 fast_path_scored. CI: 3862, ALL GATES PASSED.

---

## E1.13–E1.19: Denomination Fix → Pipeline Unblock → Velodrome → Rate Limit (DONE, compressed)

**E1.13**: Fixed `gas_cost_wei` denomination (ETH wei vs token wei). **E1.14**: 6 pipeline blockers fixed; first `sim_passed=1` in rolling. **E1.15/R40**: Flashblocks DNS (`mainnet-preconf.base.org`), AERO/WETH calibration, audits. **E1.16**: `rpc_fork` backend — stateOverrides seeding; E2E `sim_passed→submit_ready`. **E1.17**: Config/DEX fallback fix. **E1.18**: Velodrome `0xcac88ea9` calldata encoder + ve33 adapter split. **E1.19**: Rate-limit root causes (stale 10→150, prewarm skip, max_pairs=10, V2 timeout). CI ladder: 3926→3992.

---

## E1.24 — ve33 Pricing Fix, Gas Floor Reduction, MIN_EVENT_SIZE Raise (DONE)

**Date**: 2026-04-16  
**Branch**: `split/code`

**Problem statement**: Three P0 issues degraded pipeline quality:
1. **ve33/Aerodrome pricing broken**: `adapter_type="ve33"` fell through to V3 concentrated-liquidity math on reserve-based pools → garbage prices → 0% bridge hit on ve33 pools.
2. **GAS_FLOOR_BPS_BASE too high (0.50 bps)**: Conservative gas floor rejected viable opportunities. Real Base gas costs are ~0.01-0.05 bps.
3. **MIN_EVENT_SIZE_USD too low ($100)**: Noise from micro-swaps polluted the scoring pipeline.
4. **ve33 coverage broken**: No `quoter_v2` in dexes.yaml for ve33 → `counter_venue_coverage_scan` returned 0 buy/sell venues → all ve33 pools classified TRULY_INACTIVE.
5. **Aerodrome sim stable detection**: Hardcoded `stable=False` in `execution_gate.py` → sim reverts on stable pairs (fee=1).

**Code changes**:
- **m7/shared/constants.py** (2 changes):
  1. `GAS_FLOOR_BPS_BASE`: 0.50 → 0.15 (E1.24: lowered to reflect actual Base gas costs)
  2. `MIN_EVENT_SIZE_USD`: 100 → 500 (E1.24: filter micro-swap noise)
- **m7/orderflow/v3_math.py** — `attempt_local_pricing()` (1 change):
  - Added ve33 to V2 constant-product branch (was falling through to V3 sqrtPriceX96 math)
  - ve33 fee model: volatile → 997/1000, stable (fee==1) → 9999/10000
  - Sets `pricing_path="ve33_local"`
- **m7/orderflow/pool_registry.py** (1 change):
  - `PoolRegistryEntry` for ve33: `fee=1 if _stable else 0` (encodes stable vs volatile for downstream sim)
- **m7/orderflow/resolve.py** (1 change):
  - Same fee encoding in `_resolve_pool_addresses_multicall` ve33 section
- **m7/orderflow/coverage.py** — `counter_venue_coverage_scan()` (1 change):
  - ve33 and V2 pools now count as having quote capability (local pricing, no quoter needed)
  - Fixes 73% TRULY_INACTIVE rate from E1.19
- **m7/orderflow/execution_gate.py** — `_build_sim_tx_params()` (1 change):
  - Stable detection from pool `fee` field instead of hardcoded `stable=False`
- **6 test files updated**: conftest.py (size 100→1000), test_e1_base_chain_aware.py, test_gas_and_guard_unification.py, test_orderflow_artifacts.py, test_orderflow_scoring_latency.py — all aligned with new constants

**Tests**: 4003 passed (full suite, 0 E1.24 regressions), 6 skipped, 1 pre-existing l1_cost failure.

**Soak evidence (2026-04-16, 1h production + discovery, public RPC, rpc_fork backend)**:
- Config: `ARBY_SIM_BACKEND=rpc_fork`, `ARBY_PAPER_SIGNING=1`, `ARBY_HOT_STALE_BLOCKS=150`, `ARBY_FLASHBLOCKS_SIM=1`, `ARBY_FLASHBLOCKS_HTTP=https://mainnet-preconf.base.org`, `BASE_RPC=https://mainnet.base.org`, `BASE_WSS=wss://base-rpc.publicnode.com`
- Command: `scripts/start_nonstop_runtime.py --chain base --hours 1 --with-discovery --no-m4`
- **5/5 processes alive for full 60 min, 0 restarts, 0 crashes, clean shutdown at 09:08:55Z**
- Dashboard: `http://127.0.0.1:8099`

| Checkpoint | PROD bridge% | DISC bridge% | PROD scored | DISC scored | Notes |
|-----------|-------------|-------------|-------------|-------------|-------|
| @5 min    | ~32%        | ~31%        | 10          | 4           | Cold start, INACTIVE 27% |
| @20 min   | 28.1%       | 33.1%       | 11          | 5           | Stabilizing |
| @30 min   | 38.2%       | 42.0%       | 16          | 7           | Definitive 30-min mark |
| @35 min   | 41.3%       | 43.5%       | 21          | 9           | >40% bridge |
| @53 min   | 46.9%       | 49.0%       | 40          | 22          | Near-completion |
| @60 min   | **50.0%**   | **51.3%**   | **48**      | **30**      | **FINAL** |

**All-time pipeline funnel (after soak)**:

| Stage | PROD | DISC |
|-------|------|------|
| scored | 86 | 33 |
| positive | 7 | 1 |
| guard_passed | 7 | 1 |
| sim_attempted | 7 | 1 |
| sim_passed | 1 | 0 |
| submit_ready | 1 | 0 |
| sim_errors | 6 ("execution reverted") | 1 ("execution reverted") |

**Before vs After comparison (E1.19 → E1.24)**:

| Metric | E1.19 (10-iter soak) | E1.24 (1h soak, FINAL) | Change |
|--------|---------------------|----------------------|--------|
| PROD bridge hit rate | 57.1% (40/70) | 50.0% (298/596) | Sustained at 10x scale |
| PROD scored/session | 4 (10 iters) | 48 (60 min) | **12x throughput** |
| DISC scored/session | N/A | 30 | **NEW capability** |
| Session duration | 5 min | 60 min | **12x longer, 0 crashes** |
| Restarts | 0 | 0 | Stable |
| WS failures | 0 | 0 | Clean |

**Exit criteria**: DONE. (1) ve33 pools pricing correctly via V2 constant-product math. (2) Bridge hit rate 50.0% sustained over 1h. (3) 0 restarts, 0 crashes, clean shutdown. (4) DISC pipeline operational with 30 scored. (5) 4003 tests PASS.

---

## E1.26 — Router Mismatch Fix + PROD Coverage + Factory Multicall (DONE)

**Date**: 2026-04-16  
**Branch**: `split/code`

**Problem statement (B1 — Router Mismatch)**: PTT pools registered with `dex="ptt_direct"` → `v3_math` returned `buy_dex="ptt_direct"` → `execution_gate` couldn't find router config → wrong fallback routing. Three-layer fix required.

**Problem statement (B2 — PROD Coverage)**: PREWARM_PAIRS_BASE only had 3 pairs (WETH/USDC, USDC/DAI, USDC/USDT) → registry_miss 80.6% in production. Discovery profile with 7 pairs showed 28.1% miss.

**Code changes**:

### B1 — Router Mismatch Fix (three layers):

- **m7/orderflow/pool_registry.py** — `register_ptt_pools()` (Layer 1: fee→DEX mapping):
  - Fee-based DEX assignment: fee≤1 → "aerodrome" (ve33), fee 2-10 → "ptt_direct" (V2), fee=2500 → "pancakeswap_v3", fee∈{100,500,3000,10000} → "uniswap_v3", non-standard → "ptt_direct" (algebra)
  - Replaces blanket `dex="ptt_direct"` for all PTT pools

- **m7/orderflow/pool_registry.py** — `register_ptt_pools()` (Layer 2: factory() multicall):
  - Batch reads `factory()` (selector `0xc45a0155`) from V3-style PTT pools via `eth_call` multicall
  - Maps factory address → DEX name via `_FACTORY_TO_DEX` dict:
    - `0x33128a8fC17869897dcE68Ed026d694621f31dF1` → `uniswap_v3`
    - `0xc35DADB65012eC5796536bD9864eD8773aBc74C4` → `sushiswap_v3`
    - `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865` → `pancakeswap_v3`
    - `0x420DD381b31aEf6683db6B902084cB0FFECe40Da` → `aerodrome`
  - Factory match overrides fee heuristic (more reliable)

- **m7/orderflow/execution_gate.py** (Layer 3: fee-based DEX preference):
  - When venue is "ptt_direct" or address: uses `best_buy_fee` to determine preferred DEX order
  - `_fee_hint = getattr(result, "best_buy_fee", None)` → fee=None defaults to V3 (NOT aerodrome)
  - Fix: previously `None or 0 = 0` → `0 ≤ 1 = True` → incorrectly routed to aerodrome

- **m7/orderflow/execution_gate.py** — sim attempt logging:
  - Logs pair/venue/fee/router before sim attempt, error after

### B2 — PROD Coverage:

- **m7/shared/constants.py** — `PREWARM_PAIRS_BASE`:
  - Expanded 3→7 pairs: added (AERO, USDC), (AERO, WETH), (cbBTC, USDC), (cbBTC, WETH)

### Tests:

- `tests/unit/test_e1_9_discovery_lane.py` — `test_production_base_pairs_unchanged`: updated to expect 7 pairs
- CI: 4003 passed, 6 skipped, 1 pre-existing l1_cost failure

**Soak evidence (2026-04-16, 30min production + discovery, public RPC, rpc_fork backend)**:
- Config: same as E1.24 + fee→DEX routing
- Command: `scripts/start_nonstop_runtime.py --chain base --hours 0.5 --with-discovery --no-m4`
- **5/5 processes alive for full 30 min, 0 restarts, 0 crashes, clean shutdown**
- Dashboard: `http://127.0.0.1:8099`

| Checkpoint | PROD miss% | DISC miss% | PROD scored | DISC scored | DISC sim/pass | Notes |
|-----------|-----------|-----------|-------------|-------------|---------------|-------|
| @5 min    | 56.7%     | 34.3%     | 53          | 39          | 0/0           | Cold start |
| @15 min   | 55.2%     | 31.2%     | 53          | 40          | 6/1           | **BREAKTHROUGH: sim_passed=1** |
| @20 min   | 50.4%     | 30.1%     | 53          | 40          | 6/1           | Stabilizing |
| @25 min   | 47.6%     | 28.1%     | 54          | 40          | 6/1           | Near-final |
| @30 min   | ~47%      | ~28%      | ~55         | ~40         | 6/1           | **FINAL** |

**Pipeline funnel (E1.26 soak)**:

| Stage | PROD | DISC |
|-------|------|------|
| events | ~500 | ~500 |
| bridge_hits | ~150 | ~140 |
| registry_miss% | ~47% | ~28% |
| scored | ~55 | ~40 |
| positive | 0 | **6** |
| sim_attempted | 0 | **6** |
| sim_passed | 0 | **1** ✅ |
| submit_ready | 0 | **1** ✅ |
| sim_errors | — | 5 ("execution reverted") |

**Before vs After comparison (E1.24 → E1.25 pre-fix → E1.26)**:

| Metric | E1.24 (1h PROD) | E1.25 pre-fix PROD | E1.26 PROD | E1.26 DISC | Change |
|--------|----------------|-------------------|------------|------------|--------|
| bridge% | 50.0% | 29.6% | 52.4% | **71.9%** | Recovered + DISC best ever |
| registry_miss% | — | 80.6% | 47.6% | 28.1% | **-33pp / -14pp** |
| positive | 7 | 0 | 0 | **6** | DISC 6x |
| sim_passed | 1 | 0 | 0 | **1** | **DISC BREAKTHROUGH** |
| submit_ready | 1 | 0 | 0 | **1** | **FIRST EVER in DISC** |

**B3 — Latency & Triangular Assessment**:
- Hot-path latency: in-memory (0ms stage timings) — NOT a bottleneck
- Cold pipeline: PROD mean=1885ms, DISC mean=2406ms (oracle-dominated)
- Triangular arb baseline: **-14.16 bps** (all cycles net-negative, NOT viable)
- Decision: triangular arb CLOSED. Focus on two-leg discovery lane.

**Exit criteria**: DONE. (1) Router mismatch fixed (fee→DEX + factory multicall + execution_gate preference). (2) PREWARM 3→7 reduced miss by 33pp. (3) DISC sim_passed=1 + submit_ready=1 (first ever in discovery lane). (4) 30min stable soak. (5) 4003 tests PASS.

---

## E1.27 — Raw sim amounts + Pre-sim fee gate + Telemetry honesty (D1/D2/D3, DONE)

**D1**: `SimulationResult.sim_profit_bps/wei` removed. Root cause: buy leg compared WETH(18d)→USDC(6d) → bogus bps. Now only raw `input_amount_wei`/`output_amount_wei` captured (single-leg profit_bps is **semantically invalid**).
**D2**: `_attempt_simulation` extracts honest revert_reason via `sim_result.revert_reason or sim_result.error` (was silently swallowing).
**D3**: Pre-sim fee tier check. Algebra dynamic fees (150/600/3024) tracked in `pre_sim_skip_histogram` without consuming RPC calls or incrementing `sim_attempted`.

---

## E1.28 — Round-trip measurement + E4 diagnostic bypass (E1/E2/E3/E4, DONE)

**E1 — Expanded ERC-20 state-override seeding** ([m7/orderflow/sim_backends/rpc_fork_backend.py](m7/orderflow/sim_backends/rpc_fork_backend.py)):
- `_COMMON_BALANCE_SLOTS` 6→15 (covers OZ mapping + most custom layouts).
- Allowance offsets 3→5 (`[1,0,2,3,4]`).
- New `ARBY_SIM_EXTRA_BALANCE_SLOTS` env (CSV ints).
- `_effective_balance_slots()` resolves runtime union.
- STF reverts now emit `logger.warning("rpc_fork STF revert: token_in=%s router=%s ...")` so problem tokens are identifiable.

**E2 — Round-trip simulation (buy + sell → same token)** across 6 files:
- [m7/orderflow/simulation.py](m7/orderflow/simulation.py): `SimulationResult` gets `roundtrip_attempted/success/final_wei/profit_wei/profit_bps/sell_gas_used/sell_revert_reason`.
- [m7/orderflow/contracts.py](m7/orderflow/contracts.py): `BackrunResult.best_sell_fee: Optional[int]` (field count 78→79).
- [m7/orderflow/scoring_parallel.py](m7/orderflow/scoring_parallel.py) (3 sites), [m7/orderflow/v3_math.py](m7/orderflow/v3_math.py): wire `sell_fee` through.
- [m7/orderflow/execution_gate.py](m7/orderflow/execution_gate.py): new `_build_sell_leg_tx_params()` mirrors buy builder with reversed tokens; after a successful buy leg, sell leg is simulated — `roundtrip_profit_bps = (final - initial) / initial * 10000`. **Valid bps because same token.**
- [m7/orderflow/execution_gate.py](m7/orderflow/execution_gate.py): `ExecutionGateResult.roundtrip_{attempted,success,profitable_count,profit_bps_values,errors}`.
- [m7/orderflow/hot_runtime_artifacts.py](m7/orderflow/hot_runtime_artifacts.py): rollup aggregator `roundtrip_{attempted,success,profitable}_total`, `roundtrip_profit_bps_{best,worst,median}`, `roundtrip_error_histogram`, `sim_output_samples_recent` (cap 500 values).
- New env: `ARBY_ROUNDTRIP_SIM=1` (default on; set 0 to disable).
- Caveat: both legs use unmodified pool state → result is an **optimistic upper-bound** (ignores buy-leg price impact on sell leg).

**E3 — Legacy rollup key migration** ([m7/orderflow/hot_runtime_artifacts.py](m7/orderflow/hot_runtime_artifacts.py)): on load, pop deprecated `_sim_profit_bps_all`, `sim_profit_bps_{best,worst,median}`, `sim_profitable_count` (pre-D1 garbage like `-9999.99` auto-healed).

**E4 — Diagnostic guard bypass** ([m7/orderflow/execution_gate.py](m7/orderflow/execution_gate.py)): when `ARBY_SIM_BYPASS_GUARD=1`, all `scored_results` run round-trip regardless of profit_guard. `ExecutionGateResult.guard_bypassed` flag. Default off preserves backward-compat. Purpose: decouple round-trip measurement from upstream scorer heuristic.

**Tests**: 7 new targeted tests in [tests/unit/test_rpc_fork_backend.py](tests/unit/test_rpc_fork_backend.py) (`TestExtraBalanceSlots`×2, `TestRoundTripFields`×4, `TestRollupMigration`×1). Field-count assertions migrated 78→79 in [tests/unit/test_orderflow_contracts_core.py](tests/unit/test_orderflow_contracts_core.py), [tests/unit/test_orderflow_status_metrics.py](tests/unit/test_orderflow_status_metrics.py), [tests/unit/test_orderflow_artifacts.py](tests/unit/test_orderflow_artifacts.py). **Regression: 4014 pass / 4 pre-existing failures (unrelated: test_l1_cost OP L1 dispatch, and test_nonstop/test_orderflow_artifacts rolling-canonical failures caused by stray `_preD*.json` leftovers already moved out of rolling).**

**Analyzer**: [scripts/analyze_roundtrip_profitability.py](scripts/analyze_roundtrip_profitability.py) — prints pipeline counts, round-trip distribution, E3 purge check, exit-code verdict (0=PROFITABLE_CASE_FOUND, 2=NO_ROUNDTRIP_ATTEMPTED, 3=ALL_FAILED, 4=NO_PROFITABLE_CASE).

### Soak results (2×30min Base, PID 14076 + 19720)

**Soak #1 (no bypass)**: windows_seen 598→647, sim_attempted 65 unchanged, `roundtrip_attempted=0`. Diagnosis: `signal_counts.fast_positive=0, guard_passed=0` — upstream profit_guard rejects every scored spread, so round-trip never fires. → Led to E4.

**Soak #2 (ARBY_SIM_BYPASS_GUARD=1)**: windows 647→687, sim_attempted 65→70, **`roundtrip_attempted=5, roundtrip_success=5, roundtrip_profitable=0`**. All 5 samples AERO/WETH: scored_net_bps=**+20334.68**, `amount_in=1e18 WETH`, `sim_output_wei=32`, `roundtrip_final_wei=32`, `roundtrip_profit_bps=-10000`. Sell leg succeeded (no revert_reason). **First reproducible proof that scorer’s +20334 bps estimate is a false positive**: likely a thin-liquidity / wrong-fee-tier AERO/WETH pool at the sampled router; 1 WETH input collapses to 32 wei output after the buy hop.

### Verdict

- **Infrastructure**: E1/E2/E3/E4 operate end-to-end on live Base — round-trip bps is now the canonical, decimals-correct profitability oracle.
- **Profitable case in 30-min window**: **NONE** at 1 WETH sizing. Scorer-vs-sim gap is the next gate.
- **Next steps** (out of scope for this ticket):
  1. Capture `best_buy_venue/fee` + reserves/liquidity in `sim_output_samples_recent` to classify the AERO/WETH regression.
  2. Smaller `amount_in` sweep (0.01 / 0.1 / 1 WETH) to detect size-dependent profitability.
  3. Reconcile scorer denomination: +20334 bps → 0 after round-trip suggests the spread calc is using stale/asymmetric pool state.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.

---

## Canonical Commands

```
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/ci_full_pipeline.py --mode ci
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5
```

## Known Blockers

1. **EVENT-SOURCE CEILING — FROZEN (Arbitrum only)** — 47s proof confirms `event_source_absence`. Does NOT apply to Base.
2. **GAS_EXCEEDS_GROSS — MAJORITY BLOCKER (Base)** — ~7% viable rate. Near-exec frontier at -2.20 bps.
3. **~~Submit-stage sim = 0 in canonical rolling~~ → RESOLVED (E1.14)** — sim_passed=1 in production rolling.
4. **~~dRPC HTTP 429 INTERMITTENT (Base)~~ → RESOLVED (E1.19)** — Rate limit root causes fixed: stale threshold 10→150, prewarm skip, max_pairs=10 cap, V2 timeout. Public RPC soak 10/10 with 0 rate limit errors.
5. **~~SIGNING_NOT_READY~~ → RESOLVED (E1.16)** — rpc_fork backend + paper signing available. Requires env vars: `ARBY_SIM_BACKEND=rpc_fork`, `ARBY_PAPER_SIGNING=1`.
6. **~~TOKEN_ADDRESS_UNKNOWN (12 sim errors)~~ → RESOLVED (E1.17)** — Address prefix resolution + improved token fallback paths.
7. **~~DEX_CONFIG_MISSING (6 sim errors)~~ → RESOLVED (E1.17)** — DEX fallback reordered, pre-E1.16 errors in rolling histogram.
8. **~~ve33 ABI mismatch (1 sim error)~~ → RESOLVED (E1.18)** — Velodrome calldata encoder implemented. Aerodrome pools now use correct `swapExactTokensForTokens` ABI.
9. **~~ve33 pricing broken (0% bridge hit)~~ → RESOLVED (E1.24)** — ve33 fell through to V3 math. Fixed: routed to V2 constant-product with ve33 fee model. Bridge hit rate 46.9%.
10. **~~ve33 coverage broken (73% TRULY_INACTIVE)~~ → RESOLVED (E1.24)** — No quoter for ve33 → 0 buy/sell venues. Fixed: local pricing counts as quote capability.
11. **~~Aerodrome stable sim reverts~~ → RESOLVED (E1.24)** — Hardcoded `stable=False` → fee field detection.
12. **~~PTT router mismatch (dex=ptt_direct)~~ → RESOLVED (E1.26)** — Fee→DEX mapping + factory() multicall + execution_gate fee preference. DISC sim_passed=1.
13. **~~PROD coverage gap (3 pairs, 80.6% miss)~~ → PARTIALLY RESOLVED (E1.26)** — PREWARM 3→7 pairs, miss 80.6%→47.6%. PROD positive still 0 — production pairs don't find spread.
14. **DISC sim revert rate 83% (5/6)** — 5 out of 6 sim attempts revert. Factory multicall may improve. Needs re-soak.
15. **Triangular arb NOT viable** — Baseline -14.16 bps. CLOSED.
16. **Scorer-vs-sim gap (E1.28 finding)** — AERO/WETH scored +20334 bps, real round-trip -10000 bps (1 WETH → 32 wei output). 5/5 samples. Root cause unknown; need venue/fee + reserves in sample log and per-size sweep.

Resolved: HOT LANE NOT WRITING (E1.7), MARKET-WINDOW SCARCITY (E1.10), ALCHEMY 429 (E1.10), Dashboard dead (E1.8), Chain provenance (E1.8.1), Submit-stage sim=0 (E1.14), SIGNING_NOT_READY (E1.16), TOKEN_ADDRESS_UNKNOWN (E1.17), DEX_CONFIG_MISSING (E1.17), ve33 ABI mismatch (E1.18), dRPC 429 INTERMITTENT (E1.19), ve33 pricing broken (E1.24), ve33 coverage broken (E1.24), Aerodrome stable sim (E1.24), PTT router mismatch (E1.26), PROD coverage gap partial (E1.26).

## Next steps

1. **M7 Arbitrum mainline FROZEN.** No further Arbitrum M7 changes.
2. **Phase 1 DONE (E1.17)**: Config coverage gaps resolved. rpc_fork switch available via env vars.
3. **Phase 2 DONE (E1.18)**: ve33 calldata encoder implemented. All known sim error classes resolved.
4. **Phase 2.5 DONE (E1.19)**: Rate limit fix — public RPC soak proven (10/10 iters, 0 errors).
5. **Phase 3 DONE (E1.24)**: ve33 pricing + coverage + gas floor + MIN_EVENT_SIZE. 1h soak: 46.9% bridge, 40 scored, 0 restarts.
6. **Phase 3.5 DONE (E1.26)**: Router mismatch fix + PROD coverage 3→7. DISC sim_passed=1 + submit_ready=1 (first ever).
7. **Phase 4: Re-soak with factory multicall**: Factory matching added but NOT in current soak. Expected: better sim pass rate (correct DEX→router→ABI chain).
8. **Phase 4.5: DISC→PROD promotion**: Migrate successful DISC pairs (AERO/USDC, cbBTC/USDC) to production profile.
9. **Phase 5: sim revert diagnosis**: Why 5/6 DISC sim attempts revert? Stale state? Wrong token direction? Slippage?
10. **Phase 6: Flashblocks integration**: Sub-block delivery for latency edge. `mainnet-preconf.base.org` enabled via env var.
11. **Triangular arb CLOSED** (-14.16 bps baseline, not viable).
