"""Vercel serverless function: POST /api/act

Trash or permanently delete specific messages the sorter already moved to Spam.

Body (JSON):
  { "gmail": "...", "app_password": "...",
    "message_ids": ["<id@host>", ...],
    "action": "trash" | "delete",
    "confirm": true }   # required only for permanent delete

Credentials arrive in the body, are used for this one call, and are never
stored or logged. Permanent delete is irreversible, so it additionally requires
"confirm": true here (belt-and-suspenders with the UI confirm dialog).
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import imaplib  # noqa: E402
from gmail_jev_sorter import act_on_messages  # noqa: E402

MAX_IDS = 50  # cap so one call can't run long past the function budget


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

        action = data.get("action")
        if action not in ("trash", "delete"):
            return self._send(400, {"error": "action must be 'trash' or 'delete'"})

        ids = data.get("message_ids")
        if not isinstance(ids, list) or not ids:
            return self._send(400, {"error": "message_ids must be a non-empty list"})
        ids = [str(m) for m in ids][:MAX_IDS]

        # permanent delete is irreversible: require explicit confirm
        if action == "delete" and data.get("confirm") is not True:
            return self._send(400, {"error": "permanent delete requires confirm=true"})

        try:
            result = act_on_messages(gmail, app_password, ids, action)
        except imaplib.IMAP4.error as exc:
            return self._send(401, {"error": f"Gmail login/IMAP failed: {exc}"})
        except Exception as exc:  # noqa: BLE001
            return self._send(502, {"error": f"action failed: {exc}"})

        return self._send(200, result)

    def do_GET(self) -> None:
        self._send(200, {"ok": True, "hint": "POST message_ids + action to trash/delete"})
