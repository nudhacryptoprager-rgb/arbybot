# Legacy GitHub Copilot Instructions

This repository has migrated the active developer-agent workflow to Cursor.

Do not use GitHub Copilot as the primary autonomous executor for ARBY3 work.
The active executor contract is:

- `CURSOR.md`
- `.cursor/rules/*.mdc`
- `docs/agent_context/ARBY3_CURRENT_CONTEXT.md`
- `docs/agent_context/CURSOR_MIGRATION_ACCEPTANCE.md`

If Copilot is used accidentally, keep it read-only or use it only for a small
manual suggestion. Do not let it run broad edits, select premium models, read
runtime artifacts, or bypass the Cursor workflow.
