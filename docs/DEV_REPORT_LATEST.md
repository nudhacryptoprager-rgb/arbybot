# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-14, Session 6 Round 28)
**Goal**: R28 — Deep architecture audit. Fix source-of-truth contradictions, canonicalize execution layer, split god-files, formalize dynamic+verify path, close stale TODOs, harden preflight, rebuild rollout queue.

## 0) Meta
timestamp_utc: 2026-03-14T20:15:36Z
rolling_provenance: 2026-03-14T20:15:36Z (arbitrum_one NORMAL — preserved from R27.4)
mode: ARCHITECTURE (code cleanup, no online runs)
test_count: 1803 passed, 3 skipped (unchanged from R27.4)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28: Architecture audit — execution layer, god-files, discovery path, preflight, rollout queue |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb primary; ZKSYNC: drift_rejection_rate=30.77% |
| evidence_session_run_dirs | ci_m4_gate_offline_20260314_205752 (M4 profit PASS) |
| primary_blocker_of_session | strategy/execution/ duplicates execution/, god-files need splitting, stale TODOs, preflight stub semantics unclear |
| blocker_status_before | 5 files in strategy/execution/ (dead stubs), ci_m5_0_gate.py=950 lines monolith, stale TODO in roundtrip.py |
| blocker_status_after | strategy/execution/ DELETED, core/gate_helpers.py+repo_checks.py extracted, TODO removed, preflight renamed |
| start_metric | R27.4: 1803 tests, strategy/execution/ present, preflight_disabled_stub() |
| end_metric | R28: 1803 tests, strategy/execution/ removed, core/ modules added, preflight_not_available() with reason codes |
| delta | -5 files (strategy/execution/), +2 files (core/gate_helpers.py, core/repo_checks.py), comments/docs updated |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — architecture layer debt cleanup (R28 lead directive)
change_summary:
  - `strategy/execution/`: DELETED entirely (5 files, ~610 lines dead stubs — was M5/M6 placeholder, never used)
  - `core/gate_helpers.py`: NEW — discover_artifacts, get_run_dir_candidates, validate_schema_version, validate_anti_placeholder
  - `core/repo_checks.py`: NEW — ALLOWED_DEV_REPORTS, DOCS_VERSION_EXEMPT, DOCS_TIMESTAMP_EXEMPT, FORBIDDEN_KEYS, SECRET_PATTERNS
  - `scripts/ci_m5_0_gate.py`: MODIFIED — imports from core.gate_helpers, re-exports for backward compat
  - `scripts/check_repo_safety.py`: MODIFIED — imports from core.repo_checks, re-exports for backward compat
  - `engine/roundtrip.py`: MODIFIED — stale TODO removed (measured slippage via sqrtPriceAfter already integrated)
  - `strategy/quotes.py`: MODIFIED — Path B (slot0 fallback) explicitly marked DIAGNOSTIC CHANNEL
  - `strategy/jobs/run_scan_real.py`: MODIFIED — universe discovery comment formalized (R28), preflight_not_available() used
  - `execution/preflight.py`: MODIFIED — preflight_disabled_stub() → preflight_not_available(reason) with unavailable_reason field
  - `docs/WORKFLOW.md`: MODIFIED — Universe Discovery section added (config vs discovery_runtime canonical paths)
  - `docs/status/Status_M5_0.md`: MODIFIED — Rollout Queue header R28, Universe Split formalized
  - `docs/status/Status_M4.md`: MODIFIED — Rollout Queue header R28, gap fixed to 20.41 bps
touched_files: 12 files across strategy/, core/, scripts/, execution/, engine/, docs/

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1803 passed, 3 skipped, 1 warning, 30.14s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (pytest, docs, status, m5_0, m4_smoke, m4_profit all green)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: **PASS** (2 sims, $0.50, runDir ci_m4_gate_offline_20260314_205752)

## 3) Artifacts Attached (шляхи)
rolling (preserved from R27.4 — no online runs in R28):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-14T20:15:36Z)
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json

## 4) Key Results (числа з артефактів)

