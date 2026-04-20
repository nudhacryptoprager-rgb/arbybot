# Status: M4 (DEX-DEX Atomic Execution)

**Status**: **IN PROGRESS** (paper/sim capable, **NOT production-ready**)
**Updated**: 2026-04-20
**Current reading**: `M4.1 simulate-only` historically closed; `M4 online profit` **not reached** — economic truth remains negative. Truth contract (E1.33) now internally consistent: `profit_realism_status=ROUNDTRIP_NOT_PROFITABLE`, `real_quote_count=0`, `profitable_roundtrips=0`. Release gates (repo safety, pytest 4174 passed, ci_full_pipeline CI, M4 offline profit `--strict`) all PASS as of 2026-04-20.
**Fresh provenance (E1.33 cycle)**:
- `run_summary_latest.json.run_context.run_timestamp = 2026-04-17T12:59:11.866411Z`
- `run_summary_latest.json.run_context.run_dir_name = ci_m5_gate_arbitrum_one_20260417_145636_478653` (E1.33: now populated, was None)
- `_latest.json.run_dir_name = ci_m5_gate_arbitrum_one_20260417_145636_478653` (E1.33: top-level)
- rolling window: `200` runs, `pass_count=187`, `data_run_rate=1.0`, `pass_rate=0.935`, `agg_status=WARN_QUALITY` (reason: `FRAGILE_P90_ELEVATED`)
- long_scan: `total_runs=119`, `total_profitable_roundtrips=0` — confirms M4.2 not reached at market level
- `profit_realism_status=ROUNDTRIP_NOT_PROFITABLE`, `real_quote_count=0`, `profitable_roundtrips=0` (internally consistent after E1.33 invariant guard)
- tests: `4174 passed / 6 skipped` (2026-04-20 regression; E1.35/E1.36/E1.37 tests included)
- safety gate: Windows `UnicodeEncodeError` crash fixed (`scripts/check_repo_safety.py` now reconfigures stdout/stderr to UTF-8)

**E1.33 contract locks (new)**:
- `build_truth_data` demotes `ROUNDTRIP_PROFITABLE` → `ROUNDTRIP_NOT_PROFITABLE` if `real_quote_count==0` OR `profitable_count==0`; emits `profit_realism_invariant_violation` block with original_status + reason `PROFITABLE_REQUIRES_REAL_QUOTES_AND_PROFITABLE_COUNT`.
- Provenance: `run_dir_name` is now a first-class field at both top-level of `_latest.json` and inside `run_summary.run_context`.

**Previous (superseded) reading**: `Updated: 2026-03-27`, run_timestamp `2026-03-27T21:30:14`, 58-run rolling window, 2527 tests. Retained below as historical record.

**Canonical evidence**:
- `data/runs/_rolling/_latest.json`
- `data/runs/_rolling/run_summary_latest.json`
- `data/runs/_rolling/m4_stability_agg.json`
- `data/runs/_rolling/long_scan_latest.json`
- runDir evidence: `ci_m5_gate_arbitrum_one_20260327_222948_123275`, `ci_m5_gate_base_20260327_223015_126754`

---

## Executive Summary

Current M4 state is no longer blocked by basic scanner correctness. The system now produces stable online evidence, canonical roundtrip truth semantics, repeatability statistics, and near-breakeven decomposition. What it does **not** produce is profitable online DEX-DEX execution under the current public-infrastructure thesis.

The strongest current statement is:

- `M4.1 simulate-only`: historically achieved
- `M4.2 roundtrip profitable online`: not achieved
- `M4.3 real execution`: not started in production (`execution_enabled=false`, kill switch remains on)

This means M4 is still open at the roadmap level, but the current public-infrastructure two-leg DEX-DEX branch should be treated as a frozen no-go branch rather than an actively improvable mainline.

---

## Fresh Rolling Snapshot

### Aggregate

| Metric | Value |
|--------|-------|
| total_runs | `58` |
| total_pass | `58` |
| total_fail | `0` |
| total_infra_fail | `0` |
| total_included_signals | `1196` |
| total_roundtrip_evaluated | `169` |
| total_profitable_roundtrips | `0` |
| best_roundtrip_net_bps | `-3.5062` |

