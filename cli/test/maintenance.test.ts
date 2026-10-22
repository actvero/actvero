import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Client, WRITE_SCOPE } from '../src/client.js';
import { buildProgram } from '../src/commands.js';
import { authenticated, reply } from './helpers.js';
const org = 'e757d046-7b23-46f9-87a0-c39075b06cb7';
const id = '9d373b54-6c6e-42f9-937a-6a202b1352a8';
const bytes = Buffer.from('PK fixture bytes');
function downloadReply(changes: Record<string, string> = {}, body = bytes) {
  return new Response(body, {
    headers: {
      'Content-Type': 'application/zip',
      'X-Organization-ID': org,
      'X-Management-Request-ID': id,
      'X-Content-SHA256': createHash('sha256').update(bytes).digest('hex'),
      ...changes,
    },
  });
}
test('binary download verifies bytes and never follows redirects', async () => {
  let calls = 0;
  const client = new Client(
    'https://example.com',
    authenticated(WRITE_SCOPE),
    async (_url, init) => {
      calls++;
      assert.equal(init?.redirect, 'manual');
      assert.equal(init?.method, 'POST');
      assert.equal((init?.headers as Record<string, string>)['X-Management-Request-ID'], id);
      return downloadReply();
    },
  );
  assert.deepEqual((await client.download('/download', org, id)).bytes, bytes);
  assert.equal(calls, 1);
});
for (const [label, headers, body, code] of [
  ['foreign organization', { 'X-Organization-ID': id }, bytes, 'invalid_download'],
  ['foreign receipt', { 'X-Management-Request-ID': org }, bytes, 'invalid_download'],
  ['wrong content', { 'Content-Type': 'text/html' }, bytes, 'invalid_download'],
  ['corrupt bytes', {}, Buffer.from('bad'), 'checksum_mismatch'],
  ['oversized body', {}, Buffer.alloc(20 * 1024 * 1024 + 1), 'package_too_large'],
] as const) {
  test('download rejects ' + label, async () => {
    const client = new Client('https://example.com', authenticated(WRITE_SCOPE), async () =>
      downloadReply(headers, body),
    );
    await assert.rejects(client.download('/download', org, id), { code });
  });
}
test('download requires write grant and does not retry an ambiguous response', async () => {
  let calls = 0;
  const fetcher = async () => {
    calls++;
    throw new Error('connection reset');
  };
  await assert.rejects(
    new Client('https://example.com', authenticated(), fetcher).download('/download', org, id),
    { code: 'insufficient_scope' },
  );
  assert.equal(calls, 0);
  await assert.rejects(
    new Client('https://example.com', authenticated(WRITE_SCOPE), fetcher).download(
      '/download',
      org,
      id,
    ),
    { code: 'network_unavailable' },
  );
  assert.equal(calls, 1);
});
test('download preserves existing local files and removes only its failed output', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'actvero-download-'));
  const target = join(directory, 'skill.zip');
  let downloads = 0;
  const client = new Client('https://example.com', authenticated(WRITE_SCOPE), async (url) => {
    if (String(url).endsWith('/metadata'))
      return reply({ resource_contract_version: 1, capabilities: ['skills.download'] });
    downloads++;
    return downloadReply({}, Buffer.from('corrupt'));
  });
  const run = () =>
    buildProgram({
      client: () => client,
      output: () => {},
      errorOutput: () => {},
      journal: async () => {},
    }).parseAsync(
      [
        '--server',
        'https://example.com',
        'skills',
        'download',
        id,
        '--org',
        org,
        '--version-id',
        id,
        '--request-id',
        id,
        '--out',
        target,
      ],
      { from: 'user' },
    );
  try {
    await writeFile(target, 'keep me');
    await assert.rejects(run(), { code: 'output_unavailable' });
    assert.equal(await readFile(target, 'utf8'), 'keep me');
    assert.equal(downloads, 0);
    await rm(target);
    await assert.rejects(run(), { code: 'checksum_mismatch' });
    assert.deepEqual(await readdir(directory), []);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
test('OAuth start can stay headless, and invalid remote URLs never open', async () => {
  let opens = 0;
  const client = new Client('https://example.com', authenticated(WRITE_SCOPE), async (url) =>
    String(url).endsWith('/metadata')
      ? reply({ resource_contract_version: 1, capabilities: ['mcp.oauth', 'mcp.write'] })
      : reply({ result: { id, authorization_url: 'file:///tmp/private' } }),
  );
  const run = (extra: string[]) =>
    buildProgram({
      client: () => client,
      output: () => {},
      errorOutput: () => {},
      journal: async () => {},
      openBrowser: async () => {
        opens++;
      },
    }).parseAsync(
      ['--server', 'https://example.com', 'mcp', 'oauth', 'start', id, '--org', org, ...extra],
      { from: 'user' },
    );
  await run(['--no-browser']);
  assert.equal(opens, 0);
  await assert.rejects(run([]), { code: 'invalid_response' });
  assert.equal(opens, 0);
});
