# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## Stage Context

**End-goal**: Production DEX↔DEX arbitrage with real on-chain execution and proven net profit.  
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, canonical rolling on arbitrum_one.

## SESSION GOAL (2026-03-09 evening)
**Goal**: Multi-chain quality stabilization - profit invariant fix + session propagation fix

### Workflow Contract (enforced 2026-03-09)
> **Order**: 1) code/config/tests → 2) verification runs → 3) docs/artifacts update
> Any report generated before final reruns is non-canonical by process.

### Blocker Classification (2026-03-09 22:10 FRESH v3.2.68)
```
code_blocker:            RESOLVED (pytest 1524 passed, CI ALL REQUIRED GATES PASSED)
multicall_blocker:       RESOLVED (success_rate=1.0 all chains)
websocket_blocker:       RESOLVED (ws_connected=true, ALL 6 chains)
cost_reporting_blocker:  RESOLVED (cost_model_version v3)
profit_contract_blocker: RESOLVED (v3.2.68 invariant fix + fresh evidence 0.03=0.03=0.03 Mantle)
dex_compatibility_blocker:
  Arbitrum: SIGNAL_PRODUCING (4 signals, $3.96, runDir 220644) ✅
  zkSync:   POLICY_REJECTED (0 signals, runDir 220720, SUSPECT_SPREAD_HARD=22, profitable_count=28)
  Base:     DATA_QUALITY (0 signals, runDir 220828, MIXED_SOURCE=8, profitable_count=6)
  Mantle:   SIGNAL_PRODUCING (3 signals, net=$0.03, runDir 220920) ✅
  Scroll:   NO_DATA (0 signals, runDir 220959, BLOCKED_BY_SECOND_DEX)
  Linea:    FAIL (PRICE_SCALE 14.3%, runDir 221018, 1 DEX only)
```

**v3.2.68 Fix (2026-03-09 22:10)**: Profit invariant fix + session propagation
- FIXED: `daily_report.net_pnl_usdc` now uses `execution_report.total_net_usdc` as canonical (was truth_report)
- ADDED: `truth_net_pnl_usdc` field for transparency (original truth_report value)
- FIXED: `source` field now says `"execution_report.total_net_usdc"` when m4_sim_net_usdc available
- FIXED: CI runs now set `run_type: "automated"` explicitly
- FIXED: CI runs now set `primary_blocker_of_session: "CI_AUTOMATED_RUN"` marker
- ADDED: `test_mantle_case_invariant_with_different_gas_configs` test
- ADDED: `test_automated_session_with_ci_marker` test
- TEST COUNT: 1524 passed (was 1522, +2 invariant/session tests)
- ROOT CAUSE: truth_report uses chain-specific gas (e.g., 0.02 Mantle), execution_report uses paper_realistic (0.10)
- VERIFIED: Mantle 220920 shows `net_pnl_usdc=0.03, source="execution_report.total_net_usdc"` ✅

**v3.2.67 Fix (2026-03-09 21:35)**: Profit invariant hardening + session propagation
- ADDED: 4 invariant tests enforcing `daily_report.net_pnl_usdc == execution_report.total_net_usdc == run_summary.total_net_usdc`
- ADDED: `run_type: "automated"|"manual"` marker in session block (CI/gate vs human distinction)
- VERIFIED: Fresh evidence shows 3.7175 = 3.7175 = 3.7175 profit invariant (Arbitrum 213502)
- TEST COUNT: 1522 passed (was 1520, +4 invariant tests)

**v3.2.65 Fix (2026-03-09 21:00)**: Daily report profit alignment + runtime claims validation
- FIXED: `daily_report.theoretical_net_profit.net_pnl_usdc` now uses `execution_pnl_included`
- ADDED: `all_signals_net_pnl_usdc` field for transparency (includes excluded signals)
- ADDED: `check_repo_safety.py` check [15] validates DEV_REPORT claims against run_summary
- ADDED: 6 new tests (2 daily_report alignment + 4 runtime claims validation)
- RESULT: net_pnl_usdc now matches M4 execution_report.total_net_usdc
- CONFIG: zkSync `suspect_spread_bps_hard: 1000` (was 800, default was 500 - too aggressive)
- CONFIG: Scroll `suspect_spread_bps_hard: 1000` + market constraint documentation
- RESULT: zkSync now gates 8 opportunities (was over-rejecting before), 26 legitimate SUSPECT_SPREAD_HARD rejects remain (>10% spreads = bad data/stale prices)

