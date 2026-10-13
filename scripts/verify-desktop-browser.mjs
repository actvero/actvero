// Isolated test browser. Protocol and credentials travel only over private pipes.
import { createRequire } from 'node:module'
import { createInterface } from 'node:readline'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true, executablePath: process.env.ACTVERO_TEST_BROWSER })
const page = await browser.newPage()
let callback = null
for await (const line of createInterface({ input: process.stdin })) {
  try {
    const request = JSON.parse(line)
    callback = null
    await page.goto(request.url, { waitUntil: 'domcontentloaded' })
    let prompted = false
    if (!/\/(actvero\/callback|api\/v1\/auth\/callback)(\?|$)/.test(page.url())) {
      const username = page.locator('#username')
      if (await username.isVisible()) await username.fill(request.username)
      await page.locator('#password').fill(request.password)
      prompted = true
      await page.locator('#kc-login').click()
    }
    await page.waitForURL(/\/(actvero\/callback|api\/v1\/auth\/callback)(\?|$)/)
    callback = page.url()
    process.stdout.write(JSON.stringify({ callback, prompted }) + '\n')
  } catch (error) {
    process.stdout.write(JSON.stringify({ error: 'browser_login_failed', type: error.name, page: new URL(page.url()).pathname, visible: (await page.locator('body').innerText()).slice(0, 500) }) + '\n')
  }
}
await browser.close()
