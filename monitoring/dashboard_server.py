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
}

DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


class DashboardHandler(SimpleHTTPRequestHandler):
    """Serves dashboard HTML and rolling artifact JSON."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(DASHBOARD_HTML, "text/html")
        elif self.path == "/api/rolling":
            self._serve_rolling_data()
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
        """Load all 3 rolling artifacts and return as single JSON."""
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