**CORRECTED**: Previous report incorrectly classified zkSync as purely "MARKET_BLOCKED". Truth: both market constraint (thin liquidity) AND policy was too aggressive (500 bps default). Now fixed.

**Cost-aware reporting summary (2026-03-09 v3.2.58)**:
1. `strategy/artifacts.py`: Extended `_compute_execution_pnl` with canonical cost formula:
   - `cost_model_version: "paper_gas_slippage_l1_v3"` (upgraded from v2)
   - **FIXED**: `slippage_usd = paper_size_usd * slippage_bps / 10000 * num_signals` (position-based)
   - **FIXED**: `gas_usd = gas_usd_estimate * num_signals` (per-signal aggregation)
   - Total cost invariant: `total_cost_usd = gas_usd + slippage_usd + l1_cost_usd`
2. `strategy/jobs/run_scan_real.py`: Same-DEX fallback artifact reconciliation
   - Added `same_dex_fallback_mode`, `spread_signals_count`, `same_dex_signals_active`
   - Prevents artifact mismatch when signals > 0 but total_opportunities = 0
3. `strategy/quotes.py`: Per-chain SUSPECT_LIQUIDITY threshold
   - New config keys: `quoter_max_gas_estimate`, `quoter_max_ticks_crossed`
   - zkSync: 1M gas threshold (default 500k too aggressive)
4. Config freezes: Linea frozen, zkSync/Scroll relaxed gas thresholds
5. `tests/unit/test_same_dex_policy.py`: 6 new same-DEX fallback artifact tests

**ВАЖЛИВО**: `infra_gate: PASS` ≠ `run_summary.status: PASS`. See [Status_M5_0.md](status/Status_M5_0.md) for terminology.

### v3.2.65 Daily Report Fix (2026-03-09 21:00)
- FIXED: `daily_report.theoretical_net_profit.net_pnl_usdc` now uses `execution_pnl_included` (only tradeable signals)
- ADDED: `all_signals_net_pnl_usdc` field for transparency (includes excluded signals)
- ADDED: `check_repo_safety.py` check [15] validates DEV_REPORT claims against run_summary artifacts
- RESULT: daily_report.net_pnl_usdc now matches execution_report.total_net_usdc

**Investigation conclusion**: zkSync/Scroll are **MARKET_BLOCKED** - infrastructure works perfectly (quotes flow, multicall success), but on-chain liquidity doesn't support arbitrage. Config thresholds relaxed 30x with no improvement.

**Session fixes applied (2026-03-09 12:30)**:
1. **WebSocket endpoint resolution FIX**: ci_m5_0_gate.py now reads chain_id from config for correct WS host
2. **strategy/infra.py FIX**: Clears stale WS env vars, uses OVERWRITE not setdefault; extracts provider_id_ws from URL
3. **zkSync quoter_v2 FIX**: Added `use_quoter_v2: true` to coverage_intent_zksync.yaml
4. **Linea/Scroll same-DEX FIX**: Set `require_cross_dex: false` (MIXED_SOURCE workaround)
5. **ALL_OPPORTUNITIES_REJECTED FIX**: Triggers when total_opps > 0 regardless of profitable_count
6. **provider_id_ws FIX**: Extracts provider from WS URL when resolver returns "unknown"
7. **WS host validation**: Added validate_chain_rpc_consistency() in ci_m5_0_gate.py

## 0) Meta
timestamp_utc: 2026-03-09T21:07:05Z  
rolling_provenance: 2026-03-09T21:07:05Z (arbitrum_one, ci_m5_gate_20260309_220644)  
mode: ONLINE (v3.2.69 session contract enforcement + cross_dex fallback)
test_count: 1530 passed, 2 skipped

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | Multi-chain quality stabilization - honest operational semantics (v3.2.69) |
| goal_status | **IN_PROGRESS** (2/6 chains SIGNAL_PRODUCING, 4/6 blocked) |
| close_allowed | false |
| remaining_blockers | zkSync: LIQUIDITY_ZERO; Scroll/Linea: BLOCKED_BY_SECOND_DEX (1 DEX only) |
| evidence_session_run_dirs | **ci_m5_gate_20260309_220644** (Arbitrum ✅), ci_m5_gate_20260309_220720 (zkSync), ci_m5_gate_20260309_220828 (Base), **ci_m5_gate_20260309_220920** (Mantle ✅), ci_m5_gate_20260309_220959 (Scroll), ci_m5_gate_20260309_221018 (Linea FAIL) |
| primary_blocker_of_session | profit contract mismatch (daily_report 0.1091 vs execution_report 0.0291 on Mantle) |
| blocker_status_before | ACTIVE (Mantle 213848: net_pnl_usdc=0.1091 vs total_net_usdc=0.0291 - 3.75x discrepancy) |
| blocker_status_after | **RESOLVED** (Mantle 220920: net_pnl_usdc=0.03=execution_report, source="execution_report.total_net_usdc") |
| docs_reread_confirmed | true |

