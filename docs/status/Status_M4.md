# Status: M4 (DEX↔DEX Atomic Execution)

**Status**: ✅ **PROVEN** (simulate_only), ❌ **NOT PROVEN** (real execution)  
**Updated**: 2026-02-10  
**Gate Version**: v1.12.0  
**Policy Version**: v1.12.0  

## Taxonomy Contract (v1.12.0)

| Reason Prefix | Status Required | Semantic |
|---------------|-----------------|----------|
| `FAIL_*` | status=FAIL | Hard failure, blocks passage |
| `WARN_*` | status=PASS allowed | Warning, quality concern |
| `NO_DATA` | status=NO_DATA | signals_count == 0 only |

**Invariant**: If `FAIL_*` appears in reasons, status MUST be FAIL. Enforced by `compute_status()`.

## Status Contract (v1.11.0+)

| Condition | Status | Semantic |
|-----------|--------|----------|
| `signals_count == 0` | NO_DATA | True absence of data |
| `signals > 0, net > 0` | PASS | Profitable (quality may warn) |
| `signals > 0, net ≤ 0` | FAIL | Unprofitable |
| `signals < 5` | quality_status=WARN | Low sample (not NO_DATA) |

**Rule**: NO_DATA only when signals_count == 0. Low sample → WARN, not NO_DATA.

## Run Kinds (v1.11.0)

| Kind | Description | Counted in KPIs |
|------|-------------|-----------------|
| NORMAL | Regular online scan | ✅ Main KPIs |
| COVERAGE | Coverage batch run | ❌ Separate stats |
| SMOKE | Smoke test | ❌ Excluded |
| OFFLINE | Offline fixture | ❌ Excluded |

## Rolling KPIs (Targets)

| Metric | Target | FAIL | Description |
|--------|--------|------|-------------|
| `data_run_rate` | ≥ 0.50 | < 0.30 | % NORMAL runs with ≥5 signals |
| `fail_rate` | ≤ 0.10 | > 0.15 | % FAIL runs (v1.12.0 bites) |
| `fragile_rate_p90` | ≤ 0.30 | > 0.50 | p90 fragile rate |
| `unique_pairs` | ≥ 10 | < 3 | Pair diversity |
| `unique_routes` | ≥ 4 | < 2 | Route diversity |

## Thresholds (v1.12.0)

| Threshold | Value | Description |
|-----------|-------|-------------|
| `MIN_SIGNALS_FOR_PASS` | 5 | Profit-grade (is_data_run) |
| `MIN_SIGNALS_WARN` | 3 | Below = WARN_LOW_SAMPLE |
| `MAE_WARN` | 0.55 | MAE warning |
| `MAE_FAIL` | 0.80 | MAE failure |
| `SIGN_RATE_MIN` | 0.60 | Min sign correct rate |
| `AGG_FAIL_RATE_FAIL` | 0.15 | v1.12.0: fail_rate > 15% → FAIL |
| `DIVERSITY_PAIRS_MIN` | 3 | v1.12.0: < 3 pairs → FAIL |
| `DIVERSITY_ROUTES_MIN` | 2 | v1.12.0: < 2 routes → FAIL |

## Canonical Commands

```bash
# Coverage batch (COVERAGE kind)
python scripts/run_coverage_batch.py --min-signals-target 30 --max-seconds 600 --profile profit

# M4 gate (profit, require-clean by default)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# Allow dirty worktree (dev only)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --allow-dirty

# Check rolling KPIs
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "data_run_rate|no_data_rate|signals_per_run_p50"

# Reset window
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window
```

## Rolling Artifacts

| File | Purpose |
|------|---------|
| `_latest.json` | Latest run pointer |
| `run_summary_latest.json` | Full run summary |
| `m4_stability_agg.json` | Rolling aggregator (segmented by run_kind) |

Location: `data/runs/_rolling/`

## Definition of Done

### M4.1: Simulate-Only — ✅ PROVEN
- [x] Online scan generates signals
- [x] Simulator calculates PnL
- [x] Rolling artifacts persist
- [x] Evidence workflow works

### M4.2: Real Execution — ❌ NOT PROVEN
- [ ] Kill switch disabled
- [ ] Real TX submitted

## Documentation

- [Policy & Thresholds](../m4/M4_POLICY.md)
- [Rolling Contract](../m4/ROLLING_CONTRACT.md)
- [Testing Guide](../TESTING.md)
