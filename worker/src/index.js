/**
 * Welcome to Cloudflare Workers! This is your first worker.
 *
 * - Run "npm run dev" in your terminal to start a development server
 * - Open a browser tab at http://localhost:8787/ to see your worker in action
 * - Run "npm run deploy" to publish your worker
 *
 * Learn more at https://developers.cloudflare.com/workers/
 */


/**
 * mcp-stata installer service. Deployed to https://mcp-stata-install.tdmonk.com/
 *
 * Routes:
 *   GET  /install.sh    bash installer (proxied from GitHub, edge-cached)
 *   GET  /install.ps1   PowerShell installer (proxied from GitHub, edge-cached)
 *   POST /telemetry     install_start | install_success | install_failure events
 *   GET  /              info page
 *   GET  /health        liveness probe
 *
 * Configuration (wrangler.toml [vars]):
 *   INSTALL_REF         git ref to serve. Default 'main'. Pin to a release tag
 *                       (e.g. 'v1.0.0') before launches so you control the
 *                       blast radius of new commits.
 *   GITHUB_REPO         'owner/name'. Default 'tmonk/mcp-stata'.
 *
 * Bindings:
 *   MCP_STATA           Analytics Engine dataset (optional but recommended).
 *                       Without it, events are logged via console.log.
 */

const DEFAULTS = {
  GITHUB_REPO: 'tmonk/mcp-stata',
  INSTALL_REF: 'main',
};

//const SCRIPT_CACHE_TTL = 300; // 5 minutes — short enough to push fixes quickly
const SCRIPT_CACHE_TTL = 1; // 1 second — effectively disable caching for testing; set to a few minutes for production. The script files themselves are small and GitHub is fast, so caching isn't critical for performance.

const TELEMETRY_MAX_BYTES = 8 * 1024;
const ALLOWED_EVENTS = new Set([
  'install_start',
  'install_success',
  'install_failure',
  'uninstall_start',
  'uninstall_success',
  'uninstall_failure',
]);

const SECURITY_HEADERS = {
  'strict-transport-security': 'max-age=63072000; includeSubDomains',
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'no-referrer',
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    try {
      switch (url.pathname) {
        case '/install.sh':
          return serveScript(request, env, ctx, 'install.sh');
        case '/install.ps1':
          return serveScript(request, env, ctx, 'install.ps1');
        case '/telemetry':
          return handleTelemetry(request, env);
        case '/':
          return serveIndex(request, env);
        case '/health':
          return new Response('ok\n', {
            headers: { 'content-type': 'text/plain' },
          });
        default:
          return new Response('Not found\n', {
            status: 404,
            headers: { 'content-type': 'text/plain' },
          });
      }
    } catch (err) {
      console.error('worker error', err.stack || String(err));
      return new Response('Internal error\n', {
        status: 500,
        headers: { 'content-type': 'text/plain' },
      });
    }
  },
};

// ── Script delivery ──────────────────────────────────────────────────────────

async function serveScript(request, env, ctx, file) {
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  const ref = env.INSTALL_REF || DEFAULTS.INSTALL_REF;
  const upstreamUrl =
    `https://raw.githubusercontent.com/${repo}/${ref}/plugin/${file}`;

  const upstream = await fetch(upstreamUrl, {
    cf: {
      cacheTtl: SCRIPT_CACHE_TTL,
      cacheEverything: true,
    },
  });

  if (!upstream.ok) {
    console.error(`upstream ${upstream.status} for ${upstreamUrl}`);
    ctx.waitUntil(
      recordEvent(env, request, {
        event: 'install_failure',
        stage: 'serve_script',
        error_code: `upstream_${upstream.status}`,
        file,
      }),
    );
    return new Response(
      `Could not fetch ${file} (HTTP ${upstream.status}).\n` +
        `Fall back: git clone https://github.com/${repo}\n`,
      {
        status: 502,
        headers: { 'content-type': 'text/plain' },
      },
    );
  }

  const body = await upstream.text();

  ctx.waitUntil(
    recordEvent(env, request, {
      event: 'install_start',
      stage: 'fetch_script',
      file,
    }),
  );

  return new Response(body, {
    headers: {
      // text/plain so users can preview in a browser before piping to a shell.
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': `public, max-age=${SCRIPT_CACHE_TTL}`,
      'x-mcp-stata-ref': ref,
      ...SECURITY_HEADERS,
    },
  });
}

// ── Telemetry ────────────────────────────────────────────────────────────────

async function handleTelemetry(request, env) {
  // CORS preflight, in case anyone ever calls this from a browser.
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: corsHeaders(),
    });
  }

  if (request.method !== 'POST') {
    return new Response('Method not allowed\n', {
      status: 405,
      headers: { allow: 'POST', 'content-type': 'text/plain' },
    });
  }

  const length = parseInt(request.headers.get('content-length') || '0', 10);
  if (length > TELEMETRY_MAX_BYTES) {
    return new Response('Payload too large\n', { status: 413 });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return new Response('Invalid JSON\n', { status: 400 });
  }

  let rawJson = '';
  try {
    rawJson = JSON.stringify(body);
  } catch {
    rawJson = '';
  }

  const event = sanitizeEvent(body, rawJson);
  if (!event) {
    return new Response('Invalid payload\n', { status: 400 });
  }

  const result = await recordEvent(env, request, event);

  return new Response(JSON.stringify({ ok: true, ...result }), {
    headers: {
      'content-type': 'application/json',
      ...corsHeaders(),
    },
  });
}

