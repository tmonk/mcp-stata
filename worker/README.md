# `mcp-stata` installer worker

Cloudflare Worker that serves installer scripts and records install telemetry into **Analytics Engine**.

## What it does

- `GET /install.sh`: proxies `plugin/install.sh` from GitHub and edge-caches it
- `GET /install.ps1`: proxies `plugin/install.ps1` from GitHub and edge-caches it
- `POST /telemetry`: accepts install events (start/success/failure) and writes them to Analytics Engine
- `GET /`: prints a short usage page (curl/PowerShell)
- `GET /health`: liveness probe

## Cloudflare resources you need

- **Workers**: this service
- **Analytics Engine dataset**: one dataset bound in `wrangler.toml` as `MCP_STATA`
- (Optional) **Custom domain/route**: if you want a stable install URL like `mcp-stata-install.example.com`

## Configuration

### `worker/wrangler.toml`

The important pieces:

- `name`: worker name in Cloudflare
- `main`: `src/index.js`
- `[vars]`:
  - `GITHUB_REPO`: `owner/name` for the upstream repo (default is `tmonk/mcp-stata`)
  - `INSTALL_REF`: git ref to serve (default is `main`; pin to a release tag for launches)
- `[[analytics_engine_datasets]]`:
  - `binding = "MCP_STATA"`: must match the binding name used in `src/index.js`
  - `dataset = "mcp_stata_installs"`: the dataset name in Analytics Engine

### Runtime behavior if Analytics Engine is missing

If the Analytics Engine binding is not configured, telemetry events are emitted via `console.log` and the worker continues serving install scripts normally.

## Local development

From the repo root:

```bash
cd worker
npm install
npm run dev
```

Then open `http://localhost:8787/`.

## Deploy

```bash
cd worker
npm run deploy
```

If you use a custom domain, configure it in the Cloudflare dashboard (Workers routes / Custom domains) for this worker.

## Telemetry API

### Endpoint

`POST /telemetry` with `Content-Type: application/json`

Accepted `event` values:

- `install_start`
- `install_success`
- `install_failure`

### Payload schema

All fields are optional unless noted.

```json
{
  "event": "install_start",
  "stage": "fetch_script",
  "file": "install.sh",
  "os": "darwin",
  "distro": "macos-14",
  "arch": "arm64",
  "error_code": "",
  "duration_ms": 1234,
  "install_id": "b7b02e2f-...",
  "script_version": "2026-05-08"
}
```

Notes:

- `install_id` is the join key that lets you connect multiple events from the same install attempt.
- `stage` should be a stable step identifier (so you can group/funnel by it).
- `duration_ms` is recorded as an Analytics Engine double for aggregation.

### CORS

`OPTIONS` preflight is supported and responses include permissive CORS headers.

## Analytics Engine mapping (how to query it)

Analytics Engine exposes a fixed schema: `blob1..blobN`, `double1..doubleN`, and one index column `index1`.

This worker writes the following mapping:

- `index1`: `install_id` when present; otherwise falls back to a worker-generated UUID (and finally to `event` as a last resort)

Blobs:

- `blob1`: `event` (`install_*` or `uninstall_*`)
- `blob2`: `action` (`install` | `uninstall`)
- `blob3`: `stage`
- `blob4`: `client` (target MCP host: `claude|codex|gemini|cursor|windsurf|vscode|all|...`)
- `blob5`: `install_source` (`workbench|direct|unknown|...`)
- `blob6`: `scope` (`user|project|unknown`)
- `blob7`: `file` (`install.sh` | `install.ps1`)
- `blob8`: `os`
- `blob9`: `distro`
- `blob10`: `arch`
- `blob11`: `error_code`
- `blob12`: detected network client tool from `User-Agent` (`curl` | `wget` | `powershell` | `browser` | `other`)
- `blob13`: `country` (Cloudflare `request.cf.country`)
- `blob14`: `script_version`
- `blob15`: `install_repo` (from installer env/flags if available)
- `blob16`: `install_ref` (from installer env/flags if available)
- `blob17`: worker `GITHUB_REPO`
- `blob18`: worker `INSTALL_REF`
- `blob19`: `user-agent` (capped)
- `blob20`: `raw_json` (capped JSON payload)

Doubles:

- `double1`: constant `1` (useful for `COUNT(*)`-like sums)
- `double2`: `duration_ms`
- `double3`: `payload_bytes` (length of capped JSON payload)
- `double4`: `bot_score` (0 if unavailable)

