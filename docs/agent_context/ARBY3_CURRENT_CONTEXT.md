# ARBY3 Current Agent Context

This file is a compact context handoff for executor agents. It is not runtime
evidence and must not replace `Roadmap.md`, active `docs/status/Status_*.md`
files, or rolling artifacts.

## Operating Model

- GPT/team lead owns planning, review, priority, and acceptance decisions.
- Cursor is an executor for small, explicit patch tasks.
- Each Cursor task should name 3 to 7 files and one measurable goal.
- After 15 to 20 Cursor messages on one task, start a fresh Cursor chat.
- Use cheaper/default models for simple patches. Reserve premium models for hard
  debugging only after user approval.

## Source Of Truth

1. `Roadmap.md`
2. Active milestone status files under `docs/status/`
3. Runtime artifacts supplied by the user or GPT reviewer

Runtime provenance is based on `run_timestamp`, not git SHA. Git branch and
commit are only for reproducibility.

## Current Work Reading

- This section must be refreshed whenever the active development focus changes.
- The current task brief from GPT/user is the immediate executor scope.
- Active milestone details must be read from `docs/status/INDEX.md` and the
  relevant `docs/status/Status_*.md`.
- Execution remains disabled unless the user gives an explicit separate unlock
  instruction after evidence review.

## Cursor Boundaries

- Do not read or edit secrets, `.env`, runtime artifacts, logs, or virtual envs.
- Do not manually edit rolling artifacts.
- Do not update Status or DEV_REPORT before verification evidence exists.
- Do not update `Roadmap.md` without explicit user approval.
- Do not broaden scope beyond the named files without asking.

## Test Discipline

- Start with targeted pytest for the touched area.
- Then run the broader requested gate.
- Use `py -3.11` on Windows.
- Stop after two failed fix attempts for the same test or gate and report the
  blocker back to GPT/team lead.

## Default Verification Commands

```powershell
py -3.11 scripts/check_repo_safety.py
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

Run online commands only when GPT/user explicitly requests them and any required
RPC preflight is satisfied.
