# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39u**: Sweep truth promotion — fix contract mismatch between measured_economics and top-level profit semantics. Per-pair repeatability tracking. 2490 tests.
**R39t**: Contract-preserving bugfixes: slippage_max_bps enforcement, pool_usage_report opp_count, clamp accounting. 2484 tests.
**R39s**: Fixed Base sweep regression — stale block + unresolved Alchemy placeholder. Base sweep restored. 2482 tests.
**R39r**: Flashblocks read-path integration + EXECUTABLE_TRUTH_GATE + structural_advantage_met wiring. 2469 tests.

## SESSION GOAL (R39u: Sweep truth promotion + per-pair repeatability)
**Goal**: Fix contract mismatch between measured_economics/executable_evidence and top-level profit_realism_status so Base with dynamic sweep data classifies as ROUNDTRIP_NOT_PROFITABLE instead of ONE_LEG_ONLY_DIAGNOSTIC. Add per-pair repeatability block to rolling artifacts.
**Prior (R39t)**: All 3 correctness bugs fixed: slippage_max_bps enforced, pool_usage_report opp_count fixed, clamp accounting fixed. Sweep best pair correctly USDC/DAI at -8.6 bps. But profit_realism_status stuck at ONE_LEG_ONLY_DIAGNOSTIC because evaluated_count=0.
**Lead directive (R39u)**: "Contract gap, not market. If measured_economics.available=true AND executable_evidence in {SWEEP_GAP_TO_ZERO, SWEEP_PROFITABLE}, this is NOT ONE_LEG_ONLY_DIAGNOSTIC."

## 0) Meta
timestamp_utc: 2026-03-27T12:55:37Z
run_id: ci_m5_gate_arbitrum_one_20260327_135513_846104
mode: ONLINE
artifact_mode: rolling
config: real_minimal.yaml + onboard_base_profit.yaml
code_identity:
  primary: ts:2026-03-27T12:55:37Z
  dirty: true (R39u code changes uncommitted)
  desc: sweep_truth_promotion_per_pair_repeatability

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39u: Sweep truth promotion + per-pair repeatability |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | None for this session (truth semantics contract now aligned) |
| fresh_evidence_run | 20-min 2-chain scan (54 runs, 1204s) |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260327_135513_846104 + ci_m5_gate_base_20260327_135538_951781 |
| primary_blocker_of_session | profit_realism_status stuck at ONE_LEG_ONLY_DIAGNOSTIC despite measured_economics.available=true |
| blocker_status_before | ACTIVE: Base prs=ONE_LEG_ONLY_DIAGNOSTIC even with sweep gap=8.6 bps |
| blocker_status_after | RESOLVED: Base prs=ROUNDTRIP_NOT_PROFITABLE, profit_truth_source=ROUNDTRIP_CANONICAL |
| start_metric | R39t: Base prs=ONE_LEG_ONLY_DIAGNOSTIC, profit_is_diagnostic=true, no per-pair repeatability |
| end_metric | R39u: Base prs=ROUNDTRIP_NOT_PROFITABLE, profit_is_diagnostic=false, per-pair repeatability tracked |
| delta | Contract mismatch eliminated. Base sweep truth now canonical. USDC/DAI median_gap=9.37 bps, USDC/USDT=11.9 bps. |
| docs_reread_confirmed | true |

## 0.3) Fresh 2-Chain Scan Evidence (R39u)

```
Wall time:      1204s (54 runs: 27 arb + 27 base)
frontier_ranking:
  #1 base           median=9.4  best=9.0 bps  pnl=-9.0 bps  profit_state=CANDIDATE
  #2 arbitrum_one   median=25.3 best=25.2 bps pnl=-25.2 bps profit_state=PRIMARY_BLOCKER

Latest Base truth_report (ci_m5_gate_base_20260327_135538_951781):
  profit_realism_status: ROUNDTRIP_NOT_PROFITABLE
  profit_is_diagnostic:  false
  profit_truth_source:   ROUNDTRIP_CANONICAL
  measured_economics.available: true
  executable_evidence: SWEEP_GAP_TO_ZERO
  frontier_pair: USDC/DAI
  gap_to_zero_bps: 9.0

Per-pair repeatability (Base, 27 runs):
  USDC/DAI:  signals=27/27  sweep=27/27  median_gap=9.37 bps
  USDC/USDT: signals=27/27  sweep=27/27  median_gap=11.9 bps
  WETH/USDC: signals=27/27  sweep=27/27  median_gap=875.38 bps (correctly excluded by slippage gate)
```

