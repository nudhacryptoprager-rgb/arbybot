# Status: M4 (DEX↔DEX Atomic Execution)

**Status**: ✅ **PROVEN** (simulate_only), ❌ **NOT PROVEN** (real execution)  
**Updated**: 2026-02-09  
**Evidence SHA**: `a43e3cd`  
**Gate Version**: v1.9.3  
**Tests**: 562 passed

## Current State

| Metric | Value | Status |
|--------|-------|--------|
| Latest Mode | ONLINE | ✅ |
| Run Status | PASS | ✅ |
| Aggregate Status | PASS_WARMUP | ⚠️ |
| Signals in Window | 3 | ⚠️ Low |
| Evidence Attached | Yes | ✅ |
| Code Dirty | Yes | ⚠️ |

## Quick Commands

```bash
# Run M4 gate (online, profit profile)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# Attach evidence after commit
python scripts/attach_evidence.py

# Check rolling artifacts
cat data/runs/_rolling/_latest.json

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
