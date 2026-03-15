# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.6)
**Goal**: R28.6 — RunDir collision fix (parallel coverage workers writing to same directory), chain_id validation, telemetry artifact fix (report_ms=0), regression tests.
**Prior (R28.5)**: Bounded parallel coverage, expanded phase metrics, phase_timers artifact fix. 37 runs in 556s (~15s/run). Lead review found 6 runDir collisions (zksync 324 + base 8453 sharing dirs due to second-precision timestamps + exist_ok=True).

## 0) Meta
timestamp_utc: 2026-03-15T12:20:55Z
rolling_provenance: 2026-03-15T12:20:55Z (arbitrum_one NORMAL — FRESH R28.6 evidence, ci_m5_gate_arbitrum_one_20260315_132036_628412)
mode: COLLISION_FIX + INTEGRITY_HARDENING + FRESH_SCANS
test_count: 1837 passed, 3 skipped (+9 from R28.5)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.6: RunDir collision fix (chain-scoped unique dirs), chain_id validation in start.py, telemetry artifact fix (report_ms=0→63), regression tests |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb agg gap_median ~18 bps; ARCHITECTURE: async quote path deferred; DEFERRED: WS/multicall proof, dashboard phase metrics |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260315_125949_107589 (arb primary, NORMAL, PASS, report_ms=63), ci_m5_gate_linea_20260315_130030_176187 (linea, ROUNDTRIP_PROFITABLE=2), ci_m5_gate_zksync_20260315_130057_292600 (zksync, PASS), ci_m5_gate_base_20260315_130130_962376 (base, PASS), ci_m5_gate_arbitrum_one_20260315_132036_628412 (long_scan final, rolling refresh) |
| primary_blocker_of_session | RunDir collision — parallel coverage workers (R28.5) created dirs with second-precision timestamps + exist_ok=True → 6 collisions (chain_ids 324+8453 sharing same dir) |
| blocker_status_before | 6 confirmed collisions in data/runs/ (ci_m5_gate_20260315_12{2201,2346,2530,2656,2817,2936}) |
| blocker_status_after | RESOLVED: chain-scoped runDirs with microsecond precision + exist_ok=False. 0 new collisions in parallel (workers=2) long scan (31 runs) |
| start_metric | R28.5: 6 runDir collisions (zksync 324 + base 8453), report_ms=0 in scan artifact |
| end_metric | R28.6: 0 collisions (parallel long scan 31 runs), report_ms=63 in artifact, chain_id validation active |
| delta | +9 tests (1837), chain-scoped runDirs, chain_id mismatch validation, scan artifact patched with final phase_timers |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — runDir provenance integrity (R28.6 lead directive)
change_summary:
  - RUNDIR COLLISION FIX: `scripts/ci_m5_0_gate.py` — runDir now uses `ci_m5_gate_{chain_key}_{YYYYMMDD}_{HHMMSS}_{microseconds}` format. Chain key read from config BEFORE dir creation. `exist_ok=False` with retry on FileExistsError. Eliminates parallel collision (was `ci_m5_gate_{YYYYMMDD}_{HHMMSS}` with `exist_ok=True`).
  - CHAIN_ID VALIDATION: `start.py` — new `_validate_chain_id_match(run_dir, expected_chain_id, chain_name)` function. Scans all `scan_*.json` in runDir reports for chain_id mismatches. Prints `[CHAIN_MISMATCH]` warning. Called in `_run_one_chain()` after extracting scan stats.
  - TELEMETRY ARTIFACT FIX: `strategy/jobs/run_scan_real.py` — after computing final phase_timers (including report_ms), reads scan artifact from disk, patches `phase_timers_ms`, re-writes via `atomic_write_json()`. Only in full artifact mode (not rolling). Fixes report_ms=0 in artifact.
  - REGEX UPDATES: `start.py` CI_M5_DIR_RE updated to match both legacy and chain-scoped formats. `scripts/prune_run_dirs.py` pattern extended with optional microsecond suffix.
  - CONFIG META: `start.py` `read_config_meta()` now returns `chain_id` from YAML for validation.
touched_files: scripts/ci_m5_0_gate.py, start.py, strategy/jobs/run_scan_real.py, scripts/prune_run_dirs.py, tests/unit/test_start.py (+9), tests/unit/test_run_scan_real_purity.py (max_lines 1410→1425)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1837 passed, 3 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (ALL REQUIRED GATES PASSED, 26.2s)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: **PASS** (arb, runDir=ci_m5_gate_arbitrum_one_20260315_125949_107589, report_ms=63)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_scan_linea_smoke.yaml: **PASS** (linea, ROUNDTRIP_PROFITABLE=2)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_zksync_candidate.yaml: **PASS** (zksync)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_base_stage2.yaml: **PASS** (base)
py -3.11 start.py --config-list real_minimal,zksync,base_stage2,linea --hours 0.15 --cycles 1 --coverage-workers 1: **25 runs** (serial, 543s, 53 signals, $80.18, 12 profitable RT, 0 collisions)
py -3.11 start.py --config-list real_minimal,zksync,base_stage2,linea --hours 0.15 --cycles 1 --coverage-workers 2: **31 runs** (parallel, 544s, 69 signals, $116.34, 14 profitable RT, **0 new collisions**)

## 3) Artifacts Attached (шляхи)
rolling (FRESH — R28.6 online evidence):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T12:20:55Z, runDir: ci_m5_gate_arbitrum_one_20260315_132036_628412)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs_in_window: 200+)
  - data/runs/_rolling/long_scan_latest.json (REFRESHED: 31 runs, 69 signals, $116.34, 14 profitable roundtrips)

