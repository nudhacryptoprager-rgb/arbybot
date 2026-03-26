# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39r**: Flashblocks read-path integration + EXECUTABLE_TRUTH_GATE + structural_advantage_met wiring. 2469 tests.
**R39q**: Route-cost pruning + margin-first ordering + dashboard focal chain mode. 2446 tests.
**R39p**: RPC rotation + expanded endpoints — completely fixed Base rate-limiting. 2436 tests.
**R39o**: include_pairs hard clamp, per-cycle 429 quarantine, full contour no-slot0, reserved candidate slots. 2436 tests.

## SESSION GOAL (R39r: Flashblocks read-path + executable truth gate)
**Goal**: (1) Integrate Flashblocks WSS read-path for Base structural advantage, (2) Create EXECUTABLE_TRUTH_GATE constant, (3) Wire structural_advantage_met to Flashblocks connectivity, (4) Narrow notional corridor to $25/$50/$75, (5) Lock contour until executable truth proven.
**Prior (R39q)**: Base gap=8.19 bps achieved, but lead review identified REAL blocker: `profit_realism_status=ONE_LEG_ONLY_DIAGNOSTIC`, `real_quote_count=0`, `roundtrip.evaluated_count=0`. Gap is low but truth is diagnostic-only.
**Lead directive (R39r)**: "R39q є великим проривом по economics contour. Але блокер не є 'Base RPC' або 'ринок' — блокер є 'missing Flashblocks/preconf execution edge'."

## 0) Meta
timestamp_utc: 2026-03-25T10:35:31Z
long_scan_summary: long_scan_latest.json
mode: R39r_FLASHBLOCKS_EXECUTABLE_TRUTH
test_count: 2469 passed, 5 skipped (+23 R39r tests)
schema_version: start:long_scan_summary:v1.15
code_identity:
  primary: ts:2026-03-25T10:35:31Z
  dirty: true (R39r code changes uncommitted)
  desc: flashblocks_read_path_executable_truth_gate

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39r: Integrate Flashblocks read-path for Base structural advantage + executable truth gate |
| goal_status | **BLOCKED** (Flashblocks public WSS not connecting; executable truth still diagnostic-only) |
| close_allowed | true |
| remaining_blockers | (1) Flashblocks public WSS endpoint rate-limited/not connecting — need private RPC provider, (2) Base real_quote_count=0, profit_realism=ONE_LEG_ONLY_DIAGNOSTIC |
| fresh_evidence_run | 6-chain 10-min scan (ts:2026-03-25T10:36:01Z), 66 runs |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260325_113506_178747, ci_m5_gate_base_20260325_113516_* |
| primary_blocker_of_session | Base executable truth: real_quote_count=0, structural_advantage_met=false |
| blocker_status_before | ACTIVE: profit_realism=ONE_LEG_ONLY_DIAGNOSTIC, no Flashblocks infra |
| blocker_status_after | **BLOCKED**: Flashblocks read-path built + wired, but public WSS not connecting. Need private endpoint. |
| start_metric | R39q: Base gap=8.19 bps, no Flashblocks infra, structural_advantage_met=hard-coded false |
| end_metric | R39r: Base gap=8.30 bps, FlashblocksWatcher built+wired, structural_advantage_met=runtime-gated, connected=false |
| delta | Infra: +FlashblocksWatcher module, +EXECUTABLE_TRUTH_GATE, +23 tests. Gap stable (~8 bps). |
| docs_reread_confirmed | true |

## 0.3) Fresh 6-Chain Scan Evidence (R39r)

```
Wall time:      624s (10-min 6-chain scan)
Total runs:     66 (PASS=16, NO_DATA=0, FAIL=50, INFRA_FAIL=0)
Signals total:  444
Net USDC total: $568.01
Profitable RTs: 0 (evaluated: 63, best: -8.30 bps)

Per-chain:
  arbitrum_one  runs=11 PASS=11 signals=328 gap=27.40 rq=63 profit_state=PRIMARY_BLOCKER
  base          runs=11 PASS=5  signals=116 gap=8.30  rq=0  profit_state=CANDIDATE  prs=ONE_LEG_ONLY_DIAGNOSTIC
  linea         runs=11 PASS=0  signals=0   profit_state=CANDIDATE
  mantle        runs=11 PASS=0  signals=0   profit_state=CANDIDATE
  scroll        runs=11 PASS=0  signals=0   profit_state=CANDIDATE
  zksync        runs=11 PASS=0  signals=0   profit_state=CANDIDATE

Flashblocks (hot_loop_latest.json):
  connected: false
  is_healthy: false
  last_sub_block_number: null

Lane Summary:
  A_quantity_profit (base): structural_advantage_met=false, gap=8.30 bps
  benchmark_control (arb):  structural_advantage_met=true,  gap=27.40 bps
```

