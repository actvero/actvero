// Keycloak theme behavior, with an optional isolated real-provider rehearsal.
// Run: node --test scripts/test-identity-account-switch.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createHash, randomBytes } from 'node:crypto'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

const script = readFileSync(new URL('../identity/themes/actvero/login/resources/js/actvero.js', import.meta.url), 'utf8')
function navigation({ client = 'actvero-desktop', prompt = 'login', username = false,
  restart = 'https://identity.example/identity/realms/actvero/login-actions/restart?client_id=actvero-desktop&tab_id=example' } = {}) {
  const redirects = []
  const location = new URL('https://identity.example/identity/realms/actvero/protocol/openid-connect/auth')
  if (prompt) location.searchParams.set('prompt', prompt)
  location.replace = value => redirects.push(value)
  const elements = {
    'kc-form-login': { dataset: { actveroClient: client } },
    'reset-login': restart ? { href: restart } : null,
    username: username ? {} : null,
  }
  runInNewContext(script, {
    URL, URLSearchParams,
    window: { location, matchMedia: () => ({ matches: false, addEventListener() {} }) },
    document: { cookie: '', getElementById: id => elements[id],
      documentElement: { classList: { toggle() {} } }, addEventListener() {}, querySelectorAll: () => [] },
  })
  return redirects
}

test('desktop login keeps the shared theme asset version and client marker', () => {
  const template = readFileSync(new URL('../identity/themes/actvero/login/template.ftl', import.meta.url), 'utf8')
  const form = readFileSync(new URL('../identity/themes/actvero/login/login.ftl', import.meta.url), 'utf8')
  assert.ok(template.includes('actvero.js?v=${properties.actveroThemeVersion'))
  assert.ok(template.includes('generated.css?v=${properties.actveroThemeVersion'))
  assert.ok(form.includes('data-actvero-client="${client.clientId}"'))
})

test('desktop fresh authentication follows the provider-generated account restart', () => {
  assert.equal(navigation().length, 1)
  assert.equal(navigation({ prompt: 'consent login' }).length, 1)
})
test('ordinary browser SSO and a complete email/password form are preserved', () => {
  assert.deepEqual(navigation({ prompt: '' }), [])
  assert.deepEqual(navigation({ username: true }), [])
})
test('Web reauthentication and other Keycloak pages are preserved', () => {
  assert.deepEqual(navigation({ client: 'actvero-web' }), [])
  assert.deepEqual(navigation({ restart: null }), [])
})
test('the restarted flow does not redirect again', () => {
  assert.deepEqual(navigation({ prompt: '' }), [])
})
test('the theme never follows another origin, client or endpoint', () => {
  for (const restart of [
    'https://other.example/identity/realms/actvero/login-actions/restart?client_id=actvero-desktop',
    'https://identity.example/identity/realms/actvero/protocol/openid-connect/logout?client_id=actvero-desktop',
    'https://identity.example/identity/realms/actvero/login-actions/restart?client_id=actvero-web',
  ]) assert.deepEqual(navigation({ restart }), [])
})

