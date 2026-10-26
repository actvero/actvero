import { type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ModelChannelsPage } from './page'
import type { ProviderModule } from './provider-modules'
import type { Detail } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
  }),
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
    <main className='flex min-w-0 flex-col gap-6 p-4'>
      <div className='flex items-center justify-between gap-3'>
        <h1>{title}</h1>
        {action}
      </div>
      {children}
    </main>
  ),
}))

const providers: ProviderModule[] = [
  {
    id: 'openai-compatible',
    name: '自定义兼容',
    default_base_url: '',
    official_service_root: '',
    default_api_prefix: '',
    setup_help: '',
    version: 1,
    category: 'compatible',
    icon_key: 'openai-compatible',
    aliases: [],
    base_url_help: '',
    allow_no_auth: true,
    default_apis: ['chat_completions'],
    model_discovery: true,
    balance_query: false,
    member_inference: true,
    member_operations: ['chat'],
    test_operations: ['chat'],
  },
]
const base: Detail = {
  id: 'channel-one',
  version: 2,
  provider: 'openai-compatible',
  name: '一号渠道',
  description: '',
  icon: '',
  base_url: 'https://example.test/v1',
  connection: {
    address_mode: 'legacy_api_base',
    legacy_base_url: 'https://example.test/v1',
    resolver_version: 1,
  },
  manual_enabled: true,
  automatic_protection: { enabled: true },
  auth_mode: 'none',
  credential_configured: false,
  timeout_seconds: 20,
  declared_apis: ['chat_completions'],
  archived: false,
  model_count: 1,
  last_check: {
    at: '2026-10-03T00:00:00Z',
    ok: true,
    message: '目录读取成功',
    kind: 'check',
  },
  last_diagnostic: {
    at: '2026-10-02T00:00:00Z',
    ok: null,
    status: 'unconfirmed',
    operation: 'chat',
    upstream_model_id: 'demo',
    request_id: 'request-one',
    stale: true,
  },
  health_summary: {
    state: 'no_routes',
    health_counts: {},
    as_of: '2026-10-03T00:00:00Z',
  },
  created_at: '2026-10-03T00:00:00Z',
  checks: [],
  models: [
    { id: 'demo', source: 'manual', registered_at: '2026-10-03T00:00:00Z' },
  ],
}
const clients: QueryClient[] = []
beforeEach(async () => {
  await page.viewport(1280, 900)
})
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 800)
})
async function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  client.setQueryData(['organization', 'test-org', 'llm-providers'], providers)
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>
      <ModelChannelsPage />
    </QueryClientProvider>
  )
}

it('keeps health and inference visible without the directory column, filters on the server, and fits 390px', async () => {
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(url)
      return Response.json({ items: [base], total: 1 })
    })
  )
  await show()
  await expect
    .element(page.getByText('目录读取成功', { exact: true }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('columnheader', { name: '最近目录检查' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByText('结果未确认', { exact: true }))
    .toBeVisible()
  await expect.element(page.getByText('旧版本', { exact: false })).toBeVisible()
  await expect
    .element(page.getByText('未关联可调用模型', { exact: true }))
    .toBeVisible()
  await page.screenshot({ path: '/tmp/actvero-g1-03-list-desktop.png' })
  await page.viewport(390, 844)
  await expect
    .element(page.getByText('目录读取成功', { exact: true }))
    .not.toBeInTheDocument()
  await expect.element(page.getByRole('button', { name: '筛选' })).toBeVisible()
  await page.screenshot({ path: '/tmp/actvero-g1-03-list-narrow.png' })
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  const card = document.querySelector('[data-slot="card"]') as HTMLElement
  expect(card.scrollWidth).toBeLessThanOrEqual(card.clientWidth + 1)
  await page.getByRole('button', { name: '筛选' }).click()
  await page.getByRole('combobox', { name: '渠道状态' }).click()
  await page.getByRole('option', { name: '已停用' }).click()
  await page.getByRole('button', { name: '应用筛选' }).click()
  await expect
    .poll(() => requests.some((url) => url.includes('manual_enabled=false')))
    .toBe(true)
})

it('confirms a single status change and displays per-item batch conflicts', async () => {
  const second = {
    ...base,
    id: 'channel-two',
    name: '二号渠道',
    last_diagnostic: null,
  }
  let first = base
  const writes: { url: string; body: Record<string, unknown> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      const method = options?.method ?? 'GET'
      if (method === 'PUT') {
        const body = JSON.parse(String(options?.body))
        writes.push({ url, body })
        first = { ...first, version: first.version + 1, manual_enabled: false }
        return Response.json(first)
      }
      if (method === 'POST') {
        writes.push({ url, body: JSON.parse(String(options?.body)) })
        return Response.json({
          items: [
            { id: first.id, status: 'updated', version: first.version + 1 },
            { id: second.id, status: 'conflict', version: 3 },
          ],
        })
      }
      return Response.json({ items: [first, second], total: 2 })
    })
  )
  await show()
  await page.getByRole('button', { name: '停用', exact: true }).first().click()
  await expect
    .element(page.getByText('渠道状态与绑定健康独立。', { exact: false }))
    .toBeVisible()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect
    .poll(() =>
      writes.some(
        (item) =>
          item.url.endsWith('/status') && item.body.manual_enabled === false
      )
    )
    .toBe(true)
  await page.getByRole('checkbox', { name: '选择一号渠道' }).click()
  await page.getByRole('checkbox', { name: '选择二号渠道' }).click()
  await page.getByRole('button', { name: '批量启用' }).click()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect.element(page.getByText('批量操作结果')).toBeVisible()
  await expect
    .element(page.getByText('版本冲突，请刷新', { exact: false }))
    .toBeVisible()
  expect(
    writes.find((item) => item.url.endsWith('/status-batch'))?.body.items
  ).toHaveLength(2)
})

