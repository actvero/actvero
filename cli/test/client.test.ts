import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Client, READ_SCOPE, WRITE_SCOPE } from '../src/client.js';
import { authenticated, tokens, reply } from './helpers.js';

test('read grant refuses a write before sending credentials', async () => {
  let sent = 0;
  const c = new Client('https://example.com', authenticated(), async () => {
    sent++;
    return reply({});
  });
  await assert.rejects(c.request('POST', '/x', {}, 'request'), { code: 'insufficient_scope' });
  assert.equal(sent, 0);
});

test('POST is never replayed after expiry or an ambiguous network failure', async () => {
  for (const mode of ['expired', 'network']) {
    let sent = 0;
    const c = new Client('https://example.com', authenticated(WRITE_SCOPE), async () => {
      sent++;
      if (mode === 'network') throw Error('sensitive transport text');
      return reply({ error: { code: 'access_expired' } }, 401);
    });
    await assert.rejects(
      c.request('POST', '/skills/import', {}, 'request'),
      (error) => !String(error).includes('sensitive transport text'),
    );
    assert.equal(sent, 1);
  }
});

test('GET refreshes once after explicit expiry; journal is saved before rotation and acknowledgement', async () => {
  const store = authenticated();
  let calls = 0;
  const c = new Client('https://example.com', store, async (url, init) => {
    calls++;
    if (calls === 1) return reply({ error: { code: 'access_expired' } }, 401);
    if (String(url).endsWith('/refresh')) {
      const body = JSON.parse(String(init?.body));
      assert.equal(store.state.pending?.request_id, body.request_id);
      return reply({ ...tokens(READ_SCOPE, 'rotated'), refresh_request_id: body.request_id });
    }
    if (String(url).endsWith('/acknowledge')) {
      assert.equal(store.state.tokens?.access_token, 'avm_access_rotated');
      assert.ok(store.state.ack);
      return reply({ message: 'ok' });
    }
    assert.equal(
      (init?.headers as Record<string, string>).Authorization,
      'Bearer avm_access_rotated',
    );
    return reply({ ok: true });
  });
  assert.deepEqual(await c.request('GET', '/me'), { ok: true });
  assert.equal(calls, 4);
  assert.equal(store.state.pending, undefined);
  assert.equal(store.state.ack, undefined);
});

test('refresh response lost before storage uses the same recovery request next time', async () => {
  const store = authenticated();
  store.state.accessDeadline = 0;
  const requests: string[] = [];
  let fail = true;
  store.failSave = (value) => fail && value.tokens?.access_token === 'avm_access_rotated';
  const c = new Client('https://example.com', store, async (url, init) => {
    if (String(url).endsWith('/refresh')) {
      const body = JSON.parse(String(init?.body));
      requests.push(body.request_id);
      return reply({ ...tokens(READ_SCOPE, 'rotated'), refresh_request_id: body.request_id });
    }
    return reply({ ok: true });
  });
  await assert.rejects(c.request('GET', '/me'));
  assert.ok(store.state.pending);
  assert.equal(store.state.tokens?.access_token, 'avm_access_fixture');
  fail = false;
  await c.request('GET', '/me');
  assert.equal(requests.length, 2);
  assert.equal(requests[0], requests[1]);
});

test('storage failure before refresh dispatch makes no request', async () => {
  const store = authenticated();
  store.state.accessDeadline = 0;
  store.failSave = () => true;
  let calls = 0;
  const c = new Client('https://example.com', store, async () => {
    calls++;
    return reply({});
  });
  await assert.rejects(c.request('GET', '/me'));
  assert.equal(calls, 0);
});

test('rotation cannot silently escalate scope or change session', async () => {
  for (const replacement of [{ scope: WRITE_SCOPE }, { session_id: 'other' }]) {
    const store = authenticated();
    store.state.accessDeadline = 0;
    const c = new Client('https://example.com', store, async () =>
      reply({ ...tokens(), ...replacement }),
    );
    await assert.rejects(c.request('GET', '/me'), { code: 'invalid_response' });
    assert.equal(store.state.tokens?.scope, READ_SCOPE);
    assert.ok(store.state.pending);
  }
});

test('failed logout blocks business calls until a confirmed logout', async () => {
  const store = authenticated();
  let fail = true;
  let calls = 0;
  const c = new Client('https://example.com', store, async () => {
    calls++;
    if (fail) throw Error('offline');
    return reply({});
  });
  await assert.rejects(c.logout());
  assert.equal(store.state.logoutPending, true);
  await assert.rejects(c.request('GET', '/me'), { code: 'logout_pending' });
  assert.equal(calls, 1);
  fail = false;
  await c.logout();
  assert.deepEqual(store.state, {});
});

test('capability absence is explicit and redirects are not followed', async () => {
  const c = new Client('https://example.com', authenticated(), async (_url, init) => {
    assert.equal(init?.redirect, 'manual');
    return reply({ contract_version: 1, capabilities: [] });
  });
  await assert.rejects(c.requireCapability('skills.write'), { code: 'unsupported_capability' });
});
