# DEV REPORT LATEST — M8 Phase 1 Round-7 CODE_VALIDATED

**mode**: CODE_FIX_TESTS_ONLY (no new online run; R7 code changes + unit tests only)
**session_date**: 2026-05-14
**schema_family**: m8_sniper
**schema_revision**: phase1.2
**blocker_status_before**: STEP8_ARTIFACT_PATH_VIOLATION
**blocker_status_after**: RESOLVED
**phase1_close_allowed**: false (pending fresh all-factory R7 runtime gate; _rolling artifact lacks self_test_by_dex)

---

## Session Completion

session_goal: Fix Step 8 artifact path bug (isolated --dex artifact writing to _rolling/); add missing unit tests for retry logic, artifact contract, and rolling isolation; reach clean pytest run.
goal_status: REACHED
close_allowed: true
remaining_blockers:
  - FRESH_ALL_FACTORY_R7_GATE_REQUIRED: _rolling/new_pool_sniper_latest.json has old contract (no self_test_by_dex)
  - PLAIN_CI_BLOCKED_BY_INTENT_TIER_LIMIT (pre-existing, not M8-specific)
evidence_session_run_dirs: none (code-only fix session; evidence = pytest 5438 passed)
primary_blocker_of_session: STEP8_ARTIFACT_PATH_VIOLATION (isolated artifact polluted _rolling)
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

---

## Step Map (Round-7)

| Step | Description | Status | Evidence |
|------|-------------|--------|---------|
| R7.1 | `_get_logs_safe()` retries on 408/timeout | ✅ DONE | Code in smoke_run.py; 5 new unit tests |
| R7.2 | `_run_self_test()` returns per-DEX dict | ✅ DONE | Code in smoke_run.py |
| R7.3 | `FunnelTracker.set_self_test_results()` | ✅ DONE | Code in sniper_funnel.py |
| R7.4 | `FunnelTracker.set_run_scope()` | ✅ DONE | Code in sniper_funnel.py |
| R7.5 | `make_sniper_artifact()` new fields | ✅ DONE | Code in sniper_artifacts.py |
| R7.6 | Step 8 BUG FIX: isolated artifact → `data/tmp/` | ✅ DONE | `_rolling` clean, test locks it |
| R7.7 | `TestAerodromeVe33WSCallback` (2 tests) | ✅ DONE | Full pipeline: parse_ok=1, dedup_new=1 |
| R7.8 | aerodrome live status classified | ✅ DONE | MARKET_WINDOW_NO_POOL_CREATED in Status_M8.md |
| R7.9 | Phase 1 close criteria updated | ✅ DONE | ≥1 DEX live parse_ok>0 (uniswap_v3 satisfies) |
| R7.10 | Unit tests for retry, contract, isolation | ✅ DONE | new tests; 5438 total passed |

---

## Commands Executed

py -3.11 -m pytest -q: PASS (5438 passed, 17 skipped, 1 warning)
py -3.11 scripts/check_repo_safety.py: FAIL (pre-existing INTENT_TIER_LIMIT only)
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: PASS (2 doc-bloat warns, pre-existing)
git diff --check: PASS (no trailing whitespace errors; cosmetic LF→CRLF warns only)
py -3.11 scripts/ci_full_pipeline.py --mode ci: NOT RUN (code-only session)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: NOT RUN (code-only)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: NOT RUN (code-only)

---

## Test Delta (Round-7 vs Round-6)

```
Round-6 baseline: 5412 passed
After R7 aerodrome WS tests: 5414 passed  (+2)
After R7 retry + contract + isolation tests: 5438 passed  (+26 total from R7; 17 skipped)
```

New tests added this round:

| Test Class | File | Count | What it tests |
|-----------|------|-------|---------------|
| `TestAerodromeVe33WSCallback` | test_m8_ws_listener.py | 2 | aerodrome ve33 WS callback pipeline |
| `TestGetLogsSafeRetry` | test_m8_ws_listener.py | 5 | 408 retry, timeout retry, non-transient no-retry, exhausted retries |
| `TestR7NewArtifactFields` | test_m8_sniper_artifacts.py | 11 | self_test_by_dex, run_scope, dex_filter contract |
| `TestIsolatedRunRollingIsolation` | test_m8_sniper_artifacts.py | 3 | --dex artifact goes to data/tmp/, not _rolling/ |

---

## Historical Archive Probes (R6, 2026-05-14)

All 4 run against known block ranges with confirmed on-chain events:

