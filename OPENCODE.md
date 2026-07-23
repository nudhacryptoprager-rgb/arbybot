# OPENCODE.md - Legacy OpenCode Compatibility Note

OpenCode is not the active ARBY3 developer-agent executor. The active workflow
is GPT/ChatGPT (Codex) as reviewer and team lead, with Cursor as the bounded
developer agent.

For an OpenCode client opened intentionally by the user:

- follow `CURSOR.md` and `.cursor/rules/*.mdc` for executor boundaries;
- treat `AGENTS.md` as the GPT/Codex reviewer contract, not an executor prompt;
- do not override Cursor, claim acceptance, or make milestone/profit claims;
- do not read secrets or edit/commit runtime artifacts.

`opencode.json` may remain for local-tool compatibility, but it does not define
the active agent workflow.
