# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R35 directive: **Evidence discipline + QUOTE_PATH_BLOCKED heuristic fix + hot_loop canonical guard.** R34 fixed stream-to-analysis signal loss. R35 hardens evidence discipline and regenerates canonical 6-chain proof bundle.

## SESSION GOAL (R35: Evidence discipline & canonical proof bundle)
**Goal**: Fix evidence discipline: (1) harden hot_loop guard against non-canonical sessions, (2) fix QUOTE_PATH_BLOCKED heuristic for chains with active sweep evidence, (3) regenerate canonical 6-chain multi-chain proof bundle.
**Prior (R34)**: Stream-to-analysis signal loss fixed (3 UnboundLocalError hoists, 3-tier live_stream, per_chain fallback). 2154 tests PASS. Sweep working (routes_swept=13) but proof bundle destroyed by temp mini-session.

## 0) Meta
timestamp_utc: 2026-03-22T09:47:44Z (R35 canonical 6-chain scan)
run_dir_name: ci_m5_gate_arbitrum_one_20260322_104631_466460
mode: R35_EVIDENCE_DISCIPLINE
test_count: 2160 passed (2137 core + 17 R34 + 6 R35 regression), 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.14, start:hot_loop_snapshot:v1.3

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R35: Evidence discipline + QUOTE_PATH_BLOCKED fix + canonical 6-chain proof bundle |
| goal_status | **REACHED** (6-chain canonical scan, 5 acceptance criteria pass) |
| close_allowed | true |
| remaining_blockers | None for R35 scope. Market blockers remain (0 profitable RT). |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260322_104631_466460 |
| primary_blocker_of_session | Evidence discipline: hot_loop overwritten by temp session, QUOTE_PATH_BLOCKED misclassification |
| blocker_status_before | ACTIVE: hot_loop_latest.json overwritten by non-canonical mini-session, arb misclassified as QUOTE_PATH_BLOCKED despite routes_swept=13, DEV_REPORT timestamp stale |
| blocker_status_after | **FIXED**: hot_loop requires _rolling summary_file, sweep evidence overrides QUOTE_PATH_BLOCKED, 6-chain canonical bundle regenerated |
| start_metric | hot_loop=temp session, arb blocker=QUOTE_PATH_BLOCKED, long_scan=2 arb-only runs, DEV_REPORT timestamp mismatch |
| end_metric | hot_loop=canonical (25 runs, 6 chains, 16 diagnostic_pairs), arb blocker=OE_ECONOMICS, long_scan=25 runs across 6 chains |
| delta | +6 tests (2160 total), 2 code fixes (sweep override + hot_loop guard), canonical 6-chain proof bundle |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 - R35 directive: Evidence discipline + QUOTE_PATH_BLOCKED fix
change_summary:
  - **CRITICAL**: `strategy/chain_stats.py` — QUOTE_PATH_BLOCKED heuristic: when `runs_with_sweep > 0`, skip QUOTE_PATH_BLOCKED classification. Chains with active sweep evidence are economics-blocked, not quote-path-blocked.
  - **CRITICAL**: `strategy/rolling_outputs.py` — Hot loop canonical guard: `write_hot_loop_snapshot` now requires `summary_file` containing `_rolling` to write to HOT_LOOP_LATEST. Non-canonical sessions silently skip.
  - `tests/unit/test_r34_stream_reprieve.py` — 6 new R35 tests: 3 for QUOTE_PATH_BLOCKED sweep override, 3 for hot_loop non-canonical guard.
touched_files:
  - strategy/chain_stats.py (CRITICAL — QUOTE_PATH_BLOCKED sweep override)
  - strategy/rolling_outputs.py (CRITICAL — hot_loop canonical guard hardening)
  - tests/unit/test_r34_stream_reprieve.py (6 new R35 regression tests, 23 total)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2160 passed, 5 skipped)
