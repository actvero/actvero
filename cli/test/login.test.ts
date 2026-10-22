import { test } from 'node:test';
import { get } from 'node:http';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Loopback, login } from '../src/login.js';
import { Client, WRITE_SCOPE } from '../src/client.js';
import { MemoryStore, reply, tokens } from './helpers.js';

test('loopback rejects foreign, duplicate and malformed callbacks without consuming the result', async () => {
  const loop = new Loopback(10_000);
  await loop.listen();
  loop.expect('state-proof', 'https://id.example.com/realm');
  const valid =
    '?state=state-proof&iss=' + encodeURIComponent('https://id.example.com/realm') + '&code=one';
  try {
    for (const suffix of [
      valid.replace('state-proof', 'wrong'),
      valid + '&state=state-proof',
      valid.replace('id.example.com', 'other.example.com'),
      valid + '&error=denied',
    ]) {
      assert.equal((await fetch(loop.redirectUri + suffix)).status, 400);
    }
    assert.equal((await fetch(loop.redirectUri + valid, { method: 'POST' })).status, 400);
    assert.equal(
      await new Promise((resolve) => {
        get(loop.redirectUri + valid, { headers: { Host: 'evil.example.com' } }, (response) => {
          response.resume();
          resolve(response.statusCode);
        });
      }),
      400,
    );
    assert.equal((await fetch(loop.redirectUri + valid)).status, 200);
    assert.deepEqual(await loop.result, { code: 'one', issuer: 'https://id.example.com/realm' });
    assert.equal((await fetch(loop.redirectUri + valid)).status, 400);
  } finally {
    await loop.close();
  }
});

test('browser login uses PKCE and grants exactly requested write scope', async () => {
  const home = await mkdtemp(join(tmpdir(), 'actvero-cli-login-'));
  const old = process.env.ACTVERO_CLI_HOME;
  process.env.ACTVERO_CLI_HOME = home;
  const store = new MemoryStore();
  let redirect = '';
  let challenge = '';
  let exchanges = 0;
  const issuer = 'https://identity.example.com/realm';
  const c = new Client('https://platform.example.com', store, async (url, init) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (String(url).endsWith('/metadata'))
      return reply({
        contract_version: 1,
        issuer,
        instance_id: 'instance',
        supported_scopes: ['management:read', 'management:write'],
      });
    if (String(url).endsWith('/start')) {
      assert.equal(body.scope, WRITE_SCOPE);
      redirect = body.redirect_uri;
      challenge = body.code_challenge;
      return reply({
        state: 'proof',
        attempt_id: 'attempt',
        issuer,
        authorization_url: issuer + '/authorize',
      });
    }
    if (String(url).endsWith('/exchange')) {
      exchanges++;
      assert.equal(createHash('sha256').update(body.code_verifier).digest('base64url'), challenge);
      assert.equal(body.code, 'one');
      assert.equal(body.issuer, issuer);
      return reply(tokens(WRITE_SCOPE));
    }
    throw Error('unexpected request');
  });
  try {
    const result = await login(c, true, false, async () => {
      assert.ok(store.state.loginPending);
      assert.equal(
        (await fetch(redirect + '?state=proof&iss=' + encodeURIComponent(issuer) + '&code=one'))
          .status,
        200,
      );
    });
    assert.equal(result.scope, WRITE_SCOPE);
    assert.equal(exchanges, 1);
    assert.ok(store.state.tokens);
    assert.equal(store.state.loginPending, undefined);
    const settings = await readFile(join(home, 'settings.json'), 'utf8');
    assert.ok(!settings.includes('avm_'));
  } finally {
    if (old === undefined) delete process.env.ACTVERO_CLI_HOME;
    else process.env.ACTVERO_CLI_HOME = old;
    await rm(home, { recursive: true, force: true });
  }
});

test('issuer mismatch never opens browser; cancellation failure keeps proof for recovery', async () => {
  const store = new MemoryStore();
  let opened = false;
  const c = new Client('https://example.com', store, async (url) => {
    if (String(url).endsWith('/metadata'))
      return reply({ contract_version: 1, issuer: 'https://id.example.com', instance_id: 'one' });
    if (String(url).endsWith('/start'))
      return reply({
        state: 'proof',
        attempt_id: 'attempt',
        issuer: 'https://id.example.com',
        authorization_url: 'https://foreign.example.com',
      });
    throw Error('cancel network failure');
  });
  await assert.rejects(
    login(c, false, false, async () => {
      opened = true;
    }),
    { code: 'issuer_mismatch' },
  );
  assert.equal(opened, false);
  assert.ok(store.state.loginPending);
});

test('secure store availability is checked before creating a remote login attempt', async () => {
  const store = new MemoryStore();
  store.failSave = () => true;
  let calls = 0;
  const c = new Client('https://example.com', store, async () => {
    calls++;
    return reply({});
  });
  await assert.rejects(login(c));
  assert.equal(calls, 0);
});