## 1) Scope
goal (Roadmap): M5_0/M4 — R39r: Flashblocks read-path + executable truth gate
change_summary:
  - **chains/flashblocks.py** — NEW: FlashblocksWatcher (WSS sub-block events), FlashblocksState dataclass, check_flashblocks_health() HTTP health check. Public endpoints documented as not production-suitable.
  - **config/chains.yaml** — Added flashblocks_ws_endpoint and flashblocks_http_endpoint for base.
  - **config/onboard_base_profit.yaml** — R39r: Contour lock comment, sweep narrowed to $25/$50/$75, flashblocks endpoint config keys.
  - **core/constants.py** — Added EXECUTABLE_TRUTH_GATE dict (min_real_quote_count_total=1, min_roundtrip_evaluated_total=1, forbidden_profit_realism=ONE_LEG_ONLY_DIAGNOSTIC). Fixed Any import.
  - **start.py** — FlashblocksWatcher initialization, flashblocks_healthy injection into per_chain["base"], flashblocks_watcher passed to write_hot_loop_snapshot.
  - **strategy/rolling_outputs.py** — write_hot_loop_snapshot accepts flashblocks_watcher param, surfaces flashblocks state in snapshot.
  - **strategy/long_scan_summary.py** — _compute_lane_summary checks flashblocks_healthy for structural_advantage_met. classify_chain_profit_state references EXECUTABLE_TRUTH_GATE constant.
  - **tests/unit/test_r39r_flashblocks.py** — NEW: 23 tests (FlashblocksState, FlashblocksWatcher, EXECUTABLE_TRUTH_GATE, structural_advantage_met, classify gate, hot_loop snapshot).
  - **tests/unit/test_base_profit_contracts.py** — Updated sweep size assertion to [25,50,75].

touched_files:
  - chains/flashblocks.py (NEW)
  - config/chains.yaml
  - config/onboard_base_profit.yaml
  - core/constants.py
  - start.py
  - strategy/rolling_outputs.py
  - strategy/long_scan_summary.py
  - tests/unit/test_r39r_flashblocks.py (NEW)
  - tests/unit/test_base_profit_contracts.py

## 2) Root Cause Analysis

### Why Base is still CANDIDATE / ONE_LEG_ONLY_DIAGNOSTIC (R39r)
Lead's R39r review correctly identified that R39q gap reduction (499.8→8.19 bps) was a contour breakthrough but NOT executable truth. The evidence:

| Metric | Value | Meaning |
|--------|-------|---------|
| profit_realism_status | ONE_LEG_ONLY_DIAGNOSTIC | Roundtrip evaluation never happens — all quotes are diagnostic (slot0) |
| real_quote_count | 0 | No QuoterV2 executable quotes produced |
| roundtrip_evaluated_total | 0 | No roundtrips simulated end-to-end |
| structural_advantage_met | false | Flashblocks not connected (public WSS rate-limited) |

**Root cause**: Base quote path is dominated by SLOT0_DIAGNOSTIC quotes. Without Flashblocks sub-block state (~200ms), the quoting infrastructure cannot produce executable QuoterV2 quotes at competitive latency. The gap is low in theory but can't be captured without structural advantage.

### Flashblocks Integration Status (R39r)
| Component | Status | Notes |
|-----------|--------|-------|
| FlashblocksWatcher module | **BUILT** | WSS subscription + state tracking + health check |
| chains.yaml config | **DONE** | flashblocks_ws_endpoint + flashblocks_http_endpoint for base |
| start.py wiring | **DONE** | Watcher initialization + health injection into per_chain |
| hot_loop_snapshot | **DONE** | flashblocks state surfaced (connected, is_healthy, last_sub_block) |
| lane_summary | **DONE** | structural_advantage_met gated on flashblocks_healthy |
| EXECUTABLE_TRUTH_GATE | **DONE** | Constants + long_scan_summary integration |
| Public WSS connectivity | **BLOCKED** | wss://base.flashblocks.base.org/ws not connecting (rate-limited) |
| Private RPC provider | **NOT STARTED** | Need bloXroute/Alchemy/Flashbots endpoint for production |

