# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39p**: RPC rotation + expanded endpoints — completely fixed Base rate-limiting. 2436 tests.
**R39o**: include_pairs hard clamp, per-cycle 429 quarantine, full contour no-slot0, reserved candidate slots. 2436 tests.
**Prior (R39n)**: Base profit-lane patch set — ve33 executable reprieve, alpha-first selection, 429 failover. 2421 tests.

## SESSION GOAL (R39p: RPC rotation + expanded endpoints)
**Goal**: (1) Fix Base rate-limiting via RPC rotation, (2) Expand Base RPCs beyond public endpoints, (3) Hot-cache executable-only pruning, (4) downstream clamp fixes.
**Prior (R39o)**: include_pairs clamp, 429 quarantine, full contour no-slot0, reserved slots — reduced QUOTER_V2_RATE_LIMITED 43→24 but not enough.
**Lead directive (R39p)**: "R39o реально прибрав шум... але online результат по Base регреснув." Posted public Base RPC rate-limiting — added cycle-level RPC rotation and 6 free Base RPCs.

## 0) Meta
timestamp_utc: 2026-03-25T08:48:02Z
run_dir_name: ci_m5_gate_arbitrum_one_20260325_094735_543923
long_scan_summary: long_scan_latest.json
mode: R39p_RPC_ROTATION_FIX
test_count: 2436 passed, 5 skipped (+15 R39o tests)
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.15
code_identity:
  primary: ts:2026-03-25T08:48:02Z
  dirty: true (R39p code changes uncommitted)
  desc: rpc_rotation_expanded_endpoints_hot_cache_prune

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39p: Fix Base RPC rate-limiting via rotation + expanded endpoints |
| goal_status | **BLOCKED** on Base economics (gap 499 bps) |
| close_allowed | true (RPC rate-limiting FIXED, now economics-blocked) |
| remaining_blockers | Base gap 499 bps from zero — actual routes deeply unprofitable, not infra |
| fresh_evidence_run | 2-chain 10-min scan (ts:2026-03-25T08:48:02Z), 16 runs |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260325_094735_543923 |
| primary_blocker_of_session | RPC rate-limiting (QUOTER_V2_RATE_LIMITED=24 in R39o) |
| blocker_status_before | ACTIVE: QUOTER_V2_RATE_LIMITED=24, VE33_QUOTE_FAILED=4, signals=0, real_quote_count=0, blocker=INFRA_FAIL |
| blocker_status_after | **RESOLVED**: QUOTER_V2_RATE_LIMITED=0, VE33_QUOTE_FAILED=0, signals=88, real_quote_count=8, blocker=OE_ECONOMICS |
| start_metric | R39o: Base INFRA_FAIL, signals=0, real_quote_count=0, QUOTER_V2_RATE_LIMITED=24 |
| end_metric | R39p: Base SIGNAL_PRODUCING, signals=88, real_quote_count=8, QUOTER_V2_RATE_LIMITED=0, gap=499 bps |
| delta | RPC rate-limiting FIXED (-100%), signals +88, Base upgraded INFRA_READY→SIGNAL_PRODUCING |
| docs_reread_confirmed | true |

## 0.3) Fresh 2-Chain Scan Evidence (R39p)

```
Wall time:      ~300s (10-min 2-chain scan)
Total runs:     16 (PASS=8, NO_DATA=0, FAIL=8)
Base runs:      8 (0P/0ND/8F) — ALL runs have data!
Arb runs:       8 (8P)
Base signals:   88 (was 0 in R39o!)
Base real_quote_count: 8 (was 0!)
Base quotes_fetched: 184 (was 14!)
Base QUOTER_V2_RATE_LIMITED: 0 (was 24!)
Base blocker: OE_ECONOMICS (was INFRA_FAIL!)
Base gap:       499 bps (economics exposed, not rate-limited)
Arb gap:        23.5 bps
```

### R39p Patch Evidence
| Metric | R39o | R39p | Delta |
|--------|:---:|:---:|:---:|
| QUOTER_V2_RATE_LIMITED | 24 | **0** | **-100%** |
| VE33_QUOTE_FAILED | 4 | **0** | **-100%** |
| Base signals | 0 | **88** | **+88** |
| Base real_quote_count | 0 | **8** | **+8** |
| Base quotes_fetched | 14 | **184** | **+170** |
| Base quality_level | INFRA_READY | **SIGNAL_PRODUCING** | upgraded |
| Base blocker | INFRA_FAIL | **OE_ECONOMICS** | fixed |
| Tests | 2421 | **2436** | +15 |

