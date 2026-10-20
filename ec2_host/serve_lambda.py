"""Serve one former Lambda handler on localhost. Each process imports only one app."""

from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lambda_adapter import apply_lambda_result, build_lambda_event


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    app_dir = Path(args.app_dir).resolve()
    sys.path.insert(0, str(app_dir))
    import handler  # noqa: WPS433  The directory is chosen per process.

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def do_OPTIONS(self) -> None:
            self._dispatch()

        def log_message(self, fmt: str, *log_args) -> None:
            print("%s %s" % (self.address_string(), fmt % log_args), flush=True)

        def _dispatch(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            event = build_lambda_event(self.command, self.path, dict(self.headers.items()), body)
            status, headers, payload = apply_lambda_result(handler.handler, event)
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"lambda adapter listening on 127.0.0.1:{args.port} from {app_dir}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
