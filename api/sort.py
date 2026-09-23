"""Vercel serverless function: POST /api/sort

Body (JSON):
  { "gmail": "...", "app_password": "...",
    "threshold": 0.95, "live": false, "limit": 12 }

Returns the sort_inbox() report as JSON.

The user's Gmail credentials arrive in the request body, are passed straight to
sort_inbox() for this single invocation, and are never stored or logged. The
function is stateless and its process is discarded after the response, so the
password lives only in memory for the seconds the run takes.

Our own JEV_API_KEY comes from a Vercel environment variable (set in project
settings), NOT from the user.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# The function file lives in /api; the sorter module is at the repo root.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import imaplib  # noqa: E402
from gmail_jev_sorter import sort_inbox  # noqa: E402

MAX_LIMIT = 20  # hard cap so a run can't blow past the 60s function budget


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON body"})

        gmail = (data.get("gmail") or "").strip()
        app_password = (data.get("app_password") or "").replace(" ", "")
        if not gmail or not app_password:
            return self._send(400, {"error": "gmail and app_password are required"})

        # validate/clamp the tuning inputs at this trust boundary
        try:
            threshold = float(data.get("threshold", 0.95))
        except (TypeError, ValueError):
            return self._send(400, {"error": "threshold must be a number"})
        if not 0.0 < threshold <= 1.0:
            return self._send(400, {"error": "threshold must be in (0, 1]"})

        try:
            limit = int(data.get("limit", 12))
        except (TypeError, ValueError):
            return self._send(400, {"error": "limit must be an integer"})
        limit = max(1, min(limit, MAX_LIMIT))

        live = bool(data.get("live", False))

        if not os.environ.get("JEV_API_KEY"):
            return self._send(500, {"error": "server missing JEV_API_KEY"})

        try:
            report = sort_inbox(gmail, app_password, threshold, live, limit)
        except imaplib.IMAP4.error as exc:
            # Gmail login/IMAP problems: bad app password, IMAP disabled, etc.
            # Don't echo the credential back.
            return self._send(401, {"error": f"Gmail login/IMAP failed: {exc}"})
        except Exception as exc:  # noqa: BLE001 - surface a clean message, not a stack
            return self._send(502, {"error": f"classification failed: {exc}"})

        return self._send(200, report)

    def do_GET(self) -> None:
        self._send(200, {"ok": True, "hint": "POST JSON to run the sorter"})
