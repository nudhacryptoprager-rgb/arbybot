# M4 Rolling Contract

Schema and data contract for M4 execution gate rolling artifacts.

## Schema Versions

| File | Schema | Version | Description |
|------|--------|---------|-------------|
| `_latest.json` | `m4:latest` | v2.0 | Latest run pointer (timestamp provenance) |
| `run_summary_latest.json` | `m4:run_summary` | v2.0 | Full run summary |
| `m4_stability_agg.json` | `m4:stability_agg` | v2.0 | Rolling aggregator |

**Де брати ключові метрики:**
- `signals_count` -> `run_summary_latest.metrics.signals_count`
- `total_net_usdc` -> `run_summary_latest.metrics.total_net_usdc` (per run) / `m4_stability_agg.quick_stats.total_net_usdc` (window)
- `low_sample_rate` -> `m4_stability_agg.quick_stats.low_sample_rate`
- `unique_pairs/unique_routes` -> `m4_stability_agg.quick_stats.unique_pairs/unique_routes`
- `run_mode` -> `run_summary_latest.inputs.run_mode`

## Provenance Model (v2.0.0)

SHA tracking is completely removed. Provenance is based on `run_timestamp` only.

- `run_context.run_timestamp` (ISO-8601) is the primary provenance field
- `code_sha`, `evidence_sha` are `null` (deprecated, kept for schema compatibility)
- `runs_since_timestamp` replaces `runs_since_sha` in aggregator

## _latest.json (m4:latest:v2.0)

```json
{
  "schema_version": "m4:latest:v2.0",
  "updated_at": "ISO8601",
  "latest_run_timestamp": "2026-02-11T10:05:45Z",  // Primary provenance
  "code_identity": "ts:2026-02-11T10:05:45Z",      // v2.0.1
  "run_context": {
    "run_timestamp": "2026-02-11T10:05:45Z",  // Primary provenance
    "code_identity": "ts:2026-02-11T10:05:45Z", // v2.0.1
    "code_sha": null,                         // v2.0: deprecated
    "code_dirty": null,                       // v2.0: deprecated
    "code_desc": null,                        // v2.0: deprecated
    "evidence_sha": null                      // v2.0: deprecated
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
  // v2.0.2: Top-level KPIs for quick access
  "effective_pass_rate": 0.95,
  "data_run_rate": 0.90,
  "low_sample_rate": 0.10,
  "net_diversity_rate": 0.50,
  "quick_stats": { /* ... see m4_stability_agg.quick_stats */ },
  "paths": {
    "run_summary_latest": "_rolling/run_summary_latest.json",
    "rolling_agg": "_rolling/m4_stability_agg.json",
    "last_incident": null
  }
}
```

## run_summary (m4:run_summary:v2.0)

```json
{
  "schema_version": "m4:run_summary:v2.0",
  "policy_version": "2.0.1",
  "timestamp": "ISO8601",
  "run_id": "manual_run_20260209_120000",
  "run_context": {
    "run_timestamp": "2026-02-09T12:00:00Z",  // Primary provenance
    "code_identity": "ts:2026-02-09T12:00:00Z",  // v2.0.1: deterministic code ref
    "code_sha": null,                         // v2.0: deprecated
    "code_dirty": null,                       // v2.0: deprecated
    "code_desc": null,                        // v2.0: deprecated
    "evidence_sha": null                      // v2.0: deprecated
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

## m4_stability_agg (m4:stability_agg:v2.0)

```json
{
  "schema_version": "m4:stability_agg:v2.0",
  "policy_version": "2.0.1",
  "created_at": "ISO8601",
  "runs_since_timestamp": {                      // v2.0: object with metrics (replaces runs_since_sha)
    "sha": null,
    "runs_count": 10,
    "data_runs_count": 10,
    "data_signals_total": 37,
    "no_data_count": 0,
    "low_sample_count": 0,
    "infra_fail_count": 0,
    "pass_count": 10,
    "fail_count": 0,
    "data_run_rate": 1.0,
    "effective_pass_rate": 1.0,
    "fail_rate": 0.0,
    "status": "OK"
  },
  "runs": [
    {
      "run_id": "...",
      "timestamp": "ISO8601",
      "run_timestamp": "2026-02-09T12:00:00Z",  // Primary provenance
      "code_identity": "ts:2026-02-09T12:00:00Z",  // v2.0.1: deterministic code ref
      "code_sha": null,                         // v2.0: deprecated
      "net_usdc": 5.00,
      "mae": 0.25,
      "sign_rate": 1.0,
      "reasons": [],
      "fragile_rate": 0.10,
      "signals_count": 3,
      "run_status": "PASS",
      "is_data_run": true
    }
  ],
  "runs_by_date": {                            // v2.0: replaces runs_by_code_sha
    "2026-02-09": 10
  },
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

## Deprecations (v2.0)

### SHA tracking (removed in v2.0)

All SHA-based provenance fields are deprecated:
- `source_sha` - removed
- `code_sha` - null, kept for schema compatibility
- `code_dirty` - null
- `code_desc` - null
- `evidence_sha` - null
- `runs_since_sha` - replaced by `runs_since_timestamp`

Use `run_timestamp` as the canonical provenance field.

## Provenance Workflow (v2.0)

```
1. Run scan              -> run_timestamp recorded
2. Rolling update        -> runs_since_timestamp tracks window
3. Verify                -> Check run_timestamp in artifacts
```

## DEV vs RELEASE Policy (v2.0)

| Mode | Provenance | Proof |
|------|------------|-------|
| DEV | `run_timestamp` only | Not required |
| RELEASE | `run_timestamp` + `code_identity` | Document in Status_M4.md |

**code_identity** format: `ts:<ISO-8601>` (deterministic, SHA-free)
