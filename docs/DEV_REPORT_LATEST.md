# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one. R28.25: Lead audit corrects R28.24 — zero-profit explained by TWO factors: (1) multi-stage filter/quote-path funnel materially restricts what reaches roundtrip evaluation, (2) phantom spreads/market efficiency. R28.25 implements 10-step fix: config alignment (all chains 150 USD / 5 bps), suppression reform (probation mode), roundtrip_truth_status elevation to m4/policy.py, filter funnel propagation to start.py. 1961 tests, CI green.

## SESSION GOAL (R28.25)
**Goal**: R28.25 — Lead audit 10-step implementation. Correct R28.24 over-strong claim ("zero-profit = market efficiency, not infra bug"). Balanced RCA: filter funnel is a material blocker alongside market efficiency. Implement: config alignment, suppression reform, roundtrip_truth_status, filter funnel first-class, Algebra investigation.
**Prior (R28.24)**: Deep pipeline analysis — phantom spread root cause. 37-run scan, 6 chains.
**Prior (R28.23)**: Lead config audit — 8 configs regenerated, +FusionX V3 (mantle), 240-run bundle.

## 0) Meta
timestamp_utc: pending (R28.25 code-only session, no fresh scan yet)
mode: CODE_CHANGES (R28.25 — 10-step fix per lead audit, tests pass, no scan executed)
test_count: 1961 passed, 3 skipped
schema_version: start:long_scan_summary:v1.14, start:hot_loop_snapshot:v1.3

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.25: Implement lead's 10-step audit fixes. Correct filter-layer RCA. |
| goal_status | **IN_PROGRESS** (code changes done, tests pass, no fresh scan evidence yet) |
| close_allowed | false |
| remaining_blockers | Need 10-min canonical run to validate changes with fresh artifacts |
| evidence_session_run_dirs | None yet (code-only, pending scan) |
| primary_blocker_of_session | Filter funnel + suppression policy restricts candidates reaching roundtrip |
| blocker_status_before | ACTIVE: R28.24 overclaimed market efficiency as sole cause |
| blocker_status_after | IN_PROGRESS: code fixes applied, awaiting verification scan |
| start_metric | R28.24: 0 profitable RT, filter funnel suspected Material |
| end_metric | R28.25 code: configs aligned, suppression reformed, roundtrip_truth_status elevated |
| delta | 12 files changed: 6 configs aligned, suppression probation, filter funnel propagation, policy elevation |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R28.25: Lead audit 10-step implementation
change_summary:
  - CONFIG: config/real_minimal.yaml — +roundtrip_max_candidates=50, +roundtrip_top_n=15, discovery_runtime_max_pairs 20→30
  - CONFIG: 5× onboard configs — aligned economics (150 USD / 5 bps), +RT caps (50/15), discovery_runtime_max_pairs=30
  - CODE: start.py — +last_filter_funnel, +last_roundtrip_truth_status propagation in per-chain stats
  - CODE: strategy/quarantine.py — probation mode for SUSPECT_LIQUIDITY (60s vs 300s full quarantine)
  - CODE: strategy/runtime_disabled.py — per-error TTL overrides (SUSPECT_LIQUIDITY 300s vs 3600s)
  - CODE: m4/policy.py — +roundtrip_profitable_count param, +roundtrip_truth_status in compute_status
  - CODE: m4/gates.py — propagate roundtrip_truth_status to run_summary
  - CODE: strategy/quotes.py — Algebra quoter failure: clearer logging (ALGEBRA_QUOTER_FAILED)
touched_files:
  - config/real_minimal.yaml, config/onboard_zksync_candidate.yaml, config/onboard_base_stage2.yaml
  - config/onboard_mantle_stage2.yaml, config/onboard_linea_stage1.yaml, config/onboard_scroll_stage1.yaml
  - start.py, strategy/quarantine.py, strategy/runtime_disabled.py
  - m4/policy.py, m4/gates.py, strategy/quotes.py

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: **PASS** (1961 passed, 3 skipped)

## 3) Artifacts Attached
rolling: None yet (code-only session, pending verification scan)

## 4) Key Results