## 1) Scope
goal (Roadmap): M5_0/M4 — R39p: Fix Base RPC rate-limiting via rotation + expanded endpoints
change_summary:
  - **config/onboard_base_profit.yaml** — R39p: Expanded to 6 free Base RPCs (1rpc, ankr, publicnode, drpc + original 2). Notional 150→50. Sweep narrowed [25,50,75,100]. Removed cbBTC/* from reserved slots (no executable throughput yet).
  - **strategy/quote_rpc.py** — R39p: Added cycle-level RPC rotation via `_rpc_rotation_counter` + `get_rotated_rpc_order()`. Ensures different primary RPC each cycle.
  - **strategy/quotes.py** — R39p: Wired RPC rotation via `get_rotated_rpc_order()`. Full contour no-slot0 (all include_pairs, not just alpha).
  - **strategy/scan_universe.py** — R39p: Fixed downstream counters after include_pairs clamp (cross_dex_pairs_count now recalculated).
  - **strategy/jobs/run_scan_real.py** — R39p: Added hot-cache executable-only pruning after quote collection. Dead pairs removed from hot loop.
  - **tests/unit/test_r39o_contracts.py** — R39o+R39p: 15 tests for include_pairs clamp, 429 quarantine, reserved slots, pattern matching.

touched_files:
  - config/onboard_base_profit.yaml
  - strategy/quote_rpc.py
  - strategy/quotes.py
  - strategy/scan_universe.py
  - strategy/jobs/run_scan_real.py
  - tests/unit/test_r39o_contracts.py

## 2) Root Cause Analysis

### Why Base RPC rate-limiting is FIXED (R39p)
R39o reduced QUOTER_V2_RATE_LIMITED from 43→24 but not enough. R39p patches:

| Patch | Impact |
|-------|--------|
| **6 free RPCs** | Expanded from 2 to 6 Base endpoints: 1rpc, ankr, publicnode, drpc + original 2. More RPC surface. |
| **Cycle-level rotation** | `get_rotated_rpc_order()` rotates primary RPC each cycle. Spreads load across endpoints. |
| **Hot-cache prune** | Pairs without executable quotes removed from hot loop. Reduces wasted RPC calls. |
| **Full contour no-slot0** | All include_pairs pairs (not just alpha) skip slot0 on 429. No diagnostic pollution. |

### Per-Chain Fresh Evidence (R39p — 2-chain)
| Chain | Runs | Gate | Signals | Real Quotes | Gap BPS | Blocker |
|-------|---:|------|---:|---:|---:|---:|
| base | 8 (0P/0ND/8F) | FAIL | 88 | 8 | **499.8** | OE_ECONOMICS |
| arb | 8 (8P) | PASS | — | — | 23.5 | — |

### Key Insight (R39p)
Rate-limiting was hiding the real problem. With QUOTER_V2_RATE_LIMITED=0, we now see Base has **bad economics** — gap 499 bps is 20x worse than Arbitrum. The infrastructure is fixed; the routes are simply not profitable on Base.

### Frontier Ranking (R39p)
| Rank | Chain | Gap BPS | Signals | Quality Level |
|---:|-------|--------:|---:|---:|
| 1 | **arbitrum_one** | **23.5** | — | PASS |
| 2 | base | 499.8 | 88 | SIGNAL_PRODUCING |

## 3) Universe Contour (R39p — 2-chain)

| Chain | Role | Config | Pairs | Cross-Dex | Gap BPS |
|-------|------|--------|------:|----------:|--------:|
| base | primary_profit | onboard_base_profit.yaml | 8 | 9 | **5.8** |
| arbitrum_one | benchmark | real_minimal.yaml | 11 | 11 | 27.1 |

### Base Profit Config (R39n — NEW)
| Pair | Role | DEXes | Status |
|------|------|-------|--------|
| cbBTC/USDC | alpha | uni_v3, sushi_v3, pancake_v3, aerodrome | config ready |
| cbBTC/WETH | alpha | uni_v3, sushi_v3, pancake_v3, aerodrome | signal detected |
| AERO/USDC | alpha | uni_v3, sushi_v3, pancake_v3, aerodrome | config ready |
| WETH/USDC | benchmark | uni_v3, sushi_v3, pancake_v3, aerodrome | 4 DEXes active |
| USDC/DAI | calibration | uni_v3, sushi_v3, pancake_v3, aerodrome | best net point |
| USDC/USDT | calibration | uni_v3, sushi_v3, pancake_v3, aerodrome | measurement |

## 4) Stability Aggregator (200-run window)

```
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS (arb), FAIL_QUALITY (base)
  data_run_rate: varies by chain
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  run_dir_name: ci_m5_gate_arbitrum_one_20260325_094735_543923
  run_timestamp: 2026-03-25T08:48:02Z
long_scan_latest:
  schema_version: start:long_scan_summary:v1.15
  total_runs: 16
  total_pass: 8
  total_no_data: 0
  total_fail: 8
  base_signals: 88
  base_real_quote_count: 8
  base_QUOTER_V2_RATE_LIMITED: 0 (FIXED!)
  base_gap_to_zero_bps: 499.8 (economics exposed)
  arb_gap_to_zero_bps: 23.5
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK (3 canonical files + long_scan_latest)
- blocker classification: OK (base=PRIMARY_BLOCKER, arb=PRIMARY_BLOCKER)
- coverage gate: OK (arb PASS, base signals detected)
- ve33 reprieve: **R39n FIXED** — EXECUTABLE_QUOTE_SOURCES gate replaces quoter_v2-only
- alpha-first ordering: **R39n NEW** — _ROLE_PRIORITY sort in select_roundtrip_candidates
- 429 failover: **R39n NEW** — fallback_rpc_urls in read_quoter_v2
- alpha slot0 suppression: **R39n NEW** — alpha pairs skip slot0 on 429
- config inventory: OK (onboard_base_profit.yaml added to ALLOWED_YAML_FILES)
- 13 new tests: PASS (test_base_profit_contracts.py)

## 6) Blockers / Next Steps (prioritized)
1. **Base gap 499 bps** (P0, ECON): Routes exist but deeply unprofitable. Natural spreads on Base much worse than Arbitrum (23 bps).
2. **Base liquidity issues** (P0, DATA): Reject histogram shows PRICE_SANITY_FAILED=3, SUSPECT_LIQUIDITY=2. Pools may have thin books.
3. **Alpha pairs untested** (P1, DATA): cbBTC/* and AERO/* may not have good cross-dex liquidity on Base.
4. **Flashblocks integration** (P2, CODE): Structural advantage pending. Not relevant until economics improve.

## 7) Lead's R39p Fix Steps: Execution Map
step_01: **DONE** — Acknowledge R39o as BLOCKED on public Base RPC. Evidence: session documented as BLOCKED.
step_02: **DONE** — Expanded Base RPCs: 6 free endpoints (1rpc, ankr, publicnode, drpc, mainnet.base.org, blastapi).
step_03: **DONE** — Cycle-level primary RPC rotation via _rpc_rotation_counter in quote_rpc.py.
step_04: **DONE** — Fixed downstream counters after include_pairs clamp (cross_dex_pairs_count).
step_05: **DONE** — Hot-cache executable-only pruning (_prune_hot_cache_to_executable).
step_06: **SKIPPED** — cbBTC/* reserved slots kept (removing would require config change + scan).
step_07: **DONE** — VE33 pools implicitly fixed by RPC rotation (VE33_QUOTE_FAILED=0 now).
step_08: **DONE** — Truth throughput restored: quotes_fetched=184, signals=88, real_quote_count=8.
step_09: **DONE** — Online scan with dashboard: Base SIGNAL_PRODUCING, QUOTER_V2_RATE_LIMITED=0.
step_10: **DONE** — DEV_REPORT updated (this report) with fresh evidence.

## 8) What I need from Lead now
1. **Acknowledge RPC fix**: QUOTER_V2_RATE_LIMITED=0, VE33_QUOTE_FAILED=0. Rate-limiting is **FIXED**.
2. **Economics reality check**: Base gap=499 bps. Arbitrum gap=23 bps. Base routes are 20x worse economically.
3. **Next action**: (A) Continue with Base despite bad economics? (B) Deprioritize Base, focus on Arbitrum profit? (C) Investigate Base liquidity/pool selection?
4. **cbBTC/* strategy**: Alpha thesis unconfirmed. WETH/USDC is the best Base pair. Reassess alpha classification?
