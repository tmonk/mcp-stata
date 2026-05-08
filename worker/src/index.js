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

const SCRIPT_CACHE_TTL = 300; // 5 minutes — short enough to push fixes quickly
const TELEMETRY_MAX_BYTES = 8 * 1024;
const ALLOWED_EVENTS = new Set([
  'install_start',
  'install_success',
  'install_failure',
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

  const event = sanitizeEvent(body);
  if (!event) {
    return new Response('Invalid payload\n', { status: 400 });
  }

  await recordEvent(env, request, event);

  return new Response(JSON.stringify({ ok: true }), {
    headers: {
      'content-type': 'application/json',
      ...corsHeaders(),
    },
  });
}

function sanitizeEvent(body) {
  if (!body || typeof body !== 'object') return null;
  if (!ALLOWED_EVENTS.has(body.event)) return null;

  // Strip control characters; cap lengths so a misbehaving client can't blow
  // up our row size. Lengths roughly track Analytics Engine blob limits.
  const cap = (s, n) =>
    typeof s === 'string' ? s.slice(0, n).replace(/[\x00-\x1f]/g, '') : '';
  const num = (n) => (typeof n === 'number' && Number.isFinite(n) ? n : 0);

  return {
    event: cap(body.event, 32),
    stage: cap(body.stage, 64),
    file: cap(body.file, 32),
    os: cap(body.os, 32),
    distro: cap(body.distro, 64),
    arch: cap(body.arch, 16),
    error_code: cap(body.error_code, 64),
    duration_ms: num(body.duration_ms),
    install_id: cap(body.install_id, 64),
    script_version: cap(body.script_version, 32),
  };
}

async function recordEvent(env, request, event) {
  const country = request.cf?.country || 'XX';
  const tool = detectClientTool(request.headers.get('user-agent') || '');

  if (!env.MCP_STATA) {
    console.log('event', { ...event, country, tool });
    return;
  }

  try {
    env.MCP_STATA.writeDataPoint({
      // blobs are queryable in Analytics Engine SQL via blob1, blob2, ...
      blobs: [
        event.event, // 1: install_start | install_success | install_failure
        event.stage || '', // 2: ensure_uv | ensure_repo_root | setup_toolkit | ...
        event.file || '', // 3: install.sh | install.ps1
        event.os || '', // 4: linux | darwin | windows
        event.distro || '', // 5: ubuntu-22.04 | macos-14 | windows-11
        event.arch || '', // 6: x86_64 | arm64
        event.error_code || '', // 7
        tool, // 8: curl | wget | powershell | iwr | other
        country, // 9: ISO 3166-1 alpha-2
        event.script_version || '', // 10
      ],
      // doubles are aggregable: SUM(_sample_interval), AVG(double2), ...
      doubles: [1, event.duration_ms || 0],
      // single index, used for cheap WHERE filtering in queries
      indexes: [event.event],
    });
  } catch (err) {
    console.error('metrics write failed', err.stack || String(err));
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