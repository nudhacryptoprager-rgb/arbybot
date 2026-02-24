# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-24T11:25:12Z
run_id: data/runs/ci_m5_gate_20260224_122459
mode: ONLINE (dual cross-dex routes test)
artifact_mode: rolling
config: config/real_minimal.yaml (profit profile, require_cross_dex=false, paper_size_usd=250)
code_identity:
  primary: ts:2026-02-24T11:25:12+00:00
  dirty: true
  desc: Directive #14 - dual cross-dex routes v2.5.2, diversity gates FIX

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Directive #14 - fix diversity gates (DIVERSITY_ROUTES_FAIL, DIVERSITY_PAIRS_LOW)
change_summary:
  - FIX: strategy/spreads.py v2.5.2 - dual cross-DEX routes (emit both directions A->B and B->A)
  - ADD: _find_all_cross_dex_spreads() function - finds ALL profitable cross-dex combinations  
  - FIX: _compute_pair_spread() now returns List[Dict] (multiple signals per pair)
  - CHG: config/real_minimal.yaml require_cross_dex=false (include intra-DEX signals)
  - CHG: config/real_minimal.yaml paper_size_usd=250 (reduce SUSPECT_LIQUIDITY rejects)
  - ADD: tests/unit/test_same_dex_policy.py - test_dual_cross_dex_routes_emitted
  - RESULT: 1063 tests passed, agg_status=WARN_QUALITY (not FAIL!), DIVERSITY_ROUTES_FAIL RESOLVED
touched_files:
  - strategy/spreads.py (v2.5.2 dual cross-dex routes)
  - config/real_minimal.yaml (require_cross_dex=false, paper_size_usd=250)
  - tests/unit/test_same_dex_policy.py (1 new dual-route test)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: PASS (1063 passed, 1 skipped)
py -3.11 scripts/check_repo_safety.py: PASS
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)
py -3.11 scripts/ci_m5_0_gate.py --online (13 runs): PASS, agg_status=WARN_QUALITY

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json (reset for v2.5.2, 13 runs)
run_dir_bundle (ONLINE dual cross-dex test):
  - data/runs/ci_m5_gate_20260224_122459/reports
dual_cross_dex_evidence:
  - uniswap_v3->sushiswap_v3 (direction 1)
  - sushiswap_v3->uniswap_v3 (direction 2)
  - uniswap_v3->uniswap_v3 (intra-DEX, now included since require_cross_dex=false)

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY (NOT FAIL - IMPROVED!)
  agg_reasons: ['DIVERSITY_PAIRS_LOW']
  quality_warnings: ['DIVERSITY_PAIRS_LOW(6<8)']
  data_run_rate: 1.0
  low_sample_rate: 0.0
  runs_in_window: 13
  in_warmup: false

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-24T11:25:12+00:00
  inputs.run_dir_name: ci_m5_gate_20260224_122459
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 5-7 per run
    included_signals_count: 5-7 (all included, require_cross_dex=false)
    excluded_signals_count: 0 (no exclusions!)
    total_net_usdc: $35.42 (13 runs)
    profit_is_diagnostic: true

m4_stability_agg.json:
  runs_in_window: 13 (reset for v2.5.2)
  pass_count: 13 (100%)
  data_run_rate: 1.0 (PERFECT)
  total_net_usdc: $35.42
  unique_pairs: 6 (target=8)
  unique_routes: 3
  unique_routes_cross_dex: 2 (FIXED! was 1, now 2)
  agg_status: WARN_QUALITY (not FAIL!)
  agg_reasons: ['DIVERSITY_PAIRS_LOW']

## 5) Dual Cross-DEX Routes Analysis (v2.5.2)

dual_route_fix:
  - BEFORE: only emitted ONE cross-dex direction (best spread)
  - AFTER: emit BOTH cross-dex directions (A->B and B->A if both profitable)
  - MECHANISM: _find_all_cross_dex_spreads() returns all combinations  
  - ALWAYS prefer cross-DEX even when require_cross_dex=false
  - emit_dual_routes: true (default) emits both directions for route diversity

log_evidence:
  - "unique_routes: ['sushiswap_v3->uniswap_v3', 'uniswap_v3->sushiswap_v3', 'uniswap_v3->uniswap_v3']"
  - "unique_routes_cross_dex: 2 (FIXED! sushiswap_v3->uniswap_v3 AND uniswap_v3->sushiswap_v3)"

diversity_improvement:
  - BEFORE v2.5.1: unique_routes_cross_dex=0 -> 1 (only uniswap->sushi)
  - AFTER v2.5.2: unique_routes_cross_dex=2 (both directions: uni->sushi AND sushi->uni)
  - DIVERSITY_ROUTES_FAIL: RESOLVED (2 >= 2 required)
  - DIVERSITY_PAIRS_LOW: 6 < 8 (remaining warning, not blocking)

## 6) M4 DoD Status

| DoD | Status | Evidence |
|-----|--------|----------|
| Core Truth (paper +PnL) | [OK] PROVEN | N=13 runs, total_net_usdc=$35.42 |
| Rolling Quality Gate | [OK] WARN_QUALITY | agg_status=WARN_QUALITY (not FAIL!), routes=2 |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0 |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] IN_PROGRESS | 13/100 runs (warmup exit complete) |
| M4.3 Preflight Evidence | [OK] v1.0.3 | chain-aware leg2, gas_sanity |
| Cross-DEX Preference | [OK] v2.5.2 | dual routes, always prefer cross-DEX |
| Diversity Routes | [OK] FIXED | unique_routes_cross_dex=2 >= 2 |
| Diversity Pairs | [WARN] 6<8 | real_minimal.yaml limited pairs |

> **DUAL CROSS-DEX ROUTES v2.5.2**: Emit BOTH directions (A->B and B->A) when profitable.
> Evidence: sushiswap_v3->uniswap_v3 AND uniswap_v3->sushiswap_v3 both active.
> DIVERSITY_ROUTES_FAIL RESOLVED. agg_status improved from FAIL to WARN_QUALITY.

## 7) Contract Checks (коротко)
status/reasons consistency: OK (no FAIL_* with PASS status)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no SHA tracking)
runtime artifacts not committed: OK
dual cross-dex routes: IMPLEMENTED (_find_all_cross_dex_spreads)
same-dex signals: included when require_cross_dex=false

## 8) Blockers / Risks (max 5)
- DIVERSITY_PAIRS_LOW: 6 pairs < 8 required (expand config for more pairs)
- roundtrip.profitable_count=0 (market has no arb opportunity)
- Rolling window reset (13 runs, need more for stable metrics)
- paper_size_usd=250 may miss larger opportunities

## 9) Lead's 10 Steps: Execution Map (Directive #14)
step_01 (Set require_cross_dex=false): DONE
step_02 (Fix spreads.py cross-dex logic): DONE - always prefer cross-DEX
step_03 (Add dual cross-DEX routes mode): DONE - _find_all_cross_dex_spreads()
step_04 (Add dual-route unit test): DONE - test_dual_cross_dex_routes_emitted
step_05 (Reduce paper_size_usd to 250): DONE
step_06 (Run pytest verification): DONE - 1063 tests passed
step_07 (Run CI full pipeline): DONE - ALL GATES PASSED
step_08 (Generate ONLINE artifacts): DONE - 13 runs, rolling reset
step_09 (Verify rolling diversity metrics): DONE - unique_routes_cross_dex=2, agg_status=WARN_QUALITY
step_10 (Update docs): DONE
