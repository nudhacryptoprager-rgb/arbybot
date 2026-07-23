"""HTTP adapter for the read-only API (ThreadingHTTPServer).

Thin transport layer over ``api.app.ApiApp`` — all logic lives in the
transport-agnostic application.  Threaded so a slow projection read never
blocks health probes (unlike the legacy single-thread dashboard server).

Run::

    py -3.11 -m api.server --port 8100
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from api.app import ApiApp

__all__ = ["make_server", "ApiRequestHandler"]


class ApiRequestHandler(BaseHTTPRequestHandler):
    """HTTP adapter — delegates every request to ApiApp.handle."""

    app: ApiApp = ApiApp()  # bound in make_server

    def do_GET(self) -> None:  # noqa: N802 (stdlib handler name)
        self._serve("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._serve("POST")

    def _serve(self, method: str) -> None:
        status, headers, body = self.app.handle(method, self.path, dict(self.headers))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Quiet by default; access logs belong to the deployment layer.
        return


def make_server(host: str, port: int, *, repo_root: str = ".") -> ThreadingHTTPServer:
    app = ApiApp(repo_root)

    class _Handler(ApiRequestHandler):
        pass

    _Handler.app = app
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> int:
    ap = argparse.ArgumentParser(description="ARBY read-only API server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    server = make_server(args.host, args.port, repo_root=args.repo_root)
    print(f"read-only API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
