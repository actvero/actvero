import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { Client, PLATFORM_SCOPE } from '../src/client.js';
import { buildProgram } from '../src/commands.js';
import { fingerprint, importRelease, upload } from '../src/distribution.js';
import { authenticated, reply } from './helpers.js';

const id = 'b4fc2620-6884-43cb-bcf8-bb8ac16d89d5';
test('platform publication sends the reviewed plan and no organization grant', async () => {
  const sent: { url: string; init?: RequestInit }[] = [];
  const client = new Client('https://example.com', authenticated(PLATFORM_SCOPE), async (url, init) => {
    sent.push({ url: String(url), init });
    return reply(String(url).endsWith('/metadata') ? { resource_contract_version: 1, capabilities: ['client_distribution.write'] } : { status: 'published' });
  }, 'platform');
  await buildProgram({ client: () => client, output: () => {} }).parseAsync(['releases', 'publish', id, '--plan', id, '--server', 'https://example.com'], { from: 'user' });
  assert.ok(sent.at(-1)!.url.endsWith('/platform/client-distribution/releases/' + id + '/publish'));
  assert.deepEqual(JSON.parse(String(sent.at(-1)!.init?.body)), { plan_id: id });
});

test('platform credentials cannot be read from an organization client', async () => {
  let sent = false;
  const client = new Client('https://example.com', authenticated(PLATFORM_SCOPE), async () => { sent = true; return reply({}); });
  await assert.rejects(client.request('GET', '/organizations'), { code: 'credential_type_mismatch' });
  assert.equal(sent, false);
});

test('an interrupted completion is recovered without uploading the file again', async () => {
  const calls: string[] = [];
  const client = new Client('https://example.com', authenticated(PLATFORM_SCOPE), async url => {
    calls.push(String(url));
    return reply({ status: String(url).endsWith('/start') ? 'completing' : 'completed' });
  }, 'platform');
  assert.deepEqual(await upload({ client, options: {}, root: '' }, id, '/nonexistent-no-read-required', () => {}), { status: 'completed' });
  assert.equal(calls.length, 2);
  assert.ok(calls[1]!.endsWith('/complete'));
});

test('resumption skips only acknowledged chunks of the same file and sends no platform token to storage', async (t) => {
  const root = await mkdtemp(join(tmpdir(), 'client-upload-'));
  try {
    const file = join(root, 'app.exe');
    await writeFile(file, 'abcdefgh');
    const computed = await fingerprint(file);
    const signed: number[] = [];
    const acknowledgements: unknown[] = [];
    let completed = false;
    const client = new Client('https://example.com', authenticated(PLATFORM_SCOPE), async (url, init) => {
      const route = String(url);
      if (route.endsWith('/start')) return reply({ status: 'uploading', part_size: 4, part_count: 2,
        parts: { '1': 'first-etag' }, size_bytes: 8, expected_sha512: computed.sha512 });
      if (route.endsWith('/sign')) {
        const body = JSON.parse(String(init?.body));
        signed.push(...body.parts);
        return reply({ '2': 'https://storage.example.com/part?signature=test' });
      }
      if (route.endsWith('/ack')) acknowledgements.push(JSON.parse(String(init?.body)));
      if (route.endsWith('/complete')) completed = true;
      return reply({ status: 'completed' });
    }, 'platform');
    t.mock.method(globalThis, 'fetch', async (url: string | URL, init: RequestInit) => {
      assert.equal(String(url), 'https://storage.example.com/part?signature=test');
      assert.equal(new Headers(init.headers).has('authorization'), false);
      assert.equal(init.redirect, 'error');
      assert.equal(Buffer.from(init.body as Uint8Array).toString(), 'efgh');
      return new Response('', { headers: { etag: 'second-etag' } });
    });
    const context = { client, options: {}, root: '' };
    await upload(context, id, file, () => {});
    assert.deepEqual(signed, [2]);
    assert.deepEqual(acknowledgements, [{ number: 2, etag: 'second-etag' }]);
    assert.equal(completed, true);
    await writeFile(file, 'modified');
    await assert.rejects(upload(context, id, file, () => {}), { code: 'file_changed' });
    assert.deepEqual(signed, [2]);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('manifest checksum and packaged feed are checked before mutating a release', async () => {
  const root = await mkdtemp(join(tmpdir(), 'client-release-'));
  const client = new Client('https://example.com', authenticated(PLATFORM_SCOPE), async () => { throw new Error('must not send a request'); }, 'platform');
  try {
    const file = join(root, 'app.exe');
    await writeFile(file, 'fixture');
    const computed = await fingerprint(file);
    const manifest = { schema_version: 1, version: '1.0.0', feed_roots: { 'win-x64': 'https://wrong.example.com/feed/' }, artifacts: [{ file: 'app.exe', target: 'win-x64', role: 'payload', ...computed }] };
    const path = join(root, 'client-release.json');
    await writeFile(path, JSON.stringify(manifest));
    const context = { client, options: { file: path, storage: id }, root: '' };
    await assert.rejects(importRelease(context, () => {}), { code: 'feed_mismatch' });
    manifest.feed_roots['win-x64'] = 'https://example.com/api/v1/client-updates/actvero/win-x64/';
    manifest.artifacts[0]!.sha512 = 'wrong';
    await writeFile(path, JSON.stringify(manifest));
    await assert.rejects(importRelease(context, () => {}), { code: 'checksum_mismatch' });
  } finally { await rm(root, { recursive: true, force: true }); }
});
