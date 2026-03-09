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

## 8. Workflow Contract (MANDATORY)

**Rule**: Documentation updates MUST follow this strict order:

```
1. code/config/tests  →  2. verification runs  →  3. docs/artifacts
```

**Rationale**: Documentation must reflect verified evidence. Updating docs before verification runs creates stale/invalid evidence.

**Steps**:
1. **Code Phase**: Make all code, config, and test changes
2. **Verification Phase**: Run ALL verification commands:
   - `py -3.11 scripts/check_repo_safety.py`
   - `py -3.11 -m pytest tests/unit -q`
   - `py -3.11 scripts/ci_full_pipeline.py --mode ci`
   - Online coverage runs for affected chains
3. **Docs Phase**: Update docs using ONLY runDirs/evidence from step 2

**Forbidden**:
- Updating `Status_*.md` or `DEV_REPORT_LATEST.md` before verification runs complete
- Using runDirs from previous sessions as "fresh evidence"
- Mixing evidence from different verification sessions

## 9. Session Completion Gate (MANDATORY)

**Rule**: A session cannot be closed based solely on green CI/offline gates. Session closure requires:

1. **REACHED**: Session goal achieved with fresh same-session online evidence, OR
2. **BLOCKED**: Explicit blocker recorded with root cause and unblock criteria

**Session States**:
- `OPEN`: Session in progress, goal not yet reached
- `BLOCKED`: Session paused due to explicit blocker (recorded in docs)
- `CLOSED`: Session goal reached with valid evidence

**Closure Criteria**:
- `goal_status=REACHED` requires:
  - Fresh online runDirs from current session (not previous sessions)
  - All fix claims validated by actual artifacts (not just CI)
  - Evidence timestamps within current working session
- `goal_status=BLOCKED` requires:
  - Explicit blocker description
  - Unblock criteria documented
  - No completion language in docs

**Forbidden**:
- Declaring session "complete" when `goal_status != REACHED`
- Using offline CI as sole evidence for session completion
- Closing session without `goal_status` field in DEV_REPORT
- Using completion language ("All steps completed", "Session done") without REACHED status

**Enforcement**: `scripts/check_repo_safety.py` validates that DEV_REPORT_LATEST.md contains `goal_status` field when session completion language is detected.

## 10. How to Update

1. Run online scan: generates rolling artifacts
2. Update `docs/status/Status_*.md` with evidence from `run_summary_latest.json`
3. Update `docs/DEV_REPORT_LATEST.md` per `docs/DEV_REPORT_CANONICAL_UA.md`
4. Run `py -3.11 scripts/check_repo_safety.py` before commit
5. Run `py -3.11 scripts/ci_full_pipeline.py --mode ci` to verify gates

## See Also

- [DEV_REPORT_CANONICAL_UA.md](DEV_REPORT_CANONICAL_UA.md) - Report format
- [status/INDEX.md](status/INDEX.md) - Status file index
- [Roadmap.md](../Roadmap.md) - Milestone roadmap