## 1) Scope
goal (Roadmap): M5_0/M4 -- R39u: Sweep truth promotion
change_summary:
  - **strategy/artifacts.py** -- R39u: Pre-compute `_has_sweep_truth` and `_has_legacy_profitable`. When `measured_economics.available=true` AND `executable_evidence in {SWEEP_GAP_TO_ZERO, SWEEP_PROFITABLE}`, promote `profit_realism_status` to ROUNDTRIP_NOT_PROFITABLE (or ROUNDTRIP_PROFITABLE for SWEEP_PROFITABLE). `profit_is_diagnostic=false`, `profit_truth_source=ROUNDTRIP_CANONICAL`.
  - **strategy/chain_stats.py** -- R39u: Add `_per_pair_repeat` accumulator to `new_chain_stats()`. In `update_chain_stats()`, track per-pair signal presence and sweep truth from `truth_report.measured_economics.per_route_breakdown`.
  - **strategy/long_scan_summary.py** -- R39u: Add `per_pair_repeatability` block to long_scan_latest.json via `_compute_per_pair_repeatability()`. Surfaces `runs_with_signals`, `runs_with_sweep_truth`, `median_gap_to_zero_bps` per pair per chain.
  - **tests/unit/test_roundtrip_canonical_gating.py** -- R39u: 6 new tests in `TestSweepTruthPromotion` class: sweep_gap_to_zero promotes, sweep_profitable promotes, no_sweep stays diagnostic, sweep_enabled_but_no_results stays diagnostic, legacy_profitable still works, suspect_contamination_guard intact.

## 2) Test state
total_pass: 2490
total_skip: 5
total_fail: 0
delta: +6 (sweep truth promotion tests)

## 3) Pipeline state (all offline)
pytest: PASS (2490 passed, 5 skipped)
m4_gate_offline_profit_strict: PASS

## 4) Key Metrics

| chain | real_quotes | rt_evaluated | profit_realism | sweep_best | sweep_pnl_bps | infra_pass |
|-------|-------------|-------------|----------------|------------|---------------|------------|
| arbitrum_one | 121 | 121 | ROUNDTRIP_NOT_PROFITABLE | USDC/DAI | -25.2 | 27 |
| base | 0 | 0 | ROUNDTRIP_NOT_PROFITABLE | USDC/DAI | -9.0 | 27 |

## 5) Contract Fix This Session

### Core issue: truth semantics ≠ measured economics
`profit_realism_status` used `evaluated_count > 0` as sole gate for escaping `ONE_LEG_ONLY_DIAGNOSTIC`. But dynamic sweep with `measured_economics.available=true` IS two-legged truth — gas, LP fees, slippage all measured via QuoterV2, not paper estimates. The contract prohibited Base (which had full measured economics) from reaching canonical truth.

### Fix: Two promotion paths (artifacts.py)
1. **Legacy path**: `profitable_count > 0 AND real_quote_count > 0` → ROUNDTRIP_PROFITABLE (unchanged)
2. **Sweep path**: `measured_economics enabled + best_net_pnl_bps not None + executable_evidence in {SWEEP_GAP_TO_ZERO, SWEEP_PROFITABLE}` → ROUNDTRIP_NOT_PROFITABLE or ROUNDTRIP_PROFITABLE

### Per-pair repeatability (chain_stats.py + long_scan_summary.py)
New `per_pair_repeatability` block in long_scan_latest.json tracks across runs:
- `runs_with_signals`: how many runs produced signals for this pair
- `runs_with_sweep_truth`: how many runs had sweep economics for this pair  
- `median_gap_to_zero_bps`: median gap across sweep samples

## 6) Lead Fix Steps Status

| Step | Status | Detail |
|------|--------|--------|
| 1. Only Base stable truth semantics | ACKNOWLEDGED | No MEV, no contour change, no rewrite |
| 2. Align profit_realism_status with measured_economics | **DONE** | Two promotion paths in artifacts.py |
| 3. Contract: measured_economics + SWEEP → not diagnostic | **DONE** | _has_sweep_truth guard |
| 4. Negative sweep → ROUNDTRIP_NOT_PROFITABLE | **DONE** | SWEEP_GAP_TO_ZERO → ROUNDTRIP_NOT_PROFITABLE |
| 5. No new enum values | RESPECTED | Using existing ROUNDTRIP_NOT_PROFITABLE, ROUNDTRIP_CANONICAL |
| 6. Add regression tests | **DONE** | 6 tests in TestSweepTruthPromotion |
| 7. No config changes | RESPECTED | onboard_base_profit.yaml untouched |
| 8. Per-pair repeatability | **DONE** | per_pair_repeatability block in long_scan_latest |
| 9. Run prescribed sequence | **DONE** | pytest + M4 + 20-min scan + inspect_rolling |
| 10. Docs after evidence | **DONE** | This report written after 54-run scan confirms fix |

## 7) Remaining Blockers (next sessions)

1. **Base real_quote_count=0** — sweep economics work but OE economics gate rejects all candidates before roundtrip evaluation. Not blocking truth semantics but blocks EXECUTABLE_TRUTH_GATE promotion.
2. **Base FAIL rate** — 22/27 runs FAIL (coverage gate). Not infra failures — the gate checks are stricter than what the 4-pair contour can satisfy.
3. **Flashblocks not operational** — sim_success_count=0, tx_status_reachable=false (public endpoint rate-limited).
4. **Arbitrum gap** — -25.2 bps median with 121 real quotes. Stable but not profitable.
