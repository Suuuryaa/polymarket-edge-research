"""
Keep-alive server for Replit free tier.
Runs a tiny HTTP server so UptimeRobot can ping it every 5 minutes,
preventing Replit from putting the repl to sleep.
"""

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"alive")

    def log_message(self, *args):
        pass  # silence request logs


def keep_alive():
    server = HTTPServer(("0.0.0.0", 8080), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