py -3.11 start.py --config-list config/real_minimal.yaml,config/onboard_zksync_candidate.yaml,config/onboard_base_stage2.yaml,config/onboard_mantle_stage2.yaml,config/onboard_linea_stage1.yaml,config/onboard_scroll_stage1.yaml --accepted-fail-chains scroll --max-fail-chains 5 --hours 0.17 --cycles 1 --sleep-seconds 0 --coverage-workers 2 --no-dashboard --prune-keep 200 --summary-file data/runs/_rolling/long_scan_latest.json: PASS (25 runs, 6 chains)
```

## 3) R35 Architecture Changes

### QUOTE_PATH_BLOCKED Sweep Override
Problem: `_compute_blocker_evidence()` in chain_stats.py applied QUOTE_PATH_BLOCKED when quoter_v2 failure rate >50% or SLOT0_DIAGNOSTIC rejection rate >40%, even when the chain had active sweep evidence (`runs_with_sweep > 0`, `routes_swept > 0`). This misclassified arb as quote-blocked despite 30 cross_dex_pairs and 13 routes swept.
Fix: Added `has_sweep_evidence = stats.get("runs_with_sweep", 0) > 0` check. Both QUOTE_PATH_BLOCKED branches now include `and not has_sweep_evidence` guard. Chains with active sweep fall through to OE_ECONOMICS/MIXED_SOURCE.

### Hot Loop Canonical Guard
Problem: `write_hot_loop_snapshot()` only guarded against `is_test_session=True`. Non-test mini-sessions or ad-hoc runs (without `summary_file` pointing to `_rolling/`) could overwrite HOT_LOOP_LATEST, destroying canonical evidence.
Fix: Added guard: when `output_path is None` (targeting HOT_LOOP_LATEST), require `summary_file` to contain `_rolling`. Sessions without proper rolling summary_file are silently skipped.

## 4) Contract Checks
QUOTE_PATH_BLOCKED sweep override: 3 tests (quoter failure, SLOT0 diagnostic, negative control)
hot_loop non-canonical guard: 3 tests (empty summary, non-rolling path, rolling path writes)
R34 regression tests retained: 17 tests (all passing)
rolling discipline (3+1 files): OK
provenance contract: OK (run_timestamp only)
CI pipeline: 2160 tests PASS, 5 skipped

## 5) R35 Acceptance Criteria Verification
| Criterion | Status | Evidence |
|-----------|--------|----------|
| 1. `live_stream.diagnostic_pairs` non-empty | ✅ PASS | 16 entries across 6 chains |
| 2. `runs_with_sweep > 0` in long_scan | ✅ PASS | arb=5, mantle=4, scroll=4, zksync=1, base=1 |
| 3. `blocker_classification` non-null for all chains | ✅ PASS | arb=OE_ECONOMICS, zksync=INFRA_FAIL, base=INFRA_FAIL, mantle=MIXED_SOURCE, linea=INFRA_FAIL, scroll=OE_ECONOMICS |
| 4. No `roundtrip.error` in fresh scan | ✅ PASS | `error: None` |
| 5. arb blocker != QUOTE_PATH_BLOCKED | ✅ PASS | arb=OE_ECONOMICS (R35 sweep override working) |

Run: ci_m5_gate_arbitrum_one_20260322_104631_466460 (25 runs, 6 chains, 229 signals)
Rolling: hot_loop_latest.json shows 16 diagnostic_pairs, session_summary_file=data/runs/_rolling/long_scan_latest.json

## 6) What I need from Lead now
1. **R35 validated** — evidence discipline hardened, canonical 6-chain bundle regenerated, QUOTE_PATH_BLOCKED fixed.
2. **Base/linea INFRA_FAIL**: Both chains failing >50% runs. Base has partial success (2/4 pass). Root cause investigation needed.
3. **zksync INFRA_FAIL**: All 4 runs failed. Config or RPC issue?
4. **M4.2 path**: 0 profitable RT across all 6 chains. OE_ECONOMICS dominates. Next: lower cost model or higher-spread pair discovery.
