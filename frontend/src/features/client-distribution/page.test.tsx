import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ClientDistributionPage } from './page'

vi.mock('@/features/auth/session', () => ({
  useSession: () => ({ data: { csrf: 'test-csrf' } }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    children,
    action,
  }: {
    title: string
    children: ReactNode
    action?: ReactNode
  }) => (
    <main>
      <h1>{title}</h1>
      {action}
      {children}
    </main>
  ),
}))
const clients: QueryClient[] = []
afterEach(async () => {
  await cleanup()
  clients.splice(0).forEach((c) => c.clear())
  vi.unstubAllGlobals()
})
async function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <ClientDistributionPage />
    </QueryClientProvider>
  )
}
const release = {
  id: '98c807fb-86b6-49d0-9f5a-e559ef915777',
  version: '1.2.0',
  channel: 'latest',
  notes: '修复问题',
  status: 'draft',
  revision: 4,
  minimum_os: { 'win-x64': 'Windows 10' },
  artifacts: [
    {
      id: '70fb1869-51ad-47d1-9df1-cd809e083bb2',
      filename: 'app.exe',
      target: 'win-x64',
      role: 'payload',
      size_bytes: 100,
      status: 'ready',
    },
  ],
}

it('publishes only after checking a plan and a separate confirmation', async () => {
  const writes: { url: string; body: Record<string, unknown> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
        writes.push({ url, body: JSON.parse(init.body as string) })
        if (url.endsWith('/plan'))
          return Response.json({
            id: 'ab098bcb-10b1-45f0-b01e-42127d4779c8',
            release_id: release.id,
            release_revision: 4,
            targets: { 'win-x64': 0 },
            expires_at: '2099-01-01T00:00:00Z',
          })
        return Response.json({ ...release, status: 'published' })
      }
      return Response.json({
        items: url.endsWith('/releases') ? [release] : [],
      })
    })
  )
  await show()
  await page.getByRole('button', { name: '检查并发布' }).click()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '检查发布条件' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认发布' }))
    .toBeVisible()
  expect(writes).toHaveLength(1)
  expect(writes[0].body).toEqual({ expected_revision: 4, targets: ['win-x64'] })
  await page.getByRole('button', { name: '确认发布' }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].body).toEqual({
    plan_id: 'ab098bcb-10b1-45f0-b01e-42127d4779c8',
  })
})

it('keeps failed publication visible and does not offer confirmation after failed checks', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url.endsWith('/plan')
        ? Response.json(
            { error: { message: 'blockmap 尚未校验完成' } },
            { status: 422 }
          )
        : Response.json({ items: url.endsWith('/releases') ? [release] : [] })
    )
  )
  await show()
  await page.getByRole('button', { name: '检查并发布' }).click()
  await page.getByRole('button', { name: '检查发布条件' }).click()
  await expect.element(page.getByText('blockmap 尚未校验完成')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认发布' }))
    .not.toBeInTheDocument()
})

it('shows an access failure without retaining release controls', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json(
        { error: { message: '此操作仅限平台运营人员' } },
        { status: 403 }
      )
    )
  )
  await show()
  await expect.element(page.getByText('此操作仅限平台运营人员')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '新建更新版本' }))
    .toBeDisabled()
})