it.each([409, 403])(
  'keeps the detail tab after %i and prevents a repeated write',
  async (status) => {
    let current = base
    let writes = 0
    const message =
      status === 409 ? '渠道已被修改，请刷新后重试' : '管理权限已变化'
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, options?: RequestInit) => {
        if (url.endsWith('/channel-addresses/resolve')) {
          return Response.json({
            directory_method: 'GET',
            directory_url: 'https://example.test/v1/models',
            operation_targets: [],
          })
        }
        if ((options?.method ?? 'GET') === 'PUT') {
          writes += 1
          if (status === 409) current = { ...current, version: 3 }
          return Response.json({ error: { message } }, { status })
        }
        return Response.json(
          url.includes('/llm/channels?')
            ? { items: [current], total: 1 }
            : current
        )
      })
    )
    await show()
    await page.getByRole('button', { name: '一号渠道', exact: true }).click()
    await page.getByRole('tab', { name: '健康' }).click()
    await expect
      .element(page.getByRole('tab', { name: '健康' }))
      .toHaveAttribute('data-state', 'active')
    await page.getByRole('button', { name: '停用' }).click()
    await page.getByRole('button', { name: '确认', exact: true }).click()
    await expect.element(page.getByText(message)).toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '确认', exact: true }))
      .toBeDisabled()
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await expect
      .element(page.getByRole('tab', { name: '健康' }))
      .toHaveAttribute('data-state', 'active')
    expect(writes).toBe(1)
  }
)

it('loads a full copy draft without carrying over the upstream key', async () => {
  const protectedChannel: Detail = {
    ...base,
    auth_mode: 'api_key',
    credential_configured: true,
  }
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(url)
      return Response.json(
        url.includes('/llm/channels?')
          ? { items: [protectedChannel], total: 1 }
          : protectedChannel
      )
    })
  )
  await show()
  await page.getByRole('button', { name: '一号渠道的更多操作' }).click()
  await page.getByRole('menuitem', { name: '复制为新渠道' }).click()
  await expect
    .element(page.getByText('新渠道不会复制密钥', { exact: false }))
    .toBeVisible()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect.element(page.getByText('复制渠道配置')).toBeVisible()
  await expect
    .element(page.getByLabelText('渠道名称'))
    .toHaveValue('一号渠道 副本')
  await expect
    .element(page.getByLabelText('API Key', { exact: true }))
    .toHaveValue('')
  expect(
    requests.some((url) => url.endsWith('/llm/channels/channel-one'))
  ).toBe(true)
})

it('keeps action hit areas stable while tooltips change and preserves click and keyboard actions', async () => {
  const writes = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method && options.method !== 'GET') writes()
      return Response.json(
        url.includes('/llm/channels?') ? { items: [base], total: 1 } : base
      )
    })
  )
  await show()
  const test = page.getByRole('button', { name: '测试', exact: true }).first()
  const edit = page.getByRole('button', { name: '编辑', exact: true }).first()
  const status = page.getByRole('button', { name: '停用', exact: true }).first()
  await expect.element(test).toBeVisible()
  const inventory = page
    .getByRole('button', { name: '1 个登记模型' })
    .first()
    .element()
  const binding = inventory.previousElementSibling as HTMLElement
  expect(
    Math.abs(
      inventory.getBoundingClientRect().left -
        binding.getBoundingClientRect().left
    )
  ).toBeLessThan(1)
  const trigger = test.element()
  await test.hover()
  await expect
    .element(page.getByRole('tooltip', { name: '测试' }))
    .toBeVisible()
  const bounds = trigger.getBoundingClientRect()
  expect(
    document.elementFromPoint(
      bounds.x + bounds.width / 2,
      bounds.y + bounds.height / 2
    )
  ).toBe(trigger)
  await edit.hover()
  await expect
    .element(page.getByRole('tooltip', { name: '编辑' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('tooltip', { name: '测试' }))
    .not.toBeInTheDocument()
  expect(trigger.isConnected).toBe(true)
  await status.hover()
  await expect
    .element(page.getByRole('tooltip', { name: '停用' }))
    .toBeVisible()
  await status.click()
  await expect
    .element(page.getByText('渠道状态与绑定健康独立。', { exact: false }))
    .toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  const more = page.getByRole('button', { name: '一号渠道的更多操作' }).first()
  await more.click()
  await expect
    .element(page.getByRole('menuitem', { name: '查看详情' }))
    .toBeVisible()
  await userEvent.keyboard('{Escape}')
  await expect
    .element(page.getByRole('menuitem', { name: '查看详情' }))
    .not.toBeInTheDocument()
  // Wait for the menu's deferred focus restoration before moving focus again.
  await expect.element(more).toHaveFocus()
  status.element().focus()
  await expect.element(status).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  await expect
    .element(page.getByText('渠道状态与绑定健康独立。', { exact: false }))
    .toBeVisible()
  expect(writes).not.toHaveBeenCalled()
})

