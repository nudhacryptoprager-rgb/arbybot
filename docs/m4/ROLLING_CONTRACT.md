# M4 Rolling Contract

Schema and data contract for M4 execution gate rolling artifacts.

## Schema Versions

| File | Schema | Version | Description |
|------|--------|---------|-------------|
| `_latest.json` | `m4:latest` | v1.6 | Latest run pointer |
| `run_summary_latest.json` | `run:summary` | v1.6 | Full run summary |
| `m4_stability_agg.json` | `m4:stability_agg` | v1.5 | Rolling aggregator |

## _latest.json (m4:latest:v1.6)

```json
{
  "schema_version": "m4:latest:v1.6",
  "updated_at": "ISO8601",
  "latest_run_code_sha": "abc1234",       // SHA of code that ran scan
  "attached_evidence_sha": "def5678",     // SHA attached post-commit (null if not attached)
  "repo_head_sha_at_attach": "def5678",   // HEAD when attach_evidence ran
  "evidence_attached_at": "ISO8601",      // When evidence was attached
  "run_context": {
    "code_sha": "abc1234",                // Same as latest_run_code_sha
    "code_dirty": true,                   // True if uncommitted changes at run time
    "code_desc": "abc1234-dirty",         // Human-readable description
    "evidence_sha": "def5678"             // Same as attached_evidence_sha
  },
  "latest_mode": "ONLINE",                // ONLINE or OFFLINE
  "latest_kind": "NORMAL",                // NORMAL or INCIDENT
  "run_status": "PASS",                   // PASS, WARN, FAIL, NO_DATA
  "threshold_profile_name": "profit",     // Profile used
  "agg_status": "PASS_WARMUP",           // Aggregate status from rolling window
  "agg_reasons": ["WARMUP_MIN_RUNS"],    // Reasons for agg_status
  "runs_in_window": 5,
  "in_warmup": true,
  "total_signals_in_window": 15,
  "paths": {
    "run_summary_latest": "_rolling/run_summary_latest.json",
    "rolling_agg": "_rolling/m4_stability_agg.json",
    "last_incident": null
  }
}
```

## run_summary (run:summary:v1.6)

```json
{
  "schema_version": "run:summary:v1.6",
  "timestamp": "ISO8601",
  "source_sha": "abc1234",               // DEPRECATED: alias to run_context.code_sha
  "run_id": "manual_run_20260209_120000",
  "run_context": {
    "code_sha": "abc1234",
    "code_dirty": false,
    "code_desc": "abc1234-clean",
    "evidence_sha": null
  },
  "evidence": {
    "ok": true,
    "issues": [],
    "current_sha": "abc1234"
  },
  "metrics": {
    "signals_count": 5,
    "simulations_count": 5,
    "total_net_usdc": 12.50,
    "mae_net_usdc": 0.25,
    "fragile_rate": 0.20
  },
  "status": "PASS",
  "profit_status": "PASS",
  "drift_status": "PASS",
  "reasons": []
}
```

## m4_stability_agg (m4:stability_agg:v1.5)

```json
{
  "schema_version": "m4:stability_agg:v1.5",
  "created_at": "ISO8601",
  "runs": [
    {
      "run_id": "...",
      "timestamp": "ISO8601",
      "code_sha": "abc1234",
      "net_usdc": 5.00,
      "mae": 0.25,
      "sign_rate": 1.0,
      "reasons": [],
      "fragile_rate": 0.10,
      "signals_count": 3,
      "run_status": "PASS"
    }
  ],
  "rolling_window": {
    "max": 200,
    "current": 10,
    "min_runs": 10,
    "min_signals": 30,
    "in_warmup": false
  },
  "quick_stats": {
    "pass_count": 9,
    "fail_count": 0,
    "no_data_count": 1,
    "total_signals": 25
  },
  "agg_status": "PASS_WARMUP"
}
```

## Deprecations

### source_sha (v1.9.3)

The `source_sha` field in `run_summary` is **deprecated**.

- Previously: Used to match artifact provenance with git HEAD
- Issue: Created confusing SHA_MISMATCH errors
- Now: `source_sha` is always an alias to `run_context.code_sha`
- Canonical: Use `run_context.code_sha` (run time) and `evidence_sha` (post-commit)

## Evidence Workflow

```
1. Run scan              → code_sha = HEAD, code_dirty = true/false
2. Commit changes        → git commit
3. Attach evidence       → python scripts/attach_evidence.py
4. Verify                → evidence_sha != null, evidence.ok = true
```

For **PROVEN** status, require:
- `code_dirty = false` (clean worktree at run time)
- `evidence_sha` attached post-commit
- `evidence.ok = true`
