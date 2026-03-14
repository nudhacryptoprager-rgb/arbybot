# Status: M5 (Production Small)

**Status**: ✅ **DONE** (feature-complete), ⏳ **BLOCKED** by M4 online  
**Updated**: 2026-02-09  
**Tests**: 553 passed

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

## M5 vs M5_0 vs M4 Relationship

| Aspect | M5_0 | M5 | M4 |
|--------|------|-----|-----|
| Focus | Infrastructure | Reporting | Execution |
| Key artifact | truth_report | daily_report | execution_report |
| Gate | `ci_m5_0_gate.py` | `ci_m5_gate.py` | `ci_m4_execution_gate.py` |
| Schema family | semver (3.2.0) | semver (3.2.0) | namespace (m4:*:v1.1) |
| Blocks Release? | ✅ YES | ❌ NO | ✅ YES (core truth) |
| Status | ✅ DONE | ✅ DONE | ⏳ ONLINE NOT PROVEN |

---

## Schema Versions

| Artifact | Schema | Family |
|----------|--------|--------|
| scan | `3.2.0` | M5 semver |
| truth_report | `3.2.0` | M5 semver |
| reject_histogram | `3.2.0` | M5 semver |
| daily_report | `3.2.0` | M5 semver |

**Cross-family compatibility:**
- M4 artifacts use namespace pattern: `m4:execution:v1.1`, `m4:signals:v1.1`
- M5 artifacts use semver pattern: `3.2.0`
- Gates validate within their family, not across families

---

## DEX/Chain Expansion Matrix

Multi-chain readiness tracking. This matrix shows which DEX/chain combinations
are validated and which are next for expansion.

| Chain | DEX | Adapter | Status | Evidence |
|-------|-----|---------|--------|----------|
| arbitrum_one | uniswap_v3 | uniswap_v3 | ✅ LIVE | rolling N=26+ |
| arbitrum_one | sushiswap_v3 | uniswap_v3 | ✅ LIVE | rolling N=26+ |
| arbitrum_one | camelot_v3 | algebra | ⚠️ NEEDS_QUOTER | ALGEBRA_NEEDS_QUOTER |
| linea | lynex_v3 | algebra | 🔜 NEXT | config/onboard_linea_stage1.yaml ready |
| mantle | agni_v3 | uniswap_v3 | 📋 PLANNED | factory/quoter in dexes.yaml |
| base | uniswap_v3 | uniswap_v3 | 📋 PLANNED | chain in chains.yaml |

**Multi-chain Guardrails:**
- `chain_key` in all artifacts (strict fallback to `"unknown"`)
- `MIXED_CHAIN_KEYS` quality_warning when rolling window has multiple chains
- `config_fingerprint` to detect config drift across runs

**NORM-only Rolling Policy:**
- Rolling artifacts ONLY updated by `run_kind=NORMAL` runs
- SMOKE and COVERAGE runs excluded from `emit_to_aggregator_light()`
- `ci_m5_0_gate.py` detects `run_kind != NORMAL` in config, sets `refresh_rolling=False`
- Purpose: Prevent experimental/smoke/coverage runs from polluting production metrics
- Test evidence: `tests/unit/test_smoke_run_isolation.py` (10 tests)

**Rolling Window Contract:**
- Window is **N-run based** (max 200 runs), NOT time-based
- Old runs are displaced only when `runs_in_window > max_runs=200`
- Historical runs with different chain_key stay in window until displaced
- To force clean state: use `reset_rolling_window()` or wait for 200 new NORMAL runs

**run_kind Values:**
| Value | Purpose | Updates Rolling? |
|-------|---------|------------------|
| NORMAL | Production scanning | ✅ YES |
| SMOKE | Connectivity checks | ❌ NO |
| COVERAGE | Pair discovery | ❌ NO |

**Next Control Runs:**
1. `py -3.11 -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml --cycles 1` (arb)
2. `py -3.11 -m strategy.jobs.run_scan --mode real --config config/onboard_linea_stage1.yaml --cycles 1` (linea)

**Evidence Required:**
- Both runs produce artifacts with correct `chain_key`
- `inspect_run_dir.py` shows distinct chain_keys
- Rolling aggregator shows `MIXED_CHAIN_KEYS` if both added to window

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

---

## Risks

**Evidence (ci_m5_gate_20260224_141638 - capstone)**:
- `daily_report_*.json` generated with `schema_version=3.2.0`
- `health` section present, `autosize` enabled
- cross-artifact invariants validated

**Blockers**:
- M5 is blocked by M4 online proof (M5 is reporting layer, not judgment)

---

## Next Steps

**Current Stage**: DONE (feature-complete), BLOCKED by M4 online

**Next Steps**:
1. Wait for M4.2 roundtrip profit to unblock
2. Add optional alerting (Telegram/Slack) when profitable roundtrip observed
3. Add optional dashboard via simple metrics endpoint