| DEX                | Block Range           | raw | parse_ok | parse_rate |
|--------------------|-----------------------|-----|----------|------------|
| aerodrome_slipstream | 45920743-45921242   | 1   | 1        | 100%       |
| aerodrome/ve33     | 45925000-45926000     | 1   | 1        | 100%       |
| uniswap_v3         | 45946914-45947413     | 2   | 2        | 100%       |
| pancakeswap_v3     | 45926100-45926500     | 1   | 1        | 100%       |

---

## Code Changes (Round-7)

### m8/runtime/smoke_run.py
- `_get_logs_safe(w3, params, retries=3, retry_delay_s=2.0)`: retries on "408" or "timeout" in err_str; other errors break immediately; returns `(logs, had_error, error_str)`
- `_run_self_test()` return type changed to `(bool, Dict[str, Any])` — returns `(all_pass, results_by_dex)` where results_by_dex maps dex -> `{raw, parse_ok, parse_failed, range, status}`
- Call site: `self_test_ok, self_test_results = _run_self_test(w3, configs, args.chain)` → `funnel.set_self_test_results(self_test_results)`
- `funnel.set_run_scope(run_scope="all" if not _dex_filter else _dex_filter, dex_filter=_dex_filter)` added
- **Step 8 BUG FIX**: when `dex_filter` set, artifact writes to `data/tmp/new_pool_sniper_{dex}_latest.json` (not `_rolling/`)

### monitoring/sniper_funnel.py
- `FunnelTracker.__init__`: added `self._self_test_by_dex`, `self._run_scope`, `self._dex_filter`
- New methods: `set_self_test_results(results)`, `set_run_scope(run_scope, dex_filter=None)`
- `snapshot()` now includes `self_test_by_dex`, `run_scope`, `dex_filter`

### monitoring/sniper_artifacts.py
- `make_sniper_artifact()`: new keyword-only params `self_test_by_dex=None`, `run_scope="all"`, `dex_filter=None`
- Artifact JSON: three new top-level fields `run_scope`, `dex_filter`, `self_test_by_dex`

### tests/unit/test_m8_ws_listener.py (+7 new tests, R7)
- `TestAerodromeVe33WSCallback.test_aerodrome_ws_ack_and_notification_increments_callback`
- `TestAerodromeVe33WSCallback.test_aerodrome_ws_log_parses_via_funnel_pipeline`
- `TestGetLogsSafeRetry.test_succeeds_immediately_when_no_error`
- `TestGetLogsSafeRetry.test_retries_on_408_and_succeeds`
- `TestGetLogsSafeRetry.test_retries_on_timeout_keyword_and_succeeds`
- `TestGetLogsSafeRetry.test_non_transient_error_not_retried`
- `TestGetLogsSafeRetry.test_exhausted_retries_returns_error`

### tests/unit/test_m8_sniper_artifacts.py (+14 new tests, R7)
- `TestR7NewArtifactFields` (11 tests): self_test_by_dex, run_scope, dex_filter contract
- `TestIsolatedRunRollingIsolation` (3 tests): --dex artifact isolation from _rolling

---

## Current Blockers

1. **PLAIN_CI_BLOCKED_BY_INTENT_TIER_LIMIT** — pre-existing; 77 pairs vs 64 baseline.
   Workaround: `check_repo_safety.py --allow-intent-edit` → PASS. Not M8-specific.

2. **FRESH_ALL_FACTORY_R7_GATE_REQUIRED** — `_rolling/new_pool_sniper_latest.json` is old-contract
   (pre-R7, lacks `self_test_by_dex`, `run_scope`, `dex_filter`). Phase 1 close requires a fresh
   all-factory `--prefer-ws` run (≥15 min, no `--dex`, no `--skip-self-test`) that produces a
   new-contract artifact in `_rolling`.

3. **M8_MULTI_FACTORY_LIVE_PARSE_OK_MARKET_WINDOW** — uniswap_v3 proven live (R6 gate, 3
   candidates). Non-uniswap DEXes raw_logs=0 in R6 window (market-window, not code bug).
   Status pending re-validation in fresh R7 gate.

---

## Phase 1 Close Status

- all 4 factory parsers: historical archive probe PASS (4/4 proven in R6)
- WS infra: ws_connected, auto-reconnect, rpc_error_rate <5% (proven in R6 1h gate)
- Live parse_ok>0 for ≥1 DEX: YES (uniswap_v3, R6 gate)
- Artifact contract: R7 code adds self_test_by_dex, run_scope, dex_filter — unit tests PASS
- **phase1_close_allowed: false (pending fresh all-factory R7 runtime gate)**
- Condition for true: `_rolling/new_pool_sniper_latest.json` from R7 code has `run_scope="all"` and `self_test_by_dex` non-empty