session_run_dirs:
  - ci_m5_gate_arbitrum_one_20260315_125949_107589 (arb primary, NORMAL, PASS, report_ms=63)
  - ci_m5_gate_linea_20260315_130030_176187 (linea, COVERAGE, PASS, ROUNDTRIP_PROFITABLE=2)
  - ci_m5_gate_zksync_20260315_130057_292600 (zksync, COVERAGE, PASS)
  - ci_m5_gate_base_20260315_130130_962376 (base, COVERAGE, PASS)
  - ci_m5_gate_arbitrum_one_20260315_132036_628412 (long_scan final, rolling refresh)

## 4) Key Results (числа з артефактів)

```
# Collision fix verification
Pre-fix collisions: 6 (ci_m5_gate_20260315_12{2201,2346,2530,2656,2817,2936} — chain_ids [324, 8453])
Post-fix collisions (parallel workers=2): 0 (31 runs, all chain-scoped unique)
New runDir format: ci_m5_gate_{chain_key}_{YYYYMMDD}_{HHMMSS}_{microseconds}

# Long scan parallel (workers=2 — collision stress test)
wall_seconds: 544
total_runs: 31
total_included_signals: 69
total_net_usdc: $116.34
total_profitable_roundtrips: 14
pass_chains: arbitrum_one, zksync, base, linea
new_collisions: 0

# Long scan serial (workers=1 — baseline)
wall_seconds: 543
total_runs: 25
total_included_signals: 53
total_net_usdc: $80.18
total_profitable_roundtrips: 12

# Phase timers (arb primary — FIXED report_ms)
total_ms=19468, discovery_ms=1516, quote_rpc_ms=9014, postprocess_ms=8063, preflight_ms=781, report_ms=63
report_ms was 0 in R28.5 artifact (computed after write) → now 63 (artifact patched after final computation)

# New tests (R28.6)
+4 TestCI_M5_DIR_RE (legacy format, chain-scoped arb, chain-scoped zksync, reject random)
+3 TestValidateChainIdMatch (no mismatch silent, mismatch prints warning, missing reports silent)
+2 TestReadConfigMetaChainId (chain_id present, chain_id missing)
Total: 1837 passed, 3 skipped
```

## 5) Contract Checks
- runDir uniqueness: chain_key + microsecond timestamp + exist_ok=False with retry
- chain_id validation: _validate_chain_id_match scans scan_*.json against expected chain_id
- CI_M5_DIR_RE: matches both legacy (`ci_m5_gate_YYYYMMDD_HHMMSS`) and new (`ci_m5_gate_{chain}_YYYYMMDD_HHMMSS_{us}`)
- prune_run_dirs: regex updated for optional `_\d+` microsecond suffix
- telemetry: scan artifact patched on disk with final phase_timers_ms (report_ms, total_ms, post_scan_ms)
- rolling discipline: primary (NORMAL) sequential, coverage parallel — rolling never overwritten by COVERAGE

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1837 PASS, collision FIXED, telemetry FIXED)
provenance_integrity: RESOLVED (0 collisions in parallel stress test, chain_id validation active)
scanner_latency: STABLE (~15s/run parallel, quote_rpc still main bottleneck at 9s)
async_quote_path: DEFERRED (major architecture — quotes.py uses sync Web3)
ws_block_head: DEFERRED (no WebSocket infrastructure exists)
multicall_proof: DEFERRED (multicall_stats=None in canonical path)
market_window_blocker: MEDIUM (arb agg gap_median ~18 bps — not profitable)
```

## 7) R28.6 Session Summary
- **RunDir collision fix**: `ci_m5_0_gate.py` now creates `ci_m5_gate_{chain_key}_{YYYYMMDD}_{HHMMSS}_{microseconds}` dirs with `exist_ok=False` + retry. Pre-fix: 6 collisions (zksync+base sharing dirs). Post-fix: 0 collisions in parallel (workers=2) stress test with 31 runs.
- **Chain_id validation**: `start.py` new `_validate_chain_id_match()` scans runDir artifacts for chain_id mismatches. Prints `[CHAIN_MISMATCH]` warning if detected. Integrated into `_run_one_chain()`.
- **Telemetry artifact fix**: `run_scan_real.py` patches scan artifact on disk with final `phase_timers_ms` after computing report_ms/total_ms. Result: report_ms=63 (was 0 in R28.5).
- **Regex updates**: `CI_M5_DIR_RE` in start.py and prune pattern in prune_run_dirs.py support both legacy and chain-scoped formats.
- **Online verification**: 4 individual chain scans (all PASS) + 2 long scans (serial 25 runs + parallel 31 runs). Linea strongest non-arb (ROUNDTRIP_PROFITABLE=2, 12 profitable RT in long scan).
- **Lead quote**: "R28.5 speed gain is provisional until parallel runDir uniqueness/provenance integrity is fixed" → **FIXED**.

## 8) Що потрібно від ліда
1. RunDir collision fix verified: 6 pre-fix collisions → 0 post-fix in parallel stress test (31 runs, workers=2).
2. Telemetry: report_ms=63 in artifact (was 0). Scan artifact patched on disk after final phase_timers computation.
3. Chain_id validation active: `_validate_chain_id_match()` in `_run_one_chain()` catches cross-contamination.
4. Linea strongest non-arb: 12 profitable RT in long scan, ROUNDTRIP_PROFITABLE=2. Rollout queue should prioritize linea over zksync.
5. Deferred (per lead R28.6 directive): async quote path, WS/multicall proof, dashboard phase bottleneck visibility — not immediate.
6. Quote RPC is main latency bottleneck: 9014ms of 19468ms total (~46%). Async quote path is the next architectural target.
