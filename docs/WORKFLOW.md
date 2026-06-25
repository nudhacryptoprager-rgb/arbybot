# ARBY3 Workflow (GPT / Codex <-> Cursor <-> GitHub)

> **Provenance**: SHA tracking removed. Evidence based on `run_timestamp` + rolling artifacts.
> See `docs/DEV_REPORT_CANONICAL_UA.md` for canonical report format.
> See `docs/status/Status_M4.md` for current milestone status.

## Agent Workflow

- GPT / Codex is the team-lead reviewer: planning, critique, acceptance, and
  exact next-step instructions.
- Cursor is the developer-agent executor: small patches only, bounded by
  `CURSOR.md` and `.cursor/rules/*.mdc`.
- GitHub remains the collaboration and CI surface.
- Legacy GitHub Copilot / Claude helper files are not the active executor path.

## Нові режими та діагностика
- Для збору simulation_error_histogram (діагностичний прогін simulation для всіх кандидатів) використовуйте прапорець --sim-anyway (або ARBY_SIM_BYPASS_GUARD=1).
- Для аналізу нестандартних REVERT:unknown у discovery lane додано логування сирих байтів (див. _decode_revert_reason).
- Multi-hop (V3→V2/V3→Slipstream) маршрути автоматично генеруються для matched_then_gas_rejected та непрохідних direct arb (див. opportunity_engine.py).

## RPC endpoints (archive + realtime head)

Soak і anvil-fork потребують **archive-capable** HTTP RPC і **WS** для newHeads. Публічний `mainnet.base.org` НЕ archive і обмежений rate-limit.

**Резолвер** (`core.rpc_urls.resolve_rpc_http`) читає у такому порядку:
1. Chain-scoped env — `BASE_RPC` / `ARBITRUM_RPC` (і відповідні `BASE_WSS`/`ARBITRUM_WSS`)
2. Global — `ALCHEMY_RPC_HTTP` / `ARBY_RPC_HTTP_PRIMARY`
3. `ALCHEMY_API_KEY` → автобудування `wss://base-mainnet.g.alchemy.com/v2/<key>` і HTTP
4. Public fallback (`mainnet.base.org`) — тільки для лайвнес-чеків, не для fork/історії

