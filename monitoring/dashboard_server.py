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
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


ROLLING_DIR = Path("data/runs/_rolling")

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
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(DASHBOARD_HTML, "text/html")
        elif self.path == "/api/rolling":
            self._serve_rolling_data()
        elif self.path == "/api/hot":
            self._serve_hot_data()
        elif self.path == "/api/discovery":
            self._serve_discovery_data()
        elif self.path == "/api/summary":
            # M7.E1.34k: top-of-dashboard summary — pairs/pools under
            # monitoring, top spreads, gate funnel, top reject buckets.
            self._serve_summary_data()
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

    def _serve_summary_data(self):
        """M7.E1.34k: Top-of-dashboard summary.

        Surfaces the 4 questions the reviewer asks on each window:
          1. How many pairs / pools are under monitoring.
          2. Top N pairs by observed spread / net bps (scoreboard).
          3. For each top row, the gate decision
             (passed → submit_ready, or which gate blocked it).
          4. The aggregate gate funnel
             (events_seen → scored → profit_guard → sim_attempted → sim_passed
             → submit_ready) and the top reject buckets.
        Read-only — pure JSON aggregation over existing rolling artifacts.
        """
        def _load(key):
            path = ARTIFACT_FILES.get(key)
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

        session = rollup.get("session") or {}
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
        bridge_loaded = rollup.get("bridge_loaded_candidate_count_total") or 0

        # Top spreads — prefer m7_hot.top_hot_candidates, fall back to
        # orderflow.top_executable_candidates then top_route_viable.
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
            # Gate layer the candidate reached — decoded from presence of
            # roundtrip_success / sim_passed / profit_guard etc.  Reported
            # in user-readable form so the reviewer can see WHERE each row
            # dropped out.
            if cand.get("submit_ready") is True:
                gate = "submit_ready"
                passed = True
            elif cand.get("roundtrip_success") is True:
                gate = "roundtrip_success"
                passed = True
            elif cand.get("roundtrip_attempted"):
                gate = "roundtrip_failed"
                passed = False
            elif cand.get("sim_passed") or cand.get("scored_net_bps") is not None:
                gate = "sim_passed" if cand.get("sim_passed") else "scored"
                passed = bool(cand.get("sim_passed"))
            elif cand.get("profit_guard_passed"):
                gate = "profit_guard_passed"
                passed = True
            elif cand.get("reject_reason") or cand.get("guard_reject_reason"):
                gate = (
                    cand.get("guard_reject_reason")
                    or cand.get("reject_reason")
                )
                passed = False
            else:
                gate = "scored"
                passed = True
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

        # Gate funnel — aggregate totals from rollup.
        funnel = {
            "events_seen": rollup.get("events_seen_total", 0),
            "fast_score_attempted": rollup.get("fast_score_attempted_total", 0),
            "fast_path_scored": rollup.get("fast_path_scored_total", 0),
            "fast_path_positive": rollup.get("fast_path_positive_total", 0),
            "route_viable": rollup.get("route_viable_total", 0),
            "profit_guard_passed": rollup.get("profit_guard_passed_total", 0),
            "sim_attempted": rollup.get("sim_attempted_total", 0),
            "sim_passed": rollup.get("sim_passed_total", 0),
            "submit_ready": rollup.get("submit_ready_total", 0),
            "roundtrip_attempted": rollup.get("roundtrip_attempted_total", 0),
            "roundtrip_success": rollup.get("roundtrip_success_total", 0),
            "roundtrip_profitable": rollup.get("roundtrip_profitable_total", 0),
        }

        # Top reject buckets (merge guard + simulation + submit + orderflow reject hists)
        def _top(hist, n=8):
            if not isinstance(hist, dict):
                return []
            return sorted(
                ({"reason": k, "count": v} for k, v in hist.items()),
                key=lambda x: (-int(x["count"] or 0), x["reason"]),
            )[:n]

        reject_buckets = {
            "guard": _top(rollup.get("guard_reject_reason_histogram")),
            "simulation": _top(rollup.get("simulation_error_histogram")),
            "submit_blocker": _top(rollup.get("submit_blocker_histogram")),
            "roundtrip_error": _top(rollup.get("roundtrip_error_histogram")),
            "reject_histogram": _top(orderflow.get("reject_histogram")),
        }

        # Funnel debug (M7.E1.34k silent-drop counters).
        funnel_debug = hot.get("funnel_debug") or {}

        # M7.E1.34m (soak7): persistent session state + exit-reason
        # histogram. Lets operators see (a) whether session_id survived
        # restarts and (b) why the WS scan keeps ending early.
        session_state = None
        try:
            _sess_path = Path("data/runs/_rolling/m7_session_state.json")
            if _sess_path.is_file():
                with open(_sess_path, encoding="utf-8") as _sf:
                    session_state = json.load(_sf)
        except (json.JSONDecodeError, OSError):
            session_state = None
        exit_reason_hist = session.get("session_exit_reason_histogram") or {}
        last_exit_reason = session.get("last_exit_reason")

        summary = {
            "timestamp": rollup.get("last_updated"),
            "chain": rollup.get("chain"),
            "scope": {
                "pairs_monitored": pairs_monitored,
                "pools_monitored": pools_monitored,
                "bridge_loaded_candidate_count_total": bridge_loaded,
                "bridge_focused_pool_count_last": rollup.get(
                    "bridge_focused_pool_count_last", 0
                ),
            },
            "top_spreads": top_spreads,
            "gate_funnel": funnel,
            "funnel_debug": funnel_debug,
            "reject_buckets": reject_buckets,
            "simulation_backend": rollup.get("simulation_backend"),
            "sim_disabled": rollup.get("sim_disabled"),
            "session_state": session_state,
            "exit_reason_histogram": exit_reason_hist,
            "last_exit_reason": last_exit_reason,
            "current_session_id": (
                session.get("session_id") if isinstance(session, dict) else None
            ),
        }

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
