# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-14, Session 5 Round 27.3)
**Goal**: R27.3 — Deep code audit of scanner pipeline. Fix 10 strategic/contract gaps in run_scan_real.py and related modules: remove synthetic suspect metrics, enforce strict discovery_runtime, forbid intent for NORMAL, wire pre-scan validation, unify economics, encode strategy modes.

## 0) Meta
timestamp_utc: 2026-03-14T20:26:06Z
rolling_provenance: 2026-03-14T18:39:08Z (arbitrum_one NORMAL, ci_m5_gate_20260314_193819 — unchanged from R27.2)
mode: OFFLINE (code audit + contract hardening, no online runs)
test_count: 1805 passed, 2 skipped (+7 from R27.3: test_suspect_provenance.py)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R27.3: Fix 10 strategic/contract gaps in scanner pipeline per lead audit |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb primary; ADAPTER: ve33 not implemented |
| evidence_session_run_dirs | (no online runs — code audit session; CI offline gates verified) |
| primary_blocker_of_session | 10 contract gaps: synthetic suspect metrics, silent discovery_runtime fallback, dual economics, no pre-scan validation |
| blocker_status_before | 10 strategic/contract gaps identified by lead audit |
| blocker_status_after | ALL 10 RESOLVED: code changes in 6 files + 1 new test file + 1 test update |
| start_metric | R27.2: 1798 tests, synthetic _compute_sanity_rejects, silent discovery fallback, hardcoded OE slippage 5.0 |
| end_metric | R27.3: 1805 tests, real-only suspect metrics, strict discovery, unified economics, pre-scan validation wired |
| delta | +7 tests, 6 code files modified, 1 new test file, 1 test file updated |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — scanner pipeline contract hardening (R27.3 lead audit)
change_summary:
  - `strategy/jobs/run_scan_real.py`: MODIFIED — removed _compute_sanity_rejects() (synthetic suspect fabrication), replaced with _extract_suspect_from_rejects() (real data only); discovery_runtime strict-by-default (no silent fallback); intent/intent_forced forbidden for NORMAL/COVERAGE; strategy_mode/same_dex_only encoded in stats; pre-scan validate_universe wired; paper_slippage_bps passed to opportunity_engine
  - `engine/opportunity_engine.py`: MODIFIED — paper_slippage_bps parameter added (was hardcoded 5.0); evaluate_quotes() + OpportunityEngine.__init__() accept config-driven slippage
  - `scripts/validate_universe.py`: MODIFIED — intent/intent_forced forbidden for strict run_kinds; same_dex_mode warning for NORMAL; require_cross_dex/same_dex_only in summary
  - `scripts/ci_m5_0_gate.py`: MODIFIED — run_real_scan() calls validate_universe before subprocess launch
  - `strategy/jobs/run_scan.py`: MODIFIED — pre-dispatch validate_universe for REAL mode
  - `tests/unit/test_suspect_provenance.py`: NEW — 7 tests: extract_empty, extract_single, max_deviation, none_deviation, no_synthetic_function, extract_exists, no_hardcoded_way_below
  - `tests/unit/test_suspect_quotes_counter.py`: MODIFIED — removed assertion for synthetic "way_below_expected" key
touched_files:
  - strategy/jobs/run_scan_real.py
  - engine/opportunity_engine.py
  - scripts/validate_universe.py
  - scripts/ci_m5_0_gate.py
  - strategy/jobs/run_scan.py
  - tests/unit/test_suspect_provenance.py
  - tests/unit/test_suspect_quotes_counter.py
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1805 passed, 2 skipped, 1 warning, 29.12s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (ALL REQUIRED GATES PASSED, 31.4s)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: **PASS** (2 sims, $0.50)
py -3.11 scripts/ci_m5_0_gate.py --offline: **PASS** (runDir ci_m5_gate_offline_20260314_202606)
py -3.11 scripts/validate_universe.py --config config/real_minimal.yaml: **PASS** (6 pairs, 2 DEXes, NORMAL)

## 3) Artifacts Attached (шляхи)
rolling (UNCHANGED from R27.2 — no online runs this session):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json

## 4) Key Results (числа з артефактів)

