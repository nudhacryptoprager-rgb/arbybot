# Documentation Policy

This document defines the **canonical rules** for documentation in the ARBY3/arbybot repository.

## 1. Version Strings

**Rule**: Version strings (`vX.Y.Z`) are allowed **ONLY** in:
- `docs/DEV_REPORT_LATEST.md` (the single canonical DEV REPORT)

**Forbidden in**:
- `docs/status/Status_*.md` (use evidence runDir/run_timestamp instead)
- `docs/status/INDEX.md` (must be timeless)
- `docs/WORKFLOW.md`, `docs/TESTING.md`, `docs/REPORT_TEMPLATE.md`
- Any other `docs/**/*.md`

**Exception - API Contract Docs**:
- `docs/m4/ROLLING_CONTRACT.md` and `docs/m4/M4_POLICY.md` may contain schema version identifiers (e.g., `m4:latest:v2.0`) as they define API contracts
- Use placeholder timestamps (e.g., `<ISO8601>` or `2026-XX-XXTXX:XX:XXZ`) in examples

**Exception**: Script `__version__` references are allowed when documenting script behavior, but only as `script.py __version__` (not milestone versions).

## 2. Timestamps

**Rule**: ISO-8601 timestamps (`YYYY-MM-DDTHH:MM:SS`) are allowed **ONLY** in:
- `docs/status/Status_*.md` (evidence provenance from rolling artifacts)
- `docs/DEV_REPORT_LATEST.md` (single report with rolling provenance)

**Forbidden in**:
- `docs/status/INDEX.md` (must be timeless index)
- `docs/WORKFLOW.md`, `docs/TESTING.md`, `docs/REPORT_TEMPLATE.md`
- Any "Last updated:" patterns outside Status files

**Exception - API Contract Docs**:
- `docs/m4/*.md` may use placeholder timestamps in JSON examples (e.g., `<ISO8601>` or `2026-XX-XXTXX:XX:XXZ`)

## 3. Archive Policy

**Rule**: Archived/historical status files must live **OUTSIDE** `docs/`:
- Use `archive/status/**` for old milestones
- `docs/status/ARCHIVE_MAP.md` provides redirect links to git history
- Active `docs/` contains only **current** documentation

**Forbidden in `docs/`**:
- Historical status files with SHA-era provenance
- Calibration reports with dates in filenames
- Any `_legacy.md` or `_root.md` files

## 4. Active Status Files

Active `docs/status/Status_*.md` files contain:
- **Snapshot timestamp** (from rolling `run_context.run_timestamp`)
- **Evidence runDir** (from rolling artifacts)
- **Metrics** (copied from rolling JSON)

**Do NOT include**:
- "Gate Version", "Contract Version", "Script Version" fields
- Multiple `vX.Y.Z` version references
- "_Last updated:" timestamps

## 5. Canonical DEV REPORT

- **ONLY** `docs/DEV_REPORT_LATEST.md` is tracked (overwritten each session)
- Format defined in `docs/DEV_REPORT_CANONICAL_UA.md`
- Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files are **forbidden**
- Contains version and timestamp from rolling artifacts

## 6. Enforcement

`scripts/check_repo_safety.py` enforces:
- No version strings in forbidden docs (regex: `\bv\d+\.\d+\.\d+\b`)
- No timestamps in forbidden docs (regex: ISO-8601 pattern)
- No "Last updated:" outside Status files
- DEV_REPORT bloat check (only LATEST.md allowed)

## 7. Index Files

`docs/status/INDEX.md` must be **timeless**:
- Links to current Status files
- Links to Roadmap.md and DEV_REPORT_LATEST.md
- **NO** dates, versions, or "_Last updated:" patterns

## 8. How to Update

1. Run online scan: generates rolling artifacts
2. Update `docs/status/Status_*.md` with evidence from `run_summary_latest.json`
3. Update `docs/DEV_REPORT_LATEST.md` per `docs/DEV_REPORT_CANONICAL_UA.md`
4. Run `py -3.11 scripts/check_repo_safety.py` before commit
5. Run `py -3.11 scripts/ci_full_pipeline.py --mode ci` to verify gates

## See Also

- [DEV_REPORT_CANONICAL_UA.md](DEV_REPORT_CANONICAL_UA.md) - Report format
- [status/INDEX.md](status/INDEX.md) - Status file index
- [Roadmap.md](../Roadmap.md) - Milestone roadmap
