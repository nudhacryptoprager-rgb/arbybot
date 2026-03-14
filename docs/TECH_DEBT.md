# Technical Debt Tracker

> **Policy**: Track non-blocking technical debt for future cleanup.
> Items here don't block CI/CD but should be addressed proactively.

## Active Items

### TD-002: God-File Splitting (R28.1)
**Added**: 2026-03-14
**Priority**: MEDIUM
**Category**: Architecture

**Description**:
Several files remain oversized (god-files) and need meaningful extraction:

| File | Lines | Extraction Candidates |
|------|-------|----------------------|
| `scripts/ci_m5_0_gate.py` | ~1887 | Validation helpers, artifact builders, report formatters |
| `scripts/check_repo_safety.py` | ~1596 | Individual check functions to dedicated modules |
| `strategy/quotes.py` | ~1722 | Slot0 logic (diagnostic), QuoterV2 logic, price math to core/math.py |
| `strategy/jobs/run_scan_real.py` | ~1346 | Summary builders, universe handlers |

**R28 Progress**: Extracted `core/gate_helpers.py` (discover_artifacts, get_run_dir_candidates, validate_schema_version) and `core/repo_checks.py` (docs policy constants). But total god-file reduction was cosmetic — files still large.

**Impact**: Code comprehension, testing isolation, maintainability.

**Next Steps**:
1. Extract `calculate_price_from_sqrt` and relacionado math to `core/math.py`
2. Extract `read_slot0_v3` + cache functions to `strategy/slot0.py` (diagnostic-only path)
3. Split check_repo_safety into per-check modules under `scripts/checks/`
4. Extract summary builders from run_scan_real.py to dedicated module

**Tracking**: R28.1 acknowledges debt honestly; extraction ongoing.

---

### TD-001: websockets.legacy Deprecation Warning
**Added**: 2026-02-23
**Priority**: LOW
**Category**: Dependencies

**Description**:
`websockets.legacy` is deprecated in websockets major version 14. Test runs show warning:
```
websockets.legacy is deprecated; see https://websockets.readthedocs.io/en/stable/howto/upgrade.html
```

**Impact**: None currently (tests pass), but may break in future websockets versions.

**Resolution Options**:
1. Pin websockets to version below 14 in requirements.txt
2. Upgrade websockets usage to non-legacy API
3. Suppress warning temporarily

**Tracking**: pytest shows 1 warning, non-blocking.

---

## Resolved Items

(None yet)

---

## Guidelines

- Add items when they appear in CI output but don't block
- Include reproduction steps and resolution options
- Move to Resolved when fixed with date and PR reference