### Active Chains

| Chain | Runs | Signals | RT Evaluated | Real Quotes | Frontier Pair | Best Gap | Profit Status | Blocker |
|-------|------|---------|--------------|-------------|---------------|----------|---------------|---------|
| `arbitrum_one` | `29/29 PASS` | `906` | `169` | `169` | `WBTC/USDC` | `3.5062 bps` | `ROUNDTRIP_NOT_PROFITABLE` | `OE_ECONOMICS` |
| `base` | `29/29 PASS` | `290` | `0` | `0` | `USDC/USDT` | `8.6729 bps` | `ROUNDTRIP_NOT_PROFITABLE` | `OE_ECONOMICS` |

## Canonical Commands

```powershell
py -3.11 -m pytest -q
py -3.11 scripts/check_repo_safety.py
py -3.11 scripts/ci_full_pipeline.py --mode ci
py -3.11 scripts/inspect_rolling.py
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict
```

Important nuance:

- `arbitrum_one` has the single best in-window point (`-3.51 bps`), but not a stable positive lane.
- `base` is the most coherent stable-pair family by economics, but it still remains negative and non-executable in canonical roundtrip counts.

---

## Milestone Sub-State

### M4.1 - Simulate-Only

Status: **CLOSED historically**

What remains true:

- rolling discipline exists
- simulate-only path is proven
- canonical truth/reporting path is stable

### M4.2 - Online Roundtrip Profit

Status: **NOT REACHED**

Fresh evidence against closure:

- `total_profitable_roundtrips = 0`
- no chain has `N >= 5` consecutive online positive runs
- best observed current-window gap is still negative (`-3.5062 bps`)

### M4.3 - Real Execution

Status: **NOT STARTED**

The repo contains real execution scaffolding, but production remains intentionally disabled:

- `execution_enabled=false`
- kill switch remains active
- no on-chain profitable execution evidence exists

---

## What Is Actually Solved

By the end of the current M5/M5_0 phase, M4 no longer suffers from the earlier classes of ambiguity:

1. Truth semantics are canonical: `profit_realism_status=ROUNDTRIP_NOT_PROFITABLE` is now machine-consistent.
2. Sweep frontier truth is measured, not paper-only.
3. Repeatability promotion and near-breakeven decomposition exist.
4. Rolling artifacts are stable and operationally consistent.
5. Infra failures are no longer the dominant explanation for the current result.

In other words, the current negative verdict is informative, not a data-quality accident.

---

## What Is Not Solved

The following remain unresolved at the M4 level:

1. No profitable online DEX-DEX lane on current public infrastructure.
2. No chain with repeatable positive roundtrip truth.
3. No real execution path exercised in production.
4. No evidence that public-infra execution-edge tweaks materially change economics.

## Known Blockers

1. `OE_ECONOMICS` remains the blocker on both active chains.
2. `total_profitable_roundtrips = 0` in the current rolling window.
3. `M4 online` requires positive real online runs; current evidence is canonically negative, not diagnostic-only.
4. Current public-infrastructure branch is no longer a hidden-quality problem; it is an economics problem.

---

## Current M4 Interpretation

The correct current reading is narrow and specific:

**`simple two-leg DEX-DEX on current public infrastructure/public orderflow has not met M4 online-profit DoD and presently looks economically exhausted.`**

This does **not** prove that every future DEX-DEX branch is impossible. It does prove that the current public branch should not be treated as an unfinished tuning problem.

---

## Status Conclusion

M4 remains **IN PROGRESS** only because Roadmap-level closure still requires online profitable evidence or an explicitly approved strategic pivot. From the system perspective, however, the current public-infrastructure branch has already been audited hard enough to stop pretending that another small fix is likely to unlock online profit.

## Stage Clarification

Current stage is:

- `M4.1`: closed historically
- `M4.2`: unresolved on the current public-infrastructure branch
- `M4.3`: not activated

This file should now be read as a milestone-state summary, not as an invitation to continue tuning the same public simple DEX-DEX lane indefinitely.
