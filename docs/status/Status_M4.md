# Status: M4 (DEX↔DEX Atomic Execution)

**Status**: ✅ **PROVEN** (simulate_only), ❌ **NOT PROVEN** (real execution)  
**Updated**: 2026-02-10  
**Evidence SHA**: `d318f3a`  
**Gate Version**: v1.10.0  
**Policy Version**: v1.10.0  
**Tests**: 562 passed

## Rolling KPIs (Target)

| Metric | Target | Description |
|--------|--------|-------------|
| `data_run_rate` | ≥ 0.70 | % runs with ≥5 signals |
| `low_sample_rate` | ≤ 0.30 | % runs with <5 signals |
| `fragile_rate_p90` | ≤ 0.30 | p90 fragile rate across window |
| `agg_status` | PASS/WARN | Not FAIL_QUALITY |

## DoD-1 Thresholds (profit profile)

| Threshold | Value | Description |
|-----------|-------|-------------|
| `MIN_SIGNALS_FOR_PASS` | 5 | Below = NO_DATA |
| `MAE_WARN` | 0.55 | MAE warning |
| `MAE_FAIL` | 0.80 | MAE failure |
| `SIGN_RATE_MIN` | 0.60 | Sign rate minimum |
| `fragile_rate_max` | 0.20 | Max fragile rate |

## Current State

| Metric | Value | Status |
|--------|-------|--------|
| Latest Mode | ONLINE | ✅ |
| Run Status | PASS | ✅ |
| Aggregate Status | PASS_WARMUP | ⚠️ |
| Signals in Window | 3 | ⚠️ Low |
| Evidence Attached | Yes | ✅ |
| Code Dirty | Yes | ⚠️ |

## Canonical Commands

```bash
# Coverage batch (collect signals until target)
python scripts/run_coverage_batch.py --min-signals-target 30 --max-seconds 600 --profile profit

# Standard batch (N runs)
python scripts/run_coverage_batch.py --count 10 --profile profit

# M4 gate (online, profit profile, strict evidence)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --require-clean

# Attach evidence after commit
python scripts/attach_evidence.py

# Check rolling stats
Get-Content data/runs/_rolling/_latest.json | Select-String "data_run_rate|agg_status|effective_pass_rate"

# Reset rolling window
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window
```

## Evidence Workflow

```
1. Run scan    → code_sha captured, code_dirty = true/false
2. Commit      → git add -A && git commit
3. Attach      → python scripts/attach_evidence.py
4. Verify      → attached_evidence_sha != null
```

For **PROVEN** status:
- `code_dirty = false` (clean worktree at run time)
- `evidence_sha` attached post-commit
- `evidence.ok = true`

## Rolling Artifacts

| File | Purpose |
|------|---------|
| `_latest.json` | Latest run pointer |
| `run_summary_latest.json` | Full run summary |
| `m4_stability_agg.json` | Rolling aggregator |

Location: `data/runs/_rolling/`

## Documentation

| Topic | Link |
|-------|------|
| Schema & Data Contract | [docs/m4/ROLLING_CONTRACT.md](../m4/ROLLING_CONTRACT.md) |
| Policy & Thresholds | [docs/m4/M4_POLICY.md](../m4/M4_POLICY.md) |
| Testing Guide | [docs/TESTING.md](../TESTING.md) |
| Legacy Details | [Status_M4_legacy.md](Status_M4_legacy.md) |

## Key Decisions

1. **source_sha deprecated** (v1.9.3): Use `run_context.code_sha` instead
2. **Rolling only**: No per-run artifacts except incidents (FAIL)
3. **Two SHA model**: `code_sha` (run time) + `evidence_sha` (post-commit)
4. **Warmup phase**: Min 10 runs, 30 signals before trusting aggregate stats

## Definition of Done

### M4.1: Simulate-Only (PROVEN)
- [x] Online scan generates signals
- [x] Simulator calculates PnL with realistic costs
- [x] Rolling artifacts persist
- [x] Evidence workflow works

### M4.2: Real Execution (NOT PROVEN)
- [ ] Kill switch disabled
- [ ] Real TX submitted
- [ ] Actual PnL matches simulation