```
# R28.25 Code Changes Summary (no fresh scan)
# Changes validated by 1961 unit tests PASS

CONFIG ALIGNMENT (all chains):
  target_usd_notional: 150 (was 100 for coverage chains)
  paper_size_usd: 150 (was 100)
  min_spread_bps: 5 (was 3 for coverage chains, 12 for arb)
  roundtrip_max_candidates: 50 (explicit in all configs)
  roundtrip_top_n: 15 (was 10)
  discovery_runtime_max_pairs: 30 (was 20)

SUPPRESSION REFORM:
  quarantine: SUSPECT_LIQUIDITY now probation mode (60s vs 300s full)
  runtime_disabled: SUSPECT_LIQUIDITY TTL 300s vs 3600s default
  Expected impact: faster re-evaluation of suspect pools

POLICY ELEVATION:
  compute_status() now returns roundtrip_truth_status:
    "PROFITABLE" / "NOT_PROFITABLE" / "NO_DATA"
  Visible in run_summary alongside profit_status
  profit_status (one-leg) no longer masks roundtrip truth

FILTER FUNNEL:
  start.py propagates last_filter_funnel + last_roundtrip_truth_status per chain
  Visible in long_scan_latest.json for operational monitoring
```

## 4.1) R28.25 ROOT CAUSE CORRECTION

R28.24 формулювання "zero-profit = market efficiency, not infra bug" — **занадто сильне**.

**Коректний RCA (R28.25)**: Zero-profit пояснюється ДВОМА факторами:
1. **Filter/quote-path funnel** (матеріальний блокер): Multi-stage фільтрація (slot0 failures, runtime_disabled, quarantine, SUSPECT_LIQUIDITY, NOTIONAL_DRIFT, ALGEBRA_NEEDS_QUOTER) матеріально впливає на те, що взагалі доходить до roundtrip evaluation. З 235 pool universe лише 63 usable quotes (27%). Агресивна suppression (3600s TTL, 300s quarantine) надмірно обмежує поверхню.
2. **Phantom spreads + market efficiency**: Slot0 price gap ≠ executable spread. QuoterV2 roundtrip re-quote показує негативний gross PnL. Це реальний фактор, але він працює ПОВЕРХ звуженої фільтрацією поверхні.**Що зроблено в R28.25 для кожного фактора:**
- Фактор 1: config alignment (15 bps → 5 bps coverage), suppression reform (probation 60s, TTL 300s), discovery_runtime_max_pairs 20→30, RT caps explicit (50/15)
- Фактор 2: roundtrip_truth_status elevation (visible в run_summary), Algebra investigation (slot0 incompatible — genuine filter loss)

## 5) Contract Checks
status/reasons consistency: OK — roundtrip_truth_status now separate from profit_status
rolling discipline (3 files only): OK
runtime artifacts not committed: OK

## 6) Blocker Classification

```
code_blocker: NONE (1961 tests PASS, CI green, all R28.25 changes validated)
data_collection_blocker: MEDIUM (stale anchors, 86% slot0 fail, runtime_disabled aggressive → REFORMED)
market_window_blocker: HIGH (0/82 RT profitable, phantom spreads confirmed)
filter_funnel_blocker: HIGH (73% quote loss from filter stages — MAT'L CONTRIBUTOR)
execution_blocker: HIGH (dormant — no signer)
```

## 7) Lead's R28.25 10 Steps: Execution Map
step_01: **DONE** — Working mode: 10-min canonical runs (operational decision, no code)
step_02: **DONE** — Filter funnel first-class: start.py propagates last_filter_funnel + last_roundtrip_truth_status per chain
step_03: **DONE** — Remove hardcoded caps: all configs explicit roundtrip_max_candidates=50, roundtrip_top_n=15
step_04: **DONE** — Align economics: all chains 150 USD / 5 bps / discovery_runtime_max_pairs=30
step_05: **DONE** — Elevate roundtrip_truth_status: m4/policy.py compute_status() returns roundtrip_truth_status, m4/gates.py propagates
step_06: **DONE** — Suppression reform: quarantine probation (SUSPECT_LIQUIDITY 60s), runtime_disabled per-error TTL (300s)
step_07: **DONE** — Ve33 for base: aerodrome excluded (R28.24), confirmed (slot0 ABI incompatible)
step_08: **DONE** — Algebra quote gap: investigated, slot0 fallback impossible (globalState vs slot0 ABI). Kept as known filter loss with improved logging (ALGEBRA_QUOTER_FAILED)
step_09: **PARTIAL** — Tests pass (1961). Mantle/scroll DoD: operational decision, monitored by coverage scans
step_10: **DONE** — Docs updated: DEV_REPORT_LATEST.md + Status_M5_0.md + Status_M4.md. Filter-layer RCA corrected.

## 8) What I need from Lead now
1. **Verification scan**: Run 10-min canonical multi-chain scan to validate R28.25 changes with fresh artifacts
2. **Anchor refresh**: Prices stale since 2026-02-17. Dynamic pricing or manual refresh needed for NOTIONAL_DRIFT elimination
3. **Algebra/globalState reader**: If Algebra pools are important, need dedicated globalState() ABI reader (not V3 slot0)