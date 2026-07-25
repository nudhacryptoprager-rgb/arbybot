# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-08T08:18:55
canonical_rolling_timestamp: 2026-07-08T08:18:55
smoke_run_timestamp: 2026-07-25T08:59:57Z
goal_status: IN_PROGRESS
runtime_smoke: prior 1-minute smoke on stale bridge — do not repeat until fresh M8→M9 bundle
economics_claim: NOT_PROVEN
docs_reread_confirmed: true
run_id: m9-universe-contract-control-plane-2026-07-25
mode: offline CI + code fixes (no fresh online bundle this session)
config: config/exotic_base_anchor.yaml
rolling_run_dir: data/runs/ci_m5_gate_arbitrum_one_20260708_101645_712808
smoke_evidence_artifacts: data/tmp/m9_capacity_cycle_diagnostic_smoke.json, data/tmp/m9_shadow_capacity_smoke.json, data/tmp/m9_lane_acceptance_smoke.json

## Session Completion
session_goal: Tighten session/universe contracts between capacity diagnostic and runner; fix control-plane cache, trace ledger, and provenance stamping
goal_status: IN_PROGRESS
primary_blocker_of_session: CAPACITY_UNIVERSE_MISMATCH / mixed admission policy between capacity diagnostic and runner
blocker_status_before: capacity valid cycles could disagree with runner topology; session binding allowed missing provenance.session_id; topology-only mirror counted as verified
blocker_status_after: IN_PROGRESS — shared universe_contract enforced; strict session binding; verified mirror requires quote-ready; awaiting fresh aligned M8→M9 bundle
close_allowed: false
close_reason: IN_PROGRESS — code fixes landed; fresh online bundle and aligned smoke not yet run
remaining_blockers: fresh canonical M8→M9 session; regenerate capacity diagnostic with universe_contract; rerun 1-minute capacity smoke on aligned bundle
evidence_session_run_dirs: none (code-only session)
docs_reread_confirmed: true

## Code changes

1. `m8/discovery/token_classify.py`: strict session — non-empty `provenance.session_id` required when pipeline/expected session is set.
2. `m9/graph_arb/verified_mirror.py`: verified mirror requires `factory_verified` + quote-ready; `mirror_topology_ready` diagnostic-only.
3. `m9/graph_arb/universe_contract.py`: shared contract (inventory, config, lane, factory verification, cycle lengths, economics profile, session).
4. `m9/graph_arb/runner.py`: fail-close `EXIT_CAPACITY_UNIVERSE_MISMATCH` when capacity artifact universe differs; blocked shadow artifacts stamped via `apply_pipeline_provenance`.
5. `scripts/m9_capacity_cycle_diagnostic.py`: productive lane defaults `require_factory_verified=True`; cycle lengths from config scan_params; stamps `universe_contract`.
6. `m9/graph_arb/cycle_capacity.py`: passes `require_factory_verified` into graph build.
7. `api/control_cache.py`: process-wide `get_control_projection_cache()` singleton.
8. `monitoring/dashboard_server.py`: legacy `/api/control/*` uses singleton + `If-None-Match` ETag.
9. `api/control_projection.py`: trace ledger uses real `token_address`, `pool_address`, `route_id`, `cycle_id`; reject reasons as `reject_reason` entity type.
10. `tests/unit/test_m9_runner_config_gates.py`: gate tests write artifacts to temp path, not rolling `m9_graph_latest.json`.

Status files not updated (no fresh same-session online evidence).

## Fresh runtime evidence

| Source | Timestamp | Note |
|--------|-----------|------|
| canonical rolling (`run_summary_latest`) | 2026-07-08T08:18:55 | unchanged baseline |
| prior smoke capacity | 2026-07-25T08:59:57Z | stale bridge — admission only, not economics |
| prior smoke shadow | 2026-07-25 | `NO_CAPACITY_VALID_CYCLES` — universe mismatch root cause |

Do not treat prior smoke as current readiness. Regenerate capacity + shadow only after fresh M8→M9 bundle.

## Pipeline

Run after merge:

```powershell
py -3.11 -m pytest tests/unit/test_artifact_provenance.py tests/unit/test_verified_mirror.py tests/unit/test_control_projection.py tests/unit/test_m9_shadow_lane.py tests/unit/test_m8_token_classify.py tests/unit/test_m9_graph_artifact.py tests/unit/test_read_only_api.py tests/unit/test_universe_contract.py -q
py -3.11 scripts/check_repo_safety.py
py -3.11 scripts/ci_full_pipeline.py --mode ci
git diff --check
```

## Next

1. Fresh canonical M8→M9 bundle (same `session_id` across bridge, capacity, shadow).
2. Regenerate `m9_capacity_cycle_diagnostic` with aligned universe contract.
3. 1-minute capacity smoke only on that bundle.
4. Update `Status_M8*.md` / `Status_M9.md` only after same-session online evidence.
