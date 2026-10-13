// Credentials and callback proofs travel only through private subprocess pipes.
import { createRequire } from 'node:module'
import { createInterface } from 'node:readline'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true, executablePath: process.env.ACTVERO_TEST_BROWSER })
const context = await browser.newContext()
const page = await context.newPage()
let callback
let resolveCallback
page.on('request', request => {
  if (/\/(actvero\/callback|api\/v1\/auth\/callback)(\?|$)/.test(request.url())) {
    callback = request.url()
    resolveCallback?.()
  }
})
// Native callbacks are captured from navigation requests, including redirect chains.
// Web callbacks execute normally with the exact test client's session Cookie.
for await (const line of createInterface({ input: process.stdin })) {
  try {
    const request = JSON.parse(line)
    callback = null
    await context.addCookies(request.cookies ?? [])
    const received = new Promise(resolve => { resolveCallback = resolve })
    try { await page.goto(request.url, { waitUntil: 'domcontentloaded' }) }
    catch (error) { if (!callback) throw error }
    let prompted = false
    if (!callback) {
      await page.locator('#username').fill(request.username)
      await page.locator('#password').fill(request.password)
      prompted = true
      try { await page.locator('#kc-login').click() }
      catch (error) { if (!callback) throw error }
    }
    await Promise.race([received, new Promise((_, reject) => setTimeout(() => reject(new Error('Callback timeout')), 10000))])
    const names = new Set((request.cookies ?? []).map(cookie => cookie.name))
    const cookies = (await context.cookies()).filter(cookie => names.has(cookie.name))
    process.stdout.write(JSON.stringify({ callback, prompted, cookies }) + '\n')
  } catch (error) {
    await page.screenshot({ path: new URL('../.local/same-origin-rehearsal/login-failure.png', import.meta.url).pathname })
    process.stdout.write(JSON.stringify({ error: 'browser_login_failed', type: error.name, path: new URL(page.url()).pathname }) + '\n')
  }
}
await browser.close()
