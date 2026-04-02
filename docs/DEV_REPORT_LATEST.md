# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: n/a (structural-only session, no online runs)
mode: OFFLINE (unit tests only)
artifact_mode: n/a (no new artifacts generated)
config: n/a (structural refactor, no scanner runs)
code_identity:
  primary: ts:2026-04-02T08:46:12Z
  dirty: true
  desc: M7.T1 — structural test consolidation; 14 session-specific test files → 8 layer-based suites + conftest.py; 213 duplicate assertions removed; no production code changed
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275
rolling_run_timestamp: 2026-03-27T21:30:14Z
note: No online runs. Rolling artifacts from prior session (ci_m5_gate_arbitrum_one_20260327_222948_123275) remain unchanged. timestamp_utc propagated from rolling run_summary_latest per canonical format.

## Session Completion
session_goal: M7.T1 — structural test suite consolidation (no market progress)
goal_status: REACHED (14 session-specific test_orderflow_*.py files consolidated into 8 stable layer-based suites + shared conftest.py; 213 duplicate assertions removed; 3104 passed, 6 skipped; no production code changed)
close_allowed: true
remaining_blockers: none (structural-only session — no market/runtime blockers addressed or claimed)
evidence_session_run_dirs: [] (no online runs — structural only)
primary_blocker_of_session: 14 session-specific test files with massive duplication (~213 duplicate assertions across 9494 lines); two post-consolidation monoliths (1913 + 1156 lines) required further splitting
blocker_status_before: ACTIVE (test suite bloat: 14 files, 9494 lines, ~581 tests with ~213 duplicates)
blocker_status_after: RESOLVED (8 focused files + conftest.py, 368 unique tests, all files < 600 lines)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.T1 — structural test suite consolidation (referenced in Status_M7.md M7.T1 section)
change_summary:
  - Deleted 14 session-specific test_orderflow_*.py files (9494 lines, ~581 tests incl. ~213 duplicates)
  - Created 8 layer-based test suites + shared conftest.py (368 unique tests, 0 production code changes)
  - Pass 1: consolidated 14 → 4 files + conftest.py (contracts_core, registry_and_coverage, pricing_and_latency, artifacts_status)
  - Pass 2: split 2 oversized files — pricing_and_latency (1156 lines) → pricing_math + gas_oracle + scoring_latency; artifacts_status (1913 lines) → artifacts + blocker_tags + status_metrics
  - Shared helpers (_make_event, _make_result) extracted to conftest.py
  - Updated Status_M7.md: compressed M7.A.5.24/25, added M7.T1 section, updated test counts, trimmed to ≤300 lines
touched_files:
  - tests/unit/test_orderflow_base.py (DELETED)
  - tests/unit/test_orderflow_scoring.py (DELETED)
  - tests/unit/test_orderflow_m7a55_56.py (DELETED)
  - tests/unit/test_orderflow_m7a57_58.py (DELETED)
  - tests/unit/test_orderflow_m7a59_510.py (DELETED)
  - tests/unit/test_orderflow_m7a511_512.py (DELETED)
  - tests/unit/test_orderflow_m7a513_515.py (DELETED)
  - tests/unit/test_orderflow_m7a516_517.py (DELETED)
  - tests/unit/test_orderflow_m7a518_519.py (DELETED)
  - tests/unit/test_orderflow_m7a520.py (DELETED)
  - tests/unit/test_orderflow_m7a521.py (DELETED)
  - tests/unit/test_orderflow_m7a522.py (DELETED)
  - tests/unit/test_orderflow_m7a523.py (DELETED)
  - tests/unit/test_orderflow_m7a524.py (DELETED)
  - tests/unit/conftest.py (CREATED: _make_event, _make_result shared helpers)
  - tests/unit/test_orderflow_contracts_core.py (CREATED: 48 tests)
  - tests/unit/test_orderflow_registry_and_coverage.py (CREATED: 63 tests)
  - tests/unit/test_orderflow_pricing_math.py (CREATED: 44 tests)
  - tests/unit/test_orderflow_gas_oracle.py (CREATED: 33 tests)
  - tests/unit/test_orderflow_scoring_latency.py (CREATED: 38 tests)
  - tests/unit/test_orderflow_artifacts.py (CREATED: 55 tests)
  - tests/unit/test_orderflow_blocker_tags.py (CREATED: 41 tests)
  - tests/unit/test_orderflow_status_metrics.py (CREATED: 46 tests)
  - docs/status/Status_M7.md (MODIFIED: compressed, +M7.T1, updated counts, ≤300 lines)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3104 passed, 6 skipped, 56.62s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest + docs_consistency + status_m4_check + m5_0_offline + m4_smoke + m4_profit: ALL REQUIRED GATES PASSED, 57.3s)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
note: no online runs (structural-only session); no m7a_orderflow_replay.py or ci_m4/m5 gates run

## 3) Artifacts Attached

rolling (pre-session, not regenerated — structural-only session):
  - data/runs/_rolling/_latest.json (unchanged from prior session)
  - data/runs/_rolling/run_summary_latest.json (unchanged)
  - data/runs/_rolling/m4_stability_agg.json (unchanged)
no run_dir_bundle (OFFLINE structural session — no online runs)
no live evidence artifacts (no scanner/replay runs)

## 4) Key Results — M7.T1

### Coverage Map: Old Files → New Suites

