# Cursor Executor Acceptance

This checklist confirms the active ARBY3 workflow: GPT/Codex is the planner and
reviewer; Cursor is the bounded developer-agent executor.

## Required files

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

## Acceptance gate

1. `AGENTS.md` remains the GPT/Codex reviewer contract.
2. `CURSOR.md` is the active human-readable executor contract.
3. `.cursor/rules/*.mdc` are the active automatic Cursor rules.
4. Active docs name Cursor, not OpenCode, as the developer executor.
5. Cursor tasks are limited to 3 to 7 target files with a measurable goal.
6. Secrets, virtual environments, logs, and runtime artifacts are excluded
   from Cursor context and commits.
7. Targeted tests run before broader tests.
8. After two failed attempts on one gate, Cursor returns the blocker to GPT/Codex.
9. Premium model use requires user approval.
10. `py -3.11 scripts/check_repo_safety.py` passes before a commit.

## Pilot verification

```powershell
git status --short --untracked-files=all
py -3.11 scripts/check_repo_safety.py
```
