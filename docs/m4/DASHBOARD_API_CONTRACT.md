# Dashboard API Contract — `/api/summary` (`summary_v2`)

Read-only HTTP surface served by `monitoring/dashboard_server.py`. The
purpose of this contract is to keep the dashboard's **primary verdict**
based on the *current* supervisor session only. Lifetime cumulative
counters live in a separate, clearly labelled block and must never feed
the primary funnel display.

## Endpoint

```
GET /api/summary
GET /api/summary?profile=production       # default
GET /api/summary?profile=discovery        # discovery namespace
```

## Response shape

```jsonc
{
  "schema_version": "summary_v2",
  "timestamp": "<rollup.last_updated>",
  "now_utc":   "<server-side ISO-8601 UTC>",
  "chain": "base",
  "profile": "production",
  "simulation_backend": "rpc_fork",
  "sim_disabled": false,

  "current_scan": {
    "profile": "production",
    "session_id":            "<rollup.session.session_id>",
    "session_started_at":    "<rollup.session.session_started_at>",
    "last_updated":          "<rollup.last_updated>",
    "age_seconds":           12.34,
    "is_fresh":              true,
    "staleness_reason":      null,                         // or one of:
                                                          //   "MISSING_LAST_UPDATED"
                                                          //   "BASELINE_NOT_REFRESHED"
                                                          //   "STALE: age=<n>s>120s"
    "baseline_session_id":   "<reviewer_soak_baseline_latest.session.session_id>",
    "session_id_match_baseline": true,

    "scope": {
      "pairs_monitored":                 112,
      "pools_monitored":                 230,
      "bridge_focused_pool_count_last":   50
    },

    // Primary funnel — derived per field:
    //   * if rollup.session.session_<field>_total is present → use it
    //   * else delta = max(0, current_total - baseline_total)
    "gate_funnel": {
      "events_seen":            34,
      "fast_score_attempted":   34,
      "fast_path_scored":       10,
      "fast_path_positive":      0,
      "route_viable":            0,
      "profit_guard_passed":     0,
      "sim_attempted":           0,
      "sim_passed":              0,
      "submit_ready":            0,
      "roundtrip_attempted":     0,
      "roundtrip_success":       0,
      "roundtrip_profitable":    0
    },

    "top_spreads":     [ /* up to 10 candidates from m7_hot */ ],
    "reject_buckets":  { /* top guard / sim / submit / roundtrip / orderflow buckets */ },
    "session_ws_recv_error_total": 6,
    "session_ws_reconnect_total":  6,
    "last_exit_reason": "recv_error_reconnect_failed"
  },

  "historical_cumulative": {
    "events_seen_total":          822,
    "fast_score_attempted_total": 822,
    "fast_path_scored_total":     184,
    "fast_path_positive_total":     6,
    "route_viable_total":           6,
    "profit_guard_passed_total":    6,
    "sim_attempted_total":          6,
    "sim_passed_total":             3,
    "submit_ready_total":           0,
    "roundtrip_attempted_total":    3,
    "roundtrip_success_total":      3,
    "roundtrip_profitable_total":   0,
    "roundtrip_profit_bps": {
      "best":              null,
      "worst":             null,
      "median":            null,
      "outliers_dropped":  null
    }
  },

  // Auxiliary blocks (not part of primary verdict; may be empty)
  "funnel_debug":         { /* m7_hot.funnel_debug silent-drop counters */ },
  "session_state":        { /* m7_session_state.json or null */ },
  "exit_reason_histogram":{ /* lifetime WS exit reasons */ },

  // -------- Backward-compat — DEPRECATED, will be removed -------------
  "scope":             { /* same as current_scan.scope + bridge_loaded_candidate_count_total */ },
  "top_spreads":       [ /* mirrored from current_scan.top_spreads */ ],
  "gate_funnel":       { /* lifetime totals, marked _deprecated:true */ },
  "reject_buckets":    { /* mirrored from current_scan.reject_buckets */ },
  "current_session_id":"<rollup.session.session_id>",
  "last_exit_reason":  "<rollup.session.last_exit_reason>"
}
```

