# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_510_300b (ws-live corrective evidence session)
mode: ONLINE (ws-live evidence runs + unit tests + CI gates)
artifact_mode: local evidence (data/tmp/m7a_510_30b.json, data/tmp/m7a_510_300b.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-03-29T18:50:57Z
  dirty: true
  desc: M7.A.5.10 stale-gate + zero-liq reject + admission provenance fix

## Session Completion
session_goal: M7.A.5.10 -- fix 3 contract issues from M7.A.5.9 300b evidence: (1) stale-positive false viability, (2) admission provenance misattribution, (3) zero-liquidity contradiction
goal_status: REACHED (all 3 bugs fixed; corrective evidence confirms zero false viables; ZERO_LIQUIDITY is now dominant reject)
close_allowed: true
remaining_blockers: none (M7.A blocker stack fully characterized with contract-correct evidence)
evidence_session_run_dirs: [data/tmp/m7a_510_30b.json, data/tmp/m7a_510_300b.json]
primary_blocker_of_session: M7.A.5.9 evidence had 3 contract issues: stale-positive viability, admission provenance bug, zero-liquidity false viables
blocker_status_before: ACTIVE (viable_count=1 was false positive with block_lag=23 + liquidity=0)
blocker_status_after: RESOLVED -- zero false viables; ZERO_LIQUIDITY dominant reject (21/25); admission provenance correctly split
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.10 -- fix stale-positive viability, zero-liquidity contradiction, and admission provenance before evidence is treated as decisive
change_summary:
  - Added stale-gate: route_viable = (net_bps > 0 AND block_lag <= 2) in both scorers
  - Added REJECT_STALE_POSITIVE and REJECT_ZERO_LIQUIDITY reject constants (15 total, was 13)
  - Added ADMISSION_ONCHAIN_ENRICHED = "onchain_enriched_verified" (5 admission sources, was 4)
  - Added zero-liquidity reject gate: if all candidate pools have liquidity=0 in local_sim_state, reject early
  - Fixed admission provenance: subgraph_seeded_verified only when subgraph_seed_used=true; else onchain_enriched_verified
  - Rewrote build_replay_summary(): best_net_bps from scored results only; 8 new split fields
  - Updated enrichment_metrics to count ADMISSION_ONCHAIN_ENRICHED
  - Added 23 new contract tests (275 total orderflow, 3011 total suite)
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: 2 new rejects, 1 new admission source, stale-gate, zero-liq gate, provenance fix, summary rewrite)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +23 tests, 275 total; 6 new test classes)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.10 section added, header updated)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (275 passed in ~2s)
py -3.11 -m pytest tests/unit -q: PASS (3011 passed, 6 skipped in ~55s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (54.0s, ALL REQUIRED GATES PASSED)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (1 warning)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 30 --output data/tmp/m7a_510_30b.json: PASS (2 events)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --output data/tmp/m7a_510_300b.json: PASS (25 events)

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_510_30b.json (30-block ws-live, 2 events)
  - data/tmp/m7a_510_300b.json (300-block ws-live, 25 events)

## 4) Key Results -- M7.A.5.10 Contract Fixes

### Fix #1: Stale-Gate Viability

| Condition | route_viable | reject_reason |
|-----------|-------------|---------------|
| net_bps > 0, block_lag <= 2 | True | None |
| net_bps > 0, block_lag > 2 | **False** | **STALE_POSITIVE** |
| net_bps <= 0 | False | GAS_EXCEEDS_GROSS |

### Fix #2: Zero-Liquidity Reject Gate

All candidate pools with liquidity=0 in local_sim_state → **REJECT_ZERO_LIQUIDITY** (early reject, no economic scoring).
Previous behavior: these events would proceed to quoting, get inflated results from stale pricing.

### Fix #3: Admission Provenance Split

| Condition | admission_source |
|-----------|-----------------|
| enrichment_applied, subgraph_seed_used=true | subgraph_seeded_verified |
| enrichment_applied, subgraph_seed_used=false | **onchain_enriched_verified** (NEW) |
| no enrichment, canonical | canonical_core |
| no enrichment, addr_to_symbol | addr_to_symbol |

### 300-Block Evidence Summary

| Metric | M7.A.5.9 (before) | M7.A.5.10 (after) |
|--------|-------------------|-------------------|
| events_count | 22 | 25 |
| viable_count | **1 (false positive!)** | **0** |
| positive_net_count | 1 | 0 |
| ZERO_LIQUIDITY | N/A | **21** |
| GAS_EXCEEDS_GROSS | 16 | 0 |
| TOKEN_PAIR_UNRESOLVED | 1 | 2 |
| NO_COUNTER_POOL | 4 | 2 |
| admission: subgraph_seeded_verified | 18 (misattributed) | 0 |
| admission: onchain_enriched_verified | N/A | 5 |
| stale_positive_count | N/A | 0 |

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestM7A510StaleGateConstants | 4 | PASS |
| TestM7A510AdmissionOnchainEnriched | 4 | PASS |
| TestM7A510StaleGateViability | 3 | PASS |
| TestM7A510ZeroLiquidityReject | 1 | PASS |
| TestM7A510SplitSummaryFields | 7 | PASS |
| TestM7A510BackwardCompat | 4 | PASS |
| **Total new (M7.A.5.10)** | **23** | **PASS** |
| **Total orderflow tests** | **275** | **PASS** |
| **Total all tests** | **3011** | **PASS (6 skipped)** |

## 5) Strategic Reading

1. **ZERO_LIQUIDITY is the new dominant reject**: 21/25 events (84%) have candidate pools with liquidity=0. These are initialized V3 pools with no active LP positions. Previously these passed through to economic scoring and could produce false-positive viables from stale pricing.

2. **Stale-positive false viables eliminated**: The M7.A.5.9 300b run had viable_count=1 with block_lag=23 — a stale quote that would never be executable. Now route_viable requires block_lag <= 2. No false viables in corrective evidence.

3. **Admission provenance is now honest**: 5 events correctly labeled `onchain_enriched_verified` (was all `subgraph_seeded_verified` even when subgraph was unused). Admission source histogram matches actual enrichment path.

4. **Summary scoring is clean**: best_net_bps excludes 0.0 from TOKEN_PAIR_UNRESOLVED/NO_COUNTER_POOL/ZERO_LIQUIDITY. Split fields separate executable vs stale-positive economics.

5. **M7.A is fully closed with contract-correct evidence**: Previous M7.A.5.9 evidence had 3 measurement/contract issues. All fixed. The blocker has shifted: it's not just that gas exceeds gross — most pools have zero liquidity to begin with.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY -- NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY -- NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC latency) |
| M7.A.5.5 | **LIVE EVIDENCE: NOT VIABLE** (actual-pair token resolution) |
| M7.A.5.6 | **COVERAGE DECOMPOSED** (80% TOKEN_NOT_ADMITTED) |
| M7.A.5.7 | **INFRASTRUCTURE BUILT** (enrichment + oracle + local-sim) |
| M7.A.5.8 | **LIVE EVIDENCE: BLOCKER SHIFTED** (admission 100%, GAS_EXCEEDS_GROSS 100%) |
| M7.A.5.9 | **CORRECTIVE: DENOMINATION-CORRECT** (size + gas bugs fixed) |
| M7.A.5.10 | **CORRECTIVE: CONTRACT-CORRECT** (stale-gate + zero-liq + provenance fixed) |
| M7.B | NOT STARTED (closed by M7.A verdicts) |
