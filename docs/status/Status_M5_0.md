# Status: M5_0 (Infrastructure Hardening)

**Status**: **DONE**  
**Updated**: 2026-03-27  
**Tests**: `2527 passed / 5 skipped`  
**Schema family in active rolling**:
- `m4:latest:v2.0`
- `m4:run_summary:v2.0`
- `start:long_scan_summary:v1.16`

**Canonical evidence**:
- `data/runs/_rolling/_latest.json`
- `data/runs/_rolling/run_summary_latest.json`
- `data/runs/_rolling/m4_stability_agg.json`
- `data/runs/_rolling/long_scan_latest.json`
- `data/runs/_rolling/hot_loop_latest.json`

**Fresh provenance**:
- `run_summary_latest.json.run_context.run_timestamp = 2026-03-27T21:30:14.342304Z`
- `long_scan_latest.json.generated_at = 2026-03-27T21:30:49.463920Z`
- run_id: `data/runs/ci_m5_gate_arbitrum_one_20260327_222948_123275`
- run_mode: `REGISTRY_REAL` / `ONLINE`

---

## Canonical Commands

```powershell
py -3.11 -m pytest -q
py -3.11 scripts/check_repo_safety.py
py -3.11 scripts/ci_full_pipeline.py --mode ci
py -3.11 scripts/inspect_rolling.py
py -3.11 scripts/ci_m5_0_gate.py --offline
```

---

## Summary

M5_0 was about infrastructure hardening, not proving profitable execution. On that narrower goal, the current project state is strong enough to mark M5_0 as done for the current public-infrastructure thesis.

The current data plane is stable, observable, reproducible, and rich enough to support hard negative conclusions. That is an achievement of M5_0, not a failure of it.

---

## Fresh Evidence Snapshot

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

### Per Chain

| Chain | Runs | Signals | RT Evaluated | Real Quotes | Frontier Pair | Gap | Blocker |
|-------|------|---------|--------------|-------------|---------------|-----|---------|
| `arbitrum_one` | `29/29 PASS` | `906` | `169` | `169` | `WBTC/USDC` | `3.5062 bps` | `OE_ECONOMICS` |
| `base` | `29/29 PASS` | `290` | `0` | `0` | `USDC/USDT` | `8.6729 bps` | `OE_ECONOMICS` |

### Rolling Quality

| Artifact | State |
|----------|-------|
| `_latest.json` | present and current |
| `run_summary_latest.json` | present and current |
| `m4_stability_agg.json` | present and current |
| `long_scan_latest.json` | present and current |
| `hot_loop_latest.json` | present and current |

---

## What M5_0 Achieved

The current repo now has all of the following on the public-infrastructure path:

1. Stable rolling artifacts with overwrite discipline.
2. Multi-chain frontier ranking with chain roles and blocker classification.
3. Measured sweep truth rather than paper-only frontier claims.
4. Canonical profit semantics (`ROUNDTRIP_CANONICAL` vs diagnostic-only).
5. Per-pair repeatability and near-breakeven decomposition.
6. Dashboard and operator-facing hot-loop artifacts.
7. Strong CI, docs consistency, and repo-safety enforcement.
8. Enough observability to distinguish infra failure from economics failure.

This is precisely why current negative conclusions are credible.

---

## What M5_0 Did Not Prove

M5_0 does **not** prove:

1. profitable DEX-DEX execution,
2. profitable online M4 closure,
3. usefulness of private/orderflow branches,
4. viability of triangular or cross-chain strategies.

M5_0 solved the question "can we trust our current public-infrastructure evidence?"  
The current answer is: **yes**.

---

## Infrastructure Verdict

The hardened system now supports the following conclusions with high confidence:

- infra instability is no longer the main reason for missing profit,
- stale truth semantics are no longer the main reason,
- public-infra execution-edge tweaks did not materially rescue the thesis,
- the current public simple DEX-DEX branch reached an economics ceiling before profitable execution.

## Known Blockers

The remaining blockers after M5_0 are no longer infrastructure blockers for this milestone. They belong to strategy viability:

1. public-infra two-leg DEX-DEX economics remain negative,
2. online profitable M4 truth is still missing,
3. any further progress requires a new strategy branch or a higher-cost execution tier.

That is a milestone-level closure condition for M5_0.

---

## Boundary With M4

M5_0 being done does **not** close M4.

The boundary is now clean:

- **M5_0**: public-infra scan/evidence platform hardened and trustworthy -> **DONE**
- **M4**: online profitable DEX-DEX core truth -> **NOT DONE**

This distinction is important. The repo should not keep using infra work to imply strategy success.

---

## Status Conclusion

M5_0 should now be read as a completed hardening milestone for the present public-infrastructure thesis. The repo has enough stability, observability, and artifact discipline to stop blaming missing profit on hidden infra noise.

## Stage Clarification

M5_0 is complete as an infrastructure milestone. It should not be reopened merely to continue tuning a strategy branch that current evidence already classifies as economics-blocked.
