import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { OrganizationSettingsPage } from './settings-page'

const id = '00000000-0000-4000-8000-000000000001'
vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: '00000000-0000-4000-8000-000000000001' },
    csrf: 'test-csrf',
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({ children, title }: { children: ReactNode; title: string }) => (
    <main>
      <h1>{title}</h1>
      {children}
    </main>
  ),
}))
const initial = { id, name: '原组织', created_at: '2026-01-01T00:00:00Z' }
const clients: QueryClient[] = []
function respond(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
async function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  client.setQueryData(['session'], { organization: { name: initial.name } })
  await render(
    <QueryClientProvider client={client}>
      <OrganizationSettingsPage />
    </QueryClientProvider>
  )
  await expect
    .element(page.getByRole('textbox', { name: '组织名称' }))
    .toHaveValue(initial.name)
  return client
}
afterEach(async () => {
  await cleanup()
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
})

it('改名保留组织 ID，保存携带旧名称和 CSRF 并刷新组织会话', async () => {
  const writes: RequestInit[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit) => {
      if (init.method === 'PUT') {
        writes.push(init)
        return respond({ ...initial, name: '新的组织' })
      }
      return respond(initial)
    })
  )
  const client = await mount()
  const save = page.getByRole('button', { name: '保存', exact: true })
  await expect.element(save).toBeDisabled()
  await expect
    .element(page.getByRole('textbox', { name: '组织 ID' }))
    .toHaveAttribute('readonly')
  await page.getByRole('textbox', { name: '组织名称' }).fill('新的组织')
  await save.click()
  await expect.poll(() => writes.length).toBe(1)
  expect(JSON.parse(writes[0].body as string)).toEqual({
    name: '新的组织',
    expected_name: initial.name,
  })
  expect(writes[0].headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
  await expect.element(save).toBeDisabled()
  expect(client.getQueryData(['organization', id, 'settings'])).toEqual({
    ...initial,
    name: '新的组织',
  })
  expect(client.getQueryState(['session'])?.isInvalidated).toBe(true)
})

it('取消更改不写入，冲突保留草稿并允许明确重新载入', async () => {
  let reads = 0
  const writes = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit) => {
      if (init.method === 'PUT') {
        writes()
        return respond(
          {
            error: {
              message: '组织信息已被其他管理员更新，请重新载入后再保存',
            },
          },
          409
        )
      }
      reads++
      return respond({
        ...initial,
        name: reads === 1 ? initial.name : '其他管理员的名称',
      })
    })
  )
  await mount()
  const name = page.getByRole('textbox', { name: '组织名称' })
  await name.fill('草稿名称')
  await page.getByRole('button', { name: '取消更改' }).click()
  await expect.element(name).toHaveValue(initial.name)
  expect(writes).not.toHaveBeenCalled()
  await name.fill('我的草稿')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect
    .element(page.getByText('组织信息已被其他管理员更新，请重新载入后再保存'))
    .toBeVisible()
  await expect.element(name).toHaveValue('我的草稿')
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect.element(name).toHaveValue('其他管理员的名称')
  await expect
    .element(page.getByRole('button', { name: '保存', exact: true }))
    .toBeDisabled()
  expect(writes).toHaveBeenCalledTimes(1)
})