**Діагностика перед soak (обов'язково):**
```powershell
py -3.11 scripts/check_rpc_endpoints.py --chain base --ws-timeout 15
# Exit 0 = PASS; 1 = archive FAIL; 2 = WS FAIL; 3 = chain_id mismatch; 4 = no url
```

**Рекомендований ENV (Base, archive + realtime WS):**
```powershell
$env:ALCHEMY_API_KEY = "<your key>"
# або явні ендпойнти якщо використовуєте dRPC Premium / QuickNode:
# $env:BASE_RPC  = "https://lb.drpc.org/ogrpc?network=base&dkey=<key>"
# $env:BASE_WSS  = "wss://lb.drpc.org/ogws?network=base&dkey=<key>"
$env:ARBY_FLASHBLOCKS_SIM  = "1"
$env:ARBY_FLASHBLOCKS_HTTP = "https://mainnet-preconf.base.org"  # sub-200ms preconf feed
$env:ARBY_SIM_BACKEND      = "anvil"
$env:ARBY_ANVIL_RPC_URL    = "http://127.0.0.1:8545"
$env:ARBY_REQUIRE_ARCHIVE  = "1"   # hard-refuse public RPC in anvil fork bootstrap
$env:ARBY_FORK_BLOCK_OFFSET = "3"  # pin fork to head-3 to avoid reorg race
```

**НЕ встановлюйте `BASE_RPC_URL=https://mainnet.base.org` перед soak** — це перевизначить Alchemy/dRPC і anvil-fork не зможе прочитати історичні блоки (`BlockOutOfRangeError`).

**Правильна команда soak (Base, 30 хв):**
```powershell
py -3.11 scripts/check_rpc_endpoints.py --chain base  # PASS expected
py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 0.5 --with-discovery --no-m4 --with-anvil
```

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
# Dashboard (MANDATORY — start BEFORE scanner, keep running throughout session)
py -3.11 -m monitoring.dashboard_server --port 8099

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

## M8/M9 Project Pipeline Orchestrator

`start.py` is also the canonical entrypoint for the M8/M8.2/M8.3/M9 branch.
Use this path instead of manually stitching individual scripts when refreshing
the long-tail graph-arb pipeline.

Layer commands:

```powershell
# M8 sniper + M8.1 anchor
py -3.11 start.py -m_8 --no-dashboard

# M8.2 radar + expansion + acceptance
py -3.11 start.py -m_8_2 --no-dashboard

# M8.3 metadata registry + acceptance
py -3.11 start.py -m_8_3 --no-dashboard

# M9 bridge/depth/capacity diagnostics; shadow is capacity-gated
py -3.11 start.py -m_9 --no-dashboard

# Full M8 -> M9 chain
py -3.11 start.py -m8_m9 --no-dashboard

# Lane A: time-to-mirror (radar -> expand -> M8.3 metadata; no M9 shadow)
py -3.11 start.py -time_to_mirror --no-dashboard

# Lane B: patient thin-liquidity diagnostic (capacity + spread-lifetime; no profit claim)
py -3.11 start.py --patient-lane --no-dashboard
```

Useful operator flags:

```powershell
--dry-run              # print the exact command plan + RPC policy without running it
--skip-shadow          # stop after capacity/lane diagnostics (-m_9 / -m8_m9)
--skip-preflight       # skip check_repo_safety / audit_layer / check_rpc_endpoints
--resume-from m8_2     # resume at m8_2_radar_two_phase (also m8_3, m9)
--force-rerun-steps    # ignore data/tmp/start_pipeline_steps/*.done markers
--max-radar-tokens N   # cap M8.2 radar input
--sniper-minutes N     # M8 sniper duration for -m_8 / -m8_m9
--with-coingecko       # enable CoinGecko fallback; default is skipped
```

Canonical orchestration policy:

```text
START_ORCHESTRATION_POLICY: CANONICAL_START_PY_REQUIRED
- All production M8→M9 refresh/resume runs go through start.py.
- Direct scripts/...py invocations are debug-only (acceptance spot-checks, RCA).
- Per-step markers: data/tmp/start_pipeline_steps/<step>.done|.fail
- Global markers: data/tmp/start_pipeline_latest.done|.fail|.log
```

Debug-only exceptions (not the default refresh path):

```powershell
py -3.11 scripts/m8_2_acceptance_report.py --strict
py -3.11 scripts/m8_3_acceptance_report.py --strict
py -3.11 scripts/m9_capacity_cycle_diagnostic.py --bridge data/tmp/m9_bridge_inventory_production_latest.json --cycle-lengths 2,3,4 --four-leg-rca --quarantine-rca
```

Routing contract:
- local/report steps run directly under `py -3.11`;
- RPC-heavy steps run through `scripts/bootstrap_productive_rpc_env.py`;
- M8.2 radar uses DexScreener-first async/multicall verification through
  `m8_radar_two_phase_refresh.py`;
- M9 shadow is skipped unless `m9_capacity_cycle_diagnostic.py` allows it via
  `cycles_at_floor > 0`;
- dashboard is launched by default unless `--no-dashboard` is passed.

Strategic lane discipline for the M8/M9 branch:

```text
P0: M9 sizing/profile truth
    Fix and verify profile-specific attempted sizes before any market verdict.

P1: Time-to-mirror
    Keep M8 fresh long-tail tokens with one quoteable pool in a pending queue and
    re-probe for a second verified venue. This is still same-chain.

P2: Patient thin-liquidity lane
    Track depth-aware near-econ spreads with lifetime metrics. Profit claims are
    forbidden unless the active profile permits them and simulation/repeatability
    are proven.

P3: Cross-chain bridge R&D
    Research only. It must not bypass unresolved same-chain M9 sizing, depth, or
    adapter defects.
```

Operator verification commands for the current strategic lanes:

```powershell
# Profile/sizing truth before any economics interpretation
py -3.11 scripts/m9_capacity_cycle_diagnostic.py --bridge data/tmp/m9_bridge_inventory_production_latest.json --cycle-lengths 2,3,4 --four-leg-rca --quarantine-rca
py -3.11 -c "import json; d=json.load(open('data/tmp/m9_graph_handoff_quote_validation_10m.json',encoding='utf-8')); print(d.get('quote_size_truth'))"

# M8.2 and M8.3 upstream contract checks
py -3.11 scripts/m8_2_acceptance_report.py --strict
py -3.11 scripts/m8_3_acceptance_report.py --strict

# M9 report after bridge/capacity refresh
py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json --m8-3-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json --bridge data/tmp/m9_bridge_inventory_production_latest.json
```

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
py -3.11 start.py --config-list config/real_minimal.yaml,config/onboard_base_stage2.yaml,config/onboard_mantle_stage2.yaml,config/onboard_zksync_candidate.yaml,config/onboard_scroll_stage1.yaml,config/onboard_linea_stage1.yaml --hours 3 --cycles 1 --sleep-seconds 20 --prune-keep 200 --summary-file data/runs/_rolling/long_scan_latest.json
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

### Canonical Run Mode (Dashboard + Scanner)

The proven canonical mode is **external dashboard server + scanner with `--no-dashboard`**.
The dashboard process and the scanner are separate — this avoids coupling dashboard lifecycle
to scan cycles and allows the dashboard to serve idle-state data between scans.

**Start dashboard (background):**
```powershell
py -3.11 -m monitoring.dashboard_server --port 8099
```

**Start scanner (foreground, no embedded dashboard):**
```powershell
py -3.11 start.py --config-list config/real_minimal.yaml,config/onboard_zksync_candidate.yaml,config/onboard_base_stage2.yaml,config/onboard_mantle_stage2.yaml,config/onboard_linea_stage1.yaml,config/onboard_scroll_stage1.yaml --accepted-fail-chains scroll --max-fail-chains 5 --hours 0.10 --cycles 1 --sleep-seconds 0 --coverage-workers 2 --no-dashboard --prune-keep 200 --summary-file data/runs/_rolling/long_scan_latest.json
```

**Verify dashboard coherence:**
```powershell
Invoke-RestMethod http://127.0.0.1:8099/api/hot
```

Key constraints:
- `--no-dashboard` on `start.py` — the embedded dashboard is disabled
- Dashboard reads rolling artifacts (`_latest.json`, `run_summary_latest.json`, `long_scan_latest.json`, `hot_loop_latest.json`) independently
- Primary rolling (`_latest.json`, `run_summary_latest.json`) updates only from `run_kind=NORMAL` configs (e.g., `real_minimal.yaml`)
- Coverage configs (`onboard_*`) update `long_scan_latest.json` only
- Panel 0 (Hot Loop) reflects live stream state; Panels 1+ reflect rolling artifacts

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

## Test File Policy (M7 Orderflow)

### Anti-Accretion Rule

Session-specific test files (`test_orderflow_m7aXXX_YYY.py`) are **prohibited**. All M7 orderflow tests live in 8 layer-based suites organized by domain:

| File | Domain |
|------|--------|
| `conftest.py` | Shared helpers (`_make_event`, `_make_result`) |
| `test_orderflow_contracts_core.py` | Schema, field counts, constant counts, admission |
| `test_orderflow_registry_and_coverage.py` | PoolRegistry lifecycle, coverage scan |
| `test_orderflow_pricing_math.py` | V3/V2/Algebra swap math, local pricing |
| `test_orderflow_gas_oracle.py` | Chainlink, oracle guard, gas decomposition |
| `test_orderflow_scoring_latency.py` | Scoring, stale gate, pipeline latency |
| `test_orderflow_artifacts.py` | Artifact schema, ws-live, split summary |
| `test_orderflow_blocker_tags.py` | Debug rows, blocker tags, watchlist |
| `test_orderflow_status_metrics.py` | Pre-econ, consistency, reject decomposition |

### When to add a new test file

A new `test_orderflow_*.py` file is justified **only** for:
- A new stable contract (e.g., new dataclass in `m7/orderflow/contracts.py`)
- A new adapter family (e.g., CurveSwapMath)
- A new reject reason added to `ALL_REJECT_REASONS`
- A new safety gate (e.g., new blocker tag)
- A real bug regression requiring isolated reproduction

Otherwise, add tests to the appropriate existing suite.

### Constants are asserted once

Field/constant counts (`len(BackrunResult.__dataclass_fields__)`, `len(ALL_REJECT_REASONS)`, etc.) are asserted **exactly once** in `test_orderflow_contracts_core.py`. Do not duplicate these assertions in other files.

---
