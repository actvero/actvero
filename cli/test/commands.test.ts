import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { buildProgram } from '../src/commands.js';
import { Client, WRITE_SCOPE } from '../src/client.js';
import { authenticated, reply } from './helpers.js';
import { normalizeServer } from '../src/config.js';
const org = 'e757d046-7b23-46f9-87a0-c39075b06cb7';
const id = '9d373b54-6c6e-42f9-937a-6a202b1352a8';
function harness() {
  const sent: { url: string; init?: RequestInit }[] = [];
  const output: string[] = [];
  const journal: unknown[] = [];
  const c = new Client('https://example.com', authenticated(WRITE_SCOPE), async (url, init) => {
    sent.push({ url: String(url), init });
    if (String(url).endsWith('/metadata'))
      return reply({
        resource_contract_version: 1,
        capabilities: [
          'skills.read',
          'skills.write',
          'mcp.read',
          'mcp.write',
          'experts.read',
          'experts.write',
          'commands.show',
        ],
      });
    return reply({ organization: { id: org }, result: { id }, request_id: id });
  });
  const program = buildProgram({
    client: () => c,
    output: (s) => output.push(s),
    errorOutput: () => {},
    journal: async (...args) => {
      journal.push(args);
    },
  });
  program.configureOutput({ writeErr: () => {}, writeOut: () => {} });
  const run = (args: string[]) =>
    program.parseAsync(['--server', 'https://example.com', ...args], { from: 'user' });
  return { sent, output, journal, run };
}
test('resource commands require explicit organization before any network call', async () => {
  for (const args of [
    ['skills', 'list'],
    ['mcp', 'list'],
    ['experts', 'show', id],
    ['commands', 'show', id],
  ]) {
    const h = harness();
    await assert.rejects(h.run(args), { code: 'commander.missingMandatoryOptionValue' });
    assert.equal(h.sent.length, 0);
  }
});
test('CLI uses organization path and preserves request id for publication', async () => {
  const h = harness();
  await h.run([
    'experts',
    'publish',
    id,
    '--org',
    org,
    '--revision',
    '2',
    '--version',
    '1.0.0',
    '--request-id',
    id,
    '--json',
  ]);
  const sent = h.sent.at(-1)!;
  assert.ok(sent.url.endsWith(`/organizations/${org}/experts/${id}/publish`));
  assert.deepEqual(JSON.parse(String(sent.init?.body)), {
    revision: 2,
    version: '1.0.0',
    release_notes: '',
  });
  assert.equal((sent.init?.headers as Record<string, string>)['X-Management-Request-ID'], id);
  assert.equal(h.journal.length, 1);
  assert.equal(JSON.parse(h.output[0]!).request_id, id);
});
test('MCP delete requires version and sends it as concurrency precondition', async () => {
  const h = harness();
  await assert.rejects(h.run(['mcp', 'delete', id, '--org', org]), {
    code: 'commander.missingMandatoryOptionValue',
  });
  assert.equal(h.sent.length, 0);
  const second = harness();
  await second.run(['mcp', 'delete', id, '--org', org, '--version', '3']);
  assert.ok(second.sent.at(-1)!.url.endsWith(`/mcp/services/${id}?version=3`));
});
test('invalid JSON and invalid revision cannot dispatch writes', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'actvero-cli-input-'));
  try {
    const file = join(dir, 'invalid.json');
    await writeFile(file, '["not-object"]');
    const h = harness();
    await assert.rejects(h.run(['mcp', 'create', '--org', org, '--file', file]), {
      code: 'invalid_file',
    });
    assert.equal(h.sent.length, 0);
    const second = harness();
    await assert.rejects(
      second.run([
        'experts',
        'publish',
        id,
        '--org',
        org,
        '--revision',
        '0',
        '--version',
        '1.0.0',
      ]),
    );
    assert.equal(second.sent.length, 0);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('MCP preview accepts the same native or wrapped configuration file as import', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'actvero-mcp-preview-'));
  try {
    const native = { services: [{ name: 'Example', transport: 'builtin', auth_mode: 'none' }] };
    for (const input of [native, { configuration: native }]) {
      const file = join(directory, 'import.json');
      await writeFile(file, JSON.stringify(input));
      const h = harness();
      await h.run(['mcp', 'preview-import', '--org', org, '--file', file]);
      const sent = h.sent.at(-1)!;
      assert.ok(sent.url.endsWith('/mcp/import/preview'));
      assert.deepEqual(JSON.parse(String(sent.init?.body)), { configuration: native });
      assert.equal(h.journal.length, 0);
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
test('server normalization rejects credential-bearing URLs and insecure remote hosts', () => {
  assert.equal(normalizeServer('https://example.com/base///'), 'https://example.com/base');
  assert.equal(normalizeServer('http://127.0.0.1:1234/'), 'http://127.0.0.1:1234');
  for (const value of [
    'http://example.com',
    'https://user:pass@example.com',
    'https://example.com?token=x',
    'ftp://example.com',
  ])
    assert.throws(() => normalizeServer(value), { code: 'invalid_server' });
});
