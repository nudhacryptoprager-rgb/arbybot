# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14.342304Z
run_id: ci_m5_gate_arbitrum_one_20260327_222948_123275
mode: ONLINE
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one expanded_10 universe, runtime source, measured scoring
code_identity:
  primary: ts:2026-03-27T21:30:14.342304Z
  dirty: false
  desc: M7.A.2 expanded universe hypothesis — bounded token expansion test

## Session Completion
session_goal: Test M7.A.2 hypothesis — does expanded arbitrum_one universe (narrow_7 + DAI, GMX, UNI → 10 tokens) produce a second token-triple or better net than narrow_7?
goal_status: REACHED
close_allowed: true
remaining_blockers: none
evidence_session_run_dirs:
  - data/tmp/m7a_expanded_run1.json (block 446672946)
  - data/tmp/m7a_expanded_run2.json (block 446674182)
  - data/tmp/m7a_expanded_run3.json (block 446675281)
  - data/tmp/m7a_expanded_verdict.json (formal expanded verdict)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260327_222948_123275
primary_blocker_of_session: M7.A.2 expanded universe hypothesis not yet tested
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.2 — bounded expansion hypothesis. Does adding DAI, GMX, UNI to the narrow_7 universe break the single-triple concentration blocker or improve net bps?
change_summary:
  - Added M7A2_EXTRA_TOKENS_ARBITRUM_ONE, M7A2_TOKENS_ARBITRUM_ONE, filter_graph_to_m7a2_universe() to engine/triangular_graph.py
  - Added --universe narrow_7|expanded_10 CLI arg to scripts/m7a_enumerate_cycles.py
  - Updated build_blocker_repeatability() and build_verdict_summary() to carry universe_profile
  - Artifact summary includes universe_profile at top level and in m7a_universe block
  - Fixed verdict scope: "narrow_7_token" → "narrow_7" for consistency with CLI arg
  - Added 9 universe-profile contract tests (TestUniverseProfile class)
  - Total test count: 2713 passed, 17 skipped, 0 failures
touched_files:
  - engine/triangular_graph.py
  - scripts/m7a_enumerate_cycles.py
  - tests/unit/test_triangular_contracts.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest -q: PASS (2713 passed, 17 skipped)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/ci_full_pipeline.py --mode ci: FAIL only at ROADMAP_GOVERNANCE (expected, user's intentional Roadmap.md edit)
py -3.11 scripts/m7a_enumerate_cycles.py --universe expanded_10 --source runtime --score measured --sweep-top 10 (x3 runs): PASS
py -3.11 scripts/m7a_enumerate_cycles.py --universe expanded_10 --verdict (3 artifacts): PASS

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_expanded_run1.json (block 446672946, expanded_10)
  - data/tmp/m7a_expanded_run2.json (block 446674182, expanded_10)
  - data/tmp/m7a_expanded_run3.json (block 446675281, expanded_10)
  - data/tmp/m7a_expanded_verdict.json (3-block formal expanded verdict)

prior session artifacts (still valid, not overwritten):
  - data/tmp/m7a_verdict.json (narrow_7, 4-block verdict from session 17)
  - data/tmp/m7a_blocker_repeatability.json (narrow_7, 3-block aggregation)
  - data/tmp/m7a_runtime_measured_sweep.json (narrow_7, 190-quote size sweep)

rolling (unchanged):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.2 Expanded Universe Verdict

### Graph Expansion Result

Of 3 extra tokens (DAI, GMX, UNI), only **DAI** had runtime pools (GMX/UNI not in intent.txt → 0 runtime pools). Graph expanded from 7 to **8 nodes**. Edge count unchanged (248). DAI added 0 competitive edges to top cycles. Quoted routes per run: real_quote_count: 67 (same as narrow_7). Best net: -15.78 bps mean across 3 runs (no improvement over narrow's -16.60 bps mean).

### Evidence Runs (3 independent blocks)

| Run | Block | Scored | Failed | Best Net (bps) | Gross (best) | Conc. |
|-----|-------|--------|--------|----------------|-------------|-------|
| expanded_1 | 446672946 | 67 | 33 | **-15.44** | -4.77 | 1.0 |
| expanded_2 | 446674182 | 67 | 33 | **-20.91** | — | 1.0 |
| expanded_3 | 446675281 | 67 | 33 | **-11.00** | +0.19 | 1.0 |

### Expanded Verdict (from m7a_expanded_verdict.json)

| Field | Value |
|-------|-------|
| beats_two_leg_baseline | **false** |
| all_sizes_negative | **true** |
| gross_sometimes_positive | **true** |
| stable_blockers_count | **6** |
| flapping_blockers_count | **0** |
| best_net_bps_range | -20.91 to -11.00 (mean -15.78) |
| two_leg_baseline_net_bps | -3.5062 |
| dominant_triple | **true** (ARB/USDC/WETH, concentration 1.0) |
| route_failure_rate | 0.33 (stable) |
| recommend_open_m7b | **false** |
| recommend_freeze_current_m7a_scope | **true** |

### Comparison: narrow_7 vs expanded_10

| Metric | narrow_7 (session 17) | expanded_10 (session 18) |
|--------|----------------------|--------------------------|
| Graph nodes | 7 | 8 (DAI added) |
| Best net range (bps) | -23.52 to -9.56 | -20.91 to -11.00 |
| Mean best net (bps) | -16.60 | -15.78 |
| Token triple concentration | 1.0 | 1.0 |
| Stable blockers | 6/6 | 6/6 |
| Flapping blockers | 0/6 | 0/6 |
| recommend_open_m7b | false | false |

Expanded universe does NOT change the verdict. Similar net range, identical blocker structure, same dominant triple.

### New Tests Added (9 contract tests)

| Test | What it locks |
|------|--------------|
| test_m7a2_tokens_superset_of_m7a | M7A2 ⊃ M7A (strict) |
| test_m7a2_extra_tokens_are_known | Exactly DAI, GMX, UNI |
| test_m7a2_token_count | Exactly 10 tokens |
| test_filter_m7a2_produces_superset_graph | Expanded graph ⊇ narrow graph |
| test_m7a2_filter_rejects_non_stable_adapter | ve33 still rejected |
| test_m7a2_filter_rejects_excluded_tokens | wstETH still excluded |
| test_artifact_universe_profile_field | Schema carries universe_profile |
| test_verdict_with_expanded_universe_profile | Verdict carries "expanded_10" |
| test_narrow_universe_keys_unchanged | M7A constants frozen |

## 5) Strategic Reading

M7.A.2 hypothesis tested and rejected: expanding the arbitrum_one universe from 7 to 10 tokens (only DAI pooled in practice) does NOT produce a second token triple or beat the two-leg baseline. The binding multi-cost structure (gas + fees + concentration) is unchanged by universe expansion. Both narrow_7 (session 17) and expanded_10 (session 18) independently confirm the no-graduate verdict.

**M7.B remains closed.** Both universe profiles jointly strengthen the conclusion that the current M7.A scope should be frozen. Any further M7.A work requires a qualitatively different hypothesis (different chain, new adapter types, or structural cost reduction — not token-set expansion).

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY — NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY — NO-GRADUATE** (expanded_10, confirms narrow_7) |
| M7.B | NOT STARTED (closed by M7.A + M7.A.2 verdicts) |
