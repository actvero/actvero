import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Model } from './model-form'
import { ModelCatalogPage } from './page'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({ organization: { tenant_id: 'org' }, csrf: 'csrf' }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    action,
    children,
  }: {
    title: string
    action: ReactNode
    children: ReactNode
  }) => (
    <main className='flex min-w-0 flex-col gap-6 p-6'>
      <div className='flex flex-wrap items-center justify-between gap-4'>
        <h1>{title}</h1>
        {action}
      </div>
      {children}
    </main>
  ),
}))
vi.mock('./model-editor', () => ({
  ModelEditor: ({
    model,
    close,
    saved,
  }: {
    model: Model
    close: () => void
    saved: (model: Model) => void
  }) => (
    <div role='dialog' aria-label='编辑模型测试'>
      <span>编辑版本 {model.version}</span>
      <button onClick={close}>关闭编辑</button>
      <button onClick={() => saved(model)}>模拟保存</button>
    </div>
  ),
}))

const base = {
  id: 'model-1',
  name: '示例模型',
  slug: 'team-chat',
  kind: 'chat',
  archived: false,
  version: 1,
  icon: '',
  icon_key: '',
  created_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:00:00Z',
  access: { enabled: false },
  binding_states: [
    {
      binding_id: 'binding-1',
      channel_id: 'channel-1',
      channel_name: '旧渠道',
      upstream_id: 'upstream',
      operation: 'chat',
      state: 'missing',
    },
  ],
  operations: [
    {
      kind: 'chat',
      enabled: false,
      bindings: [],
      budget_price: null,
      point_price: null,
    },
  ],
  endpoint_summary: {
    ready_count: 0,
    configured_count: 1,
    reasons: ['source_missing'],
    member_authorization: 'not_evaluated',
  },
} as unknown as Model

let client: QueryClient
const calls: { url: string; method: string; body?: unknown }[] = []
function backend({
  status = 200,
  initialAccess = false,
}: { status?: 200 | 403 | 409; initialAccess?: boolean } = {}) {
  calls.length = 0
  let archived = false
  let accessEnabled = initialAccess
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ url, method, body })
      if (method === 'PUT') {
        if (status !== 200)
          return Response.json(
            {
              error: { message: status === 409 ? '版本已变化' : '权限已变更' },
            },
            { status }
          )
        archived = body.archived
        if (archived) accessEnabled = false
        return Response.json({
          ...base,
          access: { enabled: accessEnabled },
          archived,
          version: 2,
        })
      }
      if (url.endsWith('/models/model-1'))
        return Response.json({
          ...base,
          access: { enabled: accessEnabled },
          version: 8,
        })
      return Response.json({
        total: 1,
        items: [{ ...base, access: { enabled: accessEnabled }, archived }],
      })
    })
  )
}
async function show() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  await render(
    <QueryClientProvider client={client}>
      <ModelCatalogPage />
    </QueryClientProvider>
  )
  await expect.element(page.getByText('team-chat')).toBeVisible()
}
afterEach(async () => {
  await cleanup()
  await client?.cancelQueries()
  client?.clear()
  vi.unstubAllGlobals()
  await page.viewport(1280, 800)
})

it('filters on the server, reads fresh detail before editing, and keeps search and focus after save', async () => {
  await page.viewport(1280, 900)
  backend()
  await show()
  await page.screenshot({ path: '/tmp/actvero-g2-02-model-list-desktop.png' })
  await page.getByRole('textbox', { name: '搜索模型' }).fill('team')
  await expect
    .poll(() => calls.some((call) => call.url.includes('q=team')))
    .toBe(true)
  await page.getByRole('button', { name: '示例模型', exact: true }).click()
  await expect.element(page.getByText('编辑版本 8')).toBeVisible()
  expect(
    calls.filter((call) => call.url.endsWith('/models/model-1'))
  ).toHaveLength(1)
  await page.getByRole('button', { name: '模拟保存' }).click()
  await expect
    .element(page.getByRole('textbox', { name: '搜索模型' }))
    .toHaveValue('team')
  await expect
    .poll(() => document.activeElement?.textContent?.includes('示例模型'))
    .toBe(true)
  expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(0)
})

it.each([403, 409] as const)(
  'refreshes and blocks a stale archive action after %s',
  async (status) => {
    backend({ status })
    await show()
    await page.getByRole('button', { name: '示例模型的更多操作' }).click()
    await page.getByRole('menuitem', { name: '归档模型' }).click()
    await page.getByRole('button', { name: '归档', exact: true }).click()
    await expect
      .element(page.getByText(status === 409 ? '版本已变化' : '权限已变更'))
      .toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '请先刷新' }))
      .toBeDisabled()
    if (status === 403) {
      await page.getByRole('button', { name: '取消', exact: true }).click()
      await expect.element(page.getByText(/写入操作已停用/)).toBeVisible()
      await expect
        .element(page.getByRole('button', { name: '添加模型' }))
        .toBeDisabled()
    }
    expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(1)
  }
)

it('keeps a restored model closed until an administrator explicitly reopens it', async () => {
  backend({ initialAccess: true })
  await show()
  await expect.element(page.getByText('已开放')).toBeVisible()
  await page.getByRole('button', { name: '示例模型的更多操作' }).click()
  await page.getByRole('menuitem', { name: '归档模型' }).click()
  await page.getByRole('button', { name: '归档', exact: true }).click()
  await expect.element(page.getByText('已归档')).toBeVisible()
  await page.getByRole('button', { name: '示例模型的更多操作' }).click()
  await page.getByRole('menuitem', { name: '恢复模型' }).click()
  await expect.element(page.getByText(/模型调用需重新开启/)).toBeVisible()
  await page.getByRole('button', { name: '恢复', exact: true }).click()
  await expect.element(page.getByText('未开放', { exact: true })).toBeVisible()
  expect(
    calls
      .filter((call) => call.method === 'PUT')
      .map((call) => (call.body as { archived: boolean }).archived)
  ).toEqual([true, false])
})

it('shows separate open, binding, endpoint and price states in a 390px card without overflow', async () => {
  await page.viewport(390, 844)
  backend()
  await show()
  await expect.element(page.getByText('0/1 就绪')).toBeVisible()
  await expect.element(page.getByText('1 个来源缺失')).toBeVisible()
  await expect.element(page.getByText('预算价格')).toBeVisible()
  await expect.element(page.getByText('积分单价')).toBeVisible()
  const size = {
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    main: document.querySelector('main')?.scrollWidth ?? 0,
  }
  expect(size.document).toBeLessThanOrEqual(size.viewport + 1)
  expect(size.main).toBeLessThanOrEqual(size.viewport + 1)
  await page.screenshot({ path: '/tmp/actvero-g2-02-model-list-390.png' })
})
