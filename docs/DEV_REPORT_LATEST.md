# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-16, Session 9 Round 28.14)
**Goal**: R28.14 — Fix repo safety failures (forbidden version strings, DEV_REPORT timestamp drift). Formalize benchmark_chain concept (linea as strongest ALIGNED chain by merit). Unified truth standard per chain. Fresh scans to verify.
**Prior (R28.13)**: Truth contract alignment (ALIGNED/POSITIVE/BLOCKED/NOT_PROVEN), hot_loop v1.1 provenance, truth KPIs surfaced at 4 levels, dashboard Panel 0 "Hot Loop Live", PairHotQueue + micro-quote, cross-pair parallel quoter prefetch (quote_rpc_ms 8x reduction). Lead review: "repo not green — check_repo_safety.py and ci_full_pipeline.py fail due to forbidden version strings in Status files, DEV_REPORT timestamp mismatch. Linea is strongest chain, not arb. Don't cancel primary contract but formalize benchmark."

## 0) Meta
timestamp_utc: 2026-03-16T09:20:02Z
rolling_provenance: 2026-03-16T09:20:02Z (run_summary_latest.json — R28.14 fresh evidence)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260316_101945_381746
mode: BENCHMARK_CHAIN + UNIFIED_TRUTH_STANDARD + DOCS_FIX
test_count: 1888 passed, 3 skipped
schema_version: start:long_scan_summary:v1.12

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.14: Fix repo safety failures, formalize benchmark_chain, unified truth standard, fresh scans |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb/zksync BLOCKED; mantle 5/7 FAIL; scroll 7/7 FAIL; base intermittent (ALIGNED this scan, but unstable) |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260316_101945_381746 (primary rolling), long_scan_latest.json (2026-03-16T09:18:33Z, 6 chains, 42 runs 371s), ci_m5_gate_linea_20260316_101851_774878 (ROUNDTRIP_PROFITABLE=2), ci_m5_gate_base_20260316_101910_781928 |
| primary_blocker_of_session | R28.13 repo not green: forbidden version strings in Status_M4.md (v1.1, v1.12) and Status_M5_0.md (v1.11), DEV_REPORT timestamp mismatch, no formal benchmark_chain concept |
| blocker_status_before | ACTIVE: check_repo_safety.py FAIL (3 errors, 2 warnings), ci_full_pipeline.py FAIL, no benchmark_chain in artifacts, no truth_standard_met per chain |
| blocker_status_after | RESOLVED: check_repo_safety PASS (0 warnings), ci_full_pipeline PASS, benchmark_chain=linea in artifacts, truth_standard_met + is_benchmark fields per chain |
| start_metric | R28.13: 1886 tests, repo FAIL, no benchmark_chain |
| end_metric | R28.14: 1888 tests (+2), repo PASS, benchmark_chain=linea (merit-based), unified truth standard |
| delta | +benchmark_chain (merit-based: linea), +truth_standard_met per chain, +is_benchmark per chain, fixed forbidden version strings in Status files, fixed DEV_REPORT timestamp propagation, +2 tests |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R28.14 lead review directive (10 fix steps)
change_summary:
  - DOCS_FIX: Removed forbidden version strings (v1.1, v1.12, v1.11) from Status_M4.md and Status_M5_0.md. Fixed DEV_REPORT timestamp propagation to match rolling run_context.run_timestamp.
  - BENCHMARK_CHAIN: start.py — _compute_truth_path_alignment() now returns (result, benchmark_chain) tuple. Strongest ALIGNED chain selected by merit (profitable_roundtrips desc, gap_to_zero_bps asc). New fields: truth_standard_met, is_benchmark per chain. benchmark_chain as top-level field in build_summary.
  - POLICY: Primary chain (arbitrum_one) remains contractual for rolling. Benchmark chain is dynamic by merit. Linea currently holds benchmark.
touched_files: start.py, tests/unit/test_start.py, docs/DEV_REPORT_LATEST.md, docs/status/Status_M5_0.md, docs/status/Status_M4.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: **PASS** (1888 passed, 3 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (all gates green)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings)
py -3.11 start.py --config-list (6 chains) --hours 0.10 --cycles 1: **42 runs, 371s wall**
py -3.11 scripts/ci_m5_0_gate.py --online --config onboard_linea_stage1.yaml --cycles 5: **PASS** (ROUNDTRIP_PROFITABLE=2)
py -3.11 scripts/ci_m5_0_gate.py --online --config onboard_base_stage2.yaml --cycles 5: **PASS**
py -3.11 scripts/ci_m5_0_gate.py --online --config real_minimal.yaml --cycles 5 --refresh-rolling: **PASS** (rolling updated)

## 3) Artifacts Attached
rolling (FRESH from R28.14):
  - data/runs/_rolling/_latest.json (run_dir: ci_m5_gate_arbitrum_one_20260316_101945_381746)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-16T09:20:02Z)
  - data/runs/_rolling/long_scan_latest.json (generated_at: 2026-03-16T09:18:33Z, 42 runs, benchmark_chain=linea)
  - data/runs/_rolling/hot_loop_latest.json (17 full / 25 hot / 0 micro, 42 runs)

## 4) Key Results

