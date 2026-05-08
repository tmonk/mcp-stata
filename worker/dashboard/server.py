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
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("PORT", 4242))
CF_API_BASE = "https://api.cloudflare.com/client/v4"
HTML_FILE = Path(__file__).parent / "index.html"

SSE_POLL_SECONDS = float(os.environ.get("SSE_POLL_SECONDS", "2.0"))


def _now_utc_sql() -> str:
    # YYYY-MM-DD HH:MM:SS (UTC)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _shift_utc_sql(seconds: int) -> str:
    return time.strftime(
        "%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + seconds)
    )


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
        elif self.path.startswith("/api/stream"):
            self._sse_stream()
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

    def _cf_sql(self, sql: str) -> bytes:
        account_id = os.environ.get("CF_ACCOUNT_ID", "")
        api_token = os.environ.get("CF_API_TOKEN", "")
        url = f"{CF_API_BASE}/accounts/{account_id}/analytics_engine/sql"
        req = urllib.request.Request(
            url,
            data=sql.encode(),
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "text/plain"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()

    def _sse_stream(self):
        account_id = os.environ.get("CF_ACCOUNT_ID", "")
        api_token = os.environ.get("CF_API_TOKEN", "")
        if not account_id or not api_token:
            self._respond(500, "text/plain", b"CF_ACCOUNT_ID and CF_API_TOKEN not set\n")
            return

        # SSE headers (no Content-Length; keep connection open)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # Start a little in the past so we don't miss events on connect.
        since = _shift_utc_sql(-60)
        last_sent = 0.0

        def send(event: str, data_obj):
            payload = json.dumps(data_obj, separators=(",", ":"))
            msg = f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
            self.wfile.write(msg)
            self.wfile.flush()

        try:
            send("hello", {"ok": True, "server_time": _now_utc_sql()})
            while True:
                # Backpressure: don't spin if client is slow.
                now = time.time()
                if now - last_sent < SSE_POLL_SECONDS:
                    time.sleep(0.1)
                    continue

                sql = f"""
                    SELECT timestamp, blob1 AS event, blob4 AS client,
                           blob8 AS os, blob5 AS src, blob13 AS country, blob11 AS error_code,
                           blob20 AS log_tail
                    FROM mcp_stata_installs
                    WHERE timestamp > toDateTime('{since}')
                    ORDER BY timestamp ASC
                    LIMIT 250
                """.strip().replace("\n", " ")

                try:
                    raw = self._cf_sql(sql)
                    result = json.loads(raw.decode("utf-8"))
                    rows = result.get("data") or []
                except Exception as e:
                    send("error", {"error": str(e)})
                    last_sent = time.time()
                    time.sleep(min(3.0, SSE_POLL_SECONDS))
                    continue

                max_ts = None
                for r in rows:
                    send("event", r)
                    ts = r.get("timestamp") or ""
                    if ts:
                        max_ts = ts

                if max_ts:
                    # Timestamp comes back as 'YYYY-MM-DD HH:MM:SS[.mmm]'
                    since = str(max_ts).split(".")[0]

                # Keep-alive ping every ~20s even if no rows.
                if not rows and (time.time() - last_sent) > 20:
                    send("ping", {"t": _now_utc_sql()})

                last_sent = time.time()

        except (BrokenPipeError, ConnectionResetError):
            return


if __name__ == "__main__":
    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    api_token = os.environ.get("CF_API_TOKEN", "")
    if not account_id or not api_token:
        print("⚠  CF_ACCOUNT_ID and CF_API_TOKEN not set — set them via .envrc")
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Dashboard → http://127.0.0.1:{PORT}")
    server.serve_forever()