// The realm file contains disposable test users only. Never point this test at a
// real realm: the intentional account restart can retire its previous SSO session.
test('real Keycloak: existing SSO, direct account switch and Web reauthentication', {
  skip: !process.env.ACTVERO_TEST_IDENTITY_URL || !process.env.ACTVERO_TEST_IDENTITY_REALM,
  timeout: 60000,
}, async () => {
  const fixture = JSON.parse(readFileSync(process.env.ACTVERO_TEST_IDENTITY_REALM, 'utf8'))
  assert.equal(fixture.realm, 'actvero-account-switch-test')
  const issuer = `${process.env.ACTVERO_TEST_IDENTITY_URL}/realms/${fixture.realm}`
  const callback = createServer((_request, response) => { response.end('Isolated login test complete') })
  await new Promise(resolve => callback.listen(0, '127.0.0.1', resolve))
  const redirect = `http://127.0.0.1:${callback.address().port}/actvero/callback`
  const require = createRequire(new URL('../frontend/package.json', import.meta.url))
  const { chromium } = require('playwright')
  let browser
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.ACTVERO_TEST_BROWSER })
    const context = await browser.newContext()
    const page = await context.newPage()
    page.setDefaultTimeout(10000)
    function authorization(client = 'actvero-desktop', fresh = false) {
      const verifier = randomBytes(32).toString('base64url')
      const state = randomBytes(24).toString('base64url')
      const nonce = randomBytes(24).toString('base64url')
      const url = new URL(`${issuer}/protocol/openid-connect/auth`)
      url.search = new URLSearchParams({ client_id: client, response_type: 'code', scope: 'openid profile email',
        redirect_uri: redirect, code_challenge: createHash('sha256').update(verifier).digest('base64url'),
        code_challenge_method: 'S256', state, nonce,
        max_age: fresh ? '0' : '3600', ...(fresh ? { prompt: 'login' } : {}) }).toString()
      return { url: url.href, verifier, state, nonce, client }
    }
    async function identity(attempt, expectedUser) {
      const returned = new URL(page.url())
      assert.equal(returned.searchParams.get('state'), attempt.state)
      const response = await fetch(`${issuer}/protocol/openid-connect/token`, {
        method: 'POST', body: new URLSearchParams({ grant_type: 'authorization_code',
          client_id: attempt.client, code: returned.searchParams.get('code'), redirect_uri: redirect,
          code_verifier: attempt.verifier }) })
      assert.equal(response.status, 200)
      const token = await response.json()
      const claims = JSON.parse(Buffer.from(token.id_token.split('.')[1], 'base64url').toString())
      assert.equal(claims.nonce, attempt.nonce)
      assert.equal(claims.iss, issuer)
      assert.equal(claims.aud, attempt.client)
      const profile = await fetch(`${issuer}/protocol/openid-connect/userinfo`, {
        headers: { Authorization: `Bearer ${token.access_token}` } })
      assert.equal(profile.status, 200)
      assert.equal((await profile.json()).preferred_username, expectedUser)
    }
    const first = authorization()
    await page.goto(first.url)
    await page.locator('#username').fill(fixture.users[0].username)
    await page.locator('#password').fill(fixture.users[0].credentials[0].value)
    await page.locator('#kc-login').click()
    await page.waitForURL(`${redirect}?**`)
    await identity(first, fixture.users[0].username)
    const sso = authorization()
    await page.goto(sso.url)
    await page.waitForURL(`${redirect}?**`)
    await identity(sso, fixture.users[0].username)
    const switching = authorization('actvero-desktop', true)
    await page.goto(switching.url)
    await page.locator('#username').waitFor({ state: 'visible' })
    assert.equal(await page.locator('#kc-page-title').innerText(), `登录 ${fixture.displayName || 'Actvero'}`)
    assert.equal(await page.locator('#username').inputValue(), '')
    assert.equal(await page.locator('#password').inputValue(), '')
    assert.equal(await page.locator('#reset-login').count(), 0)
    assert.equal(await page.locator('#username').evaluate(element => element === document.activeElement), true)
    if (process.env.ACTVERO_TEST_SCREENSHOT) await page.screenshot({ path: process.env.ACTVERO_TEST_SCREENSHOT })
    await page.locator('#username').fill(fixture.users[1].username)
    await page.locator('#password').fill(fixture.users[1].credentials[0].value)
    await page.locator('#kc-login').click()
    await page.waitForURL(`${redirect}?**`)
    await identity(switching, fixture.users[1].username)
    const web = authorization('actvero-web-test', true)
    await page.goto(web.url)
    await page.locator('#password').waitFor({ state: 'visible' })
    assert.equal(await page.locator('#kc-page-title').innerText(), '重新登录')
    assert.equal(await page.locator('#username').count(), 0)
    assert.equal(await page.locator('#reset-login').count(), 1)
  } finally {
    await browser?.close()
    await new Promise(resolve => callback.close(resolve))
  }
})