### Example queries

#### Events per day

```sql
SELECT
  DATE_TRUNC('day', timestamp) AS day,
  blob1 AS event,
  SUM(double1) AS events
FROM mcp_stata_installs
GROUP BY day, event
ORDER BY day DESC, event;
```

#### Success rate (installs only, overall)

```sql
SELECT
  SUM(CASE WHEN blob1 = 'install_success' THEN 1 ELSE 0 END) * 1.0
    / NULLIF(SUM(CASE WHEN blob1 IN ('install_success','install_failure') THEN 1 ELSE 0 END), 0) AS success_rate
FROM mcp_stata_installs;
```

#### Install vs uninstall volume

```sql
SELECT
  blob2 AS action,
  SUM(double1) AS events
FROM mcp_stata_installs
GROUP BY action
ORDER BY events DESC;
```

#### Success rate by client (target MCP host)

```sql
SELECT
  blob4 AS client,
  SUM(CASE WHEN blob1 = 'install_success' THEN 1 ELSE 0 END) AS successes,
  SUM(CASE WHEN blob1 = 'install_failure' THEN 1 ELSE 0 END) AS failures,
  (SUM(CASE WHEN blob1 = 'install_success' THEN 1 ELSE 0 END) * 1.0)
    / NULLIF(SUM(CASE WHEN blob1 IN ('install_success','install_failure') THEN 1 ELSE 0 END), 0) AS success_rate
FROM mcp_stata_installs
WHERE blob2 = 'install'
GROUP BY client
ORDER BY successes DESC;
```

#### Success rate by install source (stata-workbench vs direct)

```sql
SELECT
  blob5 AS install_source,
  SUM(CASE WHEN blob1 = 'install_success' THEN 1 ELSE 0 END) AS successes,
  SUM(CASE WHEN blob1 = 'install_failure' THEN 1 ELSE 0 END) AS failures,
  (SUM(CASE WHEN blob1 = 'install_success' THEN 1 ELSE 0 END) * 1.0)
    / NULLIF(SUM(CASE WHEN blob1 IN ('install_success','install_failure') THEN 1 ELSE 0 END), 0) AS success_rate
FROM mcp_stata_installs
WHERE blob2 = 'install'
GROUP BY install_source
ORDER BY successes DESC;
```

#### Failures by stage and error code

```sql
SELECT
  blob2 AS stage,
  blob11 AS error_code,
  SUM(double1) AS failures
FROM mcp_stata_installs
WHERE blob1 IN ('install_failure', 'uninstall_failure')
GROUP BY stage, error_code
ORDER BY failures DESC
LIMIT 50;
```

#### Per-install “funnel” (grouped by `install_id`)

```sql
SELECT
  index1 AS install_id,
  MIN(timestamp) AS first_seen,
  MAX(timestamp) AS last_seen,
  MAX(CASE WHEN blob1 = 'install_start' THEN 1 ELSE 0 END) AS saw_start,
  MAX(CASE WHEN blob1 = 'install_success' THEN 1 ELSE 0 END) AS saw_success,
  MAX(CASE WHEN blob1 = 'install_failure' THEN 1 ELSE 0 END) AS saw_failure
FROM mcp_stata_installs
GROUP BY index1
ORDER BY last_seen DESC
LIMIT 100;
```

#### Funnel by client and source (did they start, did they finish)

```sql
SELECT
  blob4 AS client,
  blob5 AS install_source,
  COUNT(DISTINCT CASE WHEN blob1 = 'install_start' THEN index1 END) AS installs_started,
  COUNT(DISTINCT CASE WHEN blob1 = 'install_success' THEN index1 END) AS installs_succeeded,
  COUNT(DISTINCT CASE WHEN blob1 = 'install_failure' THEN index1 END) AS installs_failed
FROM mcp_stata_installs
WHERE blob2 = 'install'
GROUP BY client, install_source
ORDER BY installs_started DESC;
```

#### Median duration by stage (where duration is reported)

```sql
SELECT
  blob3 AS stage,
  APPROX_PERCENTILE(double2, 0.50) AS p50_ms,
  APPROX_PERCENTILE(double2, 0.90) AS p90_ms,
  SUM(CASE WHEN double2 > 0 THEN 1 ELSE 0 END) AS n_with_duration
FROM mcp_stata_installs
GROUP BY stage
ORDER BY n_with_duration DESC;
```

