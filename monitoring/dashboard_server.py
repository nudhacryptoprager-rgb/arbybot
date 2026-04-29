"""
Lightweight rolling-artifact dashboard server.

Read-only surface over the canonical rolling artifacts:
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json

Usage:
    py -3.11 -m monitoring.dashboard_server [--port 8099]
    Then open http://localhost:8099 in a browser.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROLLING_DIR = Path("data/runs/_rolling")

# Reviewer soak baselines snapshotted by bootstrap_system.ps1 at supervisor start.
# Used to compute fresh current-scan deltas separately from lifetime cumulative totals.
BASELINE_FILES = {
    "production": ROLLING_DIR / "reviewer_soak_baseline_latest.json",
    "discovery": ROLLING_DIR / "reviewer_soak_baseline_latest_discovery.json",
}

# Cumulative totals exposed in /api/summary primary funnel. Each must be either:
#   - subtracted from baseline to derive current-scan delta, OR
#   - read directly from rollup.session.session_*_total when available.
SESSION_TOTAL_FIELDS = (
    "events_seen_total",
    "fast_score_attempted_total",
    "fast_path_scored_total",
    "fast_path_positive_total",
    "route_viable_total",
    "profit_guard_passed_total",
    "sim_attempted_total",
    "sim_passed_total",
    "submit_ready_total",
    "roundtrip_attempted_total",
    "roundtrip_success_total",
    "roundtrip_profitable_total",
)

# Freshness threshold for the primary current_scan view. If
# now - last_updated > FRESHNESS_THRESHOLD_S, dashboard must mark stale.
# soak18: tunable via ARBY_DASHBOARD_FRESHNESS_S env (operator-side knob
# so production vs discovery can use different cadences without code
# changes). Default 120s.
# soak18 step 5: discovery profile may legitimately publish slower than
# production (longer scan, fewer events). ARBY_DASHBOARD_FRESHNESS_S_DISCOVERY
# overrides the threshold for the discovery profile only; production
# keeps the default 120s knob.
def _read_threshold_env(name: str, default: int = 120) -> int:
    try:
        v = int(os.environ.get(name, str(default)))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


FRESHNESS_THRESHOLD_S = _read_threshold_env("ARBY_DASHBOARD_FRESHNESS_S", 120)
FRESHNESS_THRESHOLD_S_DISCOVERY = _read_threshold_env(
    "ARBY_DASHBOARD_FRESHNESS_S_DISCOVERY", FRESHNESS_THRESHOLD_S
)

ARTIFACT_FILES = {
    "run_summary": ROLLING_DIR / "run_summary_latest.json",
    "stability_agg": ROLLING_DIR / "m4_stability_agg.json",
    "long_scan": ROLLING_DIR / "long_scan_latest.json",
    "hot_loop": ROLLING_DIR / "hot_loop_latest.json",
    "m7_orderflow": ROLLING_DIR / "m7_orderflow_latest.json",
    "m7_hot": ROLLING_DIR / "m7_hot_latest.json",
    "m7_hot_intents": ROLLING_DIR / "m7_hot_intents_latest.json",
    "m7_cold_hot_bridge": ROLLING_DIR / "m7_cold_hot_bridge.json",
    "m7_hot_rollup": ROLLING_DIR / "m7_hot_rollup_latest.json",
}

# E1.9.3: Discovery namespace artifacts (parallel to production)
DISCOVERY_ARTIFACT_FILES = {
    "m7_orderflow": ROLLING_DIR / "m7_orderflow_latest_discovery.json",
    "m7_hot": ROLLING_DIR / "m7_hot_latest_discovery.json",
    "m7_hot_intents": ROLLING_DIR / "m7_hot_intents_latest_discovery.json",
    "m7_cold_hot_bridge": ROLLING_DIR / "m7_cold_hot_bridge_discovery.json",
    "m7_hot_rollup": ROLLING_DIR / "m7_hot_rollup_latest_discovery.json",
    "m7_discovery_scoreboard": ROLLING_DIR / "m7_discovery_scoreboard_discovery.json",
}

DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


class DashboardHandler(SimpleHTTPRequestHandler):
    """Serves dashboard HTML and rolling artifact JSON."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            self._serve_file(DASHBOARD_HTML, "text/html")
        elif path == "/api/rolling":
            self._serve_rolling_data()
        elif path == "/api/hot":
            self._serve_hot_data()
        elif path == "/api/discovery":
            self._serve_discovery_data()
        elif path == "/api/summary":
            # M7.E1.34k+soak17: top-of-dashboard summary with strict
            # current-scan vs historical-cumulative separation.
            qs = parse_qs(parsed.query or "")
            profile = (qs.get("profile") or ["production"])[0]
            if profile not in ("production", "discovery"):
                profile = "production"
            self._serve_summary_data(profile=profile)
        else:
            self.send_error(404)

    def _serve_file(self, path: Path, content_type: str):
        if not path.is_file():
            self.send_error(404, f"Not found: {path.name}")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_rolling_data(self):
        """Load all 4 rolling artifacts and return as single JSON."""
        result = {}
        for key, path in ARTIFACT_FILES.items():
            if path.is_file():
                try:
                    with open(path, encoding="utf-8") as f:
                        result[key] = json.load(f)
                except (json.JSONDecodeError, OSError):
                    result[key] = None
            else:
                result[key] = None

        payload = json.dumps(result, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_hot_data(self):
        """M7.A.5.46: Serve M7 hot lane artifacts only.

        Returns m7_hot + m7_hot_intents + m7_hot_rollup. Panel 0 (hot_loop) uses /api/rolling.
        """
        result = {"m7_hot": None, "m7_hot_intents": None, "m7_hot_rollup": None}
        for key in ("m7_hot", "m7_hot_intents", "m7_hot_rollup"):
            path = ARTIFACT_FILES[key]
            if not path.is_file():
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    result[key] = json.load(f)
            except (json.JSONDecodeError, OSError):
                result[key] = None
        payload = json.dumps(result, default=str).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_discovery_data(self):
        """E1.9.3: Serve discovery namespace M7 artifacts."""
        result = {}
        for key, path in DISCOVERY_ARTIFACT_FILES.items():
            if path.is_file():
                try:
                    with open(path, encoding="utf-8") as f:
                        result[key] = json.load(f)
                except (json.JSONDecodeError, OSError):
                    result[key] = None
            else:
                result[key] = None
        payload = json.dumps(result, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_summary_data(self, profile: str = "production"):
        """M7.E1.34k + soak17 dashboard contract.

        Returns a strict two-block payload:
          - ``current_scan``: counts derived from the active supervisor
            session (delta from reviewer_soak_baseline_latest snapshot
            and/or rollup.session.session_*_total fields). Includes
            ``is_fresh`` / ``staleness_reason`` so the dashboard can
            refuse to render stale data as "current".
          - ``historical_cumulative``: lifetime ``*_total`` counters
            untouched, so the operator can still inspect long-running
            totals — but they MUST NOT be presented as the primary
            verdict.

        Profile selects between production and discovery namespaces.
        """
        files = (
            DISCOVERY_ARTIFACT_FILES if profile == "discovery" else ARTIFACT_FILES
        )
        baseline_path = BASELINE_FILES[profile]

        def _load(key):
            path = files.get(key)
            if path is None or not path.is_file():
                return None
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return None

        rollup = _load("m7_hot_rollup") or {}
        hot = _load("m7_hot") or {}
        orderflow = _load("m7_orderflow") or {}
        bridge = _load("m7_cold_hot_bridge") or {}
        baseline = None
        if baseline_path.is_file():
            try:
                with open(baseline_path, encoding="utf-8") as f:
                    baseline = json.load(f)
            except (json.JSONDecodeError, OSError):
                baseline = None

        summary = build_summary_payload(
            rollup=rollup,
            hot=hot,
            orderflow=orderflow,
            baseline=baseline,
            profile=profile,
            now_utc=datetime.now(timezone.utc),
            bridge=bridge,
        )

        payload = json.dumps(summary, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        """Suppress default logging noise."""
        pass


def _safe_int(value) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_iso_utc(value):
    if not isinstance(value, str) or not value:
        return None
    txt = value.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _top_hist(hist, n: int = 8):
    if not isinstance(hist, dict):
        return []
    return sorted(
        ({"reason": k, "count": _safe_int(v)} for k, v in hist.items()),
        key=lambda x: (-x["count"], x["reason"]),
    )[:n]


def build_summary_payload(
    *,
    rollup: dict,
    hot: dict,
    orderflow: dict,
    baseline: dict | None,
    profile: str,
    now_utc: datetime,
    bridge: dict | None = None,
) -> dict:
    """Pure builder for /api/summary — unit-testable.

    Splits primary view into ``current_scan`` (fresh delta vs baseline,
    plus session_*_total when available) and ``historical_cumulative``
    (raw lifetime totals).
    """
    rollup = rollup or {}
    hot = hot or {}
    orderflow = orderflow or {}
    baseline = baseline or {}
    bridge = bridge or {}

    session = rollup.get("session") if isinstance(rollup.get("session"), dict) else {}
    baseline_session = (
        baseline.get("session")
        if isinstance(baseline.get("session"), dict)
        else {}
    )
    current_session_id = session.get("session_id")
    baseline_session_id = baseline_session.get("session_id")
    session_id_match = bool(
        baseline_session_id
        and current_session_id
        and baseline_session_id == current_session_id
    )

    # Freshness — based on rollup.last_updated.
    last_updated_raw = rollup.get("last_updated")
    last_updated_dt = _parse_iso_utc(last_updated_raw)
    age_seconds = None
    is_fresh = False
    staleness_reason = None
    # soak18 step 5: discovery profile gets its own threshold knob.
    threshold = (
        FRESHNESS_THRESHOLD_S_DISCOVERY
        if profile == "discovery"
        else FRESHNESS_THRESHOLD_S
    )
    if last_updated_dt is None:
        staleness_reason = "MISSING_LAST_UPDATED"
    else:
        age_seconds = (now_utc - last_updated_dt).total_seconds()
        if age_seconds < 0:
            # Future timestamp (clock skew) — treat as fresh.
            age_seconds = 0.0
        if age_seconds <= threshold:
            is_fresh = True
        else:
            staleness_reason = (
                f"STALE: age={int(age_seconds)}s>{threshold}s"
            )
        # soak18 step 1: BASELINE_NOT_REFRESHED — supervisor restarted
        # and snapshotted a baseline whose last_updated equals the
        # current rollup last_updated. That means the lane has not
        # written ANY fresh rollup yet, so deltas are mathematically
        # zero and the primary view must NOT report as fresh.
        baseline_last_updated_raw = baseline.get("last_updated")
        if (
            is_fresh
            and baseline_last_updated_raw
            and baseline_last_updated_raw == last_updated_raw
        ):
            is_fresh = False
            staleness_reason = "BASELINE_NOT_REFRESHED"

    # ---- current_scan.gate_funnel -----------------------------------------
    # Prefer rollup.session.session_*_total when available; otherwise
    # derive delta = current_total - baseline_total. If the session_id
    # rotated relative to baseline, deltas may be approximate but never
    # fall back to raw lifetime totals.
    def _delta(field: str) -> int:
        cur = _safe_int(rollup.get(field))
        base = _safe_int(baseline.get(field)) if baseline else 0
        return max(0, cur - base)

    def _session_or_delta(session_field: str, total_field: str) -> int:
        if session_field and session.get(session_field) is not None:
            return _safe_int(session.get(session_field))
        return _delta(total_field)

    current_funnel = {
        "events_seen": _session_or_delta(
            "session_events_seen_total", "events_seen_total"
        ),
        "fast_score_attempted": _session_or_delta(
            "session_fast_score_attempted_total", "fast_score_attempted_total"
        ),
        "fast_path_scored": _session_or_delta(
            "session_fast_path_scored_total", "fast_path_scored_total"
        ),
        "fast_path_positive": _session_or_delta(
            "session_fast_path_positive_total", "fast_path_positive_total"
        ),
        "route_viable": _delta("route_viable_total"),
        "profit_guard_passed": _delta("profit_guard_passed_total"),
        "sim_attempted": _delta("sim_attempted_total"),
        "sim_passed": _delta("sim_passed_total"),
        "submit_ready": _delta("submit_ready_total"),
        "roundtrip_attempted": _delta("roundtrip_attempted_total"),
        "roundtrip_success": _delta("roundtrip_success_total"),
        "roundtrip_profitable": _delta("roundtrip_profitable_total"),
    }

    # ---- top_spreads (already session-scoped in source artifacts) ---------
    top_source = (
        hot.get("top_hot_candidates")
        or orderflow.get("top_executable_candidates")
        or orderflow.get("top_route_viable_candidates")
        or []
    )
    top_spreads = []
    for cand in top_source[:10]:
        if not isinstance(cand, dict):
            continue
        if cand.get("submit_ready") is True:
            gate, passed = "submit_ready", True
        elif cand.get("roundtrip_success") is True:
            gate, passed = "roundtrip_success", True
        elif cand.get("roundtrip_attempted"):
            gate, passed = "roundtrip_failed", False
        elif cand.get("sim_passed") or cand.get("scored_net_bps") is not None:
            passed = bool(cand.get("sim_passed"))
            gate = "sim_passed" if passed else "scored"
        elif cand.get("profit_guard_passed"):
            gate, passed = "profit_guard_passed", True
        elif cand.get("reject_reason") or cand.get("guard_reject_reason"):
            gate = (
                cand.get("guard_reject_reason") or cand.get("reject_reason")
            )
            passed = False
        else:
            gate, passed = "scored", True
        top_spreads.append({
            "pair": cand.get("pair") or cand.get("actual_pair") or "?",
            "venue": cand.get("best_buy_venue") or cand.get("venue"),
            "net_bps": cand.get("scored_net_bps")
                or cand.get("best_net_bps")
                or cand.get("net_bps"),
            "roundtrip_profit_bps": cand.get("roundtrip_profit_bps"),
            "gate_reached": gate,
            "passed": passed,
        })

    # ---- scope ------------------------------------------------------------
    reg = orderflow.get("registry_session_stats") or {}
    pairs_monitored = (
        reg.get("unique_pairs_queried")
        or reg.get("pairs_active")
        or session.get("session_pairs_active")
        or 0
    )
    pools_monitored = (
        reg.get("pools_active")
        or rollup.get("bridge_focused_pool_count_last")
        or hot.get("bridge_focused_pool_count")
        or 0
    )

    # ---- universe_breadth (reviewer post-soak19 step 6) -------------------
    # Single-glance view of how wide the scanner is searching. Production
    # readiness requires growing the active pool count from ~50 (smoke) to
    # 200+ (warm) to 1000+ (cold) — see docs/m4/DASHBOARD_API_CONTRACT.md.
    _bridge_breakdown = (
        bridge.get("candidate_source_breakdown") if isinstance(bridge, dict) else None
    ) or {}
    universe_breadth = {
        "intent_pairs": _safe_int(reg.get("unique_pairs_queried")),
        "pools_discovered_total": _safe_int(reg.get("pools_discovered")),
        "pools_active_total": _safe_int(reg.get("pools_active")),
        "ptt_total": _safe_int(_bridge_breakdown.get("ptt_total")),
        "bridge_focused_pool_count": _safe_int(
            rollup.get("bridge_focused_pool_count_last")
            or hot.get("bridge_focused_pool_count")
        ),
        "bridge_pool_hit_total": _safe_int(rollup.get("bridge_pool_hit_total")),
        "registry_hit_for_event_pool_total": _safe_int(
            rollup.get("registry_hit_for_event_pool_total")
        ),
        "hot_seen_unresolved_pool_count": _safe_int(
            rollup.get("hot_seen_unresolved_pool_count")
        ),
        "candidate_source_breakdown": {
            k: _safe_int(v)
            for k, v in _bridge_breakdown.items()
            if k != "ptt_total"
        } if _bridge_breakdown else {},
    }

    # ---- reject buckets (window-recent, not lifetime) ---------------------
    reject_buckets = {
        "guard": _top_hist(rollup.get("guard_reject_reason_histogram")),
        "simulation": _top_hist(rollup.get("simulation_error_histogram")),
        "submit_blocker": _top_hist(rollup.get("submit_blocker_histogram")),
        "roundtrip_error": _top_hist(rollup.get("roundtrip_error_histogram")),
        "reject_histogram": _top_hist(orderflow.get("reject_histogram")),
    }

    # ---- session state / exit reasons -------------------------------------
    session_state = None
    try:
        sess_path = ROLLING_DIR / "m7_session_state.json"
        if sess_path.is_file():
            with open(sess_path, encoding="utf-8") as sf:
                session_state = json.load(sf)
    except (json.JSONDecodeError, OSError):
        session_state = None
    exit_reason_hist = session.get("session_exit_reason_histogram") or {}
    last_exit_reason = session.get("last_exit_reason")

    # ---- historical_cumulative -------------------------------------------
    historical_cumulative = {
        f: _safe_int(rollup.get(f)) for f in SESSION_TOTAL_FIELDS
    }
    historical_cumulative["roundtrip_profit_bps"] = {
        "best": rollup.get("roundtrip_profit_bps_best"),
        "worst": rollup.get("roundtrip_profit_bps_worst"),
        "median": rollup.get("roundtrip_profit_bps_median"),
        "outliers_dropped": rollup.get("roundtrip_profit_bps_outliers_dropped"),
    }

    current_scan = {
        "profile": profile,
        "session_id": current_session_id,
        "session_started_at": session.get("session_started_at"),
        "last_updated": last_updated_raw,
        "age_seconds": age_seconds,
        "is_fresh": is_fresh,
        "staleness_reason": staleness_reason,
        "baseline_session_id": baseline_session_id,
        "session_id_match_baseline": session_id_match,
        "scope": {
            "pairs_monitored": pairs_monitored,
            "pools_monitored": pools_monitored,
            "bridge_focused_pool_count_last": rollup.get(
                "bridge_focused_pool_count_last", 0
            ),
        },
        "universe_breadth": universe_breadth,
        "gate_funnel": current_funnel,
        # M7.E1.34f post-soak19 reviewer fix #4: explicit guard to prevent
        # UI/reader from conflating local-quote profitability checks with
        # production profit truth. Production profit is recognised ONLY
        # when roundtrip_profitable_total > 0; verified_profitable in
        # compact rows reflects local quote + sim agreement, not real PnL.
        "production_profit_guard": {
            "production_profit_truth_metric": "roundtrip_profitable_total",
            "production_profit_truth_value": _safe_int(
                rollup.get("roundtrip_profitable_total")
            ),
            "verified_profitable_meaning": (
                "local_quote_passed AND sim_passed AND scorer_sim_divergence_ok"
            ),
            "is_production_profit_observed": (
                _safe_int(rollup.get("roundtrip_profitable_total")) > 0
            ),
            "disclaimer": (
                "verified_profitable in compact candidate rows is NOT a "
                "production profit signal. It only attests local-quote "
                "agreement with sim. Real production truth requires "
                "roundtrip_profitable_total > 0 in m7_hot_rollup."
            ),
        },
        # Reviewer post-soak19 fix #4: surface event-pipeline latency budget
        # so dashboard readers see whether the hot path stays inside the Base
        # 200ms Flashblock window. Sourced verbatim from
        # ``m7_hot_rollup.latency_budget`` to keep one source of truth.
        "latency_budget": (
            rollup.get("latency_budget")
            if isinstance(rollup.get("latency_budget"), dict)
            else {
                "samples_total": 0,
                "p50_ms": None,
                "p90_ms": None,
                "p99_ms": None,
                "max_ms": None,
                "target_ms": 200.0,
                "within_target_pct": None,
                "stage_breakdown": None,
            }
        ),
        "top_spreads": top_spreads,
        "reject_buckets": reject_buckets,
        "session_ws_recv_error_total": _safe_int(
            session.get("session_ws_recv_error_total")
        ),
        "session_ws_reconnect_total": _safe_int(
            session.get("session_ws_reconnect_total")
        ),
        "last_exit_reason": last_exit_reason,
    }

    summary = {
        "schema_version": "summary_v2",
        "timestamp": last_updated_raw,
        "now_utc": now_utc.isoformat(),
        "chain": rollup.get("chain"),
        "profile": profile,
        "simulation_backend": rollup.get("simulation_backend"),
        "sim_disabled": rollup.get("sim_disabled"),
        "current_scan": current_scan,
        "historical_cumulative": historical_cumulative,
        # Auxiliary blocks (not part of primary verdict, but useful UI).
        "funnel_debug": hot.get("funnel_debug") or {},
        "session_state": session_state,
        "exit_reason_histogram": exit_reason_hist,
        # ----- Backward-compat: pre-soak17 keys retained so any older
        # client gets the same shape it used to. NEW clients MUST read
        # current_scan / historical_cumulative instead.
        # soak18 step 6: every legacy top-level block carries
        # `_deprecated:true` (when shape allows) and is also listed in
        # `_deprecated_top_level_keys` so any client can detect it
        # programmatically. List/array blocks (top_spreads) cannot carry
        # an inline flag and are tracked only by the meta key. -----
        "_deprecated_top_level_keys": [
            "scope",
            "top_spreads",
            "gate_funnel",
            "reject_buckets",
            "current_session_id",
            "last_exit_reason",
        ],
        "scope": current_scan["scope"] | {
            "bridge_loaded_candidate_count_total": _safe_int(
                rollup.get("bridge_loaded_candidate_count_total")
            ),
            "_deprecated": True,
        },
        "top_spreads": top_spreads,
        "gate_funnel": {  # legacy: lifetime totals (deprecated)
            "events_seen": historical_cumulative["events_seen_total"],
            "fast_score_attempted": historical_cumulative[
                "fast_score_attempted_total"
            ],
            "fast_path_scored": historical_cumulative["fast_path_scored_total"],
            "fast_path_positive": historical_cumulative[
                "fast_path_positive_total"
            ],
            "route_viable": historical_cumulative["route_viable_total"],
            "profit_guard_passed": historical_cumulative[
                "profit_guard_passed_total"
            ],
            "sim_attempted": historical_cumulative["sim_attempted_total"],
            "sim_passed": historical_cumulative["sim_passed_total"],
            "submit_ready": historical_cumulative["submit_ready_total"],
            "roundtrip_attempted": historical_cumulative[
                "roundtrip_attempted_total"
            ],
            "roundtrip_success": historical_cumulative["roundtrip_success_total"],
            "roundtrip_profitable": historical_cumulative[
                "roundtrip_profitable_total"
            ],
            "_deprecated": True,
        },
        "reject_buckets": (
            reject_buckets | {"_deprecated": True}
            if isinstance(reject_buckets, dict)
            else reject_buckets
        ),
        "current_session_id": current_session_id,
        "last_exit_reason": last_exit_reason,
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description="ARBY rolling dashboard")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()

    os.chdir(Path(__file__).parent.parent)

    server = HTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print(f"Dashboard: http://127.0.0.1:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
