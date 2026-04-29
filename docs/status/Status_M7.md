# Status: M7 (Triangular Feasibility)

**Status**: **M7.E1.38 post-2h-soak FIX-LIST iteration (no new soak): BLOCKED BY ECONOMICS — quote-model uniformization (P0) still pending runtime validation, but reviewer fix-list 6 of 8 items now have code/test landing or scaffold (#1 minimal observability bridge, #2 offline replay tool, #4 pre-sim size bisection ENV-gated, #5 bootstrap probe heartbeat-aware, #6 factory enumeration scaffold + cache schema, #7 tier classifier scaffold, #8 dashboard live-deltas). Last fresh soak remains 2h Base session 37e452d6 (2026-04-29T07:32:50Z → 09:32:59Z; rollup `last_updated=2026-04-29T09:28:56Z` unchanged). New ENV: `ARBY_PRE_SIM_BISECT=1` (default 0=OFF) admits SIZE_OVER_CAP candidates by scaling amount_in_wei + best_sweep_size_wei + size_usd_estimate by `cap_usd / size_usd_estimate * 0.95` and emits `SIZE_BISECTED_TO_CAP` sample. New bootstrap param: `-RollupProbeHeartbeatSeconds 30` extends rollup probe ONCE when log heartbeat seen. New tool: `scripts/replay_divergence_samples.py` (offline; consumes `m7_hot_rollup_latest.json.scorer_sim_divergence_samples_recent`; emits per-sample reproducer manifests under `data/runs/_replays/divergence/`). Divergence sample schema extended with `input_mismatch_detected: bool` + `input_mismatch_ratio: float|None` to classify whether divergence is INPUT mismatch (scorer amount_in_wei != sim input_amount_wei) or pool-quote-model error. Dashboard `/api/summary.current_scan.live_deltas` block surfaces session_id/baseline_session_id/age_seconds/is_fresh/staleness_reason/fresh_funnel/scorer_sim_divergence totals/pre_sim_skip totals/submit_blocker_histogram/simulation_error_histogram/external_provider_blocker_total. New scaffolds (offline, no RPC): `discovery/factory_enumeration.py` (`FactoryPoolRecord` + `EnumerationCache` JSON schema_version=`factory_enum_v1` + `enumerate_factory_pools` offline reader) and `discovery/tier_classifier.py` (`PoolTier` Literal hot/warm/cold + `TierThresholds` defaults 120s/1800s + pure `classify_tier` function). All scaffolds ship with full unit-test coverage (12 + 12 = 24 tests) but are NOT yet wired into runtime; live impl + soak pending. Reviewer item **#3 (eth_simulateV1 pending-state sim)** remains DEFERRED per CLAUDE.md §1.2 (large coordinated multi-module change, requires own soak). Production gating criteria unchanged. **Status**: **M7.E1.37 post-2h diagnostic soak: BLOCKED BY ECONOMICS — SCORER_SIM_DIVERGENCE root cause not yet uniformized; 2h Base session 37e452d6 (2026-04-29T07:32:50Z → 09:32:59Z) clean process-wise (5/5 children alive, `crash_restarts=0`, `simulation_backend=rpc_fork`, `external_provider_blocker_total=0`) but reviewer FAIL: `NO_FRESH_SIM_PASSED`, `NO_FRESH_ROUNDTRIP_ATTEMPTED`, `FAST_PATH_SCORED_TOO_LOW=1<20`, `STALE_ROLLUP[production] age=243s>120s`. SCORER_SIM_DIVERGENCE structured reproducer ring (50, session-scoped) IMPLEMENTED on both `ExecutionGateResult.scorer_sim_divergence_samples` and `m7_hot_rollup_latest.json.scorer_sim_divergence_samples_recent` (per post-soak21 P0); fallback fields hardened in execution_gate.py and zero-sample rollup contract in hot_runtime_artifacts.py. Reviewer fix-list items #1/#5/#6 VALIDATED via earlier 4h Base soak (session c12124ff, 2026-04-28T13:25:55Z, simulation_backend=rpc_fork). **#4 NOW FULL** — `latency_budget` block lifted to rollup surface in `_update_hot_rollup` with bounded 500-sample session ring, p50/p90/p99/within_target_pct/stage_breakdown; structurally validated by 10-min control run (session b4e231a0, 2026-04-29T06:52:25Z; samples=0 because window was quiet but schema/keys present and reviewer echoes `simulation_backend=rpc_fork`, `external_provider_blocker_total=0`). **#9 IMPLEMENTED, runtime path STILL UNVERIFIED** — control10 ran with `ARBY_MAX_TRADE_USD=50` but produced 0 fresh fast scores (quiet 10-min window); 2h diagnostic soak ran with `ARBY_MAX_TRADE_USD=0` (cap OFF) so SIZE_OVER_CAP path not exercised; structural unit tests (3 tests) cover the logic. Reviewer items **#1 quote-model uniformization (P0)**, **#2/#3 (Flashblocks pendingLogs + eth_simulateV1 pending-state)**, **#4 pre-sim size bisection**, **#6/#7 (factory enumeration + tiered universe)**, **#8 dashboard live-delta panels** DEFERRED per CLAUDE.md §1.2 (each is a coordinated multi-module refactor requiring own soak). Earlier acceptance and structural items unchanged below. Reviewer fix-list items #1/#5/#6 VALIDATED via 4h Base soak (session c12124ff, 2026-04-28T13:25:55Z, simulation_backend=rpc_fork). **#4 NOW FULL** — `latency_budget` block lifted to rollup surface in `_update_hot_rollup` with bounded 500-sample session ring, p50/p90/p99/within_target_pct/stage_breakdown; structurally validated by 10-min control run (session b4e231a0, 2026-04-29T06:52:25Z; samples=0 because window was quiet but schema/keys present and reviewer echoes `simulation_backend=rpc_fork`, `external_provider_blocker_total=0`). **#9 IMPLEMENTED, runtime path STILL UNVERIFIED** — control10 ran with `ARBY_MAX_TRADE_USD=50` but produced 0 fresh fast scores (quiet 10-min window), so `PRE_SIM_SKIP:SIZE_OVER_CAP` did not trigger; structural unit tests cover the logic. Reviewer items **#2/#3/#7/#8 DEFERRED** per CLAUDE.md §1.2. Unit: **4309 passed / 6 skipped / 0 failed** (+11 new vs E1.35 baseline: 2 per-iteration latency contract + 2 rollup latency contract + 3 PRE_SIM_SKIP:SIZE_OVER_CAP + 2 SCORER_SIM_DIVERGENCE regression guard + 2 zero-sample rollup contract / fallback fields); `check_repo_safety.py` PASS 0 warnings (20 gates). 4h Base soak ran with rpc_fork pinned for PROD+DISC, archive required (`ARBY_REQUIRE_ARCHIVE=1`), paper signing enabled (`ARBY_PAPER_SIGNING=1`), `ARBY_HOT_SWEEP_ENABLE=1`, `ARBY_LATENCY_TARGET_MS=200`, `ARBY_MAX_TRADE_USD=0` (cap observability OFF default). 5/5 children alive across full window, **`crash_restarts=0`**. Cumulative session counters at last flush (13:18:56Z): `events_seen_total=2338`, `fast_path_scored_total=389`, `fast_path_positive_total=15`, `sim_attempted_total=7`, `sim_passed_total=4`, `roundtrip_attempted_total=4`, `roundtrip_success_total=4`, `roundtrip_profitable_total=0`, `submit_ready_total=0`, `external_provider_blocker_total=0`, `windows_seen=67`, `windows_with_events=58`, `windows_with_fast_scores=32`. Submit-blocker histogram dominated by **`SCORER_SIM_DIVERGENCE` (4 samples: fast-path predicted +2424–2441 bps but rpc_fork sim returned −9988 bps, indicating fast-path price model diverges from real-pool simulation under non-trivial sizes)** plus 4 `ROUNDTRIP_NOT_PROFITABLE`. `simulation_error_histogram`: `PRE_SIM_SKIP:MISSING_SIZE_METADATA=8` (down from soak19; fix #5 fallbacks effective on extended symbol set), `REVERT:unknown:no_data=2`, 1 Tenderly 403 (legacy artifact, `external_provider_blocker_total=0` confirms no fresh Tenderly hits this session). Reviewer verdict (`ARBY_REVIEWER_QUIET_OK=1`, anchor=last_updated): **FAIL/NO_FRESH_SIM_PASSED+NO_FRESH_ROUNDTRIP_ATTEMPTED** — session-fresh deltas vs baseline (3d48b072 → c12124ff): events +970, fast_path_scored +45, profit_guard_passed +2, sim_attempted/passed/roundtrip/submit_ready all +0; `simulation_backend=rpc_fork`, `external_provider_blocker_total=0`. Production-readiness criteria (`sim_passed>0 AND submit_ready>0 AND roundtrip_profitable_total>0`) NOT met. Reviewer fix-list closures this iteration: **(#1) rpc_fork canonical** (bootstrap pin + reviewer echo); **(#4) latency_budget block** (samples_total / p50/p90/p99 / max_ms / target_ms / within_target_pct / 7-stage stage_breakdown) emitted in per-iteration `m7_hot_latest.json`, on rollup surface in `m7_hot_rollup_latest.json` (bounded 500-sample session ring), and on `/api/summary.current_scan` — FULL structurally; **(#5) sizing fallbacks** extended to USDC/USDT/USDC.e/USDT.e/USDbC/PYUSD/DAI/FRAX/WETH/WBTC/cbBTC/cbETH/wstETH/rETH/tBTC heuristic decimals + coarse stable-USD fallback + `default_18_inferred` source label; **(#6) hot-path size sweep gate** via `ARBY_HOT_SWEEP_ENABLE=1` lifts `registry_direct` block; **(#9) PRE_SIM_SKIP:SIZE_OVER_CAP** via `ARBY_MAX_TRADE_USD>0` (default 0=OFF, fully backward compatible). Reviewer fixes **#2 (Flashblocks pendingLogs read path)**, **#3 (eth_simulateV1 pending-state sim)**, **#7 (factory enumeration)**, **#8 (tiered cold/warm/hot universe topology)** remain DEFERRED to dedicated iterations per CLAUDE.md §1.2/§5.1 large-refactor rule (each requires new modules/ABIs/retry policies and own soak). M7.B remains policy-closed.

Unit baseline: **4348 PASS / 6 skipped / 0 failed** (+39 vs E1.36 baseline 4309: 8 replay tool + 3 size-bisection + 1 dashboard live-deltas + 2 input-mismatch detector + 12 factory-enum scaffold + 12 tier-classifier scaffold + 1 carryover from soak21 P0 batch). `check_repo_safety.py`: PASS 0 warnings (all 20 gates). Production readiness: NOT MET (fresh `sim_passed=0`, `roundtrip_attempted=0`, `submit_ready=0`, `roundtrip_profitable=0` per 2h soak 37e452d6); SCORER_SIM_DIVERGENCE reproducer landed but quote-model uniformization (P0 root cause) DEFERRED.

**Updated**: 2026-04-29

**Acceptance criterion (unchanged)**:
`Δsim_passed > 0 AND Δroundtrip_attempted > 0 AND ΔBlockOutOfRangeError == 0
AND strict_provider_breaches_total_delta == 0
AND fast_path_scored_delta >= ARBY_REVIEWER_MIN_FAST_PATH_SCORED (default 20,
unless ARBY_REVIEWER_QUIET_OK=1)
AND production rollup not stale (default 120s, anchor = supervisor end
when available)` on both lanes.

**Next P0 blockers (operational; no local Anvil required)**:
(a) **run the corrected soak** — mixed backend policy that already
exists in code (`simulation.py`, `rpc_fork_backend`, tenderly→rpc_fork
fallback) and in supervisor wiring
(`scripts/start_nonstop_runtime.py`): `ARBY_SIM_BACKEND=tenderly`
for PROD + `ARBY_SIM_BACKEND_DISC=rpc_fork` for DISC. Tenderly API
credentials are in `.env`; `rpc_fork` reuses the premium Base archive
RPC already used by the WS feed. No `--with-anvil`, no
`ARBY_ANVIL_*`; the previous Alchemy monthly cap path is not used;
(b) **raise feed coverage** to hit `supervisor_window.events_per_minute
>= 5`; registry / pair-filter work unlocked by the enriched bridge
samples (`bridge_hit_but_not_fast_scored.samples[]`);
(c) **classify fresh `HOT_SKIP_UNKNOWN_PAIR`** pools listed above into
either scoring candidates or concrete non-UNKNOWN reject reasons.

**M7.B remains policy-closed** — opening requires all six of:
`fast_path_scored >= 20`, `sim_passed > 0`, `roundtrip_attempted > 0`,
`BlockOutOfRangeError == 0`, `strict_provider_breaches == 0`, rollup
not stale. The 2026-04-22 soak meets only the last three.

**Previous (M7.E1.34h code cycle)** retained: enriched
`bridge_hit_not_scored_sample` (raw pool_address / scoring_path /
actual_pair / token_in / token_out / fee_tier / venue / adapter_type)
propagated into rollup `bridge_hit_but_not_fast_scored.samples[]`
(bounded ring of 10); `rollup.supervisor_window` (first_window_at,
events_total, elapsed_minutes, events_per_minute) surviving child
restarts; `flush_rollup_shutdown(chain)` stamps `shutdown_flush_at` on
clean loop exit; `sim_failed_samples_recent` ring pruned to current
`_SESSION_ID` before each append.
**Previous (M7.E1.34g)** retained: feed-rate counters
(`session.session_events_per_minute` + `session.session_elapsed_minutes`);
bridge-drop reason classification (`HOT_SKIP_UNKNOWN_PAIR` / `NOT_SCORED`
/ `SCORING_PATH_*`); `fast_path_net_bps_histogram` (8 buckets).
**Previous (M7.E1.34f)** retained: per-lane `last_heartbeat_utc` /
`last_event_utc` / `last_scored_utc`; `bridge_hit_but_not_fast_scored`
diagnostic bucket; `--staleness-anchor-utc` CLI flag;
`fresh_failed_samples` helper.

**Previous (M7.E1.34b) note** retained: 1h reviewer soak 2026-04-21: 0 restarts; production 99 fast_scored / 21 guard_passed / 19 sim_attempted / 0 sim_passed; discovery 99 / 21 / 15 / 0; ΔVENUE_MISSING=0, ΔAMOUNT_ZERO=0 (Step 7 admission filter directionally validated); 100% fresh sim attempts failed with `BlockOutOfRangeError` from the static anvil fork. **Step 9**: `anvil_backend._resolve_anvil_block_tag()` clamps event-block > local-head to "latest"; `_eth_call_anvil` retries "latest" on `BlockOutOfRangeError`; new `refresh_anvil_fork_if_stale()` calls `anvil_reset` with a fresh `head-offset` target; `scripts/start_anvil_fork.py` runs a periodic refresher thread (ENV `ARBY_ANVIL_AUTO_REFRESH=1`, `ARBY_ANVIL_REFRESH_INTERVAL_S=60`, `ARBY_ANVIL_REFRESH_DRIFT_BLOCKS=120`) and cleans orphan `anvil.exe` on Windows via `taskkill` on exit. `scripts/analyze_roundtrip_profitability.py` now demotes cumulative verdicts to `HISTORICAL_PROFITABLE_CASE` unless run with `--session-only` or `--baseline`; `scripts/reviewer_soak_summary.py` compares a pre-soak baseline and prints ONLY fresh deltas (ASCII `delta=` for Windows compatibility).

**2026-04-20 note** (audit cycle): 30-min Base `prod+discovery` soak shows runtime activity (PROD 61 windows / 121 events / 10 fast_scored; DISC 60/133/16/1 sim_attempted → REVERT:unknown), **but no profitable roundtrip**. `roundtrip_profitable_total=0` across both lanes. **Production readiness remains blocked** by economics (scorer-vs-sim gap, thin market windows) and was previously red on repo gates (INTENT_TIER_LIMIT, DOCS_CONTENT_BLOAT). As of 2026-04-20 repo gates are GREEN (safety PASS, pytest 4174 passed, ci_full_pipeline CI PASS, M4 `--strict` offline profit PASS). Historical verbose detail archived to [archive/status/Status_M7_history.md](../../archive/status/Status_M7_history.md). E1.35 (audit-recs P0–P3) and E1.36 (Tenderly state-override) are implemented but **not yet validated on PROD lane** — PROD got 0 `sim_attempted` in the last quiet-market window; validation deferred until a busier market window or `anvil`/`rpc_fork` PROD soak.

**Open action**: run a fresh 30-min Base PROD soak on a single declared sim backend (prefer `anvil` local fork or unified `rpc_fork`) to validate E1.35/E1.36 fixes end-to-end; expand revert decoding (`Error(string)`/`Panic(uint256)`/custom selectors) before canary; do not claim production-ready until `roundtrip_profitable_total>0`.
**M7 production definition (unchanged)**: `sim_passed>0 AND submit_ready>0 AND roundtrip_profitable_total>0 AND profit_realism_status=ROUNDTRIP_PROFITABLE`. Current: **first 2 clauses TRUE, last 2 clauses FALSE в†’ NOT PRODUCTION-READY.**
**Blocker classification**: `data_collection_blocker: MEDIUM` (Tenderly credit throttling on discovery lane). `market_window_blocker: HIGH` (zero profitable roundtrips across both lanes over ~3.3k windows). `code_blocker: LOW` (runtime plumbing stable, heartbeat_on_error_windows=49 PROD / 30 DISC).
**Open action**: request `rpc_fork` soak for discovery lane to eliminate Tenderly HTTP 403 noise; archive pre-April-17 history to clear `DOCS_CONTENT_BLOAT` (current 330 lines, target в‰¤300).

**Previous (superseded) reading**: E1.29 30-min production soak GREEN on 2026-04-17 вЂ” runtime artifacts refreshed, 210 iterations, 73 N5 anchor records; `guard_passed=0` (market-expected). Retained below as historical record.

---


**Scope**: M7.A only вЂ” runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep, 9 canonical blocker tags, temporal repeatability, verdict summary, universe profiles, orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, gas decomposition, stale/low-lag split, pool-class truth, V2 direct resolve, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, registry activation in ws-live, pipeline latency optimization, profit guard + hot-mode fast path, hot-lane no-fallback + execution-readiness timing, cold/hot artifact isolation + promoted watchlist, batch pre-resolve + supervisor fix. M7.B remains closed.

---

## Strategic Focus (E1.12.1)

**Base M7 production = main lane.** Arbitrum M4 = regression/paper benchmark only. Base delivers 183x more swap events per block than Arbitrum One. Arbitrum M7 FROZEN at 5.47s. Production closure requires: sim_passed>0, submit_ready>0, profit_realism=ROUNDTRIP_PROFITABLE.

## E1.12.2 вЂ” Modularize loop + wire execution gate (DONE, compressed)

Monolith (`scripts/m7a_orderflow_loop.py`) split: 2750в†’204 lines (-93%). Modules: `runtime_io.py`, `bridge_runtime.py`, `execution_gate.py`, `profit_guard.py`, `hot_runtime_artifacts.py`, `loop_runner.py`. Execution gate wired. Discovery hot artifact path-rebinding regression found and fixed. 30mГ—2 soak evidence: prod+disc 0 restarts, clean shutdown. CI: 3881.

## E1.12.3 вЂ” Simulation Telemetry + Blocker Refinement (DONE, compressed)

Added `sim_errors`, `submit_blockers_detail` to `ExecutionGateResult`. Added `simulation_error_histogram` + `submit_blocker_histogram` to rollup. Removed SUBGRAPH_API_KEY_REQUIRED blocker. Added `gas_l1_breakdown`. Key finding: sim failures were Tenderly HTTP 403 (credits exhausted). CI: 3888.

## E1.12.4 вЂ” Anvil Backend + rpc_fork (DONE, compressed)

4 sub-steps (A-D). Backend abstraction (`ARBY_SIM_BACKEND=tenderly|anvil|rpc_fork`). Anvil soak: 40/200 sim_passed. First non-Tenderly `sim_passed > 0` via Anvil fork (block 44618144). SwapRouter02 encoding (selector `0x04e45aaf`). CI: 3924.

---

## M7.AвЂ“A.5.47s: Triangular + Orderflow + Hot Execution (CLOSED, archived)

Steps 1-8, A.4, A.5.1-5.47s all CLOSED. Triangular: NO-GRADUATE (all cycles net-negative). Orderflow backrun (Arbitrum): sequential pipeline too slow. WS-live: NOT VIABLE (2.3s/event). Hot execution: bridge truth converged. **Arbitrum M7 FROZEN** (5.47s: event_source_absence confirmed, 0 hot events in peak-hours proof). Full history available in git diff.

Modules: `engine/triangular_*.py`, `scripts/m7a_*.py`, `m7/orderflow/`. Tests: 152 triangular + 369 orderflow.

---

## M7.E1: Base Flashblocks Event-Source Pilot (OPEN)

**Hypothesis**: Base delivers abundant V3 Swap events via newHeads+logs, enabling backrun scoring impossible on Arbitrum.

**E1 pilot evidence (April 7)**: 73.4 events/block (183x Arbitrum), all same-block (lag=0), best_net=-2.28 bps, sole blocker GAS_EXCEEDS_GROSS. CI: 3698.

### E1.1вЂ“E1.7: Nonstop в†’ Contamination Fix в†’ Funnel в†’ Hot Write (CLOSED, compressed)

**E1.1вЂ“E1.4**: Hot+cold nonstop, Arbitrum contamination fix, registry vs gas separation (registry NOT blocker, gas IS blocker), convergence fields. CI: 3702в†’3741.
**E1.5вЂ“E1.7**: Funnel inversion fix, strict exec (route_viable AND size_valid), hot lane write fix. CI: 3746в†’3775.

---

### M7.E1.8вЂ“E1.9.3: Dashboard + Chain Provenance + Discovery Lane Split (CLOSED, compressed)

**E1.8+E1.8.1**: Dashboard M7 freshness, `chain`+`run_context.chain` in all artifacts, 9-key signal_counts zero dict. CI: 3790в†’3797.
**E1.9вЂ“E1.9.3**: Production/discovery lane split, namespace isolation (`*_discovery.json`), peak-hours A/B (market scarcity confirmed), session-first dashboard. CI: 3817в†’3829.

---

### M7.E1.10вЂ“E1.11: Peak-Hours A/B + Contour Cleanup + dRPC (CLOSED, compressed)

**E1.10**: 1h A/B proof (1953 windows, 0 events). Contour cleanup: removed AMONGUS dead slot, meme families diagnostic_only, AERO/cbBTC prioritized. VIRTUAL family added. 429-fallback fix: Alchemyв†’publicnode WS/HTTP automatic. Post-fix: production 230 events/46 windows, discovery 245/50. CI: 3831в†’3838.
**E1.11**: dRPC provider upgrade (`BASE_RPC`/`BASE_WSS` chain-scoped envs). dRPC WS 100% stable (0 failures), HTTP 50% 429 fallback. Discovery now scoring (31 fast_path_scored vs prior 0). CI: 3838.
**E1.12**: Premium-provider gate generalized (alchemy+drpc+infura). CI gates PASS, rolling refreshed.

**E1.12.1 artifact-semantics + start.py + 10-step audit (2026-04-11)**:
Fixes: `cold_executable_positive` semantic (route_viable AND size_valid), `start.py` single-chain auto-partial. Full audit (10 steps): premium RPC backoff (3 retries), Flashblocks URL fix, Tenderly/Subgraph scaffolding, L1 data fee first-class, stricter release semantics. 30min burn-in: production +1 guard_passed, discovery 6 fast_path_scored. CI: 3862, ALL GATES PASSED.

---

## E1.13вЂ“E1.19: Denomination Fix в†’ Pipeline Unblock в†’ Velodrome в†’ Rate Limit (DONE, compressed)

**E1.13**: Fixed `gas_cost_wei` denomination (ETH wei vs token wei). **E1.14**: 6 pipeline blockers fixed; first `sim_passed=1` in rolling. **E1.15/R40**: Flashblocks DNS (`mainnet-preconf.base.org`), AERO/WETH calibration, audits. **E1.16**: `rpc_fork` backend вЂ” stateOverrides seeding; E2E `sim_passedв†’submit_ready`. **E1.17**: Config/DEX fallback fix. **E1.18**: Velodrome `0xcac88ea9` calldata encoder + ve33 adapter split. **E1.19**: Rate-limit root causes (stale 10в†’150, prewarm skip, max_pairs=10, V2 timeout). CI ladder: 3926в†’3992.

---

## E1.24–N1+N5 — Historical detail (archived)

Detailed deltas, soak tables, and per-file change-lists for **E1.24, E1.26, E1.27, E1.28, E1.29, E5, and N1+N5**
are archived at [archive/status/Status_M7_history.md](../../archive/status/Status_M7_history.md) per DOCS_POLICY bloat rule.
One-line summaries:

- **E1.24** (2026-04-16, DONE) — ve33 pricing routed to V2 constant-product; gas floor 0.50→0.15 bps; MIN_EVENT_SIZE 100→500; coverage for ve33/V2 local-pricing. Soak 1h: bridge 50.0%, 48 scored, 0 restarts.
- **E1.26** (2026-04-16, DONE) — Router mismatch fix (fee→DEX + factory() multicall + execution_gate fee preference). PREWARM 3→7 pairs. First-ever DISC sim_passed=1, submit_ready=1.
- **E1.27** (D1/D2/D3, DONE) — Removed invalid single-leg sim_profit_bps; honest revert_reason propagation; pre-sim fee gate for dynamic Algebra fees (no RPC waste).
- **E1.28** (E1–E4, DONE) — Round-trip simulation (buy+sell same token, valid bps). Wider state-override slot set. ARBY_ROUNDTRIP_SIM=1. Diagnostic ARBY_SIM_BYPASS_GUARD=1. AERO/WETH scorer-vs-sim gap surfaced (+20334 bps scored → −10000 bps actual).
- **E1.29** (2026-04-17, DONE) — Runtime hardening N5–N9: anchor write hook, prewarm wall-clock budgets (30s/15s), None-guard filter, symbol/decimals fallback. 30-min soak: 210 iter, 73 N5 records, 0 crashes.
- **E5** (DONE) — Dynamic USD price resolver 
esolve_token_usd_price(); STABLE_USD_PRICES table; stale-DEFAULT fallback emits WARN; non-stable hardcodes purged from onboard_base_profit.yaml.
- **N1+N5** (DONE) — Anchor-recording hooks wired to fast+live scoring paths; strict resolver at runtime callsites (scoring_parallel, pricing). Live soak validation pending WS event-source stability.

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

1. **EVENT-SOURCE CEILING вЂ” FROZEN (Arbitrum only)** вЂ” 47s proof confirms `event_source_absence`. Does NOT apply to Base.
2. **GAS_EXCEEDS_GROSS вЂ” MAJORITY BLOCKER (Base)** вЂ” ~7% viable rate. Near-exec frontier at -2.20 bps.
3. **~~Submit-stage sim = 0 in canonical rolling~~ в†’ RESOLVED (E1.14)** вЂ” sim_passed=1 in production rolling.
4. **~~dRPC HTTP 429 INTERMITTENT (Base)~~ в†’ RESOLVED (E1.19)** вЂ” Rate limit root causes fixed: stale threshold 10в†’150, prewarm skip, max_pairs=10 cap, V2 timeout. Public RPC soak 10/10 with 0 rate limit errors.
5. **~~SIGNING_NOT_READY~~ в†’ RESOLVED (E1.16)** вЂ” rpc_fork backend + paper signing available. Requires env vars: `ARBY_SIM_BACKEND=rpc_fork`, `ARBY_PAPER_SIGNING=1`.
6. **~~TOKEN_ADDRESS_UNKNOWN (12 sim errors)~~ в†’ RESOLVED (E1.17)** вЂ” Address prefix resolution + improved token fallback paths.
7. **~~DEX_CONFIG_MISSING (6 sim errors)~~ в†’ RESOLVED (E1.17)** вЂ” DEX fallback reordered, pre-E1.16 errors in rolling histogram.
8. **~~ve33 ABI mismatch (1 sim error)~~ в†’ RESOLVED (E1.18)** вЂ” Velodrome calldata encoder implemented. Aerodrome pools now use correct `swapExactTokensForTokens` ABI.
9. **~~ve33 pricing broken (0% bridge hit)~~ в†’ RESOLVED (E1.24)** вЂ” ve33 fell through to V3 math. Fixed: routed to V2 constant-product with ve33 fee model. Bridge hit rate 46.9%.
10. **~~ve33 coverage broken (73% TRULY_INACTIVE)~~ в†’ RESOLVED (E1.24)** вЂ” No quoter for ve33 в†’ 0 buy/sell venues. Fixed: local pricing counts as quote capability.
11. **~~Aerodrome stable sim reverts~~ в†’ RESOLVED (E1.24)** вЂ” Hardcoded `stable=False` в†’ fee field detection.
12. **~~PTT router mismatch (dex=ptt_direct)~~ в†’ RESOLVED (E1.26)** вЂ” Feeв†’DEX mapping + factory() multicall + execution_gate fee preference. DISC sim_passed=1.
13. **~~PROD coverage gap (3 pairs, 80.6% miss)~~ в†’ PARTIALLY RESOLVED (E1.26)** вЂ” PREWARM 3в†’7 pairs, miss 80.6%в†’47.6%. PROD positive still 0 вЂ” production pairs don't find spread.
14. **DISC sim revert rate 83% (5/6)** вЂ” 5 out of 6 sim attempts revert. Factory multicall may improve. Needs re-soak.
15. **Triangular arb NOT viable** вЂ” Baseline -14.16 bps. CLOSED.
16. **Scorer-vs-sim gap (E1.28 finding)** вЂ” AERO/WETH scored +20334 bps, real round-trip -10000 bps (1 WETH в†’ 32 wei output). 5/5 samples. Root cause unknown; need venue/fee + reserves in sample log and per-size sweep.

Resolved: HOT LANE NOT WRITING (E1.7), MARKET-WINDOW SCARCITY (E1.10), ALCHEMY 429 (E1.10), Dashboard dead (E1.8), Chain provenance (E1.8.1), Submit-stage sim=0 (E1.14), SIGNING_NOT_READY (E1.16), TOKEN_ADDRESS_UNKNOWN (E1.17), DEX_CONFIG_MISSING (E1.17), ve33 ABI mismatch (E1.18), dRPC 429 INTERMITTENT (E1.19), ve33 pricing broken (E1.24), ve33 coverage broken (E1.24), Aerodrome stable sim (E1.24), PTT router mismatch (E1.26), PROD coverage gap partial (E1.26).

## Next steps

1. **M7 Arbitrum mainline FROZEN.** No further Arbitrum M7 changes.
2. **Phase 1 DONE (E1.17)**: Config coverage gaps resolved. rpc_fork switch available via env vars.
3. **Phase 2 DONE (E1.18)**: ve33 calldata encoder implemented. All known sim error classes resolved.
4. **Phase 2.5 DONE (E1.19)**: Rate limit fix вЂ” public RPC soak proven (10/10 iters, 0 errors).
5. **Phase 3 DONE (E1.24)**: ve33 pricing + coverage + gas floor + MIN_EVENT_SIZE. 1h soak: 46.9% bridge, 40 scored, 0 restarts.
6. **Phase 3.5 DONE (E1.26)**: Router mismatch fix + PROD coverage 3в†’7. DISC sim_passed=1 + submit_ready=1 (first ever).
7. **Phase 4: Re-soak with factory multicall**: Factory matching added but NOT in current soak. Expected: better sim pass rate (correct DEXв†’routerв†’ABI chain).
8. **Phase 4.5: DISCв†’PROD promotion**: Migrate successful DISC pairs (AERO/USDC, cbBTC/USDC) to production profile.
9. **Phase 5: sim revert diagnosis**: Why 5/6 DISC sim attempts revert? Stale state? Wrong token direction? Slippage?
10. **Phase 6: Flashblocks integration**: Sub-block delivery for latency edge. `mainnet-preconf.base.org` enabled via env var.
11. **Triangular arb CLOSED** (-14.16 bps baseline, not viable).