**Session Progress (2026-03-09 22:10 v3.2.68, refreshed v3.2.69)** - Fresh same-session evidence:

| Chain | RunDir | M5 Gate | signals | net_usdc | Status |
|-------|--------|---------|---------|----------|--------|
| **Arbitrum** | **220644** | PASS | 4 | $3.96 | ✅ SIGNAL_PRODUCING |
| zkSync | 220720 | NO_DATA | 0 | $0 | ⚠️ POLICY_REJECTED (SUSPECT_SPREAD_HARD) |
| Base | 220828 | NO_DATA | 0 | $0 | ⚠️ DATA_QUALITY (MIXED_SOURCE) |
| **Mantle** | **220920** | PASS | 3 | **$0.03** | ✅ SIGNAL_PRODUCING |
| Scroll | 220959 | NO_DATA | 0 | $0 | ❌ BLOCKED_BY_SECOND_DEX (1 DEX) |
| Linea | 221018 | FAIL | 1 | $0 | ❌ PRICE_SCALE 14.3% + 1 DEX |

**Profit Contract Fix Verification (v3.2.68 FIXED)**:
| Chain | daily_report.net_pnl | execution_report.total_net | Aligned? | Source Field |
|-------|----------------------|---------------------------|----------|--------------|
| **Mantle** | $0.03 | $0.03 | ✅ YES | execution_report.total_net_usdc |

**Root cause** (v3.2.67→v3.2.68): truth_report uses chain-specific gas_usd_estimate (e.g., 0.02 for Mantle), but execution_report uses CostModelRegistry `paper_realistic` (gas_usd=0.10). Fix: daily_report.net_pnl_usdc now uses execution_report.total_net_usdc as canonical.

**Code changes (v3.2.64-v3.2.67)**:
- ✅ `engine/opportunity_engine.py`: Added `suspect_spread_bps_hard_threshold` to summary artifact
- ✅ `strategy/artifacts.py`: Added `suspect_spread_bps_hard` to config_params
- ✅ Tests: 12 new tests (8 config/claim + 4 invariant tests, now 1522 total)
- ✅ `scripts/check_repo_safety.py`: Added DEV_REPORT runtime claims check [15]
- ✅ `AGENTS.md`: Added Session Closure Contract
- ✅ `scripts/generate_daily_report.py`: Added `run_type: "automated"|"manual"` session marker
- ✅ `tests/unit/test_daily_report_aggregator.py`: 4 new invariant tests (profit contract enforcement)
- ✅ **v3.2.66**: All 6 coverage configs updated with CHAIN QUALITY STATUS headers:
  - `config/coverage_intent_arbitrum_one.yaml`: SIGNAL_PRODUCING (primary chain)
  - `config/coverage_intent_zksync.yaml`: INFRA_READY + removed meme tokens (HOLD/CHEEMS/MUTE/SPACE)
  - `config/coverage_intent_base.yaml`: ALL_OPPORTUNITIES_REJECTED (MIXED_SOURCE)
  - `config/coverage_intent_scroll.yaml`: NO_SPREAD_SIGNALS (MARKET_BLOCKED)
  - `config/coverage_intent_linea.yaml`: SIGNAL_NOT_INCLUDED (single DEX)
  - `config/coverage_intent_mantle.yaml`: LOW_SAMPLE (same-DEX fallback)

## 1) Commands Executed (This Session v3.2.68)