function sanitizeEvent(body, rawJson) {
  if (!body || typeof body !== 'object') return null;
  if (!ALLOWED_EVENTS.has(body.event)) return null;

  // Strip control characters; cap lengths so a misbehaving client can't blow
  // up our row size. Lengths roughly track Analytics Engine blob limits.
  const cap = (s, n) =>
    typeof s === 'string' ? s.slice(0, n).replace(/[\x00-\x1f]/g, '') : '';
  const num = (n) => (typeof n === 'number' && Number.isFinite(n) ? n : 0);

  // Allow newlines/tabs in log_tail; strip other control chars.
  const capLog = (s, n) =>
    typeof s === 'string' ? s.slice(0, n).replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '') : '';

  return {
    event: cap(body.event, 32),
    action: cap(body.action, 16),
    stage: cap(body.stage, 64),
    file: cap(body.file, 32),
    client: cap(body.client, 64), // comma-separated when multiple agents in one run
    install_source: cap(body.install_source, 32),
    scope: cap(body.scope, 16),
    install_ref: cap(body.install_ref, 64),
    install_repo: cap(body.install_repo, 128),
    os: cap(body.os, 32),
    distro: cap(body.distro, 64),
    arch: cap(body.arch, 16),
    error_code: cap(body.error_code, 128),
    duration_ms: num(body.duration_ms),
    install_id: cap(body.install_id, 64),
    user_id: cap(body.user_id, 32),
    username: cap(body.username, 64),
    machine_id: cap(body.machine_id, 64),
    script_version: cap(body.script_version, 32),
    // Last ~100 lines of the install log, sent on failure for diagnostics.
    log_tail: capLog(body.log_tail || '', 4000),
  };
}

export function buildAnalyticsDataPoint(env, request, event) {
  const country = request.cf?.country || 'XX';
  const asn = request.cf?.asn ? String(request.cf.asn) : '';
  const asOrg = request.cf?.asOrganization || request.cf?.as_organization || '';
  const tool = detectClientTool(request.headers.get('user-agent') || '');
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  const ref = env.INSTALL_REF || DEFAULTS.INSTALL_REF;
  const installId = event.install_id || (globalThis.crypto?.randomUUID?.() ?? '');

  const ua = request.headers.get('user-agent') || '';
  const botScore = request.cf?.botManagement?.score || 0;
  const logBytes = event.log_tail ? event.log_tail.length : 0;

  const action =
    event.action ||
    (event.event.startsWith('uninstall_') ? 'uninstall' : 'install');

  return {
    blobs: [
      event.event, // 1: install_* | uninstall_*
      action, // 2: install | uninstall
      event.stage || '', // 3
      event.client || '', // 4
      event.install_source || '', // 5
      event.scope || '', // 6
      event.file || '', // 7
      event.os || '', // 8
      event.distro || '', // 9
      event.arch || '', // 10
      event.error_code || '', // 11
      tool, // 12
      country, // 13
      event.script_version || '', // 14: version
      event.user_id || '', // 15
      event.username || '', // 16
      event.machine_id || '', // 17
      event.log_tail || '', // 18: truncated log for failures
      `${asn} ${asOrg}`.trim().slice(0, 256), // 19: network info
      `${repo}@${ref}`.slice(0, 256), // 20: worker context
    ],
    doubles: [
      1, // double1: row count
      event.duration_ms || 0, // double2: duration_ms
      logBytes || 0, // double3: log_tail bytes
      botScore || 0, // double4: bot score (0 if unavailable)
    ],
    indexes: [installId || event.event],
  };
}

export function sanitizeTelemetryPayload(body, rawJson) {
  return sanitizeEvent(body, rawJson);
}

async function recordEvent(env, request, event) {
  const dataPoint = buildAnalyticsDataPoint(env, request, event);

  if (!env.MCP_STATA) {
    console.log('event', { ...event, index1: dataPoint.indexes?.[0] || '' });
    return { stored: false, sink: 'console', index1: dataPoint.indexes?.[0] || '' };
  }

  try {
    env.MCP_STATA.writeDataPoint(dataPoint);
    return { stored: true, sink: 'analytics_engine', index1: dataPoint.indexes?.[0] || '' };
  } catch (err) {
    console.error('metrics write failed', err.stack || String(err));
    return { stored: false, sink: 'analytics_engine', index1: dataPoint.indexes?.[0] || '', error: 'write_failed' };
  }
}

function detectClientTool(ua) {
  const lower = ua.toLowerCase();
  if (lower.startsWith('curl/')) return 'curl';
  if (lower.startsWith('wget/')) return 'wget';
  if (lower.includes('powershell')) return 'powershell';
  if (lower.includes('mozilla')) return 'browser';
  return 'other';
}

function corsHeaders() {
  return {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'POST, OPTIONS',
    'access-control-allow-headers': 'content-type',
    'access-control-max-age': '86400',
  };
}

// ── Index page ───────────────────────────────────────────────────────────────

function serveIndex(request, env) {
  const ref = env.INSTALL_REF || DEFAULTS.INSTALL_REF;
  const repo = env.GITHUB_REPO || DEFAULTS.GITHUB_REPO;
  const host = new URL(request.url).host;

  const body = `mcp-stata installer service

Serving: ${repo}@${ref}

  Linux / macOS:
    curl -fsSL https://${host}/install.sh | bash

  Windows:
    irm https://${host}/install.ps1 | iex

By default this configures every supported MCP host found on your machine
(Claude Desktop, Claude Code, Cursor, Windsurf, Continue, Zed).

Source: https://github.com/${repo}
`;

  return new Response(body, {
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      ...SECURITY_HEADERS,
    },
  });
}