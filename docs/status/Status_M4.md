# Status: M4 (DEX<->DEX Atomic Execution)

**Status**: PROVISIONAL (code-level fixes validated offline; online proof pending)  
**Updated**: 2026-02-10  
**Gate Version**: v1.12.3  
**Policy Version**: v1.12.0  
**Evidence**: `9b07ab7` code-level fixes validated offline; online proof currently blocked by chain/provider mismatch and NO_DATA run; canonical evidence pending clean online rerun + attach_evidence.  

## Workflow Split (v1.12.3)

| Mode | Description | SHA Binding | Evidence Required |
|------|-------------|-------------|-------------------|
| **DEV** | Fast iteration cycle | Soft | Rolling trio + runDir |
| **RELEASE_EVIDENCE** | Public proof | Hard | attach_evidence + SHA linkage |

**SHA Policy (v1.12.3):**
> Hard commit-binding disabled (HEAD may differ from run_context.code_sha).  
> BUT `run_context.code_sha` and `evidence_sha` fields remain **mandatory** in all artifacts for provenance and audit.

**DEV Mode:**
- No hard HEAD == run_context.code_sha check (allows iteration without commit)
- run_context.code_sha still recorded (captures which code actually ran)
- No mandatory attach_evidence on every cycle
- Minimal bundle: `_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json` + runDir
- Use for rapid development and debugging

**RELEASE_EVIDENCE Mode:**
- Clean worktree required (code_dirty=false)
- `attach_evidence.py --sha <commit>` mandatory after successful run
- `evidence_sha` in artifacts must match committed code
- Use for milestone claims in Status_M4.md  

## Taxonomy Contract (v1.12.0)

| Reason Prefix | Status Required | Semantic |
|---------------|-----------------|----------|
| `FAIL_*` | status=FAIL | Hard failure, blocks passage |
| `WARN_*` | status=PASS allowed | Warning, quality concern |
| `NO_DATA` | status=NO_DATA | signals_count == 0 only |

**Invariant**: If `FAIL_*` appears in reasons, status MUST be FAIL. Enforced by `compute_status()`.

## Status Contract (v1.11.0+)

| Condition | Status | Semantic |
|-----------|--------|----------|
| `signals_count == 0` | NO_DATA | True absence of data |
| `signals > 0, net > 0` | PASS | Profitable (quality may warn) |
| `signals > 0, net ≤ 0` | FAIL | Unprofitable |
| `signals < 5` | quality_status=WARN | Low sample (not NO_DATA) |

**Rule**: NO_DATA only when signals_count == 0. Low sample → WARN, not NO_DATA.

## Run Kinds (v1.11.0)

| Kind | Description | Counted in KPIs |
|------|-------------|-----------------|
| NORMAL | Regular online scan | ✅ Main KPIs |
| COVERAGE | Coverage batch run | ❌ Separate stats |
| SMOKE | Smoke test | ❌ Excluded |
| OFFLINE | Offline fixture | ❌ Excluded |

## Rolling KPIs (Targets)

| Metric | Target | FAIL | Description |
|--------|--------|------|-------------|
| `data_run_rate` | ≥ 0.50 | < 0.30 | % NORMAL runs with ≥5 signals |
| `fail_rate` | ≤ 0.10 | > 0.15 | % FAIL runs (v1.12.0 bites) |
| `fragile_rate_p90` | ≤ 0.30 | > 0.50 | p90 fragile rate |
| `unique_pairs` | ≥ 10 | < 3 | Pair diversity |
| `unique_routes` | ≥ 4 | < 2 | Route diversity |

## Thresholds (v1.12.0)

| Threshold | Value | Description |
|-----------|-------|-------------|
| `MIN_SIGNALS_FOR_PASS` | 5 | Profit-grade (is_data_run) |
| `MIN_SIGNALS_WARN` | 3 | Below = WARN_LOW_SAMPLE |
| `MAE_WARN` | 0.55 | MAE warning |
| `MAE_FAIL` | 0.80 | MAE failure |
| `SIGN_RATE_MIN` | 0.60 | Min sign correct rate |
| `AGG_FAIL_RATE_FAIL` | 0.15 | v1.12.0: fail_rate > 15% → FAIL |
| `DIVERSITY_PAIRS_MIN` | 3 | v1.12.0: < 3 pairs → FAIL |
| `DIVERSITY_ROUTES_MIN` | 2 | v1.12.0: < 2 routes → FAIL |

## Canonical Commands

```bash
# Coverage batch (COVERAGE kind)
python scripts/run_coverage_batch.py --min-signals-target 30 --max-seconds 600 --profile profit

# M4 gate (profit, require-clean by default)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# Allow dirty worktree (dev only)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --allow-dirty

# Check rolling KPIs
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "data_run_rate|no_data_rate|signals_per_run_p50"

# Reset window
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window
```

## Rolling Artifacts

| File | Purpose |
|------|---------|
| `_latest.json` | Latest run pointer |
| `run_summary_latest.json` | Full run summary |
| `m4_stability_agg.json` | Rolling aggregator (segmented by run_kind) |

Location: `data/runs/_rolling/`

## Definition of Done

### M4.1: Simulate-Only — ✅ PROVEN
- [x] Online scan generates signals
- [x] Simulator calculates PnL
- [x] Rolling artifacts persist
- [x] Evidence workflow works

### M4.2: Real Execution -- NOT PROVEN
- [ ] Kill switch disabled
- [ ] Real TX submitted

## Known Blockers (2026-02-10)

1. **Python version**: Pipelines running under Python 3.14, repo requires 3.11
2. **Chain/provider mismatch**: chain_id=42161 (Arbitrum) with Mantle RPC host detected in last online run
3. **Online scan unusable**: quotes_fetched=0, dexes_active=0 in last run
4. **Rolling artifacts need reset**: existing artifacts have v1.11 schema/policy_version
5. **Provenance fixes in v1.12.2**: _latest and runs_since_sha now use artifact context, not git
6. **Rolling artifacts stale**: `latest_run_code_sha`/`runs_since_sha.sha` still at `6661379`, not HEAD; M4 online DoD remains open until fresh online run + M4 gate PASS on that runDir

### v1.12.2 Provenance Fixes
- `_latest.latest_run_code_sha` now sourced from run artifact, not live git context
- `_latest.run_context.*` copied from run artifact, with fallback for legacy runs
- `runs_since_sha` computed against artifact SHA, with optional `target_sha` override
- Added `validate_chain_rpc_consistency()` to detect chain_id/RPC host mismatches

### Recovery Steps
```bash
# 0. Enforce Python 3.11
py -3.11 -m venv .venv && .\.venv\Scripts\Activate.ps1

# 1. Verify chain/RPC consistency before running online
python -c "from core.rpc_urls import validate_chain_rpc_consistency; print(validate_chain_rpc_consistency(42161, 'arb-mainnet.g.alchemy.com'))"

# 2. Reset rolling window (clean worktree)
git stash && python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window

# 3. Re-run online M5_0 until quotes_fetched > 0
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

# 4. Run M4 profit gate on valid runDir
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# 5. Attach evidence SHA
python scripts/attach_evidence.py --sha <new_commit_sha>

# 6. Validate rolling artifacts
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "schema_version|policy_version|agg_status"
```

## Documentation

- [Policy & Thresholds](../m4/M4_POLICY.md)
- [Rolling Contract](../m4/ROLLING_CONTRACT.md)
- [Testing Guide](../TESTING.md)