## 3) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2469 passed, 5 skipped, 47.4s)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED (47.0s)
py -3.11 start.py --config-list [6 chains] --minutes 10 --cycles 1: 66 runs (16P/50F), Flashblocks surfaced
py -3.11 scripts/inspect_rolling.py: rolling artifacts healthy
```

## 4) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK (3 canonical files + long_scan_latest + hot_loop_latest)
- EXECUTABLE_TRUTH_GATE: OK (constant in __all__, referenced in classify_chain_profit_state)
- structural_advantage_met: OK (runtime-gated on flashblocks_healthy, not hard-coded false)
- flashblocks surfaced in hot_loop: OK (connected, is_healthy, last_sub_block_number)
- contour lock: OK (comment block in onboard_base_profit.yaml)
- sweep narrowed: OK ($25/$50/$75 — lead step 7)
- 23 new contract tests: PASS (test_r39r_flashblocks.py)
- config inventory: OK (onboard_base_profit.yaml in ALLOWED_YAML_FILES)

## 5) Blockers / Next Steps (prioritized)
1. **Flashblocks private RPC** (P0, INFRA): Public WSS not connecting. Need private Flashblocks/preconf endpoint (bloXroute, Alchemy, etc.) for sub-block state.
2. **Base executable truth** (P0, ECON): real_quote_count=0, roundtrip_evaluated=0. QuoterV2 quotes not produced. Cannot promote from CANDIDATE until Flashblocks connected + executable quotes flowing.
3. **Arb gap 27 bps** (P1, ECON): PRIMARY_BLOCKER with 63 real quotes but 0 profitable RTs. Gas dominates.
4. **Coverage chains all FAIL** (P2, COVERAGE): linea/mantle/scroll/zksync all 0 signals. Expected for explorer chains.

## 6) Lead's R39r Fix Steps: Execution Map
step_01: **DONE** — Fix P0 blocker classification: "Base executable truth without Flashblocks/preconf" (EXECUTABLE_TRUTH_GATE constant + config comments).
step_02: **DONE** — Lock contour USDC/DAI+USDC/USTT primary, WETH/USDC benchmark/diagnostic only (config comment block).
step_03: **DONE** — Integrate Flashblocks read-path: FlashblocksWatcher module + chains.yaml + start.py + hot_loop + lane_summary.
step_04: **DONE** — Public preconf not for production: documented in flashblocks.py module docstring.
step_05: **DONE** — Split read-path vs submit-path: FlashblocksWatcher is read-only, submit-path deferred to private RPC.
step_06: **DONE** — Promotion gate: EXECUTABLE_TRUTH_GATE wired into classify_chain_profit_state.
step_07: **DONE** — Narrow notional corridor to $25/$50/$75.
step_08: **DONE** — Tests: 2469 passed (+23 R39r), all gates PASS.
step_09: **DONE** — Online scan: 66 runs, 6 chains, flashblocks surfaced in artifacts.
step_10: **DONE** — DEV_REPORT updated (this report) with fresh evidence.

## 7) What I need from Lead now
1. **Flashblocks endpoint**: Public WSS not connecting. Do we have access to a private Flashblocks RPC (bloXroute Base Fast RPC, Alchemy Flashblocks, etc.)?
2. **QuoterV2 path review**: Base has 116 signals but real_quote_count=0. Is the quote path correctly attempting QuoterV2 for Base pairs, or is it falling back to slot0 exclusively?
3. **Executable truth path**: With Flashblocks connected, what's the expected flow to get real_quote_count > 0? Is it: Flashblocks sub-block → DirtySetTracker → PairHotQueue → QuoterV2 re-quote?
4. **Promotion criteria**: Once Flashblocks connected + real_quote_count > 0 + roundtrip_evaluated > 0, should Base auto-promote from CANDIDATE → PRIMARY_BLOCKER/THIN_POSITIVE?
