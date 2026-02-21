# ARBY3 Docs Index

> Primary provenance: `run_timestamp` (see `docs/status/INDEX.md`).
> For documentation policy see `docs/DOCS_POLICY.md`.

## What lives in /docs
This folder is the "human layer" of the repo:
- **Status**: progress + contracts + evidence per milestone (see `docs/status/`).
- **Workflow**: how we develop, review, and accept changes (`docs/WORKFLOW.md`).
- **Testing**: how to run tests and generate artifacts (`docs/TESTING.md`).
- **Issue checklists** / file maps: tracking scope for targeted fixes (Issue #3, etc.).

## Status policy (important)
- Keep **one** active status file per milestone/subphase.
- Historical variants live outside `docs/` in `archive/` (see `docs/status/ARCHIVE_MAP.md`).
- Every status should reference:
  - Evidence provenance (rolling `run_timestamp` + evidence `runDir`)
  - Proof commands used (pytest + relevant gates)
  - Optional: repo revision (branch/commit) for reproducibility only (**NOT** evidence)

## Artifacts policy (golden fixtures)
We store **golden fixtures** only when they are needed for reproducible testing or schema verification.
- Prefer committing **small, stable** JSON artifacts under `docs/artifacts/...` when they are used by tests or by CI verification scripts.
- Do **not** commit full run directories (`data/runs/...`) unless explicitly designated as golden fixtures.

See `docs/TESTING.md` and `docs/WORKFLOW.md` for exact rules.
