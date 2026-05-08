#!/usr/bin/env python3
"""Local proxy server for mcp-stata Cloudflare Analytics Engine dashboard.

Requires:
  CF_ACCOUNT_ID  – Cloudflare account ID
  CF_API_TOKEN   – API token with Analytics Engine Read permission

Usage:
  cd dashboard && python server.py
  open http://localhost:4242
"""

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = int(os.environ.get("PORT", 4242))
CF_API_BASE = "https://api.cloudflare.com/client/v4"
HTML_FILE = Path(__file__).parent / "index.html"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D102
        print(f"  {self.address_string()}  {fmt % args}")

    # ── GET / → serve dashboard  /api/config → env-based defaults ───────────

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            data = HTML_FILE.read_bytes()
            self._respond(200, "text/html; charset=utf-8", data)
        elif self.path == "/api/config":
            cfg = {
                "from": os.environ.get("DASHBOARD_FROM", ""),
                "to":   os.environ.get("DASHBOARD_TO",   ""),
            }
            self._respond(200, "application/json", json.dumps(cfg).encode())
        else:
            self._respond(404, "text/plain", b"Not found\n")

    # ── POST /api/query → proxy to CF Analytics Engine ───────────────────────

    def do_POST(self):
        if self.path != "/api/query":
            self._respond(404, "text/plain", b"Not found\n")
            return

        length = int(self.headers.get("Content-Length", 0))
        if length > 8192:
            self._respond(413, "text/plain", b"Too large\n")
            return

        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._respond(400, "application/json", b'{"error":"invalid JSON"}')
            return

        sql = body.get("sql", "").strip()
        if not sql:
            self._respond(400, "application/json", b'{"error":"sql required"}')
            return

        account_id = os.environ.get("CF_ACCOUNT_ID", "")
        api_token = os.environ.get("CF_API_TOKEN", "")
        if not account_id or not api_token:
            msg = json.dumps({"error": "CF_ACCOUNT_ID and CF_API_TOKEN not set"}).encode()
            self._respond(500, "application/json", msg)
            return

        url = f"{CF_API_BASE}/accounts/{account_id}/analytics_engine/sql"
        req = urllib.request.Request(
            url,
            data=sql.encode(),
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "text/plain"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = resp.read()
            self._respond(200, "application/json", result)
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            self._respond(e.code, "application/json", json.dumps({"error": err}).encode())
        except Exception as e:
            self._respond(502, "application/json", json.dumps({"error": str(e)}).encode())

    # ── helpers ───────────────────────────────────────────────────────────────

    def _respond(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    api_token = os.environ.get("CF_API_TOKEN", "")
    if not account_id or not api_token:
        print("⚠  CF_ACCOUNT_ID and CF_API_TOKEN not set — set them via .envrc")
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Dashboard → http://127.0.0.1:{PORT}")
    server.serve_forever()
