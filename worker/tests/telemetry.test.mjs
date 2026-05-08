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

