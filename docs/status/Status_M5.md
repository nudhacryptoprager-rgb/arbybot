# Status: M5 (Production Small)

**Status**: ✅ **DONE** (feature-complete)  
**Updated**: 2026-02-09  
**Gate Version**: `ci_m5_gate.py` v1.0.0 (when created)  
**Tests**: 549 passed

---

## ⚠️ Core Truth Statement

> **M5 не блокує M4-profit.**  
> M5 — це reporting/monitoring поверх working execution truth.  
> M4 execution gate є "core truth" для релізу.

**Пріоритет:** Не шліфувати M5, поки M4 online-profit не стабільний.

---

## Canonical Commands

```bash
# M5 Online Gate (requires runDir with scan/truth/histogram)
python scripts/ci_m5_gate.py --online --config config/real_minimal.yaml

# M5 with existing runDir
python scripts/ci_m5_gate.py --generate-report data/runs/<rundir>

# Full CI Pipeline (M5 is SKIPPED in offline mode)
python scripts/ci_full_pipeline.py --mode ci   # M5: SKIPPED
python scripts/ci_full_pipeline.py --mode e2e  # M5: RUN
```

### ⚠️ M5 Offline Behavior

M5 gate validates `daily_report` which **requires a complete runDir** with
scan/truth/histogram artifacts. In CI mode (`--mode ci`), M5 is **SKIPPED**:

```
M5 gate: SKIPPED (CI mode - daily_report requires runDir)
```

This is **expected** because:
1. `daily_report` is an aggregation layer on top of M5_0 artifacts
2. M5_0 offline gate validates the underlying artifacts
3. M5 online is verified via `--mode e2e`

---

## DoD Summary

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Daily report with net PnL, win-rate, tail losses | ✅ | `daily_report_*.json` |
| Auto-size adjustment (impact-based) | ✅ | `autosize` object present |
| Health score for RPC/DEX/System | ✅ | `health` section in reports |
| Golden artifacts | ✅ | `docs/artifacts/m5_golden/` |

---

## Golden Update Policy

⚠️ **Golden artifacts are updated ONLY via explicit script:**

```bash
# ONLY way to update golden (M5 daily_report)
python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage m5

# Or use legacy script
python scripts/make_golden_daily_report.py --output docs/artifacts/m5_golden/

# Gates NEVER auto-update golden
```

---

## Artifacts Produced

| Artifact | Purpose |
|----------|---------|
| `scan_*.json` | Raw scan results |
| `truth_report_*.json` | Validated truth |
| `reject_histogram_*.json` | Reject reasons distribution |
| `daily_report_*.json` | Daily summary (M5) |

---

## Cross-Artifact Invariants

All gates validate using `core/artifact_invariants.py`:

| Invariant | Description |
|-----------|-------------|
| `current_block` | Same in scan, truth, histogram |
| `chain_id` | Same in all artifacts |
| `run_mode` | Consistent across artifacts |
| `quotes_total` | Matches between scan and truth |
| `schema_version` | Supported version |

---

## M5 vs M5_0 Relationship

| Aspect | M5_0 | M5 |
|--------|------|-----|
| Focus | Infrastructure hardening | Production features |
| Key artifact | truth_report | daily_report |
| Gate | `ci_m5_0_gate.py` | `ci_m5_gate.py` |
| Status | ✅ DONE | ✅ DONE |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL validation |
| 2 | FAIL missing artifacts |
| 3 | FAIL scanner error |

---

## Critical Invariants

```
1. execution_enabled = false ALWAYS in M5
   blocker: "EXECUTION_DISABLED_M5_0"

2. opportunities == net-positive paper signals (is_net_positive_est=true)
   NOT "ready to execute" — merely paper estimates

3. PRICE_SCALE_BOUNDS validated for all pairs

4. No fake quotes (pool_address=null rejected)

5. Tenderly is OPTIONAL (never blocks)
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/ci_m5_gate.py` | M5 acceptance gate |
| `scripts/make_golden_daily_report.py` | Golden update script |
| `core/artifact_invariants.py` | Cross-artifact validation |
| `docs/artifacts/m5_golden/` | Golden reference artifacts |
