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
from decimal import Decimal, InvalidOperation
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

# E1.65 step 5/10: Minimum trade size for production-ready classification.
# Candidates below this threshold are classified as research_profitable only.
# Set via ARBY_MIN_EXECUTABLE_SIZE_USD env var.
try:
    MIN_EXECUTABLE_SIZE_USD: float = float(
        os.environ.get("ARBY_MIN_EXECUTABLE_SIZE_USD", "10.0")
    )
except (TypeError, ValueError):
    MIN_EXECUTABLE_SIZE_USD = 10.0

# E1.66 step 3/10: Separate "serious production" size threshold.
# pipeline_ready uses MIN_EXECUTABLE_SIZE_USD ($10, research gate).
# production_profit_ready uses MIN_PRODUCTION_SIZE_USD ($50, serious gate).
# Set via ARBY_MIN_PRODUCTION_SIZE_USD env var.
try:
    MIN_PRODUCTION_SIZE_USD: float = float(
        os.environ.get("ARBY_MIN_PRODUCTION_SIZE_USD", "50.0")
    )
except (TypeError, ValueError):
    MIN_PRODUCTION_SIZE_USD = 50.0
    MIN_EXECUTABLE_SIZE_USD = 10.0

# Standard size buckets used for linear profit extrapolation.
_SIZE_BUCKETS_USD = (0.01, 0.10, 1.0, 10.0, 50.0, 100.0)

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

