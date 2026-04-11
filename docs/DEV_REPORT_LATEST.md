# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-11T10:39:56Z
run_id: ci_m5_gate_arbitrum_one_20260411_123905_815779
mode: ONLINE (M7.E1.12.1 -- full 10-step audit response + 30min burn-in)
artifact_mode: rolling
config: Base M7 nonstop + config/real_minimal.yaml (M4/M5 rolling)
code_identity:
  primary: ts:2026-04-11T10:39:56Z
  dirty: true
  desc: E1.12.1 full audit -- RPC backoff, L1 fee integration, Flashblocks URL fix, Tenderly/Subgraph scaffolding, stricter release semantics, strategic focus codification, 30min burn-in

## Session Completion
session_goal: E1.12 audit full response -- implement all 10 fix steps from audit. (1) Strategic focus codification. (2) start.py fix. (3) Premium RPC backoff. (4) Flashblocks URL fix. (5) Tenderly scaffolding. (6) Subgraph API key scaffolding. (7) L1 data fee first-class. (8) cold_executable_positive fix. (9) Stricter release semantics. (10) 30min burn-in with analysis.
goal_status: REACHED (all 10 steps implemented, 30min burn-in completed, CI ALL GATES PASSED)
close_allowed: true
remaining_blockers: (1) M7 submit_ready_total=0, sim_passed_total=0. (2) profit_realism_status=ROUNDTRIP_NOT_PROFITABLE. (3) Tenderly/Subgraph API keys not configured (scaffolding only).
evidence_session_run_dirs: [burnin_production_20260411_120325, burnin_discovery_20260411_120337]
primary_blocker_of_session: 10_step_audit_incomplete
blocker_status_before: ACTIVE (only 2/10 audit steps done)
blocker_status_after: RESOLVED (all 10/10 audit steps implemented + verified)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.12.1 = full 10-step audit response -- all code fixes + scaffolding + 30min burn-in
change_summary:
  - m7/orderflow/mode_ws_live.py: Premium RPC exponential backoff (3 retries, 1/2/4s) + ARBY_RPC_PREMIUM_ONLY env + L1 fee caching + l1_fee_bps passthrough to scoring
  - m7/orderflow/scoring_parallel.py: score_backrun_fast() accepts l1_fee_bps, gas floor = max(static, l1_fee_bps)
  - m7/orderflow/simulation.py: NEW — Tenderly fork simulation scaffolding (SimulationResult, simulate_swap, is_tenderly_configured)
  - chains/l1_cost.py: OP-Stack GasPriceOracle support + get_l1_cost_for_chain() dispatcher + get_l1_fee_bps()
  - chains/flashblocks.py: Fixed default URL from base.flashblocks.base.org to mainnet.flashblocks.base.org
  - m7/shared/constants.py: _subgraph_url() helper with GRAPH_API_KEY env var injection
  - m4/fixtures.py: production_readiness block (profit_realism_profitable, sim_passed_positive, submit_ready_positive)
  - scripts/ci_m5_0_gate.py: production_readiness block for offline run_summary
  - docs/status/Status_M7.md: Strategic Focus (E1.12.1) section — Base M7 = main lane
  - (prior turn) m7/orderflow/artifacts.py: cold_executable_positive requires route_viable AND size_valid_for_token
  - (prior turn) start.py: auto-partial for single configs
touched_files:
  - m7/orderflow/mode_ws_live.py
  - m7/orderflow/scoring_parallel.py
  - m7/orderflow/simulation.py (NEW)
  - chains/l1_cost.py
  - chains/flashblocks.py
  - m7/shared/constants.py
  - m4/fixtures.py
  - scripts/ci_m5_0_gate.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3862 passed, 6 skipped, 116s)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED, 107s)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.5 --no-m4 --chain base --m7-profile production --dashboard-port 8101: COMPLETED (12:03:25Z → 12:33:26Z, 0 restarts)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.5 --no-m4 --chain base --m7-profile discovery --dashboard-port 8102: COMPLETED (12:03:37Z → 12:33:38Z, 0 restarts)

