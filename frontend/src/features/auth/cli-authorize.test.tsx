import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { CliConsentForm } from './cli-authorize'

const proof = {
  attempt_id: '3cf25a2b-87ad-4e65-b3f6-3efce56f25df',
  state: 's'.repeat(43),
}
const organizations = [
  { org_id: 'b4de7d4e-04bb-4bc8-81a0-744401d1c36e', name: 'Studio One' },
  { org_id: 'c18a53df-f9f3-4398-8e43-bc0d4b8efea5', name: 'Studio Two' },
]
const context = {
  device_name: 'My terminal',
  user: { name: 'Test User', email: 'test@example.com' },
  organizations,
}
const clients: QueryClient[] = []

it('grants selected platform permissions without granting any organization access', async () => {
  let decision: Record<string, unknown> | undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith('/context'))
        return Response.json({
          ...context,
          target: 'platform',
          organizations: [],
        })
      decision = JSON.parse(init.body as string)
      return Response.json({
        redirect_url: 'https://identity.example.com/auth',
      })
    })
  )
  await show()
  await page.getByRole('checkbox', { name: '维护版本与上传文件' }).click()
  await page.getByRole('button', { name: '确认授权' }).click()
  expect(decision).toEqual({
    ...proof,
    approve: true,
    org_ids: [],
    scope: 'platform:read',
    platform_permissions: ['releases.write'],
  })
})
async function show(navigate = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <CliConsentForm proof={proof} csrf='browser-csrf' navigate={navigate} />
    </QueryClientProvider>
  )
  return navigate
}
afterEach(async () => {
  await cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 900)
})

it('does not authorize on load and sends exactly the organizations and scope selected by the user', async () => {
  const requests: Array<{ url: string; body: Record<string, unknown> }> = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'browser-csrf' })
      const body = JSON.parse(init.body as string)
      requests.push({ url, body })
      return Response.json(
        url.endsWith('/context')
          ? context
          : { redirect_url: 'https://identity.example.com/auth' }
      )
    })
  )
  const navigate = await show()
  await expect.element(page.getByText('My terminal')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认授权' }))
    .toBeDisabled()
  expect(requests.map((row) => row.url)).toEqual([
    '/api/v1/cli-authorization/context',
  ])
  await expect
    .element(page.getByRole('radio', { name: /只读查询/ }))
    .toBeChecked()
  await page.getByRole('checkbox', { name: /Studio Two/ }).click()
  await page.getByRole('radio', { name: /管理资源/ }).click()
  await page.getByRole('button', { name: '确认授权' }).click()
  expect(requests[1].body).toEqual({
    ...proof,
    approve: true,
    org_ids: [organizations[1].org_id],
    scope: 'management:read management:write',
  })
  expect(navigate).toHaveBeenCalledWith('https://identity.example.com/auth')
})

it('supports denying without any organization and blocks repeated clicks while returning', async () => {
  let body: Record<string, unknown> | undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith('/context')) return Response.json(context)
      body = JSON.parse(init.body as string)
      return Response.json({
        redirect_url:
          'http://127.0.0.1:49161/actvero/cli/callback?error=access_denied',
      })
    })
  )
  const navigate = await show()
  await page.getByRole('button', { name: '拒绝' }).click()
  expect(body).toEqual({
    ...proof,
    approve: false,
    org_ids: [],
    scope: 'management:read',
  })
  expect(navigate).toHaveBeenCalledOnce()
  await expect
    .element(page.getByRole('button', { name: '拒绝' }))
    .toBeDisabled()
})

it('shows a failed authorization without navigating or pretending success', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.endsWith('/context')
          ? context
          : { error: { message: '授权请求已过期' } },
        { status: url.endsWith('/context') ? 200 : 410 }
      )
    )
  )
  const navigate = await show()
  await page.getByRole('checkbox', { name: /Studio One/ }).click()
  await page.getByRole('button', { name: '确认授权' }).click()
  await expect.element(page.getByText('授权请求已过期')).toBeVisible()
  expect(navigate).not.toHaveBeenCalled()
})

it('does not offer implicit organization access to accounts without eligible memberships', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ ...context, organizations: [] }))
  )
  await page.viewport(390, 844)
  await show()
  await expect
    .element(page.getByText('当前账号没有可管理的组织，请联系组织管理员。'))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认授权' }))
    .toBeDisabled()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth
  )
})