```
test_delta: +7 (1798 → 1805)
code_changes: 6 files modified, 1 file created
removed_function: _compute_sanity_rejects() — 82 lines of synthetic suspect generation
new_function: _extract_suspect_from_rejects() — 16 lines, real-data-only extraction
economics_unified: opportunity_engine now uses config paper_slippage_bps (was hardcoded 5.0)
pre_scan_validation: wired in run_scan.py, run_scan_real.py main(), ci_m5_0_gate.py run_real_scan()
discovery_strict: discovery_runtime_allow_fallback=false by default (was silent fallback)
intent_forbidden: intent/intent_forced raise RuntimeError for NORMAL/COVERAGE run_kind
strategy_modes: stats["strategy_mode"] = DYNAMIC_VERIFIED|BOOTSTRAP|TRUTH_PROBE
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline (3+1 canonical files): OK — unchanged from R27.2
- synthetic suspect metrics: REMOVED — _compute_sanity_rejects deleted, provenance tests lock it
- discovery_runtime fallback: STRICT — requires explicit config flag to allow fallback
- intent/intent_forced for NORMAL: FORBIDDEN — runtime + validate_universe enforce
- economics alignment: UNIFIED — OE uses config paper_slippage_bps (same as spreads.py)
- pre-scan validation: WIRED — 3 entrypoints call validate_universe before scan
- strategy modes: ENCODED — stats carry strategy_mode and same_dex_only
- test delta: +7 tests (1798 → 1805)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1805 PASS, CI green)
data_collection_blocker: LOW (unchanged from R27.2)
market_window_blocker: HIGH (unchanged — roundtrip_profitable=0 on primary)
adapter_blocker: MEDIUM (ve33 not implemented)
```

## 7) Lead's R27.3 10 Steps: Execution Map
step_01: **DONE** — Removed _compute_sanity_rejects(). Suspect metrics now come from real rejected_quotes (PRICE_SANITY_FAILED entries) via _extract_suspect_from_rejects(). Removed unused imports (Decimal, calculate_deviation_bps).
step_02: **DONE** — 7 regression tests in test_suspect_provenance.py: empty/single/max_dev/None extractors + 3 purity tests (no synthetic function, extract exists, no hardcoded way_below_expected). Updated test_suspect_quotes_counter.py (removed synthetic "way_below_expected" assertion).
step_03: **DONE** — discovery_runtime strict-by-default: exception raises RuntimeError unless config has discovery_runtime_allow_fallback=true. Stats record "discovery_runtime_failed" as universe_source.
step_04: **DONE** — intent/intent_forced forbidden for NORMAL/COVERAGE: RuntimeError in run_scan_real.py + VIABILITY_FAIL in validate_universe.py.
step_05: **DONE** — validate_universe wired: (a) ci_m5_0_gate.py run_real_scan() calls validate_universe before subprocess, (b) run_scan_real.py main() runs validate_universe after config load, (c) run_scan.py pre-dispatch for REAL mode.
step_06: **DONE** — Unified economics: paper_slippage_bps parameter added to evaluate_quotes() and OpportunityEngine (was hardcoded 5.0). run_scan_real passes config.get("paper_slippage_bps", 0.0).
step_07: **DONE** — Strategy modes encoded: stats["strategy_mode"] = DYNAMIC_VERIFIED|BOOTSTRAP|TRUTH_PROBE based on universe_source. stats["same_dex_only"] from require_cross_dex. validate_universe warns on same-DEX for NORMAL.
step_08: **DONE** — Pre-dispatch validation: run_scan.py REAL mode calls validate_universe(config_path) before delegating. Raises RuntimeError on FAIL.
step_09: **DONE** — Tests: 1805 passed (+7). CI full pipeline PASS. M4 offline profit PASS. M5 offline PASS. validate_universe real_minimal PASS.
step_10: **DONE** — DEV_REPORT refresh with R27.3 evidence.

## 8) Що потрібно від ліда
1. Online runs needed: R27.3 was code audit only — recommend online run to verify no regression in real scan behaviour
2. discovery_runtime_allow_fallback flag: should existing configs get this flag, or is strict-by-default the intended production state?
3. paper_slippage_bps default: spreads.py uses 0.0 default, OE now matches — confirm this is correct (was previously 5.0 in OE)
