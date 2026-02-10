# Status: M4 (DEX↔DEX Atomic Execution)

**Status**: ✅ **PROVEN** (simulate_only), ❌ **NOT PROVEN** (real execution)  
**Updated**: 2026-02-10  
**Gate Version**: v1.10.0  
**Policy Version**: v1.10.0  

## Rolling KPIs (Targets)

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| `data_run_rate` | ≥ 0.70 | _check rolling_ | ❓ |
| `low_sample_rate` | ≤ 0.30 | _check rolling_ | ❓ |
| `fragile_rate_p90` | ≤ 0.30 | _check rolling_ | ❓ |
| `unique_pairs` | ≥ 10 | _check rolling_ | ❓ |
| `unique_routes` | ≥ 4 | _check rolling_ | ❓ |
| `agg_status` | PASS/WARN | _check rolling_ | ❓ |

## Thresholds (v1.10.0)

| Threshold | Value | Description |
|-----------|-------|-------------|
| `MIN_SIGNALS_FOR_PASS` | 5 | Profit-grade data_run |
| `MIN_SIGNALS_COVERAGE` | 3 | Coverage-grade (diagnostic) |
| `MAE_WARN` | 0.55 | MAE warning |
| `MAE_FAIL` | 0.80 | MAE failure |
| `fragile_rate_max` | 0.20 | Max fragile (profit) |

## Canonical Commands

```bash
# Coverage batch
python scripts/run_coverage_batch.py --min-signals-target 30 --max-seconds 600 --profile profit

# M4 gate (strict evidence)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --strict-evidence

# Check rolling
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "data_run_rate|agg_status|unique_pairs"

# Reset window
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window
```

## Rolling Artifacts

| File | Purpose |
|------|---------|
| `_latest.json` | Latest run pointer |
| `run_summary_latest.json` | Full run summary |
| `m4_stability_agg.json` | Rolling aggregator |

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
