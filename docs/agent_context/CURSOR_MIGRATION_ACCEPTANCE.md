# Cursor Migration Acceptance

This checklist validates that ARBY3 can use Cursor as the economical developer
agent while keeping GPT / Codex as planner and reviewer.

## External Baseline

- Cursor Project Rules live in `.cursor/rules` and use `.mdc` frontmatter.
- Cursor still supports `AGENTS.md` as simple markdown agent instructions, but
  this repo scopes `AGENTS.md` to Codex reviewer work.
- `CURSOR.md` is this repo's human-readable executor contract; automatic Cursor
  behavior is driven by `.cursor/rules/*.mdc`.
- `.cursorrules` is legacy; do not add it.
- `.cursorignore` limits indexing and AI code access, but it is not a security
  sandbox for terminal or MCP tool calls.
- Practical rule organization should keep always-on rules short and move
  stage-specific context into scoped or manually referenced files.

References:
- https://cursor.com/docs/rules
- https://cursor.com/docs/reference/ignore-file
- https://openbooklet.com/blog/cursor-rules-that-work

## Repository Files Required

- `.cursorignore`
- `.cursor/rules/00-source-of-truth.mdc`
- `.cursor/rules/10-executor-scope.mdc`
- `.cursor/rules/20-artifacts-and-secrets.mdc`
- `.cursor/rules/30-testing-policy.mdc`
- `.cursor/rules/40-docs-policy.mdc`
- `.cursor/rules/50-model-cost-policy.mdc`
- `.cursor/rules/60-current-work-context.mdc`
- `CURSOR.md`
- `docs/agent_context/ARBY3_CURRENT_CONTEXT.md`

## Acceptance Gate

1. `CLAUDE.md` is removed from the active repo root.
2. `CURSOR.md` contains the executor contract formerly carried by `CLAUDE.md`.
3. Active docs do not describe Claude or GitHub Copilot as the current executor.
4. Heavy model usage is user-approved only.
5. Cursor rules are split by concern and remain small enough for economical
   context loading.
6. Runtime, logs, virtual environments, and secrets are excluded from Cursor
   context by `.cursorignore`.
7. Cursor tasks are limited to 3 to 7 target files.
8. Targeted tests run before broad tests.
9. A repeated failure stops after two fix attempts and returns to GPT review.
10. `py -3.11 scripts/check_repo_safety.py` passes before commit.

## Pilot Run

Use one small docs-only or test-only patch to validate the migration:

```powershell
git status --short --untracked-files=all
py -3.11 scripts/check_repo_safety.py
```

In Cursor, confirm that the agent:
- sees `.cursor/rules/*.mdc`;
- does not read `.env`, `.venv`, `data/runs`, `data/snapshots`, or logs;
- asks before expanding beyond the named files;
- reports targeted verification first;
- does not select a premium model without user approval.
