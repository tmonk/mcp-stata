import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildAnalyticsDataPoint,
  sanitizeTelemetryPayload,
} from '../src/index.js';

function makeRequest({
  headers = {},
  cf = {},
} = {}) {
  return {
    headers: {
      get(name) {
        const key = String(name || '').toLowerCase();
        for (const [k, v] of Object.entries(headers)) {
          if (k.toLowerCase() === key) return v;
        }
        return null;
      },
    },
    cf,
  };
}

test('sanitizeTelemetryPayload rejects unknown events', () => {
  const raw = { event: 'something_else' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized, null);
});

test('sanitizeTelemetryPayload accepts uninstall events', () => {
  const raw = { event: 'uninstall_success', install_id: 'abc' };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.ok(sanitized);
  assert.equal(sanitized.event, 'uninstall_success');
});

test('buildAnalyticsDataPoint maps client/source/uninstall fields', () => {
  const env = { GITHUB_REPO: 'x/y', INSTALL_REF: 'v1.2.3' };
  const request = makeRequest({
    headers: { 'user-agent': 'curl/8.0.0' },
    cf: { country: 'GB', botManagement: { score: 42 } },
  });
  const event = {
    event: 'uninstall_success',
    action: 'uninstall',
    stage: 'setup_toolkit',
    client: 'vscode',
    install_source: 'workbench',
    scope: 'user',
    file: 'install.sh',
    os: 'darwin',
    distro: 'macos-14',
    arch: 'arm64',
    error_code: '',
    duration_ms: 1234,
    install_id: 'install-123',
    script_version: '1.0.0',
    install_repo: 'https://github.com/tmonk/mcp-stata',
    install_ref: 'main',
    raw_json: '{"event":"uninstall_success"}',
  };

  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.indexes[0], 'install-123');
  assert.equal(dp.blobs[0], 'uninstall_success'); // event
  assert.equal(dp.blobs[1], 'uninstall'); // action
  assert.equal(dp.blobs[3], 'vscode'); // client
  assert.equal(dp.blobs[4], 'workbench'); // install_source
  assert.equal(dp.blobs[5], 'user'); // scope
  assert.equal(dp.blobs[11], 'curl'); // tool
  assert.equal(dp.blobs[12], 'GB'); // country
  assert.equal(dp.blobs[16], ''); // machine_id
  assert.equal(dp.blobs[17], ''); // log_tail
  assert.equal(dp.blobs[18], ''); // network info
  assert.equal(dp.blobs[19], 'x/y@v1.2.3'); // worker context
  assert.equal(dp.doubles[1], 1234);
  assert.equal(dp.doubles[3], 42);
});

test('buildAnalyticsDataPoint handles log_tail and network info', () => {
  const env = {};
  const request = makeRequest({
    cf: { asn: 12345, asOrganization: 'Test ASN', country: 'US' },
  });
  const event = {
    event: 'install_failure',
    machine_id: 'mach-1',
    log_tail: 'line 1\nline 2',
    duration_ms: 500,
  };

  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[0], 'install_failure');
  assert.equal(dp.blobs[1], 'install'); // inferred from start
  assert.equal(dp.blobs[16], 'mach-1');
  assert.equal(dp.blobs[17], 'line 1\nline 2');
  assert.equal(dp.blobs[18], '12345 Test ASN');
  assert.equal(dp.doubles[1], 500);
  assert.equal(dp.doubles[2], 13); // 'line 1\nline 2'.length
});

test('sanitizeTelemetryPayload strips control characters from log_tail', () => {
  const raw = {
    event: 'install_failure',
    log_tail: 'line 1\x07\x00line 2', // bell and null char
  };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.log_tail, 'line 1line 2');
});

test('sanitizeTelemetryPayload caps log_tail at 4000 chars', () => {
  // Installer should send up to ~4000 chars; the worker is the final guard.
  // If a misbehaving (or experimental) client floods us, we trim — we do not
  // reject (failure-event diagnostics are too important to drop wholesale).
  const big = 'x'.repeat(10_000);
  const sanitized = sanitizeTelemetryPayload({
    event: 'install_failure',
    log_tail: big,
  }, '');
  assert.equal(sanitized.log_tail.length, 4000);
});

test('sanitizeTelemetryPayload preserves newlines and tabs in log_tail', () => {
  // Multi-line installer output must round-trip through sanitization so the
  // dashboard's "view log" modal can split by `\n` and render properly.
  const raw = {
    event: 'install_failure',
    log_tail: 'banner\n  step 1\twith tab\n  step 2\nfailure here',
  };
  const sanitized = sanitizeTelemetryPayload(raw, JSON.stringify(raw));
  assert.equal(sanitized.log_tail, raw.log_tail);
});

test('install_failure with realistic log_tail builds a usable data point', () => {
  // Regression coverage for the production bug: every install_failure shipped
  // with log_tail="" because of a heredoc bug in install.sh. This test
  // documents what a healthy payload looks like end-to-end so a future
  // regression on either side (client or worker) is visible.
  const env = {};
  const request = makeRequest({
    cf: { country: 'US', botManagement: { score: 0 } },
  });
  const event = {
    event: 'install_failure',
    action: 'install',
    stage: 'ensure_uv',
    error_code: 'Could not install uv via astral.sh',
    install_id: 'i-1',
    log_tail:
      '======\n' +
      'BOOTSTRAP RUNTIME\n' +
      '======\n' +
      'Installing uv\n' +
      '    • Bootstrap via https://astral.sh/uv/install.sh\n' +
      'curl: (28) Operation timed out after 30001 ms\n' +
      'sh: error: failed to download uv\n',
  };
  const dp = buildAnalyticsDataPoint(env, request, event);
  assert.equal(dp.blobs[0], 'install_failure');
  assert.equal(dp.blobs[10], 'Could not install uv via astral.sh');
  // The dashboard renders blobs[17] as the log tail.
  assert.ok(dp.blobs[17].includes('curl: (28) Operation timed out'));
  assert.ok(dp.blobs[17].includes('BOOTSTRAP RUNTIME'));
  // logBytes (doubles[2]) reflects the full pre-sanitize length.
  assert.equal(dp.doubles[2], event.log_tail.length);
});

