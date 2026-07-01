# CURSOR.md - Legacy Cursor Executor Contract

> Scope: legacy compatibility only. Cursor is no longer the active
> developer-agent executor for ARBY3 / arbybot.

The active executor contract is now `OPENCODE.md`.

If Cursor is opened accidentally:
- do not act as the primary autonomous executor;
- do not use `.cursor/rules/*.mdc` to override `OPENCODE.md`;
- keep work read-only unless the user gives an explicit Cursor-specific task;
- use `AGENTS.md` only for source-of-truth, artifact, safety, and documentation
  constraints, not for the Codex/team-lead role or final-response format.

Historical Cursor migration material has been isolated under `archive/docs/`.