```
# R28.14 Fresh Evidence (long_scan_latest.json)
schema: start:long_scan_summary:v1.12
generated_at: 2026-03-16T09:18:33Z
total_runs: 42, wall_seconds: 371
benchmark_chain: linea

# Hot Loop: 17 full sweeps, 25 hot requotes, 0 micro requotes
# PairHotQueue: 5 chains loaded, 54 pairs

# Per-Chain
arbitrum_one: runs=7 pass=7 fail=0 signals=61 profitable_rt=0  state=PRIMARY_BLOCKER    quote_rpc_ms=5563
zksync:       runs=7 pass=7 fail=0 signals=14 profitable_rt=0  state=PRIMARY_BLOCKER    quote_rpc_ms=10516
base:         runs=7 pass=1 fail=0 signals=1  profitable_rt=1  state=CONFIRMED_POS_CTRL quote_rpc_ms=21968
mantle:       runs=7 pass=0 fail=5 signals=0  profitable_rt=0  state=CANDIDATE           quote_rpc_ms=9467
linea:        runs=7 pass=7 fail=0 signals=21 profitable_rt=14 state=CONFIRMED_POS_CTRL quote_rpc_ms=8125
scroll:       runs=7 pass=0 fail=7 signals=0  profitable_rt=0  state=CANDIDATE           quote_rpc_ms=4233

# Truth Path Alignment (R28.14 — benchmark_chain + unified truth standard)
arbitrum_one: BLOCKED     truth_standard_met=false  is_benchmark=false  real_quotes=28
zksync:       BLOCKED     truth_standard_met=false  is_benchmark=false  real_quotes=14
base:         ALIGNED     truth_standard_met=true   is_benchmark=false  real_quotes=3   profitable_rt=1
linea:        ALIGNED     truth_standard_met=true   is_benchmark=true   real_quotes=14  profitable_rt=14
mantle:       NOT_PROVEN  truth_standard_met=false  is_benchmark=false  real_quotes=0
scroll:       NOT_PROVEN  truth_standard_met=false  is_benchmark=false  real_quotes=0

# Arb gap improvement: 3.25 bps (best-ever from rolling sweep)
# quote_rpc_ms arb: 14.6s (R28.13) -> 5.6s (R28.14): further improvement
```

## 5) Contract Checks
- Forbidden version strings removed from Status files — VERIFIED (check_repo_safety PASS)
- DEV_REPORT timestamp propagated from rolling run_context.run_timestamp — VERIFIED
- benchmark_chain=linea in long_scan_latest.json — VERIFIED (14 profitable RT, is_benchmark=true)
- truth_standard_met per chain: linea=true, base=true, arb/zksync/mantle/scroll=false — VERIFIED
- Primary chain (arb) remains contractual for rolling; benchmark is dynamic — ARCHITECTURAL
- Linea M5 gate ROUNDTRIP_PROFITABLE=2 — VERIFIED (separate ci_m5_0_gate run)
- CI pipeline all gates green — VERIFIED

## 6) Blocker Classification

```
code_blocker: NONE (pytest 1888 PASS, CI pipeline green, repo safety PASS)
market_gap: MEDIUM (arb gap=3.25 bps best-ever but BLOCKED; zksync BLOCKED; mantle/scroll infra-fail)
linea: ALIGNED / BENCHMARK (14 profitable RT, quality healthy, truth_standard_met=true)
base: ALIGNED (intermittent — this scan 0 fails, but previous scan had 3 fails)
arb: BLOCKED (gap=3.25 bps approaching breakeven — fee structure is root cause)
quote_performance: arb 5.6s, linea 8.1s, base 22s (still highest), zksync 10.5s
```

## 7) R28.14 Session Summary
- DOCS_FIX: Removed all forbidden version strings from Status_M4.md and Status_M5_0.md. Fixed DEV_REPORT timestamp propagation. check_repo_safety PASS (0 warnings).
- BENCHMARK_CHAIN: Formal merit-based benchmark_chain selection. Linea is current benchmark (most profitable_roundtrips among ALIGNED chains). Per-chain truth_standard_met and is_benchmark fields.
- POLICY: "Primary" = contractual role (arbitrum_one for rolling). "Benchmark" = dynamic merit (linea currently). Next milestone: unified truth standard across all chains + event-driven hot-loop speed, NOT priority reshuffling.
- FRESH_SCANS: 42-run 6-chain long scan + linea M5 (ROUNDTRIP_PROFITABLE=2) + base M5 (PASS) + arb M5 with rolling refresh.
- Tests: 1888 (+2 benchmark_chain tests).

## 8) What Lead Needs To Decide
1. Formal promotion rule: if linea holds ALIGNED for N consecutive scans, should it become primary rolling chain?
2. Base intermittency: ALIGNED this scan (0 fails) but POSITIVE last scan (3 fails). Needs RPC stability investigation.
3. Arb gap=3.25 bps (best-ever): approaching breakeven. Fee=100 lever would save ~8 bps. When to attempt fee-100 testing?
4. Mantle/scroll persistent failures: quarantine or continue monitoring? mantle 5/7 FAIL, scroll 7/7 FAIL.
5. Event-driven hot-loop: micro-quote pathway wired but 0 WSS connected. Next priority or defer?