# Technical Debt Tracker

> **Policy**: Track non-blocking technical debt for future cleanup.
> Items here don't block CI/CD but should be addressed proactively.

## Active Items

### TD-001: websockets.legacy Deprecation Warning
**Added**: 2026-02-23
**Priority**: LOW
**Category**: Dependencies

**Description**:
`websockets.legacy` is deprecated in websockets v14.0. Test runs show warning:
```
websockets.legacy is deprecated; see https://websockets.readthedocs.io/en/stable/howto/upgrade.html
```

**Impact**: None currently (tests pass), but may break in future websockets versions.

**Resolution Options**:
1. Pin websockets < 14.0 in requirements.txt
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
