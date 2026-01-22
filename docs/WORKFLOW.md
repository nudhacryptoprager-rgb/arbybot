# ARBY3 Workflow (ChatGPT ↔ Claude ↔ VSCode ↔ GitHub)

_Last cleaned: 2026-01-21_

## Rules (hard)
- Work via GitHub SHA + latest Status as source of truth.
- Small PRs (1–2 commits). Every PR must have:
  - updated Status file
  - `python -m pytest -q` green
  - smoke run artifact evidence (as text link or designated golden fixtures)
- Do not commit runtime run directories (`data/runs/...`) unless explicitly marked as **golden** and placed under `docs/artifacts/...`.

## Review loop
1) Developer pushes branch + Status update.
2) Run tests + smoke and attach evidence.
3) Reviewer provides max **10 critical issues + 10 fix steps**.
4) Repeat until green and contracts stable.

## Artifact handling
- If an artifact is required for reproducibility, move/copy it into `docs/artifacts/<scope>/<date>/...` and commit.
- Otherwise keep it local (do not pollute git history).