## 3) Artifacts Attached

rolling:
  - data/runs/_rolling/m7_hot_rollup_latest.json (Base production, 4903 cumulative windows, 961 events, 18 viable, 0 sim/submit)
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json (Base discovery, 284 windows, 38 events, 0 viable)
  - data/runs/_rolling/m7_orderflow_latest.json (Base production, blocker_tags: [SUBGRAPH_API_KEY_REQUIRED])
  - data/runs/_rolling/m7_orderflow_latest_discovery.json (Base discovery)
  - data/runs/_rolling/_latest.json (arbitrum_one, run_timestamp: 2026-04-11T10:39:56Z)
  - data/runs/_rolling/run_summary_latest.json (status: PASS, profit_realism: ROUNDTRIP_NOT_PROFITABLE)

## 4) Key Results

### 4.1) 10-Step Audit Completion

| Step | Description | Status | Evidence |
|------|-------------|--------|----------|
| 1 | Strategic focus: Base M7 = main lane | DONE | Status_M7.md Strategic Focus section |
| 2 | Fix start.py single-chain contract | DONE | start.py auto-partial, CI PASS |
| 3 | Premium-only RPC with exponential backoff | DONE | mode_ws_live.py: 3 retries (1/2/4s), ARBY_RPC_PREMIUM_ONLY env |
| 4 | Flashblocks URL fix | DONE | flashblocks.py: mainnet.flashblocks.base.org/ws |
| 5 | Tenderly simulation scaffolding | DONE | simulation.py: SimulationResult, simulate_swap(), is_tenderly_configured() |
| 6 | Subgraph API key scaffolding | DONE | constants.py: _subgraph_url() with GRAPH_API_KEY |
| 7 | L1 data fee first-class | DONE | l1_cost.py: OP-Stack GasPriceOracle, get_l1_fee_bps(); scoring_parallel.py: dynamic gas floor |
| 8 | Fix cold_executable_positive | DONE | artifacts.py: requires route_viable AND size_valid_for_token |
| 9 | Stricter release semantics | DONE | fixtures.py + ci_m5_0_gate.py: production_readiness block |
| 10 | 30min burn-in with analysis | DONE | 30min prod+disc, 0 restarts, analysis below |

### 4.2) 30min Burn-In Results (12:03-12:33Z, Base)

**Production** (profile=production, 4 focused pairs):
| Metric | Delta this run | Cumulative |
|--------|---------------|------------|
| Duration | 30.0 min | multi-day |
| Windows | +300 | 4903 |
| Events | +37 | 961 |
| Fast path scored | +10 | 265 |
| Positive | +1 | 21 |
| Route viable | +1 | 18 |
| Guard passed | +1 | 18 |
| Sim passed | +0 | 0 |
| Submit ready | +0 | 0 |
| WS provider | drpc | connected |
| WS 429 | 0 | stable |
| HTTP fallback | 39/42 sessions | 93% fallback |
| Restarts | 0 | clean shutdown |

**Discovery** (profile=discovery, 10+ pairs, fresh rollup):
| Metric | Total this run |
|--------|---------------|
| Duration | 30.0 min |
| Windows | 284 |
| Events | 38 |
| Fast path scored | 6 |
| Positive | 0 |
| Route viable | 0 |
| WS provider | drpc |
| WS 429 | 0 |
| HTTP fallback | 34/37 sessions |
| Restarts | 0 |

### 4.3) Key Findings

