# ARBY3 Workflow (ChatGPT <-> Claude <-> VSCode <-> GitHub)

> **Provenance**: SHA tracking removed. Evidence based on `run_timestamp` + rolling artifacts.
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
  - `py -3.11 -m pytest -q` green
  - `py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit` green
  - No emojis in subprocess output (ASCII only)
- Do not commit runtime run directories (`data/runs/...`) unless explicitly marked as **golden**

## Review Loop

1. Developer pushes branch + Status update
2. Run tests + gates; evidence = `run_timestamp` + rolling artifacts (`_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`) + runDir bundle
3. Reviewer provides max **10 critical issues + 10 fix steps**
4. Repeat until green and contracts stable

## Session Lifecycle

A **session** is a working period with a declared goal. Sessions have explicit states:

| State | Meaning | Allowed Actions |
|-------|---------|-----------------|
| `OPEN` | Session in progress, goal not yet reached | All work, no completion claims |
| `BLOCKED` | Explicit blocker prevents goal completion | Document blocker, pause work |
| `CLOSED` | Goal reached with fresh same-session evidence | Update docs with REACHED status |

### Session Completion Rules

1. **Cannot close on green CI alone**: Offline gates (pytest, ci_full_pipeline) prove code correctness but NOT session goal achievement
2. **Requires fresh online evidence**: Session goal claims require online runDirs from current session, not previous sessions
3. **REACHED requires verification**: All fix claims must map to actual artifact changes in fresh runDirs
4. **BLOCKED requires documentation**: If blocked, document the blocker and unblock criteria explicitly

### Primary Blocker Contract (MANDATORY)

Every session MUST have one `primary_blocker_of_session` - the main project blocker this session aims to resolve.

| Field | Required | Description |
|-------|----------|-------------|
| `primary_blocker_of_session` | YES | The main blocker this session addresses |
| `blocker_status_before` | YES | Status at session start (e.g., `ACTIVE`, `UNRESOLVED`) |
| `blocker_status_after` | YES | Status at session end (`RESOLVED` or `BLOCKED`) |
| `resolution_evidence` | YES if RESOLVED | Fresh runDir(s) proving blocker is resolved |
| `block_reason` | YES if BLOCKED | Why blocker cannot be resolved this session |

**Session closure requires**:
- `blocker_status_after` = `RESOLVED` with fresh evidence, OR
- `blocker_status_after` = `BLOCKED` with explicit block_reason

**Forbidden**:
- Closing session while `blocker_status_after` = `IN_PROGRESS`
- Closing on infra/reporting improvements without addressing primary blocker
- Green CI gates alone are NOT sufficient for session closure

### Session State Transitions

```
OPEN → CLOSED  : goal_status=REACHED (fresh evidence validates all claims)
OPEN → BLOCKED : explicit blocker recorded (unblock criteria documented)
BLOCKED → OPEN : blocker resolved (new evidence shows resolution)
```

### Forbidden Session Patterns

- Declaring "session complete" without `goal_status=REACHED`
- Using pre-session runDirs as "fresh evidence"
- Closing session with fixes that lack online verification
- Completion language ("All steps done") without REACHED status

## Artifact Handling

- If an artifact is required for reproducibility, move/copy it into `docs/artifacts/<scope>/<date>/...` and commit
- Otherwise keep it local (do not pollute git history)

## Universe Discovery (R28 canonical paths)

Two mutually exclusive universe sources exist. Every scan config must declare exactly one.

### Path 1: `universe_source: config` (Production Probe)
- Loads hardcoded pairs + pre-verified pool addresses from the config YAML
- Used by: `real_minimal.yaml`, `real_roundtrip_probe*.yaml`
- Canonical for Arbitrum-ONE primary scanning (pools already proven)

### Path 2: `universe_source: discovery_runtime` (Dynamic + Verify)
- Flow: `intent.txt` → `TokenRegistry` → factory RPC queries → `RuntimePair`
- Resolves pools on-chain via DEX factory contracts (`dexes.yaml`)
- Used by: all `onboard_*.yaml` configs (base, linea, mantle, scroll, zksync)
- Canonical for chain bring-up and ongoing pool discovery
- Must satisfy `require_cross_dex: true` (≥2 DEXes per pair) for spread viability

`discovery_runtime` is THE canonical successor for all non-probe universe.
Static config probe remains as the documented Arbitrum production exception.

**NOT related**: `dynamic_probe` (size sweep) is a post-baseline optimization that re-quotes
at multiple notional sizes. It is NOT a universe discovery mode.

## Python Version Enforcement

- `.python-version` file pins 3.11.9
- `pyproject.toml` enforces `>=3.11,<3.12`
- CI gate checks Python version
- Never use Python 3.12+ or 3.10-

### Version Check (mandatory before any command)

```powershell
# Quick version check (Windows)
py -0p  # Shows all installed Python versions

# Verify 3.11 is available
py -3.11 --version  # MUST output 3.11.x

# If using activated venv, verify it's 3.11
python --version  # MUST be 3.11.x
```

### Canonical Commands (Windows)

**CRITICAL**: Always use `py -3.11` prefix on Windows to ensure correct Python version.
Using wrong Python (e.g., 3.14) will cause `ci_full_pipeline.py` to FAIL with version check error.

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
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_intent_arbitrum_one.yaml --prune-keep 50

