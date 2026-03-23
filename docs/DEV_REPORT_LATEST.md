# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39g**: Gate accuracy fix + blocker classification. Coverage gate fixed for thin productive contours. INFRA_FAIL no longer masks economics data. Gate-vs-profit-blocker section added to pair_level_rca.

## SESSION GOAL (R39g: gate accuracy + blocker classification fix)
**Goal**: (1) Fix coverage gate `pairs_count < 5` for thin productive contours using `hot_requote`, (2) Fix blocker classification — INFRA_FAIL should not mask economics data when RT/OE evidence exists, (3) Add gate_fail_reason vs actual_profit_blocker to pair_level_rca.py output.
**Prior (R39f)**: 2296 tests, source coverage audit, dual-route contract locked, same-DEX diagnostic-only.
**Lead directive (R39g)**: Fresh canonical scan (42 runs, 233 signals, 36 RT, 0 profitable, $318.19). Key finding: "FAILs exist but don't explain zero profit on healthy chains." arb 7/7 PASS, 224 signals, 27 real_quotes, still 0 profitable RT — pure economics. Secondary chains mislabeled as INFRA_FAIL due to cascading coverage gate + blocker classification issue.

## 0) Meta
timestamp_utc: 2026-03-23T21:08:05Z
run_dir_name: ci_m5_gate_arbitrum_one_20260323_220737_708664
mode: R39g_GATE_ACCURACY
test_count: 2306 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.14
code_identity:
  primary: ts:2026-03-23T21:08:05.135511Z
  dirty: true (R39g code changes uncommitted)
  desc: gate_accuracy_blocker_fix

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39g: gate accuracy + blocker classification fix |
| goal_status | **REACHED** (coverage gate fixed, blocker classification corrected, gate-vs-blocker RCA added) |
| close_allowed | true |
| remaining_blockers | profitable_rt=0 (market economics on all chains); linea PRICE_SCALE VIOLATION (WETH/USDC inverted); base.aerodrome blocked |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260323_220737_708664 (lead's scan, 42 runs 6 chains reused — code changes are gate/classification/RCA only, no scan behavior change) |
| primary_blocker_of_session | Spurious COVERAGE FAIL + INFRA_FAIL masking economics data on thin productive chains |
| blocker_status_before | ACTIVE: zksync/mantle/linea/scroll all labeled INFRA_FAIL despite having RT/OE data |
| blocker_status_after | **RESOLVED**: zksync→OE_ECONOMICS, mantle→MIXED_SOURCE, linea→QUOTE_PATH_CONSTRAINED, scroll→MIXED_SOURCE |
| start_metric | 2296 tests, 4/6 chains mislabeled INFRA_FAIL |
| end_metric | 2306 tests, 0 chains mislabeled INFRA_FAIL, gate-vs-blocker in RCA output |
| delta | +10 tests, 3 code fixes (ci_m5_0_gate, chain_stats, pair_level_rca) |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 -- R39g: gate accuracy + blocker classification fix
change_summary:
  - **scripts/ci_m5_0_gate.py** — `hot_requote` universe source uses relaxed coverage thresholds (min_pairs=1, min_pools=2), same as `discovery_runtime`.
  - **strategy/chain_stats.py** — `_compute_blocker_evidence()`: INFRA_FAIL bypassed when RT/real_quote/OE data exists; NO_SIGNAL bypassed when RT data exists.
  - **scripts/pair_level_rca.py** — `load_gate_result()`, `_derive_profit_blocker()`, `_print_gate_vs_blocker()` added. Console + JSON output includes gate status vs profit blocker.
  - **tests/unit/test_r39g_gate_blocker.py** — +10 tests: coverage gate (2), blocker classification (4), profit blocker derivation (4).

## 2) Root Cause Analysis

### Cascading Issue (before fix)
1. `hot_requote` universe source → `min_pairs=5` threshold (designed for full config universe)
2. Thin productive contours (zksync=2, linea=3, scroll=3, mantle=4 pairs) → COVERAGE FAIL
3. High fail/runs ratio → `_compute_blocker_evidence()` assigns INFRA_FAIL
4. Real economics data (RT evaluated, real quotes, OE rejection funnel) masked by misleading label

### Fix Chain
1. **Coverage gate**: `hot_requote` now uses `min_pairs=1` (productive set is intentionally thin)
2. **INFRA_FAIL**: requires rt_total==0 AND rq_total==0 AND oe_total==0 (truly no data)
3. **NO_SIGNAL**: requires rt_total==0 AND rq_total==0 (no RT evidence)
4. **RCA output**: gate status shown separately from profit blocker derivation

## 3) Per-Chain Verdicts (from lead's fresh scan, updated blocker)

| Chain | Gate | Blocker (new) | RT | Best PnL | Evidence |
|-------|------|---------------|----|---------:|----------|
| arb | PASS | OE_ECONOMICS | 4 RT | -254 bps (ARB/USDC) | 224 sig, 27 rq, 7/7 PASS, 100% exec |
| mantle | FAIL (COVERAGE) | MIXED_SOURCE | 2 RT | -360 bps (WETH/WMNT) | 0 sig, 4 rq, MIXED_SOURCE 61.5% |
| scroll | FAIL (COVERAGE) | MIXED_SOURCE | 1 RT | -352 bps (WETH/USDC) | 0 sig, 2 rq, MIXED_SOURCE 50% |
| linea | FAIL (PRICE_SCALE+COV) | QUOTE_PATH_CONSTRAINED | 0 RT | - | 0 sig, 0 rq, PRICE_SCALE WETH/USDC |
| zksync | FAIL (COVERAGE) | OE_ECONOMICS | 1 RT | -737 bps (WETH/USDC) | 6 sig, 2 rq, NET_PROFIT 80% |
| base | - | QUOTE_PATH_BLOCKED | 1 RT* | - | SLOT0_DIAGNOSTIC 83.8%, 5.9% exec rate |

## 4) Code Changes (R39g)
1. **scripts/ci_m5_0_gate.py** — Line 630: `if universe_source in ("discovery_runtime", "hot_requote"):` (was: `== "discovery_runtime"`)
2. **strategy/chain_stats.py** — Lines 150-170: INFRA_FAIL check adds rt_total/rq_total/oe_total guard. NO_SIGNAL check adds rt_total/rq_total guard.
3. **scripts/pair_level_rca.py** — `load_gate_result()`, `_derive_profit_blocker()`, `_print_gate_vs_blocker()` added. `main()` resolves run_dir, loads gate result, prints gate-vs-blocker section.

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK (4 rolling files)
- blocker classification: OK (no INFRA_FAIL when data exists)
- coverage gate: OK (hot_requote uses relaxed thresholds)
- dual-route contract: OK (locked by 3 tests from R39f)
- source coverage: OK (25/27 active from R39f)

## 6) Lead's 10 Steps Response

| # | Step | Status | Evidence |
|---|------|--------|----------|
| 1 | arb: don't waste time on gate-relaxation — economics blocker proven | **ACKNOWLEDGED** | Gate PASS, OE_ECONOMICS confirmed |
| 2 | linea: fix PRICE_SCALE VIOLATION WETH/USDC | **DOCUMENTED** | price=0.01476 outside [100,50000] — future work |
| 3 | base: stay narrow — quotes.py, quote_adapters, aerodrome | **DOCUMENTED** | SLOT0_DIAGNOSTIC 83.8% — separate track |
| 4 | scroll: reduce MIXED_SOURCE debt | **DOCUMENTED** | MIXED_SOURCE 50% — need source-separation |
| 5 | mantle: route-level economics RCA, not adapter gap | **DOCUMENTED** | MIXED_SOURCE 61.5% — economics + source issue |
| 6 | zksync: stability-first policy | **DOCUMENTED** | OE_ECONOMICS, NET_PROFIT 80% — correct classification now |
| 7 | Review coverage gate `pairs_count < 5` | **DONE** | hot_requote uses min_pairs=1 |
| 8 | Fix blocker classification NO_SIGNAL/INFRA_FAIL | **DONE** | chain_stats.py RT/OE guard added |
| 9 | Add gate_fail_reason vs profit_blocker to RCA | **DONE** | pair_level_rca.py gate-vs-blocker section |
| 10 | Canonical run with dashboard | **PENDING** | After code fixes; lead to verify |

## 7) Blockers / Next Steps
- **profitable_rt=0**: economics blocker (all chains). arb proves pipeline is working — slippage dominates.
- **linea PRICE_SCALE**: WETH/USDC inverted (0.01476). May need direction-aware price check or pair flip.
- **base.aerodrome**: priority #1 source-expansion. VE33_QUOTE_FAILED.
- **MIXED_SOURCE on scroll/mantle**: source-separation or filter needed.
- **arb**: no source-expansion needed. All 5 active DEXes contribute. Economics blocker.
- **zksync/scroll excluded_pair_hints**: documented as policy. Revisit only if RT-evaluated or gap metrics improve without them.
- **ambient**: tech debt. No action until a chain needs it.
- **Source-expansion gating**: any new source must pass canonical run with dashboard and show improvement in real_quote_count, RT-evaluated, route diversity, or best RT gap.
