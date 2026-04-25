"""
Lightweight mock of three Uptime Kuma REST endpoints used for performance
and chaos testing in environments where the real Node.js server cannot be
booted (no Node toolchain in WSL, no internet for npm install).

Endpoints:
    GET /api/status-page/<slug>            -> 200 JSON
    GET /api/status-page/heartbeat/<slug>  -> 200 JSON (heavier payload)
    GET /api/badge/<id>/status             -> 200 SVG-ish text

A control endpoint lets the chaos harness flip server behavior at runtime:
    POST /__control { "mode": "normal|slow|error|down", "extra_ms": 0 }

The endpoint shapes and status codes mirror what tests/rest_api/* expect.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import random
import sys
import threading
import time

STATE = {
    "mode": "normal",       # normal | slow | error | down
    "extra_ms": 0,          # additional latency injected per request
    "fail_rate": 0.0,       # 0..1 probability of 500 in normal mode
}
LOCK = threading.Lock()


def _sleep_for(mode: str) -> None:
    """Per-mode base latency (milliseconds)."""
    if mode == "normal":
        base = random.uniform(8, 25)
    elif mode == "slow":
        base = random.uniform(120, 400)
    elif mode == "error":
        base = random.uniform(8, 25)
    else:
        base = 0
    time.sleep((base + STATE["extra_ms"]) / 1000.0)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default access log
        return

    def _respond(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/__control":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            with LOCK:
                STATE.update({k: v for k, v in payload.items() if k in STATE})
            self._respond(200, json.dumps(STATE).encode(), "application/json")
            return
        self._respond(404, b"not found", "text/plain")

    def do_GET(self):
        with LOCK:
            mode = STATE["mode"]
            fail_rate = STATE["fail_rate"]

        if mode == "down":
            # Simulate the server being unreachable: drop the connection.
            try:
                self.wfile.close()
            except Exception:
                pass
            return

        _sleep_for(mode)

        if mode == "error" or random.random() < fail_rate:
            self._respond(500, b'{"error":"injected"}', "application/json")
            return

        if self.path.startswith("/api/status-page/heartbeat/"):
            slug = self.path.rsplit("/", 1)[-1]
            heartbeats = {str(i): [
                {"status": 1, "time": "2026-04-25T10:00:00Z", "ping": 42}
                for _ in range(20)
            ] for i in range(1, 6)}
            body = json.dumps({
                "heartbeatList": heartbeats,
                "uptimeList": {f"{i}_24": 0.999 for i in range(1, 6)},
                "slug": slug,
            }).encode()
            self._respond(200, body, "application/json")
            return

        if self.path.startswith("/api/status-page/"):
            slug = self.path.rsplit("/", 1)[-1]
            body = json.dumps({
                "config": {"slug": slug, "title": "Mock Status"},
                "incident": None,
                "publicGroupList": [],
                "maintenanceList": [],
            }).encode()
            self._respond(200, body, "application/json")
            return

        if self.path.startswith("/api/badge/"):
            body = (
                b'<svg xmlns="http://www.w3.org/2000/svg" width="88" height="20">'
                b'<text x="44" y="14">Up</text></svg>'
            )
            self._respond(200, body, "image/svg+xml")
            return

        if self.path == "/":
            self._respond(200, b'{"ok":true}', "application/json")
            return

        self._respond(404, b'{"error":"not found"}', "application/json")


def serve(host: str = "127.0.0.1", port: int = 3001) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"mock-kuma listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3001
    serve(port=port)