DASHBOARD_HTML = Path(__file__).parent / "dashboard_m7.html"


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
        elif path == "/api/m7/current":
            # Step 9 (reviewer): M7-only fresh current-scan stream.
            # Returns active opportunities table + gate status + submit readiness.
            # Refreshed every 10s by the dashboard (no server-sent events needed).
            qs = parse_qs(parsed.query or "")
            profile = (qs.get("profile") or ["production"])[0]
            if profile not in ("production", "discovery"):
                profile = "production"
            self._serve_m7_current(profile=profile)
        elif path == "/api/m7/pair_family_heatmap":
            # E1.76 step 9: pair-pool matrix heatmap.  Reads
            # pair_pool_matrix from the bridge artifact and projects each
            # family onto the canonical depth ladder.
            qs = parse_qs(parsed.query or "")
            profile = (qs.get("profile") or ["production"])[0]
            if profile not in ("production", "discovery"):
                profile = "production"
            self._serve_pair_family_heatmap(profile=profile)
        elif path == "/api/m7/family_table":
            # E1.81: family-level scoring table — pools_found, spread_bps,
            # max_size_usd, profit_usd per pair family.  Reads cold_executable
            # from the bridge artifact and merges with pair_pool_matrix pools.
            qs = parse_qs(parsed.query or "")
            profile = (qs.get("profile") or ["production"])[0]
            if profile not in ("production", "discovery"):
                profile = "production"
            self._serve_family_table(profile=profile)
        elif path == "/m7" or path == "/m7/":
            self._serve_file(Path(__file__).parent / "dashboard_m7.html", "text/html")
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

    def _serve_m7_current(self, profile: str = "production"):
        """Step 9 (reviewer): /api/m7/current — M7-only fresh scan data.

        Returns every 10s the operator decision table:
          pair, route (dex/pool), amount_in_optimal_usd, net_spread_bps,
          expected_profit_usd, gas_usd, slippage_bps, gate_status,
          submit_ready, live_exec_blocked_reason, kill_switch_active.
        """
        files = DISCOVERY_ARTIFACT_FILES if profile == "discovery" else ARTIFACT_FILES

        def _load(key, inject_mtime: bool = False):
            path = files.get(key)
            if path is None or not path.is_file():
                return None
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if inject_mtime and isinstance(data, dict):
                    # E1.65 fix step 1/2: inject file mtime as _file_mtime_utc so
                    # _candidate_source_status() can use mtime as freshness fallback
                    # when the internal artifact timestamp was not updated this cycle.
                    import os as _os
                    try:
                        mtime = _os.path.getmtime(path)
                        from datetime import timezone as _tz
                        mtime_iso = datetime.fromtimestamp(mtime, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        data["_file_mtime_utc"] = mtime_iso
                    except Exception:
                        pass
                return data
            except (json.JSONDecodeError, OSError):
                return None

        rollup = _load("m7_hot_rollup") or {}
        hot = _load("m7_hot") or {}
        orderflow = _load("m7_orderflow") or {}
        bridge = _load("m7_cold_hot_bridge", inject_mtime=True) or {}

        # Live submit + PnL artifacts (may not exist yet)
        live_submit = None
        live_pnl = None
        canary = None
        for fname, key in [
            ("live_submit_latest.json", "live_submit"),
            ("live_pnl_latest.json", "live_pnl"),
            ("canary_latest.json", "canary"),
        ]:
            p = ROLLING_DIR / fname
            if p.is_file():
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                    if key == "live_submit":
                        live_submit = data
                    elif key == "live_pnl":
                        live_pnl = data
                    else:
                        canary = data
                except (json.JSONDecodeError, OSError):
                    pass

        result = build_m7_current_payload(
            rollup=rollup,
            hot=hot,
            orderflow=orderflow,
            bridge=bridge,
            profile=profile,
            now_utc=datetime.now(timezone.utc),
            live_submit=live_submit,
            live_pnl=live_pnl,
            canary=canary,
        )

        payload = json.dumps(result, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache, max-age=0")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_pair_family_heatmap(self, profile: str = "production"):
        """E1.76 step 9: heatmap of pair-families × depth-ladder profit.

        Reads ``pair_pool_matrix`` and ``cold_executable`` from the
        bridge artifact, projects each family onto the canonical depth
        rungs and returns a flat list of ``{pair, pool_count, dex_count,
        tvl_total_usd, best_size_usd, best_profit_usd, lag_score}`` rows.
        """
        files = DISCOVERY_ARTIFACT_FILES if profile == "discovery" else ARTIFACT_FILES
        bridge_path = files.get("m7_cold_hot_bridge")
        bridge: dict = {}
        if bridge_path and bridge_path.is_file():
            try:
                with open(bridge_path, encoding="utf-8") as fh:
                    bridge = json.load(fh) or {}
            except (json.JSONDecodeError, OSError):
                bridge = {}

        try:
            from m7.orderflow.depth_ladder import (
                DEFAULT_DEPTH_LADDER_USD,
                build_depth_ladder,
                lag_score,
                mav_estimate_usd,
            )
        except Exception:
            DEFAULT_DEPTH_LADDER_USD = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0)
            build_depth_ladder = None
            lag_score = None
            mav_estimate_usd = None

        # Build a {pair -> [depth_curve rows]} map from cold_executable.
        cold_exec = bridge.get("cold_executable") or []
        family_curves: dict = {}
        family_lag_inputs: dict = {}
        for c in cold_exec:
            pair = (c.get("pair") or c.get("symbol") or "").upper()
            if not pair:
                continue
            curve = c.get("depth_curve") or []
            if curve:
                family_curves.setdefault(pair, []).extend(curve)
            else:
                # Fall back: synthesise a one-rung curve from amount/profit fields.
                size = c.get("amount_in_optimal_usd") or c.get("size_usd")
                profit = c.get("expected_profit_usd")
                if size and profit is not None:
                    family_curves.setdefault(pair, []).append(
                        {"size_usd": size, "expected_profit_usd": profit}
                    )
            secs = c.get("seconds_since_last_swap")
            div = c.get("price_divergence_bps") or c.get("net_spread_bps")
            if secs is not None or div is not None:
                family_lag_inputs[pair] = {
                    "seconds_since_last_swap": secs,
                    "price_divergence_bps": div,
                }

        matrix = bridge.get("pair_pool_matrix") or {}
        rows: list = []
        for fam in matrix.get("pairs") or []:
            pair = fam.get("pair") or ""
            curve = family_curves.get(pair) or []
            mav = (
                mav_estimate_usd(curve) if mav_estimate_usd is not None
                else {"mav_usd": 0.0, "best_size_usd": 0.0}
            )
            ladder = (
                build_depth_ladder(curve) if build_depth_ladder is not None
                else []
            )
            lag_inputs = family_lag_inputs.get(pair) or {}
            score = (
                lag_score(**lag_inputs) if (lag_score is not None and lag_inputs)
                else 0.0
            )
            rows.append({
                "pair": pair,
                "pool_count": fam.get("pool_count", 0),
                "dex_count": fam.get("dex_count", 0),
                "tvl_total_usd": fam.get("tvl_total_usd", 0.0),
                "volume_24h_total_usd": fam.get("volume_24h_total_usd", 0.0),
                "best_pool": fam.get("best_pool"),
                "fee_tiers": fam.get("fee_tiers", []),
                "depth_ladder": ladder,
                "mav_usd": mav.get("mav_usd", 0.0),
                "best_size_usd": mav.get("best_size_usd", 0.0),
                "lag_score": score,
            })
        # Sort by MAV desc, ties broken by TVL.
        rows.sort(key=lambda r: (r["mav_usd"], r["tvl_total_usd"]), reverse=True)

        # E1.77 step 6: staleness/age fields so reviewers can see which
        # layer of the data plane is stale (pool snapshot vs price feed
        # vs scout pull vs volume aggregate).
        def _age_from_iso(ts: str | None) -> int | None:
            if not ts:
                return None
            try:
                _t = ts.replace("Z", "+00:00")
                dt = datetime.fromisoformat(_t)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
            except Exception:
                return None

        def _file_age(p) -> int | None:
            try:
                if p and p.is_file():
                    import os as _os
                    return max(0, int(datetime.now(timezone.utc).timestamp() - _os.path.getmtime(p)))
            except Exception:
                pass
            return None

        scout_path = ROLLING_DIR / "m7_tvl_scout_latest.json"
        gecko_path = ROLLING_DIR / "m7_gecko_scout_latest.json"
        volume_path = ROLLING_DIR / "m7_defillama_volume_latest.json"
        staleness = {
            "bridge_age_s": _age_from_iso(bridge.get("timestamp")),
            "matrix_age_s": _age_from_iso(matrix.get("matrix_timestamp_utc")),
            "pool_age_s": _file_age(scout_path),
            "scout_age_s": _file_age(scout_path),
            "price_age_s": _age_from_iso(bridge.get("timestamp")),
            "volume_age_s": _file_age(volume_path) or _file_age(gecko_path),
        }

        result = {
            "profile": profile,
            "rows": rows,
            "summary": matrix.get("summary") or {
                "pair_count": 0, "pool_count": 0, "tvl_total_usd": 0.0,
            },
            "depth_rungs_usd": list(DEFAULT_DEPTH_LADDER_USD),
            "staleness": staleness,
        }
        payload = json.dumps(result, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache, max-age=0")
        self.end_headers()
        self.wfile.write(payload)

    def _serve_family_table(self, profile: str = "production"):
        """E1.81: family-level table — pools_found, spread_bps, max_size_usd, profit_usd.

        Reads ``cold_executable`` from the bridge artifact to extract the
        best observed spread/size/profit per pair family.  Merges with
        ``pair_pool_matrix`` pool counts so the viewer sees both the depth
        landscape (scout-derived) and the live scoring result (cold-derived).

        Response schema::

            {
              "profile": "production",
              "timestamp": "...",
              "rows": [
                {
                  "pair":          "USDC/WETH",
                  "pools_found":   5,
                  "dex_count":     3,
                  "fee_tiers":     [100, 500, 3000],
                  "spread_bps":    1988.9,
                  "max_size_usd":  50.0,
                  "profit_usd":    0.5,
                  "depth_verdict": "micro",
                  "tvl_total_usd": 1200000.0,
                },
                ...
              ],
              "pair_count": 17,
            }
        """
        files = DISCOVERY_ARTIFACT_FILES if profile == "discovery" else ARTIFACT_FILES
        bridge_path = files.get("m7_cold_hot_bridge")
        bridge: dict = {}
        if bridge_path and bridge_path.is_file():
            try:
                with open(bridge_path, encoding="utf-8") as fh:
                    bridge = json.load(fh) or {}
            except (json.JSONDecodeError, OSError):
                bridge = {}

        # --- Pool count / TVL per family from pair_pool_matrix ---
        matrix = bridge.get("pair_pool_matrix") or {}
        matrix_by_pair: dict = {}
        for fam in matrix.get("pairs") or []:
            p = (fam.get("pair") or "").upper()
            if p:
                matrix_by_pair[p] = fam

        # --- Best spread/size/profit per family from cold_executable ---
        cold_exec = bridge.get("cold_executable") or []
        family_best: dict = {}  # pair -> {spread_bps, max_size_usd, profit_usd, depth_verdict}
        for c in cold_exec:
            pair = (c.get("pair") or c.get("symbol") or c.get("actual_pair") or "").upper()
            if not pair:
                continue
            net_bps = c.get("net_spread_bps") or c.get("net_bps") or 0.0
            size_usd = c.get("amount_in_optimal_usd") or c.get("size_usd") or 0.0
            profit_usd = c.get("expected_profit_usd") or 0.0
            depth_verdict = c.get("depth_verdict") or ""
            try:
                net_bps = float(net_bps)
                size_usd = float(size_usd)
                profit_usd = float(profit_usd)
            except (TypeError, ValueError):
                net_bps = size_usd = profit_usd = 0.0
            existing = family_best.get(pair)
            if existing is None or net_bps > existing["spread_bps"]:
                family_best[pair] = {
                    "spread_bps": net_bps,
                    "max_size_usd": size_usd,
                    "profit_usd": profit_usd,
                    "depth_verdict": depth_verdict,
                }

        # --- Also pull from orderflow for supplementary data ---
        orderflow_path = files.get("m7_orderflow")
        orderflow: dict = {}
        if orderflow_path and orderflow_path.is_file():
            try:
                with open(orderflow_path, encoding="utf-8") as fh:
                    orderflow = json.load(fh) or {}
            except (json.JSONDecodeError, OSError):
                orderflow = {}
        for c in orderflow.get("viable_candidates") or []:
            pair = (c.get("actual_pair") or "").upper()
            if not pair:
                continue
            net_bps = float(c.get("net_bps") or 0.0)
            size_usd = float(c.get("amount_in_optimal_usd") or 0.0)
            profit_usd = float(c.get("expected_profit_usd") or 0.0)
            depth_verdict = c.get("depth_verdict") or ""
            existing = family_best.get(pair)
            if existing is None or net_bps > existing["spread_bps"]:
                family_best[pair] = {
                    "spread_bps": net_bps,
                    "max_size_usd": size_usd,
                    "profit_usd": profit_usd,
                    "depth_verdict": depth_verdict,
                }

        # --- E1.81: merge family_promotion_snapshot (per-pair bps accumulation) ---
        fpromo_snap = bridge.get("family_promotion_snapshot") or {}
        for promo in fpromo_snap.get("promotions") or []:
            pair = (promo.get("pair") or promo.get("canonical_key") or "").upper()
            if not pair:
                continue
            promo_bps = float(promo.get("profit_bps") or 0.0)
            promo_size = float(promo.get("max_size_usd") or 0.0)
            promo_profit = float(promo.get("max_profit_usd") or 0.0)
            existing = family_best.get(pair)
            # Only overwrite if promotion has higher bps AND current best is unknown
            if existing is None:
                family_best[pair] = {
                    "spread_bps": promo_bps,
                    "max_size_usd": promo_size,
                    "profit_usd": promo_profit,
                    "depth_verdict": "family_promo",
                    "family_pool_count": promo.get("family_pool_count", 0),
                    "family_dex_count": promo.get("family_dex_count", 0),
                    "profitable_count": promo.get("profitable_count", 0),
                }
            else:
                # Annotate existing row with family promotion count
                existing["family_pool_count"] = promo.get("family_pool_count", 0)
                existing["family_dex_count"] = promo.get("family_dex_count", 0)
                existing["profitable_count"] = promo.get("profitable_count", 0)

        # --- Merge into rows ---
        all_pairs = sorted(set(list(matrix_by_pair.keys()) + list(family_best.keys())))
        rows = []
        for pair in all_pairs:
            mat = matrix_by_pair.get(pair) or {}
            best = family_best.get(pair) or {}
            # fee_tiers from matrix (bps) or empty
            fee_tiers = mat.get("fee_tiers") or []
            rows.append({
                "pair": pair,
                "pools_found": mat.get("pool_count", 0),
                "dex_count": mat.get("dex_count", 0),
                "fee_tiers": fee_tiers,
                "tvl_total_usd": mat.get("tvl_total_usd", 0.0),
                "spread_bps": best.get("spread_bps", 0.0),
                "max_size_usd": best.get("max_size_usd", 0.0),
                "profit_usd": best.get("profit_usd", 0.0),
                "depth_verdict": best.get("depth_verdict", ""),
                "family_pool_count": best.get("family_pool_count", 0),
                "family_dex_count": best.get("family_dex_count", 0),
                "profitable_count": best.get("profitable_count", 0),
            })
        # Sort by spread_bps descending, then tvl descending
        rows.sort(key=lambda r: (r["spread_bps"], r["tvl_total_usd"]), reverse=True)

        result = {
            "profile": profile,
            "timestamp": bridge.get("timestamp"),
            "rows": rows,
            "pair_count": len(rows),
            "family_active_count": fpromo_snap.get("active_count", 0),
            "family_promo_ttl_s": fpromo_snap.get("ttl_s"),
        }
        payload = json.dumps(result, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache, max-age=0")
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


def _artifact_timestamp(artifact: dict):
    if not isinstance(artifact, dict):
        return None
    candidates = [
        artifact.get("last_updated"),
        artifact.get("timestamp_utc"),
        artifact.get("timestamp"),
        # E1.65 fix step 1/2: file mtime injected by _load(inject_mtime=True).
        # Use the newest valid timestamp because cold bridge files can be
        # rewritten with an unchanged internal timestamp.
        artifact.get("_file_mtime_utc"),
    ]
    parsed = []
    for value in candidates:
        dt = _parse_iso_utc(str(value)) if value else None
        if dt is not None:
            parsed.append((dt, value))
    if parsed:
        return max(parsed, key=lambda item: item[0])[1]
    return next((value for value in candidates if value), None)


def _candidate_source_status(artifact: dict, now_utc: datetime, threshold_s: int) -> dict:
    ts = _artifact_timestamp(artifact)
    if not ts:
        return {"timestamp": None, "age_s": None, "is_fresh": True}
    dt = _parse_iso_utc(str(ts))
    if dt is None:
        return {"timestamp": str(ts), "age_s": None, "is_fresh": False}
    age_s = max(0, int((now_utc - dt).total_seconds()))
    return {"timestamp": str(ts), "age_s": age_s, "is_fresh": age_s <= threshold_s}


def _top_hist(hist, n: int = 8):
    if not isinstance(hist, dict):
        return []
    return sorted(
        ({"reason": k, "count": _safe_int(v)} for k, v in hist.items()),
        key=lambda x: (-x["count"], x["reason"]),
    )[:n]


def _safe_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _safe_float(value):
    dec = _safe_decimal(value)
    if dec is None:
        return None
    try:
        return float(dec)
    except (OverflowError, ValueError):
        return None


def _short_pool(value) -> str:
    if not value:
        return "?"
    txt = str(value)
    return txt[:10] + "..." if len(txt) > 10 else txt


def _string_or_none(value):
    return None if value is None else str(value)


def _candidate_key(candidate: dict) -> str:
    event_id = candidate.get("event_id")
    if event_id:
        return str(event_id)
    return "|".join(
        str(candidate.get(k) or "")
        for k in ("actual_pair", "pair", "pool_address", "net_bps", "scored_net_bps")
    )


def _micro_index(*artifacts: dict) -> dict:
    idx = {}
    for artifact in artifacts:
        for row in artifact.get("micro_refinement") or []:
            if not isinstance(row, dict):
                continue
            for key in (row.get("event_id"), row.get("actual_pair"), row.get("pair")):
                if key:
                    idx[str(key)] = row
    return idx


def _candidate_micro(candidate: dict, micro_by_key: dict) -> dict:
    for key in (candidate.get("event_id"), candidate.get("actual_pair"), candidate.get("pair")):
        if key and str(key) in micro_by_key:
            return micro_by_key[str(key)]
    return {}


def _candidate_net_bps(candidate: dict, micro: dict):
    for value in (
        micro.get("verified_net_bps_after_refinement"),
        micro.get("best_micro_net_bps"),
        candidate.get("roundtrip_profit_bps"),
        candidate.get("verified_net_bps"),
        candidate.get("scored_net_bps"),
        candidate.get("best_net_bps"),
        candidate.get("net_bps"),
        candidate.get("best_backrun_net_bps"),
    ):
        if value is not None:
            return _safe_float(value)
    return None


def _candidate_gate_status(candidate: dict) -> str:
    gate_trace = candidate.get("gate_trace") if isinstance(candidate.get("gate_trace"), dict) else {}
    if candidate.get("submit_ready") is True or gate_trace.get("submit_ready") is True:
        return "SUBMIT_READY"
    if candidate.get("roundtrip_profitable") is True:
        return "ROUNDTRIP_PROFITABLE"
    if candidate.get("roundtrip_success") is True:
        return "ROUNDTRIP_SUCCESS"
    if candidate.get("sim_passed") is True or gate_trace.get("sim_passed") is True:
        return "SIM_PASSED"
    if candidate.get("profit_guard_passed") is True or gate_trace.get("profit_guard_passed") is True:
        return "PROFIT_GUARD_PASSED"
    if candidate.get("route_viable") is True:
        return "ROUTE_VIABLE"
    return (
        candidate.get("submit_blocker")
        or candidate.get("reject_reason")
        or candidate.get("guard_reject_reason")
        or candidate.get("sim_error")
        or "SCANNED"
    )


def _candidate_priority(row: dict) -> tuple:
    gate_rank = {
        "SUBMIT_READY": 7,
        "ROUNDTRIP_PROFITABLE": 6,
        "ROUNDTRIP_SUCCESS": 5,
        "SIM_PASSED": 4,
        "PROFIT_GUARD_PASSED": 3,
        "ROUTE_VIABLE": 2,
        "SCANNED": 1,
    }.get(str(row.get("gate_status")), 0)
    net = row.get("net_spread_bps")
    return (
        1 if row.get("submit_ready") else 0,
        gate_rank,
        _safe_float(net) if net is not None else -10**12,
    )


def _expected_profit_usd(size_usd, net_bps):
    size_dec = _safe_decimal(size_usd)
    bps_dec = _safe_decimal(net_bps)
    if size_dec is None or bps_dec is None:
        return None
    return float((size_dec * bps_dec / Decimal("10000")).quantize(Decimal("0.000001")))


def _usd_from_bps(size_usd, bps):
    size_dec = _safe_decimal(size_usd)
    bps_dec = _safe_decimal(bps)
    if size_dec is None or bps_dec is None:
        return None
    return float((size_dec * bps_dec / Decimal("10000")).quantize(Decimal("0.000001")))


def _first_decimal_field(source: dict, keys: tuple[str, ...]):
    for key in keys:
        value = source.get(key)
        dec = _safe_decimal(value)
        if dec is not None:
            return dec
    return None


def _candidate_size_usd(candidate: dict, optimal_wei):
    """Return USD notional only from artifact-provided USD fields.

    The dashboard deliberately does not hardcode token prices. If the runtime
    did not write a USD notional, the UI must say USD unavailable.
    """
    base_dec = _first_decimal_field(
        candidate,
        (
            "amount_in_optimal_usd",
            "size_usd_estimate",
            "amount_in_usd",
            "notional_usd",
            "paper_size_usd",
        ),
    )
    if base_dec is None:
        return None
    # E1.65 fix step 2/5: a value of 0.0 means USD basis is unknown (not computed).
    # Return None so dashboard correctly marks USD as unavailable for this candidate.
    if base_dec <= 0:
        return None
    amount_dec = _safe_decimal(candidate.get("amount_in_wei"))
    optimal_dec = _safe_decimal(optimal_wei)
    if amount_dec is not None and amount_dec > 0 and optimal_dec is not None:
        base_dec = base_dec * optimal_dec / amount_dec
    if base_dec <= 0:
        return None
    return float(base_dec.quantize(Decimal("0.000001")))


def _candidate_expected_profit_usd(candidate: dict, size_usd, net_bps):
    explicit = _first_decimal_field(
        candidate,
        (
            "expected_profit_usd",
            "expected_pnl_usd",
            "net_pnl_usd",
            "profit_usd",
            "expected_profit_usdc",
            "net_pnl_usdc",
        ),
    )
    if explicit is not None:
        return float(explicit.quantize(Decimal("0.000001")))
    return _usd_from_bps(size_usd, net_bps)


def _candidate_gas_usd(candidate: dict, size_usd):
    explicit = _first_decimal_field(
        candidate,
        ("gas_cost_usd", "total_gas_cost_usd", "gas_paid_usd", "gas_paid_usdc"),
    )
    if explicit is not None:
        return float(explicit.quantize(Decimal("0.000001")))
    return _usd_from_bps(size_usd, candidate.get("total_gas_bps"))


def _candidate_slippage_usd(candidate: dict, size_usd):
    explicit = _first_decimal_field(candidate, ("slippage_usd", "slippage_usdc"))
    if explicit is not None:
        return float(explicit.quantize(Decimal("0.000001")))
    return _usd_from_bps(size_usd, candidate.get("slippage_bps"))


def _size_category(size_usd) -> str:
    """Classify trade size into research/operational buckets.

    dust   < $1    — proof-of-pricing only; not economically executable
    micro  $1–$10  — research-grade; real AMM spread may not survive size increase
    small  $10–$100 — potentially production-sized; verify depth before execution
    medium $100+   — production-grade if spread holds at size
    """
    if size_usd is None:
        return "unknown"
    if size_usd < 1.0:
        return "dust"
    if size_usd < 10.0:
        return "micro"
    if size_usd < 100.0:
        return "small"
    return "medium"


def _profit_at_buckets(size_usd, expected_profit_usd) -> dict | None:
    """Estimate expected_profit_usd at standard size buckets via linear extrapolation.

    WARNING: This is a ROUGH UPPER-BOUND ESTIMATE only.
    Real AMM profit degrades non-linearly with size due to price impact.
    Always verify with a depth sweep (QuoterV2 multi-size probe) before execution.
    """
    if size_usd is None or size_usd <= 0 or expected_profit_usd is None:
        return None
    profit_per_usd = expected_profit_usd / size_usd
    return {
        f"${b:.2f}": round(profit_per_usd * b, 6)
        for b in _SIZE_BUCKETS_USD
    }


def _depth_verdict(size_usd, net_bps) -> str:
    """Classify depth confidence based on known trade size.

    depth_unknown   — no USD size available (can't assess)
    dust_only       — size < $1: profitable only at dust level
    micro_unverified — size $1-$10: promising but depth unverified at $10+
    viable_probe_needed — size >= $10: meets MIN threshold; needs depth sweep
    depth_curve_pending — placeholder for future QuoterV2 multi-size probe
    """
    if size_usd is None or size_usd <= 0:
        return "depth_unknown"
    if size_usd < 1.0:
        return "dust_only"
    if size_usd < MIN_EXECUTABLE_SIZE_USD:
        return "micro_unverified"
    return "viable_probe_needed"


def _candidate_usd_basis(candidate: dict, size_usd, profit_usd, gas_usd) -> str:
    if size_usd is None and profit_usd is None and gas_usd is None:
        return "unavailable"
    explicit_usd_keys = {
        "amount_in_optimal_usd",
        "size_usd_estimate",
        "amount_in_usd",
        "notional_usd",
        "paper_size_usd",
        "expected_profit_usd",
        "expected_pnl_usd",
        "net_pnl_usd",
        "profit_usd",
        "gas_cost_usd",
        "total_gas_cost_usd",
    }
    artifact_basis = (
        "artifact_usd_fields"
        if any(candidate.get(key) is not None for key in explicit_usd_keys)
        else "derived_from_artifact_usd_notional"
    )
    # E1.65 step 4/10: tag DUST_PROFIT_ONLY when profitable only at sub-$1 size.
    # This lets the operator filter research-grade from production-grade candidates.
    if (
        size_usd is not None
        and size_usd < 1.0
        and profit_usd is not None
        and profit_usd > 0
    ):
        return f"DUST_PROFIT_ONLY:{artifact_basis}"
    return artifact_basis


def _build_m7_opportunity_rows(
    *,
    hot: dict,
    orderflow: dict,
    bridge: dict,
    limit: int = 20,
) -> list[dict]:
    """Build M7 live dashboard rows from the artifacts that actually carry candidates."""
    micro_by_key = _micro_index(orderflow, bridge, hot)
    # E1.65 fix step 3/5: bridge_cold_executable with valid USD must come first.
    # Previously this list came after orderflow (which was hot-path unpriced rows).
    # Re-order so priced bridge candidates are visible even when hot rows are present.
    _bridge_cold_all = bridge.get("cold_executable") or []
    _bridge_cold_priced = [c for c in _bridge_cold_all
                           if isinstance(c, dict) and (
                               (c.get("size_usd_estimate") or 0) > 0
                               or (c.get("amount_in_optimal_usd") or 0) > 0
                           )]
    _bridge_cold_unpriced = [c for c in _bridge_cold_all if c not in _bridge_cold_priced]
    sources = [
        # Priced bridge candidates first (have real USD size from stable-dec fix)
        ("bridge_cold_executable_priced", _bridge_cold_priced),
        ("cold_executable", orderflow.get("top_executable_candidates") or []),
        ("cold_route_viable", orderflow.get("top_route_viable_candidates") or []),
        # Unpriced bridge candidates after orderflow
        ("bridge_cold_executable", _bridge_cold_unpriced),
        ("near_executable", orderflow.get("near_executable_candidates") or []),
        ("bridge_near_executable", bridge.get("near_executable") or []),
        ("bridge_stale_positive", bridge.get("stale_positive") or []),
        ("hot_recent", hot.get("top_hot_candidates") or []),
        ("sim_output", orderflow.get("sim_output_samples") or []),
    ]
    rows = []
    seen = set()
    for source, candidates in sources:
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            key = _candidate_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            micro = _candidate_micro(candidate, micro_by_key)
            net_bps = _candidate_net_bps(candidate, micro)
            optimal_wei = (
                micro.get("best_submit_size")
                or candidate.get("best_sweep_size_wei")
                or candidate.get("amount_in_wei")
            )
            size_usd = _candidate_size_usd(candidate, optimal_wei)
            route = (
                f"{candidate.get('best_buy_venue') or candidate.get('venue') or '?'}"
                f" -> {candidate.get('best_sell_venue') or '?'}"
                f" / {candidate.get('best_buy_fee') or '?'}:{candidate.get('best_sell_fee') or '?'}"
                f" / {_short_pool(candidate.get('pool_address'))}"
            )
            expected_profit_usd = _candidate_expected_profit_usd(
                candidate, size_usd, net_bps
            )
            gas_usd = _candidate_gas_usd(candidate, size_usd)
            slippage_usd = _candidate_slippage_usd(candidate, size_usd)
            gate_status = _candidate_gate_status(candidate)
            pnl_wei = (
                candidate.get("net_pnl_wei")
                if candidate.get("net_pnl_wei") is not None
                else candidate.get("gross_pnl_wei")
            )
            _size_cat = _size_category(size_usd)
            _is_prod_sized = (
                size_usd is not None and size_usd >= MIN_EXECUTABLE_SIZE_USD
            )
            _is_serious_prod_sized = (
                size_usd is not None and size_usd >= MIN_PRODUCTION_SIZE_USD
            )
            row = {
                "source": source,
                "event_id": candidate.get("event_id"),
                "pair": candidate.get("pair") or candidate.get("actual_pair"),
                "route": route,
                "pool_address": candidate.get("pool_address"),
                "amount_in_optimal_usd": size_usd,
                "amount_in_optimal_wei": _string_or_none(optimal_wei),
                "amount_in_wei": _string_or_none(candidate.get("amount_in_wei")),
                "best_sweep_size_wei": _string_or_none(candidate.get("best_sweep_size_wei")),
                "net_spread_bps": net_bps,
                "net_edge_usd": expected_profit_usd,
                "expected_profit_usd": expected_profit_usd,
                "expected_profit_wei": _string_or_none(pnl_wei),
                "profit_basis": "usd" if expected_profit_usd is not None else "unpriced_token_wei",
                "usd_basis": _candidate_usd_basis(
                    candidate, size_usd, expected_profit_usd, gas_usd
                ),
                "usd_basis_source": candidate.get("usd_basis_source"),
                # E1.65 steps 1-8: size classification, production readiness, depth verdict
                "size_category": _size_cat,
                "is_production_sized": _is_prod_sized,
                "is_serious_production_sized": _is_serious_prod_sized,
                "depth_verdict": _depth_verdict(size_usd, net_bps),
                # Linear profit extrapolation at standard size buckets.
                # ESTIMATE ONLY — real AMM impact is non-linear. Use for triage.
                "profit_size_buckets_est": _profit_at_buckets(size_usd, expected_profit_usd),
                "gas_usd": gas_usd,
                "total_gas_bps": candidate.get("total_gas_bps"),
                "slippage_usd": slippage_usd,
                "slippage_bps": candidate.get("slippage_bps"),
                "gate_status": gate_status,
                "submit_ready": bool(
                    candidate.get("submit_ready")
                    or (candidate.get("gate_trace") or {}).get("submit_ready")
                ),
                "submit_blocker": (
                    candidate.get("submit_blocker")
                    or candidate.get("reject_reason")
                    or candidate.get("guard_reject_reason")
                ),
                "block_lag": candidate.get("block_lag"),
                "pipeline_latency_ms": candidate.get("pipeline_latency_ms"),
            }
            rows.append(row)
    rows.sort(key=_candidate_priority, reverse=True)
    return rows[:limit]


def _m7_usd_coverage(rows: list[dict]) -> dict:
    """USD coverage + production-vs-research split.

    production_profitable_total       — rows where profit>0 and size >= MIN_EXECUTABLE_SIZE_USD ($10)
    production_sized_profitable_total — rows where profit>0 and size >= MIN_PRODUCTION_SIZE_USD ($50)
    research_profitable_total         — rows where profit>0 but size < MIN_EXECUTABLE_SIZE_USD
    dust_only_total                   — rows where size < $1

    pipeline_ready         — True when system is scanning + bridge is populating (code works)
    production_profit_ready — True when production_sized_profitable_total > 0 (market found)
    """
    total = len(rows)
    research_profitable = sum(
        1 for r in rows
        if (r.get("expected_profit_usd") or 0) > 0 and not r.get("is_production_sized", False)
    )
    production_profitable = sum(
        1 for r in rows
        if (r.get("expected_profit_usd") or 0) > 0 and r.get("is_production_sized", False)
    )
    production_sized_profitable = sum(
        1 for r in rows
        if (r.get("expected_profit_usd") or 0) > 0 and r.get("is_serious_production_sized", False)
    )
    dust_only = sum(
        1 for r in rows
        if (r.get("amount_in_optimal_usd") or 0) > 0
        and (r.get("amount_in_optimal_usd") or 0) < 1.0
    )
    # E1.69 Step 8: production-size candidate visibility (regardless of profit
    # sign).  Distinguishes "no production-size routes seen at all" (market
    # absence) from "production-size routes seen but unprofitable" (gas/spread
    # constraint).  Counts ALL candidates with optimal_usd >= MIN_PRODUCTION,
    # including negative-profit ones, so reviewers can audit the funnel.
    production_sized_candidate_total = sum(
        1 for r in rows
        if (r.get("amount_in_optimal_usd") or 0) >= MIN_PRODUCTION_SIZE_USD
    )
    research_sized_candidate_total = sum(
        1 for r in rows
        if (r.get("amount_in_optimal_usd") or 0) >= MIN_EXECUTABLE_SIZE_USD
    )
    # E1.70 fix 9: "near production" — $25...$50 zone. Positive-profit routes in
    # this band indicate we are close to the production gate threshold and the
    # next sizing / depth fix may unlock them.
    near_production_min = MIN_PRODUCTION_SIZE_USD / 2.0
    near_production_candidate_total = sum(
        1 for r in rows
        if near_production_min <= (r.get("amount_in_optimal_usd") or 0) < MIN_PRODUCTION_SIZE_USD
    )
    near_production_profitable_total = sum(
        1 for r in rows
        if near_production_min <= (r.get("amount_in_optimal_usd") or 0) < MIN_PRODUCTION_SIZE_USD
        and (r.get("expected_profit_usd") or 0) > 0
    )
    near_production_best_amount = max(
        (r.get("amount_in_optimal_usd") or 0)
        for r in rows
        if near_production_min <= (r.get("amount_in_optimal_usd") or 0) < MIN_PRODUCTION_SIZE_USD
    ) if any(
        near_production_min <= (r.get("amount_in_optimal_usd") or 0) < MIN_PRODUCTION_SIZE_USD
        for r in rows
    ) else 0.0
    # pipeline_ready: True when we have candidates at all (scanning is working)
    pipeline_ready = total > 0
    # production_profit_ready: True when any pair has confirmed $50+ profitable depth
    production_profit_ready = production_sized_profitable > 0
    return {
        "opportunities_total": total,
        "amount_usd_available": sum(
            1 for row in rows if row.get("amount_in_optimal_usd") is not None
        ),
        "profit_usd_available": sum(
            1 for row in rows if row.get("expected_profit_usd") is not None
        ),
        "gas_usd_available": sum(1 for row in rows if row.get("gas_usd") is not None),
        # E1.65/E1.66: production vs research split
        "production_profitable_total": production_profitable,
        "production_sized_profitable_total": production_sized_profitable,
        "research_profitable_total": research_profitable,
        "dust_only_total": dust_only,
        # E1.69 Step 8: candidate-side counters (no profit-sign filter).
        "production_sized_candidate_total": production_sized_candidate_total,
        "research_sized_candidate_total": research_sized_candidate_total,
        "min_executable_size_usd": MIN_EXECUTABLE_SIZE_USD,
        "min_production_size_usd": MIN_PRODUCTION_SIZE_USD,
        # E1.66 step 2: explicit pipeline/profit readiness flags
        "pipeline_ready": pipeline_ready,
        "production_profit_ready": production_profit_ready,
        "conversion_contract": "dynamic_artifact_usd_only_no_price_hardcode",
        # E1.69 reviewer fix step 1: PRIMARY KPI - production-size depth, not max bps.
        # production_gate_pass is the single Boolean reviewers should check first.
        "primary_kpi": "production_sized_candidate_total",
        "production_gate_pass": (production_sized_candidate_total or 0) > 0,
        # E1.70 fix 9: "near production" block ($25-$50, positive profit).
        # Routes here confirm depth/routing is almost viable; next sizing fix
        # or lower gas context should unlock production gate.
        "near_production": {
            "min_usd": near_production_min,
            "max_usd": MIN_PRODUCTION_SIZE_USD,
            "candidate_total": near_production_candidate_total,
            "profitable_total": near_production_profitable_total,
            "best_amount_usd": near_production_best_amount,
        },
    }


def _m7_metric_audit(rollup: dict, rows: list[dict]) -> dict:
    rate_metrics = rollup.get("rate_metrics") if isinstance(rollup.get("rate_metrics"), dict) else {}
    session = rollup.get("session") if isinstance(rollup.get("session"), dict) else {}
    rate_baseline = (
        session.get("rate_baseline")
        if isinstance(session.get("rate_baseline"), dict)
        else {}
    )
    submit_ready_delta = _safe_int(rate_metrics.get("submit_ready_delta"))
    rt_profit_delta = _safe_int(rate_metrics.get("roundtrip_profitable_delta"))
    submit_ready_total = _safe_int(rollup.get("submit_ready_total"))
    rt_profit_total = _safe_int(rollup.get("roundtrip_profitable_total"))
    return {
        "usd_conversion_basis": "dynamic_artifact_usd_only_no_price_hardcode",
        "synthetic_amount_1e18_rows": sum(
            1 for row in rows if row.get("amount_in_wei") == "1000000000000000000"
        ),
        "l1_fee_source_last": rollup.get("l1_fee_source_last"),
        "l1_fee_wei_last": _string_or_none(rollup.get("l1_fee_wei_last")),
        "rate_metrics_basis": rate_metrics.get("rate_basis"),
        "rate_baseline_present": bool(rate_baseline),
        "rate_metrics_zero_delta_with_nonzero_totals": bool(
            (submit_ready_total > 0 and submit_ready_delta == 0)
            or (rt_profit_total > 0 and rt_profit_delta == 0)
        ),
        "rate_submit_ready_delta": submit_ready_delta,
        "rate_roundtrip_profitable_delta": rt_profit_delta,
    }


def build_m7_current_payload(
    *,
    rollup: dict,
    hot: dict,
    orderflow: dict,
    bridge: dict,
    profile: str,
    now_utc: datetime,
    live_submit: dict | None = None,
    live_pnl: dict | None = None,
    canary: dict | None = None,
) -> dict:
    """Pure builder for /api/m7/current."""
    rollup = rollup or {}
    hot = hot or {}
    orderflow = orderflow or {}
    bridge = bridge or {}
    pr = rollup.get("production_readiness") or {}

    last_updated = (
        rollup.get("last_updated")
        or hot.get("timestamp")
        or hot.get("last_updated")
        or orderflow.get("timestamp")
        or orderflow.get("last_updated")
    )
    is_fresh = False
    if last_updated:
        dt = _parse_iso_utc(last_updated)
        if dt:
            age_s = (now_utc - dt).total_seconds()
            if age_s < 0:
                age_s = 0
            threshold = (
                FRESHNESS_THRESHOLD_S_DISCOVERY
                if profile == "discovery"
                else FRESHNESS_THRESHOLD_S
            )
            is_fresh = age_s < threshold

    def _age_s(ts_str) -> int | None:
        if not ts_str:
            return None
        dt = _parse_iso_utc(str(ts_str))
        if dt:
            return max(0, int((now_utc - dt).total_seconds()))
        return None

    # ---- WS health (Step 5 reviewer) -------------------------------------
    _total_windows = _safe_int(rollup.get("windows_seen"))
    _failed_429 = _safe_int(rollup.get("session_ws_failed_429_windows"))
    _connected_windows = _safe_int(rollup.get("session_ws_connected_windows"))
    ws_health = {
        "connected_windows": _connected_windows,
        "failed_429_windows": _failed_429,
        "failed_windows": _safe_int(rollup.get("session_ws_failed_windows")),
        "fallback_windows": _safe_int(rollup.get("session_ws_fallback_windows")),
        "total_windows": _total_windows,
        "last_status": rollup.get("last_ws_connection_status"),
        "last_provider": rollup.get("last_ws_provider"),
        # coverage_pct: fraction of windows where WS connected (not 429/fail).
        # Distinct from pct_429 (fraction that hit 429 specifically).
        "coverage_pct": (
            round(100.0 * (_connected_windows or 0) / _total_windows, 1)
            if _total_windows > 0 else None
        ),
        "pct_429": (
            round(100.0 * _failed_429 / _total_windows, 1)
            if _total_windows > 0 else None
        ),
        "http_fallback_active": bool(
            rollup.get("http_fallback_active")
            or rollup.get("pool_state_http_feed_active")
        ),
    }

    # ---- Execution funnel stages (Step 8 reviewer) -----------------------
    # Explicit separation: paper → canary → live receipt → live PnL
    _canary_rollup = rollup.get("canary_rehearsal") or {}
    _live_submit_total = (
        _safe_int(live_submit.get("receipt_ok_total")) if live_submit else 0
    )
    _live_pnl_total = (
        _safe_int(live_pnl.get("pnl_ok_total")) if live_pnl else 0
    )
    execution_funnel = {
        "paper_submit_ready": _safe_int(rollup.get("submit_ready_total")),
        "canary_ready": _safe_int(
            _canary_rollup.get("canary_dry_run_submitted")
            if isinstance(_canary_rollup, dict) else 0
        ),
        "live_receipt_ok": _live_submit_total,
        "live_pnl_ok": _live_pnl_total,
        "note": (
            "paper_submit_ready: sim+preflight+canary rehearsal passed (no real tx). "
            "canary_ready: dry-run 1-wei canary submitted. "
            "live_receipt_ok / live_pnl_ok: require real on-chain execution."
        ),
    }

    threshold = (
        FRESHNESS_THRESHOLD_S_DISCOVERY
        if profile == "discovery"
        else FRESHNESS_THRESHOLD_S
    )
    # E1.65 fix step 1/2: bridge is written by the cold lane (slow path, ~8-30s cycles).
    # Use a 2× threshold for bridge freshness so a single cold cycle gap doesn't
    # evict priced candidates that are still operationally relevant.
    _bridge_threshold = threshold * 2
    candidate_sources = {
        "hot": _candidate_source_status(hot, now_utc, threshold),
        "orderflow": _candidate_source_status(orderflow, now_utc, threshold),
        "bridge": _candidate_source_status(bridge, now_utc, _bridge_threshold),
    }
    opportunity_rows = _build_m7_opportunity_rows(
        hot=hot if candidate_sources["hot"]["is_fresh"] else {},
        orderflow=orderflow if candidate_sources["orderflow"]["is_fresh"] else {},
        bridge=bridge if candidate_sources["bridge"]["is_fresh"] else {},
    )

    return {
        "schema_version": "m7_current_v1",
        "now": now_utc.isoformat(),
        "profile": profile,
        "is_fresh": is_fresh,
        "last_updated": last_updated,
        "kill_switch_active": pr.get("kill_switch_active", True),
        "live_submit_blocked_reason": pr.get("live_submit_blocked_reason"),
        "live_exec_blocked_reason": rollup.get("live_exec_blocked_reason"),
        "submit_ready_total": _safe_int(rollup.get("submit_ready_total")),
        "live_executions_total": _safe_int(rollup.get("live_executions_total")),
        "hot_cycle_age_s": _age_s(rollup.get("last_heartbeat_utc")),
        "last_event_age_s": _age_s(rollup.get("last_event_utc")),
        "last_scored_age_s": _age_s(rollup.get("last_scored_utc")),
        "cold_scan_age_s": _age_s(bridge.get("timestamp") or orderflow.get("timestamp")),
        "submit_ready_age_s": _age_s(
            rollup.get("last_submit_ready_utc") or rollup.get("last_scored_utc")
        ),
        "ws_health": ws_health,
        "execution_funnel": execution_funnel,
        "candidate_sources": candidate_sources,
        "usd_coverage": _m7_usd_coverage(opportunity_rows),
        "metric_audit": _m7_metric_audit(rollup, opportunity_rows),
        "opportunities": opportunity_rows,
        "live_submit": live_submit,
        "live_pnl": live_pnl,
        "canary": canary,
    }


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

    def _hist_delta(field: str) -> dict:
        cur_hist = rollup.get(field) if isinstance(rollup.get(field), dict) else {}
        base_hist = baseline.get(field) if isinstance(baseline.get(field), dict) else {}
        out = {}
        for key in sorted(set(cur_hist.keys()) | set(base_hist.keys())):
            diff = _safe_int(cur_hist.get(key)) - _safe_int(base_hist.get(key))
            if diff:
                out[key] = diff
        return out

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
    submit_blocker_hist_delta = _hist_delta("submit_blocker_histogram")
    simulation_error_hist_delta = _hist_delta("simulation_error_histogram")

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
        # Reviewer post-2h-soak step #8: live-delta panels — one block
        # that surfaces the very fields a reviewer/operator looks at
        # first when a soak fails (fresh deltas, blocker histogram delta,
        # divergence sample count, metadata skips). All values are
        # derived from the SAME rollup snapshot so they are internally
        # consistent.
        "live_deltas": {
            "session_id": current_session_id,
            "baseline_session_id": baseline_session_id,
            "age_seconds": age_seconds,
            "is_fresh": is_fresh,
            "staleness_reason": staleness_reason,
            "fresh_funnel": current_funnel,
            "scorer_sim_divergence_samples_total": _safe_int(
                rollup.get("scorer_sim_divergence_samples_total")
            ),
            "scorer_sim_divergence_samples_recent_count": len(
                rollup.get("scorer_sim_divergence_samples_recent") or []
            ),
            "pre_sim_skip_samples_total": _safe_int(
                rollup.get("pre_sim_skip_samples_total")
            ),
            "pre_sim_skip_samples_recent_count": len(
                rollup.get("pre_sim_skip_samples_recent") or []
            ),
            "submit_blocker_histogram_delta": submit_blocker_hist_delta,
            "simulation_error_histogram_delta": simulation_error_hist_delta,
            "scorer_sim_divergence_submit_blocker_delta": sum(
                _safe_int(v)
                for k, v in submit_blocker_hist_delta.items()
                if str(k).startswith("SCORER_SIM_DIVERGENCE")
            ),
            "pre_sim_skip_delta_total": sum(
                _safe_int(v)
                for k, v in simulation_error_hist_delta.items()
                if str(k).startswith("PRE_SIM_SKIP")
            ),
            # Backward-compatible cumulative fields. New clients should
            # prefer *_delta fields above for current-scan decisions.
            "submit_blocker_histogram": rollup.get("submit_blocker_histogram") or {},
            "simulation_error_histogram": rollup.get("simulation_error_histogram") or {},
            "external_provider_blocker_total": _safe_int(
                rollup.get("external_provider_blocker_total")
            ),
        },
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
