"""Local stand-in for the production Cloudflare wiring, for try.html dev.

The Try Live page posts to relative ``/api/v1/*`` paths, so it only works
behind something that serves the static site *and* proxies the API — in
production that's the Worker (assets binding + container proxy). A plain
``python -m http.server website`` cannot do this: it has no backend and
rejects POST outright, so every run dies at the ``plan`` stage.

This script reproduces the production wiring on one port:

- starts the demo backend (uvicorn, public-demo env) on BACKEND_PORT
- serves ``website/`` statically with extensionless ``.html`` resolution
  (``/try`` -> ``try.html``, like the Worker's assets html_handling)
- proxies ``/api/*`` and ``/mcp`` to the backend

Usage:  python scripts/dev/try_live_server.py  [PORT]      (default 8094)
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE = REPO_ROOT / "website"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8094
BACKEND_PORT = PORT + 1
BACKEND = f"http://127.0.0.1:{BACKEND_PORT}"


def start_backend() -> subprocess.Popen:
    env = dict(
        os.environ,
        SEMANTIC_RAILS_PACKAGE="jaffle_shop",
        SEMANTIC_RAILS_PUBLIC_DEMO="1",
        PYTHONPATH=str(REPO_ROOT),
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "semantic_rails.asgi:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
        env=env,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(BACKEND + "/api/v1/ready", timeout=2) as resp:
                if json.loads(resp.read()).get("ok"):
                    return proc
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.4)
    proc.terminate()
    raise SystemExit(f"backend on {BACKEND} never became ready")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            BACKEND + self.path,
            data=body,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
            method=self.command,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                status = resp.status
                content_type = resp.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
            content_type = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path.startswith("/api/") or self.path == "/mcp":
            return self._proxy()
        clean = self.path.split("?", 1)[0]
        if clean != "/" and "." not in clean.rsplit("/", 1)[-1]:
            candidate = SITE / (clean.lstrip("/") + ".html")
            if candidate.exists():
                self.path = clean + ".html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path.startswith("/api/") or self.path == "/mcp":
            return self._proxy()
        self.send_error(405)


def main() -> None:
    backend = start_backend()
    print(f"try-live dev server: http://127.0.0.1:{PORT}/try  (backend {BACKEND})")
    try:
        http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    finally:
        backend.terminate()


if __name__ == "__main__":
    main()
