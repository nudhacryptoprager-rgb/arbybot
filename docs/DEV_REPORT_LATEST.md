# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14.342304Z
run_id: rolling audit snapshot
mode: ONLINE
artifact_mode: rolling
config: rolling evidence from `real_minimal.yaml` + `onboard_base_profit.yaml`
code_identity:
  primary: ts:2026-03-27T21:30:14.342304Z
  dirty: false
  desc: full project audit and documentation sync after M5/M5_0 public-infra hardening phase

## Session Completion
session_goal: full repo audit + current-stage documentation sync
goal_status: REACHED
close_allowed: true
remaining_blockers: no code/infrastructure blocker for the audit itself; public-infra simple DEX-DEX remains economics-blocked
evidence_session_run_dirs:
  - ci_m5_gate_arbitrum_one_20260327_222948_123275
  - ci_m5_gate_base_20260327_223015_126754
primary_blocker_of_session: documentation drift versus current rolling truth
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

## 1) Scope

This report is a current-state project summary after the full M5/M5_0 hardening cycle.

Audited:

- repository structure and active code surface,
- source-of-truth docs and status files,
- active rolling artifacts,
- latest arb/base truth bundles,
- current architecture boundaries,
- current strategic state of the public-infrastructure DEX-DEX thesis.

Refreshed docs: `docs/DEV_REPORT_LATEST.md`, `docs/FILES_SUMMARY.md`, `docs/status/Status_M4.md`, `docs/status/Status_M5_0.md`, `docs/status/INDEX.md`, `docs/TECH_DEBT.md`.

## 2) Verification

Fresh evidence used for this audit:

- `data/runs/_rolling/_latest.json`
- `data/runs/_rolling/run_summary_latest.json`
- `data/runs/_rolling/m4_stability_agg.json`
- `data/runs/_rolling/long_scan_latest.json`
- `data/runs/_rolling/hot_loop_latest.json`
- `data/runs/ci_m5_gate_arbitrum_one_20260327_222948_123275/reports/truth_report_20260327_223000.json`
- `data/runs/ci_m5_gate_base_20260327_223015_126754/reports/truth_report_20260327_223042.json`

## 3) Current System Snapshot

### 3.1 Repository Shape

Current repo snapshot excluding local virtual environments:

- Python files: `297`
- Markdown files: `69`
- JSON files: `26`

Largest code surfaces are concentrated in a few expected orchestration and gate files:

- `strategy/jobs/run_scan_real.py`
- `strategy/quotes.py`
- `scripts/ci_m5_0_gate.py`
- `scripts/check_repo_safety.py`
- `engine/roundtrip.py`
- `strategy/artifacts.py`

### 3.2 Folder-Level Reading

Current repo roles are now clear:

- `core/`: low-level contracts, math, invariants, models, env, validation
- `chains/`: chain services, provider failover, L1 cost, Flashblocks read-path
- `dex/`: adapter registry and ABI assets
- `discovery/`: intent-driven pair/pool universe construction
- `engine/`: seed opportunity model plus canonical roundtrip truth
- `execution/`: substantial but dormant execution stack
- `m4/`: gate/evidence/policy/rolling storage for milestone truth
- `monitoring/`: dashboard and operator-facing reporting
- `strategy/`: active runtime orchestration, scan assembly, artifacts, chain stats
- `scripts/`: CI gates, repo safety, rolling inspection, RCA, maintenance
- `docs/`: source-of-truth human layer
- `tests/`: heavy regression and contract protection surface

### 3.3 Test Surface

The test suite is now a major product asset:

- `2527` tests passing
- milestone regressions are encoded directly in unit tests
- many recent R39/R39x contracts are permanently locked by tests

## 4) Current Runtime Truth

### 4.1 Rolling Aggregate

Fresh rolling state:

| Metric | Value |
|--------|-------|
| total_runs | `58` |
| total_pass | `58` |
| total_fail | `0` |
| total_infra_fail | `0` |
| total_included_signals | `1196` |
| total_roundtrip_evaluated | `169` |
| total_profitable_roundtrips | `0` |
| best_roundtrip_net_bps | `-3.5062` |

Core truth: the system is producing data and canonical profit semantics, but not profitable roundtrips.

### 4.2 Chain Summary

| Chain | Runs | Signals | RT Eval | Real Quotes | Frontier Pair | Gap To Zero | Profit State | Blocker |
|-------|------|---------|---------|-------------|---------------|-------------|--------------|---------|
| `arbitrum_one` | `29/29 PASS` | `906` | `169` | `169` | `WBTC/USDC` | `3.5062 bps` | `ROUNDTRIP_NOT_PROFITABLE` | `OE_ECONOMICS` |
| `base` | `29/29 PASS` | `290` | `0` | `0` | `USDC/USDT` | `8.6729 bps` | `ROUNDTRIP_NOT_PROFITABLE` | `OE_ECONOMICS` |

Reading:

- `arbitrum_one` remains the best single-point near-miss chain in current rolling
- `base` remains the cleanest stable-pair family, but still negative
- neither chain currently supports a claim of online profitable DEX-DEX truth

### 4.3 Hot Loop / Reactivity

`hot_loop_latest.json` shows:

- `total_full_sweeps = 12`
- `total_hot_requotes = 46`
- `total_micro_requotes = 0`

The repo already contains hot-loop scaffolding, but reactive execution edge is not the current reason profit is missing.

## 5) Strategic Reading of the System

### 5.1 What the Project Already Is

At the current stage, the project is already a serious research/execution-prep platform:

1. It can build a dynamic universe from intent and discovery.
2. It can quote across multiple DEX families.
3. It can reject poor-quality or policy-invalid routes with reason codes.
4. It can compute measured roundtrip economics with sweep-based truth.
5. It can aggregate rolling multi-chain frontier evidence.
6. It can expose operator-facing artifacts and dashboard data.

### 5.2 What the Project Is Not Yet

It is not yet:

1. a proven profitable online DEX-DEX execution system,
2. a production trade engine operating with real execution enabled,
3. a validated private-orderflow/searcher stack,
4. a graph-based multi-hop engine.

### 5.3 Current Strategic Verdict

The strongest current conclusion is now narrow but firm:

**the current public-infrastructure simple two-leg DEX-DEX thesis has reached an economics ceiling before reaching profitable online execution.**

This conclusion is supported by stable rolling evidence, canonical truth semantics, per-pair repeatability, near-breakeven decomposition, execution-edge feasibility research, and the absence of dominant hidden infra failure.

## 6) Milestone Reading

### M0-M3

Completed foundation.

### M4

Still open at roadmap level.

Current internal interpretation:

- `M4.1 simulate-only`: closed historically
- `M4.2 online roundtrip profitable`: not reached
- `M4.3 real execution`: not started operationally

The current public-infrastructure branch of M4 should be treated as frozen, not actively improvable by small local fixes.

### M5_0

Reached for the current thesis because rolling artifacts are stable, zero infra failures dominate the window, repo safety and CI are strong, and evidence is detailed enough to support strategy closure decisions.

### M5

Reporting layer exists and remains secondary to M4 truth. It does not override the missing profitable online core result.

## 7) Final Summary

The project now has three strong properties:

1. **The data is credible.**
2. **The profit truth is credible.**
3. **The negative verdict on the current public-infra simple DEX-DEX branch is credible.**

That is the right summary for the current stage of system development: a reusable scanning and truth platform has been built, but a profitable online DEX-DEX engine on the current public-infrastructure path has not.
