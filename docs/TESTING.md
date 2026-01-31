# ARBY Testing Guide

## M5_0 CI Gate

The M5_0 CI Gate validates infrastructure hardening contracts.

### Two Modes (Mutually Exclusive)

#### 1. Offline Mode (Always Works)

Creates fixture artifacts in `data/runs/`. Use for:
- CI pipelines without RPC access
- Quick validation of gate logic
- Development without network

```powershell
# Basic offline
python scripts/ci_m5_0_gate.py --offline

# Custom output root
python scripts/ci_m5_0_gate.py --offline --output-root data/ci_runs
```

**Behavior**:
- Ignores `ARBY_RUN_DIR` and `ARBY_REQUIRE_REAL` ENV variables
- Creates `data/runs/ci_m5_0_gate_offline_<timestamp>/`
- Generates valid fixture artifacts
- Always exits 0 (PASS) unless internal error

#### 2. Online Mode (Runs Real Scan)

Runs real scan and validates results. Use for:
- Full integration testing
- Pre-deployment validation
- Infrastructure regression testing

```powershell
# Basic online (uses config/real_minimal.yaml)
python scripts/ci_m5_0_gate.py --online

# With golden config (more coverage)
python scripts/ci_m5_0_gate.py --online --config config/real_m5_0_golden.yaml

# Multiple cycles
python scripts/ci_m5_0_gate.py --online --cycles 3 --config config/real_m5_0_golden.yaml
```

**Behavior**:
- Ignores `ARBY_RUN_DIR` (creates its own)
- Creates `data/runs/ci_m5_0_gate_<timestamp>/`
- Runs `python -m strategy.jobs.run_scan_real`
- Validates real artifacts (rejects fixtures)

### Legacy Mode (Deprecated)

For backward compatibility, you can still use `--run-dir`:

```powershell
# Explicit run directory
python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260131_120000

# With ENV
$env:ARBY_RUN_DIR = "data\runs\real_20260131_120000"
python scripts/ci_m5_0_gate.py
```

**Note**: Prefer `--offline` or `--online` for new workflows.

### Utility Commands

```powershell
# List available run directories
python scripts/ci_m5_0_gate.py --list-candidates

# Version
python scripts/ci_m5_0_gate.py --version
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL (validation) |
| 2 | FAIL (artifacts missing) |
| 3 | FAIL (mode error) |

---

## Unit Tests

```powershell
# All unit tests
python -m pytest tests/unit -q

# Specific test file
python -m pytest tests/unit/test_ci_m5_0_gate.py -v

# Import smoke tests
python -m pytest tests/unit/test_imports_contract.py -v

# Price sanity tests
python -m pytest tests/unit/test_price_sanity_inversion.py -v
```

---

## Integration Tests

```powershell
# Smoke run tests
python -m pytest tests/integration/test_smoke_run.py -v

# Full integration suite
python -m pytest tests/integration -v
```

---

## Full Regression

```powershell
# 1. Unit tests
python -m pytest tests/unit -q

# 2. Offline gate (always works)
python scripts/ci_m5_0_gate.py --offline

# 3. Online gate (requires RPC)
python scripts/ci_m5_0_gate.py --online --config config/real_m5_0_golden.yaml

# 4. Verify artifacts
dir data\runs\ci_m5_0_gate_*
```

---

## Artifact Locations

| Mode | Location |
|------|----------|
| `--offline` | `data/runs/ci_m5_0_gate_offline_<timestamp>/` |
| `--online` | `data/runs/ci_m5_0_gate_<timestamp>/` |
| Manual run | `data/runs/real_<timestamp>/` |

Each contains:
```
<run_dir>/
└── reports/
    ├── scan_<timestamp>.json
    ├── truth_report_<timestamp>.json
    └── reject_histogram_<timestamp>.json
```

---

## Environment Variables (Legacy)

These are used in legacy mode only. `--offline` and `--online` ignore them.

| Variable | Description |
|----------|-------------|
| `ARBY_RUN_DIR` | Explicit run directory path |
| `ARBY_REQUIRE_REAL` | Set to `1` to reject fixtures |
| `ARBY_GATE_MODE` | (Deprecated, use CLI instead) |
