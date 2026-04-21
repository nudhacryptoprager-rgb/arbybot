# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: reviewer 30-min control soak 2026-04-21 (Base, anvil + dRPC)
mode: ONLINE
artifact_mode: rolling
config: Base, strict admission, Step 9 drift mitigation live
code_identity:
  primary: ts:2026-04-17T12:59:11Z
  dirty: true — M7.E1.34c reviewer-fix cycle
  desc: anvil revert decode (STF/SLIPPAGE/...), sim_failed_samples ring, profit_guard vs route_viable invariant, strict_provider_policy

## 1) Scope
goal: Implement reviewer fix steps #2 / #4 / #5 / #7 after 30-min control
soak showed Step 9 drift mitigation directionally validated
(`ΔBlockOutOfRangeError=0`) but `Δsim_passed=0` on both lanes. New stopper:
`eth_call: execution reverted: STF`.

change_summary:
  - `m7/orderflow/sim_backends/anvil_backend.py` — `_eth_call_anvil` revert
    strings now piped through `rpc_fork_backend._decode_revert_reason`
    (fix #4). STF / SLIPPAGE / INSUFFICIENT_* get dedicated buckets.
  - `m7/orderflow/execution_gate.py` — new
    `ExecutionGateResult.sim_failed_samples` with
    pair/venue/token_in/token_out/router/amount_in_wei/bucket/revert_reason
    (fix #5).
  - `m7/orderflow/hot_runtime_artifacts.py` — ring of 50
    `sim_failed_samples_recent` + `sim_failed_samples_total`; invariant
    `profit_guard_passed_total ≤ route_viable_total`
    → `invariant_violations.profit_guard_exceeds_route_viable` (fix #2);
    `ARBY_STRICT_PROVIDER_POLICY=1` → `strict_provider_breaches_total`
    (fix #7).
  - `tests/unit/test_m7_e1_34c_reviewer_fixes.py` (NEW, 8 tests).
  - `tests/unit/test_anvil_backend.py::test_eth_call_revert` updated to
    decoded `REVERT:*` contract.

touched_files:
  - m7/orderflow/sim_backends/anvil_backend.py
  - m7/orderflow/execution_gate.py
  - m7/orderflow/hot_runtime_artifacts.py
  - tests/unit/test_m7_e1_34c_reviewer_fixes.py (NEW)
  - tests/unit/test_anvil_backend.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed
pytest tests/unit: **PASS** 4216 / 0 failed / 17 skipped (139.39s)
pytest target (`anvil_backend` + `execution_gate` + `hot_rollup_semantics`
+ `test_m7_e1_34c_reviewer_fixes`): **PASS** 121 / 0
ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
reviewer 30-min control soak: COMPLETED (see §4)

## 3) Artifacts
canonical rolling: `_latest.json`, `run_summary_latest.json`,
  `m4_stability_agg.json`, `m7_hot_rollup_latest.json`,
  `m7_hot_rollup_latest_discovery.json`, `m7_orderflow_latest*.json`
run_dir_bundle: `data/runs/ci_m5_gate_arbitrum_one_20260417_145636_478653/reports`
reviewer ephemera: `reviewer_soak_baseline_latest{,_discovery}.json`,
  `reviewer_soak_delta_latest.json`, `reviewer_soak_30m_stdout.log`
new rollup fields:
  - `sim_failed_samples_recent` / `sim_failed_samples_total`
  - `invariant_violations.profit_guard_exceeds_route_viable`
  - `strict_provider_breaches_total` (when policy enabled)

## 4) Key Results — Reviewer 30-min control soak (2026-04-21)
production: +58 windows / +150 events / +16 fast_scored / +1 guard_passed /
  +1 sim_attempted / **+0 sim_passed** / +0 BlockOutOfRangeError
discovery:  +59 windows / +143 events / +30 fast_scored / +3 guard_passed /
  +3 sim_attempted / **+0 sim_passed** / +0 BlockOutOfRangeError
verdict: `Δsim_passed=0` both lanes → **ACCEPTANCE FAIL** (exit 2).
Step 9 directional PASS (`ΔBlockOutOfRangeError=0`). NEW stopper:
`eth_call: execution reverted: STF`. Discovery rollup contract smell
(`profit_guard_passed +3` vs `route_viable +0`) now captured by invariant.

## 4.1) Theoretical Net Profit
mode: paper_simulated; net_pnl_usdc: n/a (no profitable roundtrip).
execution_enabled=false, kill_switch_active=true. No real trades.

## 5) Contract Checks
pytest tests/unit: **PASS** 4216 / 0
status/reasons consistency: OK; rolling discipline: OK
check_repo_safety.py v1.15.0: PASS expected after this overwrite
  (timestamp_utc matches run_summary_latest.run_context.run_timestamp).

## 6) Blocker Classification
code_blocker: **LOW** — 4216 PASS (+8 reviewer-fix tests).
data_collection_blocker: **MEDIUM** — strict-provider counter now surfaces
  `public_fallback` usage; reviewer requested production-grade provider.
market_window_blocker: **HIGH** — STF / toxic-pair reverts dominate
  terminal stage; canonical M4 still `ROUNDTRIP_NOT_PROFITABLE`.

## 6.1) Risks
- `sim_failed_samples_recent` bounded at 50 — sufficient for diagnostics,
  not a per-run calldata archive.
- Invariant is surfaced, not enforced; scorer/guard contract fix still
  required before removing the divergence at source.

## 7) Execution Map
step_01 venue fallback: DONE | step_02 block retry: DONE | step_05 quality
gates: DONE | step_06 AMOUNT_ZERO autofill: DONE | step_07 admission
filter: DONE | step_08 TOKEN_ADDRESS_UNKNOWN: NOT STARTED |
step_09 anvil drift: VALIDATED (`ΔBlockOutOfRangeError=0`) |
**step_10 reviewer fix batch (#2/#4/#5/#7): DONE** |
step_11 STF root-cause (fix #3): NEXT.

## 8) Requests to Lead
request_1: Review STF-tagged `sim_failed_samples_recent` to decide on
  pair-level filter (KellyClaude/USDC, RNBW/USDC, 0xa538…/USDC).
request_2: Enable `ARBY_STRICT_PROVIDER_POLICY=1` by default for next soak?
q_1: Expected STF cause — missing allowance for victim's source, or
  toxic-token transfer hooks?

---

## REVIEWER RUNBOOK — 30-min STF validation soak

### Term A — anvil fork + refresher (unchanged)
```powershell
.\venv\Scripts\Activate.ps1
$env:PATH = "$PWD\tools\foundry;$env:PATH"
$env:ARBY_FORK_RPC_URL = "<dRPC base archive URL>"
$env:ARBY_ANVIL_AUTO_REFRESH="1"; $env:ARBY_ANVIL_REFRESH_INTERVAL_S="60"; $env:ARBY_ANVIL_REFRESH_DRIFT_BLOCKS="120"
py -3.11 scripts/start_anvil_fork.py --chain base --fork-block-offset 5
```

### Term B — 30m soak with STF classification + strict provider
```powershell
$env:ARBY_SIM_BACKEND="anvil"; $env:ARBY_ANVIL_RPC_URL="http://127.0.0.1:8545"
$env:ARBY_SIM_FALLBACK="rpc_fork"; $env:ARBY_HOT_REHYDRATE="1"
$env:ARBY_SIM_ADMISSION_STRICT="1"; $env:ARBY_SIM_MIN_NET_BPS="1.0"
$env:ARBY_SIM_BYPASS_GUARD="0"; $env:ARBY_ANVIL_CLAMP_BLOCK="1"
$env:ARBY_STRICT_PROVIDER_POLICY="1"
Copy-Item data/runs/_rolling/m7_hot_rollup_latest.json data/runs/_rolling/reviewer_soak_baseline_latest.json
Copy-Item data/runs/_rolling/m7_hot_rollup_latest_discovery.json data/runs/_rolling/reviewer_soak_baseline_latest_discovery.json
py -3.11 scripts/start_nonstop_runtime.py --chain base --minutes 30 --with-discovery --no-m4
```

### Post-soak acceptance
```powershell
py -3.11 scripts/reviewer_soak_summary.py --discovery   # exit 0=PASS / 2=FAIL
py -3.11 -c "import json,pathlib; d=json.loads(pathlib.Path('data/runs/_rolling/m7_hot_rollup_latest.json').read_text()); [print(s['bucket'],s['pair'],s['venue']) for s in d.get('sim_failed_samples_recent',[])]"
```
**Acceptance:** `Δsim_passed>0` both lanes, `ΔBlockOutOfRangeError==0`,
`Δroundtrip_attempted>0`, `strict_provider_breaches_total==0`.

---

## Session Completion
session_goal: Reviewer fix steps #2 / #4 / #5 / #7.
goal_status: REACHED (code-level); BLOCKED at field validation pending
reviewer's next 30-min soak with STF classification live.
close_allowed: true
remaining_blockers: STF root-cause (fix #3); Step 8 TOKEN_ADDRESS_UNKNOWN;
  canonical M4 still NOT_PROFITABLE.
evidence_session_run_dirs: data/runs/_rolling.
primary_blocker_of_session: `eth_call: execution reverted: STF` on fresh
  sim attempts (was: static Anvil fork drift → resolved by Step 9).
blocker_status_before: ACTIVE — 30m control `Δsim_passed=0`; generic
  `execution reverted` dominated histogram with no STF breakdown.
blocker_status_after: MITIGATED at tooling level — STF / SLIPPAGE /
  INSUFFICIENT_* each have their own histogram bucket; failed-sim ring
  gives calldata-level visibility; invariant catches guard-vs-viable drift;
  strict-provider counter gates production-grade RPC policy. Field
  validation pending next 30m soak.
docs_reread_confirmed: true
