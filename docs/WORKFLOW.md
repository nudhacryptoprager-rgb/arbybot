# ARBY3 Workflow (ChatGPT ↔ Claude ↔ VSCode ↔ GitHub)

_Last updated: 2026-02-13 (v2.x SHA-free)_

> **v2.0+ Provenance**: SHA tracking removed. Evidence based on `run_timestamp` + rolling artifacts.
> See `docs/DEV_REPORT_CANONICAL_UA.md` for canonical report format.
> See `docs/status/Status_M4.md` for current milestone status.

## Setup (STEP 1+2)

```powershell
# Clone and setup
git clone https://github.com/nudhacryptoprager-rgb/arbybot
cd arbybot
git checkout split/code

# Create venv (MUST use .venv, Python 3.11)
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1

# Install
pip install -e ".[dev]"

# Verify
python --version  # Must be 3.11.x
python -c "from monitoring import calculate_confidence; print('import ok')"
```

## Rules (hard)

- Work via rolling artifacts + latest Status as source of truth (v2.x: no SHA binding)
- Small PRs (1-2 commits). Every PR must have:
  - Updated Status file (with Updated timestamp, run_id)
  - `python -m pytest -q` green
  - `python scripts/ci_m4_execution_gate.py --offline --profile profit` green
  - No emojis in subprocess output (ASCII only)
- Do not commit runtime run directories (`data/runs/...`) unless explicitly marked as **golden**

## Review Loop

1. Developer pushes branch + Status update
2. Run tests + gates; evidence = `run_timestamp` + rolling artifacts (`_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`) + runDir bundle
3. Reviewer provides max **10 critical issues + 10 fix steps**
4. Repeat until green and contracts stable

## Artifact Handling

- If an artifact is required for reproducibility, move/copy it into `docs/artifacts/<scope>/<date>/...` and commit
- Otherwise keep it local (do not pollute git history)

## Python Version Enforcement

- `.python-version` file pins 3.11.9
- `pyproject.toml` enforces `>=3.11,<3.12`
- CI gate checks Python version
- Never use Python 3.12+ or 3.10-

### Canonical Commands (Windows)

**IMPORTANT**: Always use `py -3.11` on Windows to ensure correct Python version:

```powershell
# Tests
py -3.11 -m pytest -q

# Full CI pipeline
py -3.11 scripts/ci_full_pipeline.py --mode ci

# M4 gates
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict --artifact-mode rolling
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# M5 gate (online scan)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

# Retention (preview then execute)
py -3.11 scripts/prune_run_dirs.py --keep 50 --dry-run
py -3.11 scripts/prune_run_dirs.py --keep 50 --yes
```

If using activated venv, `python` is sufficient but verify version first:
```powershell
python --version  # MUST be 3.11.x
```

---

## Artifacts Policy

### Rule #1: Runtime artifacts are NEVER committed

The following files stay local or in CI artifacts only:

| Pattern | Location | Purpose |
|---------|----------|---------|
| `data/runs/**` | Local | All run outputs |
| `**/run_summary_*.json` | Local | Per-run summaries |
| `**/stability_summary_*.json` | Local | Stability reports |
| `**/execution_report_*.json` | Local | Simulation results |
| `**/m4_stability_agg*.json` | Local | Rolling aggregator |
| `**/_latest.json` | Local | Latest pointer |
| `**/online_runs_report_*.md` | Local | Analysis reports |

### Rule #2: Only golden fixtures in git

Golden fixtures live under `docs/artifacts/golden/` only:
- Maximum 1-3 examples per schema family
- Versioned (e.g., `run_summary_v1.4_golden.json`)
- Used in tests for schema validation
- Rarely updated (only on schema changes)

### Rule #3: Continuous scan storage

For continuous/rolling operations:
- `data/runs/_rolling/m4_stability_agg.json` — overwritten on each emit
- `data/runs/_rolling/_latest.json` — overwritten pointer
- No dated copies of latest/agg in runtime

### Rule #4: Retention policy

- **NEVER manually delete** `data/runs/ci_*` directories — use `prune_run_dirs.py` only
- Keep only last N=50 run directories in `data/runs/`
- **Protected (never deleted)**:
  - `data/runs/_rolling/` — canonical rolling artifacts
  - `data/runs/_incidents/` — incident records
  - `data/runs/_cache/` — cache data
  - `run_dir_name` referenced in `_latest.json` / `run_summary_latest.json`
- Older runs: auto-delete via script or archive to zip outside git
- CI: save runtime artifacts as GitHub Actions artifacts (7-30 day retention)
- **Usage**: `py -3.11 scripts/prune_run_dirs.py --keep 50 --dry-run` (preview), then `--yes` to execute

### Rule #5: Pre-commit guard

If `scripts/ci_no_runtime_artifacts.py` exists, it will FAIL if:
- Any file from `data/runs/` is staged
- Any `*_summary_*.json` outside `docs/artifacts/golden/` is staged

### Allowed in git

| Path | Description |
|------|-------------|
| `docs/artifacts/golden/**` | Golden fixtures for tests |
| `docs/artifacts/calibration_report_*.md` | One-time calibration docs |
| Schema examples (`*_schema.json`) | Documentation only |

### NOT allowed in git

| Path | Why |
|------|-----|
| `data/runs/**` | Runtime outputs |
| `docs/artifacts/*.json` (non-golden) | Bloats repo |
| `docs/artifacts/online_runs_report_*.md` | Ephemeral analysis |
| Any `_latest.json` | Changes every run |

---
