"""Local dev server to preview the UI without the Vercel CLI.

Serves index.html at / and routes POST /api/sort to the same handler used on
Vercel (api/sort.py). Stdlib only. NOT for production — Vercel runs the real one.

Run:
  export JEV_API_KEY='apikey_...'
  python3 dev_server.py           # then open http://localhost:8000
"""
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api.sort import handler as SortHandler  # reuse the exact serverless handler

PORT = int(os.environ.get("PORT", "8000"))
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


class Router(SortHandler):
    """Inherits _send + do_POST (the API) from SortHandler; overrides GET so /
    serves the page and /api/sort keeps the API health response."""

    def do_GET(self):
        if self.path.split("?")[0] == "/api/sort":
            return super().do_GET()
        with open(INDEX, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?")[0] == "/api/sort":
            return super().do_POST()
        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    print(f"Dev server on http://localhost:{PORT}  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", PORT), Router).serve_forever()