| Old File (DELETED) | Primary New Suite(s) | Domain |
|---|---|---|
| test_orderflow_base.py | contracts_core | Schema, field counts (66), constants (21/12/8), admission |
| test_orderflow_scoring.py | contracts_core, scoring_latency | Scoring path, event classification |
| test_orderflow_m7a55_56.py | pricing_math, contracts_core | V2/V3 swap math, scoring path |
| test_orderflow_m7a57_58.py | registry_and_coverage | Coverage scan, state read path |
| test_orderflow_m7a59_510.py | registry_and_coverage, gas_oracle | Coverage decomposition, gas decomposition |
| test_orderflow_m7a511_512.py | contracts_core, blocker_tags | Admission contract, blocker tag constants |
| test_orderflow_m7a513_515.py | pricing_math, gas_oracle | Local pricing, oracle guard, enrichment |
| test_orderflow_m7a516_517.py | registry_and_coverage, scoring_latency | Registry lifecycle, stale gate viability |
| test_orderflow_m7a518_519.py | scoring_latency, blocker_tags | Two-queue priority, watchlist, mid-pipeline abort |
| test_orderflow_m7a520.py | artifacts, status_metrics | Pipeline optimization artifact, pre-econ metrics |
| test_orderflow_m7a521.py | artifacts, blocker_tags | Debug rows, pool truth, dex family |
| test_orderflow_m7a522.py | artifacts, status_metrics | Split summary, reject decomposition |
| test_orderflow_m7a523.py | pricing_math, scoring_latency | Adapter dispatch, session prewarm |
| test_orderflow_m7a524.py | gas_oracle, scoring_latency, status_metrics | Gas denomination, detection lag, backward compat |

### New Suite Structure

| New File | Tests | Domain |
|---|---|---|
| conftest.py | — | Shared helpers: `_make_event(eid, block, **ov)`, `_make_result(**ov)` |
| test_orderflow_contracts_core.py | 48 | Schema, field counts (66), constant counts (21/12/8), admission, blocker tags, scoring_path, PRICING_ANOMALY |
| test_orderflow_registry_and_coverage.py | 63 | PoolRegistry lifecycle, coverage scan, admission, fixture events, state read path, registry fields |
| test_orderflow_pricing_math.py | 44 | NormalizedBounds, size normalization, V3/V2/Algebra swap math, attempt_local_pricing, adapter dispatch |
| test_orderflow_gas_oracle.py | 33 | Chainlink constants, oracle guard, enrichment, local sim state, subgraph seed, gas decomposition/denomination |
| test_orderflow_scoring_latency.py | 38 | Event classification, backrun scoring, stale gate, zero-liquidity, two-queue, mid-pipeline abort, session prewarm, detection lag |
| test_orderflow_artifacts.py | 55 | Core artifact schema, intent scout, ws-live, split summary, local pricing artifact, registry artifacts, pipeline optimization |
| test_orderflow_blocker_tags.py | 41 | Debug rows, pool truth, dex family, read path, blocker tags, watchlist, quote-fail provenance |
| test_orderflow_status_metrics.py | 46 | Pre-econ metrics, consistency, stale/low-lag split, reject decomposition, backward compat |
| **Total** | **368** | |

### Duplicate Removal Summary

213 duplicate assertions removed. Primary duplication sources:
- Field-count assertions (`len(BackrunResult.__dataclass_fields__) == 66`) duplicated across 11 files
- Constant-count assertions (`len(ALL_REJECT_REASONS) == 21`, `len(UNSCORED_REJECTS) == 12`, `len(ALL_BLOCKER_TAGS) == 8`) duplicated across 10 files
- Admission logic re-tested in 6+ files with overlapping fixtures
- Coverage scan patterns repeated across m7a57_58, m7a59_510, m7a516_517

Post-consolidation: each constant/field count asserted exactly once in contracts_core.

### Anti-Accretion Policy

New test files are created only for: new stable contract, new adapter family, new reject reason, new safety gate, or real bug regression. Session-specific test files (test_orderflow_m7aXXX_YYY.py) are prohibited — tests go into the appropriate layer-based suite.

## 5) Strategic Reading

1. **No market progress**: This session is structural-only. All market-facing metrics (viable_count, best_net_bps, STALE_POSITIVE, pipeline latency) are unchanged from M7.A.5.25.
2. **Test suite is now maintainable**: 8 files organized by domain (contracts, registry, pricing, gas, scoring, artifacts, blockers, status) instead of 14 files organized by session date. New test additions go to the correct domain file.
3. **213 duplicates removed**: Every constant/field-count assertion exists exactly once. Adding a new reject reason or blocker tag requires updating exactly 1 test file (contracts_core).
4. **All files < 600 lines**: The two post-pass-1 monoliths (artifacts_status: 1913, pricing_and_latency: 1156) were split in pass 2 into 3 focused files each.
5. **conftest.py is minimal**: Only `_make_event` and `_make_result` helpers. No business logic, no constants, no fixtures beyond these two factories.
6. **Production code untouched**: Zero changes to m7/, core/, engine/, strategy/, execution/, or any non-test code.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 66 fields, ALL_BLOCKER_TAGS: 8 — all unchanged)
rolling discipline (3 files only): OK (rolling artifacts not modified)
v2.x provenance contract: OK (no provenance changes)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (no m7/ modules modified)
test file size constraint: OK (all 8 orderflow test files < 600 lines)
Status_M7.md size constraint: OK (296 lines ≤ 300)

## 5.2) Blockers / Risks
- UNCHANGED (from M7.A.5.25): Scoring pipeline latency (~1500-2000ms) exceeds block_time_ms (250ms); viable_count=0; all positives STALE_POSITIVE
- UNCHANGED: M4 baseline still negative; SUBGRAPH_API_KEY_REQUIRED persists
- RESOLVED (this session): Test suite bloat — 14 session-specific files with 213 duplicates consolidated into 8 layer-based suites
- NOTE: This session made no market progress. All market-facing blockers remain as documented in M7.A.5.25.