```
files_deleted: 5 (strategy/execution/: accounting.py, kill_switch.py, simulator_gate.py, state_machine.py, __init__.py)
files_created: 2 (core/gate_helpers.py, core/repo_checks.py)
stale_todo_removed: 1 (roundtrip.py economics TODO — measured slippage already integrated)
preflight_reason_codes: 2 (NO_W3_INSTANCE, NO_OPPORTUNITIES)
slot0_diagnostic_marker: added to Path B in quotes.py
discovery_path_formalized: docs/WORKFLOW.md Universe Discovery section
rollout_queue_updated: R28 header in Status_M5_0.md and Status_M4.md
test_count: 1803 (unchanged — no new tests, architecture-only session)
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline (3+1 canonical files): OK — preserved from R27.4
- execution layer: CANONICAL — execution/ is sole layer, strategy/execution/ deleted
- god-files: SPLIT — core/gate_helpers.py (artifact discovery), core/repo_checks.py (docs policy constants)
- stale TODOs: CLOSED — roundtrip.py economics TODO removed
- slot0 path: DIAGNOSTIC — explicit DIAGNOSTIC CHANNEL marker added to Path B
- preflight semantics: CLARIFIED — preflight_not_available(reason) with unavailable_reason field
- discovery path: FORMALIZED — docs/WORKFLOW.md Universe Discovery section (config vs discovery_runtime)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1803 PASS, CI gates green, architecture clean)
data_collection_blocker: LOW (online runs producing signals — R27.4 evidence)
market_window_blocker: HIGH (roundtrip_profitable=0 on primary, gap_to_zero=20.41 bps)
adapter_blocker: RESOLVED (ve33 implemented R27.4)
architecture_debt: RESOLVED (R28 cleanup complete)
```

## 7) Lead's R28 10 Steps: Execution Map
step_01: **DONE** — Fixed source-of-truth: Status_M4.md header R27.2→R28, Status_M5_0.md Chain Quality updated (ve33 implemented, blockers changed).
step_02: **DONE** — Canonicalized execution layer: strategy/execution/ deleted entirely (5 files, ~610 lines dead stubs). execution/ is canonical and sole implementation.
step_03: **DONE** — Split god-files: core/gate_helpers.py (discover_artifacts, get_run_dir_candidates, validate_schema_version, validate_anti_placeholder), core/repo_checks.py (docs policy constants). Scripts import+re-export for backward compat.
step_04: **DONE** — Formalized dynamic+verify path: docs/WORKFLOW.md Universe Discovery section added. discovery_runtime is canonical successor for non-probe universe.
step_05: **DONE** — Closed economics debt: stale TODO in roundtrip.py removed (measured slippage via sqrtPriceAfter already integrated at lines 365-388).
step_06: **DONE** — Cut slot0 from decision path: Path B in quotes.py marked DIAGNOSTIC CHANNEL explicitly. slot0 quotes already gated as is_diagnostic_only=True when truth_mode_m42=true.
step_07: **DONE** — Hardened preflight: preflight_disabled_stub() → preflight_not_available(reason) with unavailable_reason field (NO_W3_INSTANCE, NO_OPPORTUNITIES). Backward compat alias preserved.
step_08: **DONE** — Rebuilt rollout queue: Status_M5_0.md and Status_M4.md updated to R28 header, Universe Split formalized, discovery_runtime noted as canonical successor.
step_09: **DONE** — Verification runs: pytest 1803 PASS, ci_full_pipeline PASS, M4 offline profit strict PASS (2 sims, $0.50).
step_10: **DONE** — Docs refresh: DEV_REPORT_LATEST.md updated with R28 evidence, Status files synced.

## 8) Що потрібно від ліда
1. R28 sign-off: Architecture audit complete — execution layer canonical, god-files split, discovery formalized
2. Online verification: If fresh evidence needed, run arb primary + onboard chains (no RPC in this env)
3. ve33 online testing: base/mantle need online runs with aerodrome/stratum (adapter implemented R27.4, needs runtime proof)
4. zksync drift: Market blocker (30.77% > 25% threshold) — need sustained low-drift window for promotion
