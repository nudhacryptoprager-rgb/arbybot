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
        """R28.16: Lightweight endpoint — serve only hot_loop_latest.json.

        Much smaller payload than /api/rolling; suitable for fast 3s polling
        when only live stream data is needed.
        """
        hot_path = ARTIFACT_FILES["hot_loop"]
        if not hot_path.is_file():
            payload = b'{"hot_loop": null}'
        else:
            try:
                with open(hot_path, encoding="utf-8") as f:
                    data = json.load(f)
                payload = json.dumps({"hot_loop": data}, default=str).encode("utf-8")
            except (json.JSONDecodeError, OSError):
                payload = b'{"hot_loop": null}'

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
