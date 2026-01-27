# ARBY3 Workflow (ChatGPT ↔ Claude ↔ VSCode ↔ GitHub)

_Last updated: 2026-01-27_

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

- Work via GitHub SHA + latest Status as source of truth
- Small PRs (1-2 commits). Every PR must have:
  - Updated Status file
  - `python -m pytest -q` green
  - `python scripts/ci_m4_gate.py --offline` green with 4/4 artifacts
  - No emojis in subprocess output (ASCII only)
- Do not commit runtime run directories (`data/runs/...`) unless explicitly marked as **golden**

## Review Loop

1. Developer pushes branch + Status update
2. Run tests + gates and attach evidence
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
