# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## SESSION GOAL + DONE CRITERIA (v3.3.2)
**Goal**: Fix NO_DATA contract violation (signals_count>0 → FAIL, not NO_DATA) + multi-chain evidence refresh

### Fixes Applied (v3.3.2)
| # | Issue | Fix | Status |
|---|-------|-----|--------|
| 1 | `status=NO_DATA` + `signals_count>0` | Changed: `NO_DATA` only when `signals_count==0` | ✅ |
| 2 | All-excluded case wrong status | Added `FAIL_ALL_EXCLUDED` reason, quality_status=FAIL_QUALITY | ✅ |
| 3 | `no_data_reason=null` when NO_DATA | Fallback to `NO_SPREAD_SIGNALS` when status=NO_DATA | ✅ |
| 4 | Missing regression test | Added `TestExcludedOnlyNotNoData` test class (3 tests) | ✅ |
| 5 | Status_M5_0.md stale evidence | Updated to fresh `ci_m5_gate_20260307_11*` runDirs | ✅ |
| 6 | Test count wrong (1391) | Updated to 1402 passed, 12 skipped | ✅ |

### Multi-chain Evidence (v3.3.2 post-fix)
| Chain | RunDir | Status | signals | included | Notes |
|-------|--------|--------|---------|----------|-------|
| base | `ci_m5_gate_20260307_110131` | PASS | n/a | n/a | infra OK |
| linea | `ci_m5_gate_20260307_110206` | PASS | n/a | n/a | infra OK |
| mantle | `ci_m5_gate_20260307_111454` | PASS | 1 | 0 | `status=FAIL`, FAIL_ALL_EXCLUDED ✅ |
| zksync | `ci_m5_gate_20260307_110332` | PASS | n/a | n/a | infra OK |
| scroll | `ci_m5_gate_20260307_110346` | PASS | n/a | n/a | require_cross_dex=false |

## 0) Meta
timestamp_utc: 2026-03-07T11:15:00Z  
rolling_provenance: 2026-03-05T17:49:43Z (arbitrum_one, ci_m5_gate_20260305_184929)  
mode: ONLINE (v3.3.2: NO_DATA contract fix)

## 1) Code Changes (v3.3.2)

| File | Change |
|------|--------|
| `m4/fixtures.py` | `signals_count==0` for NO_DATA; FAIL_ALL_EXCLUDED for excluded-only case |
| `tests/unit/test_no_data_reason.py` | Added `TestExcludedOnlyNotNoData` (3 tests) |
| `docs/status/Status_M5_0.md` | Fresh evidence runDirs, test count 1402, v3.3.1 note |

## 2) Commands Executed

```
py -3.11 scripts/check_repo_safety.py: PASS (3 DEV_REPORT warnings - expected)
py -3.11 -m pytest -q: 1402 passed, 12 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_base.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_linea.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_mantle.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_zksync.yaml --cycles 1: PASS
py -3.11 scripts/ci_m5_0_gate.py --online --config config/coverage_intent_scroll.yaml --cycles 1: PASS
```

## 3) Evidence Artifacts

**Multi-chain coverage** (v3.3.2 post-fix):
- `ci_m5_gate_20260307_110131` (Base) - infra PASS
- `ci_m5_gate_20260307_110206` (Linea) - infra PASS
- `ci_m5_gate_20260307_111454` (Mantle) - infra PASS, run_summary.status=FAIL (FAIL_ALL_EXCLUDED)
- `ci_m5_gate_20260307_110332` (zkSync) - infra PASS
- `ci_m5_gate_20260307_110346` (Scroll) - infra PASS

**Rolling canonical** (unchanged - arbitrum_one):
- `data/runs/_rolling/run_summary_latest.json` (2026-03-05T17:49:43Z)

**Golden artifacts**:
- `docs/artifacts/scroll_dex_audit.json` — Scroll DEX audit (BLOCKED_BY_SECOND_DEX)

## 4) Status Contract Verification

Mantle run `ci_m5_gate_20260307_111454` confirms fix:
```json
{
  "signals_count": 1,
  "included_signals_count": 0,
  "excluded_signals_count": 1,
  "status": "FAIL",           // ← NOT NO_DATA (v3.3.2 fix)
  "quality_status": "FAIL_QUALITY",
  "quality_reasons": ["WARN_EXCLUDED_SIGNALS", "WARN_CRITICAL_REJECTS", "FAIL_ALL_EXCLUDED"]
}
```

---
*Generated: 2026-03-07T11:15:00Z*
