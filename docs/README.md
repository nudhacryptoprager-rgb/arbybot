# ARBY3 Docs Index

_Last cleaned: 2026-01-21_

## What lives in /docs
This folder is the “human layer” of the repo:
- **Status**: progress + contracts + evidence per milestone (see `docs/status/`).
- **Workflow**: how we develop, review, and accept changes (`docs/WORKFLOW.md`).
- **Testing**: how to run tests and generate artifacts (`docs/TESTING.md`).
- **Issue checklists** / file maps: tracking scope for targeted fixes (Issue #3, etc.).

## Status policy (important)
- Keep **one** active status file per milestone/subphase.
- Older variants are archived (do not delete history until the clean pack is merged).
- Every status should reference:
  - HEAD SHA / branch (when applicable)
  - Evidence (artifacts path + test command used)

## Artifacts policy (golden fixtures)
We store **golden fixtures** only when they are needed for reproducible testing or schema verification.
- Prefer committing **small, stable** JSON artifacts under `docs/artifacts/...` when they are used by tests or by CI verification scripts.
- Do **not** commit full run directories (`data/runs/...`) unless explicitly designated as golden fixtures.

See `docs/TESTING.md` and `docs/WORKFLOW.md` for exact rules.