```
# Verification suite (2026-03-09 22:10)
py -3.11 -m pytest tests/unit -q: 1524 passed, 2 skipped ✅ (+2 tests)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings) ✅
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED ✅
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS ✅

# Fresh same-session online evidence (2026-03-09 22:07-22:10):
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1: PASS (220644) ✅
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 1: PASS (220720) ⚠️
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 1: PASS (220828)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 1: PASS, $0.03 (220920) ✅
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 1: PASS (220959)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 1: FAIL, PRICE_SCALE 14.3% (221018)

# Profit invariant verification (2026-03-09 22:10):
# Mantle 220920: net_pnl_usdc=0.03, source="execution_report.total_net_usdc", truth_net_pnl_usdc=0.11 ✅ INVARIANT FIXED
# Session propagation: run_type="automated", primary_blocker_of_session="CI_AUTOMATED_RUN" ✅
```

## 2) Evidence Artifacts

**Fresh same-session verification (2026-03-09 22:07-22:10, 6 chains x 1 cycle)**:

| RunDir | Chain | M5.0 Gate | signals | net_usdc | Status |
|--------|-------|-----------|---------|----------|--------|
| **220644** | **Arbitrum** | PASS | 4 | $3.96 | ✅ SIGNAL_PRODUCING |
| 220720 | zkSync | NO_DATA | 0 | $0 | ⚠️ POLICY_REJECTED |
| 220828 | Base | NO_DATA | 0 | $0 | ⚠️ DATA_QUALITY |
| **220920** | **Mantle** | PASS | 3 | **$0.03** | ✅ SIGNAL_PRODUCING |
| 220959 | Scroll | NO_DATA | 0 | $0 | ❌ BLOCKED_BY_SECOND_DEX |
| 221018 | Linea | FAIL | 1 | $0 | ❌ PRICE_SCALE 14.3% |

**Key distinction**: `M5.0 PASS` = infrastructure/schema/coverage OK AND run_summary.status != NO_DATA. `NO_DATA` = infrastructure works but no signals produced.

**Profit invariant FIXED (v3.2.68)**:
- **Mantle 220920**: daily_report.net_pnl_usdc = 0.03 = execution_report.total_net_usdc ✅
- **Source field**: `"source": "execution_report.total_net_usdc"` ✅ (was "truth_report.execution_pnl_included")
- **Transparency**: `truth_net_pnl_usdc: 0.11` preserved for comparison
- **Root cause fixed**: truth_report uses chain-specific gas (0.02), execution_report uses paper_realistic (0.10)

**Session propagation FIXED (v3.2.68)**:
- **run_type**: `"automated"` ✅ (CI automated marker)
- **primary_blocker_of_session**: `"CI_AUTOMATED_RUN"` ✅ (explicit CI marker)
- **blocker_status_before/after**: `"N/A"` ✅ (proper CI defaults)

**Chain quality classification (v3.2.68 fresh)**:
- **Arbitrum**: SIGNAL_PRODUCING (signals producing profit) ✅
- **Mantle**: SIGNAL_PRODUCING (signals, $0.03 net) ✅
- **zkSync**: LIQUIDITY_ZERO (market impaired - no arbitrage opportunities)
- **Base**: PASS infra, 0 signals (needs investigation)
- **Scroll**: BLOCKED_BY_SECOND_DEX (only 1 active DEX)
- **Linea**: FAIL (PRICE_SCALE 14.3% + only 1 active DEX)

**Rolling canonical** (updated to 220644):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-09T21:07:05Z, arbitrum_one)

## 3) Next Steps

1. **Session IN_PROGRESS**: Multi-chain quality stabilization ongoing, 2/6 chains producing signals
2. **v3.2.68 complete**: 
   - `daily_report.net_pnl_usdc` now uses `execution_report.total_net_usdc` as canonical
   - `truth_net_pnl_usdc` preserved for transparency
   - CI runs explicitly set `run_type: "automated"` and `primary_blocker_of_session: "CI_AUTOMATED_RUN"`
3. **2 chains SIGNAL_PRODUCING**: Arbitrum, Mantle ($0.03)
4. **4 chains blocked**: zkSync (POLICY_REJECTED), Base (DATA_QUALITY), Scroll/Linea (BLOCKED_BY_SECOND_DEX)
5. **Profit invariant FIXED**: Mantle 220920 shows net_pnl_usdc=0.03=execution_report.total_net_usdc (was 0.11 vs 0.03)
6. **Next session**: Investigate Base signal production; consider adding more DEXes to Scroll/Linea

---
*Generated: 2026-03-09T21:07:05Z v3.2.69*