# Retention (preview then execute)
py -3.11 scripts/prune_run_dirs.py --keep 50 --dry-run
py -3.11 scripts/prune_run_dirs.py --keep 50 --yes
```

If using activated venv, `python` is sufficient but verify version first:
```powershell
python --version  # MUST be 3.11.x
```

### Profit Reality Audit (one-liner)

Quick audit to check roundtrip profit realism state:

```powershell
# Check roundtrip_summary from latest rolling artifact
py -3.11 -c "import json; d=json.load(open('data/runs/_rolling/run_summary_latest.json')); r=d.get('roundtrip_summary',{}); print(f'real_quote_count={r.get(\"real_quote_count\",0)}, profitable_count={r.get(\"profitable_count\",0)}, best={r.get(\"best_net_pnl_bps\",\"N/A\")}bps')"
```

Expected output when Truth Engine works correctly:
- `real_quote_count>0` - we're getting real callback quotes
- `profitable_count=0` + `best_net_pnl_bps<0` - no profitable arb = ROUNDTRIP_NOT_PROFITABLE (expected behavior)
- `profitable_count>0` + `best>0` - found profitable arb = ROUNDTRIP_PROFITABLE (ready for execution)

**Interpretation**: ROUNDTRIP_NOT_PROFITABLE is NOT a bug - it's proof Truth Engine correctly identifies non-profitable conditions.

---

## Non-stop Scan Demo

Canonical command for continuous scanning with rolling artifact refresh. This demonstrates real-time arbitrage detection capability.

### Single-chain Non-stop Loop

```powershell
# Single-chain scan with rolling refresh (primary chain only)
py -3.11 start.py --config config/real_minimal.yaml --hours 2 --sleep-seconds 20
```

### Multi-chain Long Scan (recommended)

Round-robins all 6 chains. Only the primary `run_kind=NORMAL` chain gets `--refresh-rolling`;
coverage configs skip rolling refresh to respect the rolling-discipline guardrail.

A long scan is a **market/data probe** -- it confirms infrastructure stability, data quality,
and signal coverage across chains. It is not proof of constant profit.

```powershell
py -3.11 start.py --config-list config/real_minimal.yaml,config/onboard_base_stage1.yaml,config/onboard_mantle_stage1.yaml,config/onboard_zksync_candidate.yaml,config/onboard_scroll_stage1.yaml,config/onboard_linea_stage1.yaml --hours 3 --cycles 1 --sleep-seconds 20 --prune-keep 200 --summary-file data/runs/_rolling/long_scan_latest.json
```

Strict mode (exit 1 if any chain has failures):
```powershell
py -3.11 start.py --config-list ... --hours 3 --max-fail-chains 0 --summary-file data/runs/_rolling/long_scan_latest.json
```

Summary output goes to `data/runs/_rolling/long_scan_latest.json` (canonical rolling artifact, overwritten, never committed).

### Native Loop Mode (single config, no per-chain summary)

```powershell
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --loop --sleep-seconds 20
```

### Monitoring During Non-stop Run

Check rolling artifact status:
```powershell
py -3.11 scripts/inspect_rolling.py
```

Quick roundtrip profitability check:
```powershell
py -3.11 -c "import json,glob; rs=json.load(open('data/runs/_rolling/run_summary_latest.json','r',encoding='utf-8')); rd=rs['inputs']['run_dir_name']; trp=sorted(glob.glob(f'data/runs/{rd}/reports/truth_report_*.json'))[-1]; tr=json.load(open(trp,'r',encoding='utf-8')); print('runDir',rd,'profit_realism_status',tr.get('profit_realism_status'),'roundtrip_profitable_count',(tr.get('roundtrip_summary') or {}).get('profitable_count'))"
```

### Alert Conditions

When `roundtrip_summary.profitable_count > 0`:
- Console prints `[ALERT] ROUNDTRIP_PROFITABLE detected!`
- `data/runs/_rolling/last_roundtrip_profitable.json` is created (runtime-only, gitignored)
- RunDir is auto-protected from pruning

### Interpretation

| Metric | Meaning |
|--------|---------|
| `ROUNDTRIP_NOT_PROFITABLE` | No arbitrage opportunity found (expected most of the time) |
| `ROUNDTRIP_PROFITABLE` | Profitable arbitrage detected! Check truth_report for details |
| `data_run_rate > 0.90` | System has good data quality |
| `agg_status=PASS` | Rolling quality gate passing |

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
- `data/runs/_rolling/m4_stability_agg.json` - overwritten on each emit
- `data/runs/_rolling/_latest.json` - overwritten pointer
- No dated copies of latest/agg in runtime

### Rule #4: Retention policy

**Canonical semantics** for `--prune-keep N`:
- **N=50 means 50 runDirs** (directories like `ci_m5_gate_20260215_140031`)
- Protected directories are NOT counted toward N (they stay forever)
- Deletion order: oldest first by timestamp in directory name

**Protected directories** (NEVER deleted):
| Directory | Reason |
|-----------|--------|
| `data/runs/_rolling/` | Canonical rolling artifacts |
| `data/runs/_incidents/` | Incident records |
| `data/runs/_cache/` | Cache data |
| Any runDir referenced in `_latest.json` | Active evidence |
| Any runDir referenced in Status_M4.md | Active evidence (automatic detection) |

**Usage workflow**:
```powershell
# 1. Preview what will be deleted
py -3.11 scripts/prune_run_dirs.py --keep 50 --dry-run

# 2. Execute deletion
py -3.11 scripts/prune_run_dirs.py --keep 50 --yes
```

**M5 gate integration**: `--prune-keep 50` in M5 gate automatically prunes after scan.

- **NEVER manually delete** `data/runs/ci_*` directories - use `prune_run_dirs.py` only
- CI: save runtime artifacts as GitHub Actions artifacts (7-30 day retention)

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
