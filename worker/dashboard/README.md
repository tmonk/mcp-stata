# mcp-stata telemetry dashboard

Local dashboard for Cloudflare Analytics Engine telemetry from the mcp-stata installer worker.

## Setup

**1. Get credentials**

- **Account ID** — Cloudflare dashboard → right sidebar
- **API token** — [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) → Create Token → use the *Account Analytics Read* template

**2. Configure direnv**

```bash
# from repo root
cp .envrc.example .envrc
# edit .envrc — fill in CF_ACCOUNT_ID and CF_API_TOKEN
direnv allow
```

**3. Run**

```bash
python server.py
```

Opens at [http://localhost:4242](http://localhost:4242). Change port with `export PORT=8080`.

No dependencies beyond Python's standard library.

## What it shows

| Panel | Details |
|---|---|
| KPI cards | Total installs, today's installs, success rate, failures, uninstalls |
| Time series | Daily successes vs failures |
| By client | Which MCP host (Claude, Cursor, Windsurf, …) |
| By OS | macOS / Linux / Windows breakdown |
| Top countries | Where installs come from |
| Install source | workbench vs direct vs unknown |
| Download tool | curl / wget / powershell / browser |
| Top errors | Only shown when failures exist |
| Recent events | Last 30 events with relative timestamps |

Time range toggle: **7d / 30d / 90d**. Auto-refreshes every 5 minutes.

## Dataset schema

Queries run against the `mcp_stata_installs` Analytics Engine dataset defined in [`wrangler.toml`](../wrangler.toml).

| blob | field |
|------|-------|
| blob1 | event (`install_start/success/failure`, `uninstall_*`) |
| blob4 | client (MCP host) |
| blob5 | install_source |
| blob8 | os |
| blob11 | error_code |
| blob12 | download tool |
| blob13 | country |
