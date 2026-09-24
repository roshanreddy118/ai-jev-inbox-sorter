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
from api.sort import handler as SortHandler  # reuse the exact serverless handlers
from api.act import handler as ActHandler

PORT = int(os.environ.get("PORT", "8000"))
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

# map each API path to the serverless handler class that owns it
ROUTES = {"/api/sort": SortHandler, "/api/act": ActHandler}


class Router(BaseHTTPRequestHandler):
    """Dispatch API paths to the real serverless handlers; serve index.html at /."""

    def _dispatch(self, verb: str):
        path = self.path.split("?")[0]
        target = ROUTES.get(path)
        if target is not None:
            # call the handler's method with THIS instance as self; it works
            # because both classes subclass BaseHTTPRequestHandler. The handler
            # defines _send, so bind it here too.
            self._send = target._send.__get__(self, type(self))
            return getattr(target, verb)(self)
        if verb == "do_GET":
            with open(INDEX, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        self._dispatch("do_GET")

    def do_POST(self):
        self._dispatch("do_POST")


if __name__ == "__main__":
    print(f"Dev server on http://localhost:{PORT}  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", PORT), Router).serve_forever()
