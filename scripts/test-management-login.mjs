// Isolated browser fixture. stdout is consumed privately by the Python test.
import fs from 'node:fs'
import http from 'node:http'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'

const input = JSON.parse(fs.readFileSync(0, 'utf8'))
const target = new URL(input.authorization_url)
if (target.origin !== 'http://127.0.0.1:56611' ||
    !target.pathname.startsWith('/realms/actvero-cli-test/')) {
  throw new Error('Only the isolated CLI identity fixture is allowed')
}
let receive
const callback = new Promise(resolve => { receive = resolve })
const listener = http.createServer((request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1:49163')
  response.writeHead(url.pathname === '/actvero/cli/callback' ? 200 : 404, {
    'Content-Type': 'text/plain', 'Cache-Control': 'no-store',
  })
  response.end('CLI fixture callback received')
  if (url.pathname === '/actvero/cli/callback') {
    receive({
      code: url.searchParams.get('code'),
      state: url.searchParams.get('state'),
      issuer: url.searchParams.get('iss'),
    })
  }
})
await new Promise((resolve, reject) => {
  listener.once('error', reject)
  listener.listen(49163, '127.0.0.1', resolve)
})
const executablePath = process.env.ACTVERO_TEST_BROWSER
let browser
let phase = 'launch'
try {
  browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
  const page = await browser.newPage()
  page.setDefaultTimeout(15000)
  phase = 'authorization'
  await page.goto(target.href)
  await page.locator('#username').fill('cli-user')
  await page.locator('#password').fill('cli-user-ephemeral-only')
  phase = 'submit'
  await page.locator('#kc-login').click()
  phase = 'callback'
  let timer
  try {
    const result = await Promise.race([
      callback,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('Isolated callback timeout')), 15000)
      }),
    ])
    process.stdout.write(JSON.stringify(result))
  } finally {
    clearTimeout(timer)
  }
} catch {
  // Playwright errors can include authorization URLs. Never expose them to test logs.
  process.stderr.write('Isolated browser fixture failed at ' + phase + '\n')
  process.exitCode = 1
} finally {
  if (browser) await browser.close()
  await new Promise(resolve => listener.close(resolve))
}
