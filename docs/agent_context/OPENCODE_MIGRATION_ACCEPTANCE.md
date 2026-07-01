# OpenCode Migration Acceptance

This checklist validates that ARBY3 uses OpenCode as the economical developer
agent while keeping Codex as planner/reviewer and Opus/Fable as independent
auditors.

## External Baseline

- `opencode.json` selects the active executor model.
- `OPENCODE.md` is the human-readable executor contract.
- `AGENTS.md` is scoped to Codex/team-lead reviewer work.
- `docs/agent_context/AUDITOR_CONTRACT.md` governs independent auditors.
- Cursor files are legacy compatibility only and must not be treated as active
  executor authority.

## Repository Files Required

- `opencode.json`
- `OPENCODE.md`
- `AGENTS.md`
- `docs/agent_context/ARBY3_CURRENT_CONTEXT.md`
- `docs/agent_context/AUDITOR_CONTRACT.md`
- `docs/agent_context/OPENCODE_MIGRATION_ACCEPTANCE.md`

## Acceptance Gate

1. `OPENCODE.md` defines the active executor contract.
2. `CURSOR.md` is explicitly marked legacy.
3. Active docs do not describe Cursor, Claude, or GitHub Copilot as the current
   executor.
4. OpenCode tasks are bounded and evidence-driven.
5. Runtime, logs, virtual environments, and secrets are excluded from OpenCode
   watcher context through `opencode.json`.
6. OpenCode does not update Status or DEV_REPORT before same-session
   verification evidence exists.
7. Opus/Fable auditors are read-only and cannot execute patches or close
   milestones.
8. Targeted tests run before broad tests.
9. A repeated failure stops after two fix attempts and returns to Codex review.
10. `py -3.11 scripts/check_repo_safety.py` passes before commit.

## Pilot Run

Use one small docs-only or test-only patch to validate the migration:

```powershell
git status --short --untracked-files=all
py -3.11 scripts/check_repo_safety.py
py -3.11 scripts/ci_docs_consistency.py
```

Confirm that OpenCode:
- uses `OPENCODE.md`;
- does not read `.env`, `.venv`, `data/runs`, `data/snapshots`, or logs;
- asks before expanding beyond the named files unless the user explicitly
  requested a repo-wide migration;
- reports targeted verification first;
- does not select a premium model without user approval.
