"""Minimal HTTP health endpoint (WORKER_PORT, default 18400) for probes."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps({"status": "UP", "service": "pfm-ai-worker-python"}).encode()
        code = 200 if self.path in ("/", "/health") else 404
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