it('keeps narrow card actions clickable with stable icon hit areas', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.includes('/llm/channels?') ? { items: [base], total: 1 } : base
      )
    )
  )
  await page.viewport(390, 844)
  await show()
  const status = page.getByRole('button', { name: '停用', exact: true }).first()
  await expect.element(status).toBeVisible()
  const bounds = status.element().getBoundingClientRect()
  expect(bounds.width).toBeGreaterThanOrEqual(36)
  await status.hover()
  await expect
    .element(page.getByRole('tooltip', { name: '停用' }))
    .toBeVisible()
  await status.click()
  await expect
    .element(page.getByText('渠道状态与绑定健康独立。', { exact: false }))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
})

it.each([true, false])(
  'preserves hovered actions and an open menu during refreshes (enabled: %s)',
  async (enabled) => {
    const channel = { ...base, manual_enabled: enabled }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ items: [channel], total: 1 }))
    )
    await show()
    const client = clients[0]
    let modelCount = 1
    const refresh = () => {
      modelCount += 1
      client.setQueriesData(
        { queryKey: ['organization', 'test-org', 'model-channels', 'list'] },
        { items: [{ ...channel, model_count: modelCount }], total: 1 }
      )
    }
    const statusLabel = enabled ? '停用' : '启用'
    for (const label of ['测试', '编辑', statusLabel]) {
      const button = page.getByRole('button', { name: label, exact: true })
      await button.hover()
      const tooltip = page.getByRole('tooltip', { name: label })
      await expect.element(tooltip).toBeVisible()
      const trigger = button.element()
      // Keep the pointer still while independent query updates reach the page.
      // An immediate hover/click would miss a lost tooltip or replaced trigger.
      for (let update = 0; update < 3; update += 1) {
        refresh()
        await expect
          .element(page.getByText(`${modelCount} 个登记模型`, { exact: true }))
          .toBeVisible()
        await new Promise((resolve) => window.setTimeout(resolve, 150))
        expect(button.element()).toBe(trigger)
        await expect.element(tooltip).toBeVisible()
      }
    }
    await page.getByRole('button', { name: statusLabel, exact: true }).click()
    await expect
      .element(page.getByRole('button', { name: '确认', exact: true }))
      .toBeVisible()
    await page.getByRole('button', { name: '取消', exact: true }).click()

    const more = page.getByRole('button', { name: '一号渠道的更多操作' })
    await more.click()
    const details = page.getByRole('menuitem', { name: '查看详情' })
    await expect.element(details).toBeVisible()
    refresh()
    await expect
      .element(page.getByText(`${modelCount} 个登记模型`, { exact: true }))
      .toBeVisible()
    await expect.element(details).toBeVisible()
    await userEvent.keyboard('{Escape}')
    await expect.element(more).toHaveFocus()
  }
)

it('keeps an open menu on its channel after reordering and uses the latest version', async () => {
  const second = { ...base, id: 'channel-two', name: '二号渠道' }
  const writes: { url: string; body: Record<string, unknown> }[] = []
  let items = [base, second]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === 'PUT') {
        writes.push({ url, body: JSON.parse(String(options.body)) })
        return Response.json({ ...base, version: 4, archived: true })
      }
      return Response.json({ items, total: items.length })
    })
  )
  await show()
  await page.getByRole('button', { name: '一号渠道的更多操作' }).click()
  await expect
    .element(page.getByRole('menuitem', { name: '归档渠道' }))
    .toBeVisible()

  items = [second, { ...base, version: 3, name: '更新后的一号渠道' }]
  clients[0].setQueriesData(
    { queryKey: ['organization', 'test-org', 'model-channels', 'list'] },
    { items, total: items.length }
  )
  await expect
    .element(page.getByText('更新后的一号渠道', { exact: true }))
    .toBeVisible()
  await page.getByRole('menuitem', { name: '归档渠道' }).click()
  await expect
    .element(page.getByText('确认归档“更新后的一号渠道”？'))
    .toBeVisible()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect
    .poll(() => writes)
    .toEqual([
      {
        url: '/api/v1/llm/channels/channel-one/archive',
        body: { version: 3, archived: true },
      },
    ])
})