1. **Stability proven**: Both profiles ran 30 full minutes, 3/3 workers, 0 restarts, clean shutdown.
2. **Event flow active**: 12-13% event rate (37 events / 300 windows production, 38/284 discovery).
3. **Production scoring healthy**: +10 fast_path_scored, +1 positive, +1 viable, +1 guard_passed in 30min.
4. **Discovery wider but sparser**: 6 fast_path_scored, 0 positive — wider pair set dilutes signal density.
5. **dRPC WS 100% stable**: 0 WS failures, 0 429 windows across both profiles.
6. **dRPC HTTP still 429-heavy**: 93% HTTP fallback to public — quoting goes through public RPC.
7. **Sim/submit still zero**: Expected — no Tenderly API key configured, simulation scaffolding only.

## 5) Strategic Reading

1. **All 10 audit steps implemented and verified.** Code fixes, scaffolding, and 30min burn-in all complete.
2. **Base M7 production is the main lane.** Codified in Status_M7.md. Arbitrum M4 = regression/paper only.
3. **L1 data fee now first-class input to scoring.** OP-Stack GasPriceOracle queries feed into gas floor dynamically — no more hardcoded 0.5 bps when real L1 fees are available.
4. **RPC resilience improved.** Exponential backoff on 429 (3 retries before public fallback). `ARBY_RPC_PREMIUM_ONLY=1` prevents public fallback entirely for production use.
5. **Production_readiness gate prevents false go-signals.** `production_ready=True` requires ALL of: profit_realism=ROUNDTRIP_PROFITABLE, sim_passed>0, submit_ready>0. Currently all three are False → `production_ready=False`.
6. **Tenderly + Subgraph ready for API keys.** Scaffolding in place — set `TENDERLY_USER/PROJECT/ACCESS_KEY` and `GRAPH_API_KEY` env vars to activate.
7. **Flashblocks URL corrected** from `base.flashblocks.base.org` to `mainnet.flashblocks.base.org`. Note: infrastructure stream is for node operators; production should use ARBY_FLASHBLOCKS_WS env var with a Flashblocks-aware RPC provider.

## 5.1) Contract Checks
status/reasons consistency: OK (production_readiness block prevents PASS + NOT_PROFITABLE false go-signal)
rolling discipline: OK
runtime artifacts not committed: OK
docs_reread_confirmed: true

## 6) Blocker Classification

code_blocker: RESOLVED (all 10 audit steps implemented — RPC backoff, L1 fee, Flashblocks, Tenderly/Subgraph scaffolding, release semantics, cold_exec fix, start.py fix)
infra_blocker: ACTIVE (dRPC HTTP 429 ~93% fallback; Tenderly/Subgraph API keys not configured)
market_window_scarcity: PARTIALLY ACTIVE (12-13% event rate, market activity present but sparse)

## 6.1) Blockers / Risks
- **profit_realism_status=ROUNDTRIP_NOT_PROFITABLE**: No roundtrip has been profitable under current economics.
- **submit_ready_total=0, sim_passed_total=0**: Sim scaffolded but Tenderly API key required to activate.
- **production_readiness=False**: Correctly prevents false go-signal. Requires profit_realism + sim + submit all positive.
- **dRPC HTTP 429**: ~93% HTTP fallback to public. WS 100% stable. Not blocking — events flow through WS.
- **SUBGRAPH_API_KEY_REQUIRED**: Gateway URLs scaffolded with GRAPH_API_KEY env var. Without key: rate-limited keyless access.
- **Discovery zero positive**: Wider pair set dilutes signal; needs more accumulation or pair refinement.

## 6.2) New Environment Variables (this session)
- `ARBY_RPC_PREMIUM_ONLY=1`: Refuse public RPC fallback entirely (premium-only mode)
- `GRAPH_API_KEY`: The Graph Network API key for authenticated subgraph access
- `TENDERLY_USER`, `TENDERLY_PROJECT`, `TENDERLY_ACCESS_KEY`: Tenderly fork simulation credentials
- `ARBY_FLASHBLOCKS_WS`: Override Flashblocks WebSocket URL (for Flashblocks-aware RPC provider)