## Freshness rules

`current_scan.is_fresh` is `true` **only if all hold**:

1. `rollup.last_updated` exists and parses as ISO-8601 UTC.
2. `now_utc - rollup.last_updated <= ARBY_DASHBOARD_FRESHNESS_S` (default `120`).
3. `baseline.last_updated != rollup.last_updated` (else
   `staleness_reason = "BASELINE_NOT_REFRESHED"` — the lane has not
   produced a single fresh write past the supervisor-start snapshot).

Any failed precondition leaves `is_fresh = false` and populates
`staleness_reason` with one of: `MISSING_LAST_UPDATED`,
`BASELINE_NOT_REFRESHED`, or `STALE: age=<n>s><threshold>s`.

`session_id_match_baseline` is `true` **iff** both `baseline.session.session_id`
and `rollup.session.session_id` are non-empty and equal.

## Funnel derivation rules

For each gate the dashboard uses the first available source:

| field                  | session counter (preferred)              | fallback (baseline-delta) |
|------------------------|-------------------------------------------|----------------------------|
| `events_seen`          | `session.session_events_seen_total`       | `events_seen_total`        |
| `fast_score_attempted` | `session.session_fast_score_attempted_total` | `fast_score_attempted_total` |
| `fast_path_scored`     | `session.session_fast_path_scored_total`  | `fast_path_scored_total`   |
| `fast_path_positive`   | `session.session_fast_path_positive_total` | `fast_path_positive_total` |
| all other fields       | (no session counter today)                | corresponding `*_total`    |

Baseline-delta is always clamped to `max(0, current - baseline)` — snapshot
drift never produces a negative count.

## Environment overrides

| env var                                     | default | effect                                           |
|---------------------------------------------|---------|--------------------------------------------------|
| `ARBY_DASHBOARD_FRESHNESS_S`                | `120`   | freshness threshold for production `current_scan`|
| `ARBY_DASHBOARD_FRESHNESS_S_DISCOVERY`      | mirrors `ARBY_DASHBOARD_FRESHNESS_S` | freshness threshold for discovery profile only |

## Test coverage

`tests/unit/test_dashboard_summary.py` locks the contract:
- two-block separation (`current_scan` vs `historical_cumulative`)
- `submit_ready` reads from baseline-delta, never from lifetime
- `events_seen` reads from `session_events_seen_total` when present
- `is_fresh=false` when stale, `BASELINE_NOT_REFRESHED`, or `MISSING_LAST_UPDATED`
- baseline-delta clamps to zero on snapshot drift
- empty / missing baseline `session.session_id` ⇒ `session_id_match_baseline=false`
- env-tunable freshness threshold (override + invalid fallback)
- end-to-end through real `HTTPServer`, including `?profile=discovery`
  and `404` for unknown routes

## Cross-checking with reviewer

`scripts/reviewer_soak_summary.py --summary-url http://127.0.0.1:8109/api/summary`
fetches the live API verdict and flags `DASHBOARD_DRIFT` when the API
freshness verdict disagrees with the file-based reviewer logic. Drift
must be resolved by aligning `build_summary_payload` with the reviewer
thresholds — never by relaxing tests.

## Backward compatibility

Top-level keys `scope`, `top_spreads`, `gate_funnel`, `reject_buckets`,
`current_session_id`, `last_exit_reason` are retained for clients
written before `summary_v2`. All dict-shaped legacy blocks carry an
inline `_deprecated: true` marker, and the meta key
`_deprecated_top_level_keys` enumerates every deprecated top-level
field so any client can detect them programmatically. The legacy
`gate_funnel` continues to serve **lifetime** totals — new clients
**must not** depend on those values. They will be removed once the
`schema_version` bumps to `summary_v3`.
