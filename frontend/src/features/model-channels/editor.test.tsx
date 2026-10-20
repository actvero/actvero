import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ChannelEditor } from './channel-editor'
import type { ProviderModule } from './provider-modules'
import type { Detail } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'editor-test' },
    csrf: 'csrf-test',
  }),
}))

const providers: ProviderModule[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    default_base_url: 'https://api.openai.com/v1',
    official_service_root: 'https://api.openai.com',
    default_api_prefix: '/v1',
    setup_help: '普通 API',
    version: 1,
    category: 'vendor',
    icon_key: 'openai',
    aliases: [],
    base_url_help: '旧 Base URL',
    allow_no_auth: false,
    default_apis: ['chat_completions'],
    model_discovery: true,
    balance_query: false,
    member_inference: true,
    member_operations: ['chat'],
    test_operations: ['chat'],
  },
  {
    id: 'openai-compatible',
    name: '自定义兼容',
    default_base_url: '',
    official_service_root: '',
    default_api_prefix: '',
    setup_help: '',
    version: 1,
    category: 'compatible',
    icon_key: 'custom',
    aliases: [],
    base_url_help: '旧 Base URL',
    allow_no_auth: true,
    default_apis: ['chat_completions'],
    model_discovery: true,
    balance_query: false,
    member_inference: true,
    member_operations: ['chat'],
    test_operations: ['chat'],
  },
]

const legacy: Detail = {
  id: 'legacy-channel',
  version: 3,
  provider: 'openai-compatible',
  name: '旧渠道',
  description: '',
  icon: '',
  base_url: 'https://example.test/v1',
  connection: {
    address_mode: 'legacy_api_base',
    legacy_base_url: 'https://example.test/v1',
    resolver_version: 1,
  },
  manual_enabled: false,
  automatic_protection: { enabled: false },
  auth_mode: 'api_key',
  credential_configured: true,
  timeout_seconds: 20,
  declared_apis: ['chat_completions'],
  archived: false,
  model_count: 1,
  last_check: null,
  created_at: '2026-10-03T00:00:00Z',
  checks: [],
  models: [
    { id: 'model-a', source: 'manual', registered_at: '2026-10-03T00:00:00Z' },
  ],
  test_defaults: {
    upstream_id: 'model-a',
    operation: 'chat',
    endpoint: 'chat_completions',
    stream: false,
  },
  test_defaults_status: { valid: true, reason: 'ready' },
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

async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  client.setQueryData(
    ['organization', 'editor-test', 'llm-providers'],
    providers
  )
  clients.push(client)
  const view = await render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
  await expect
    .poll(() => page.getByRole('dialog').element().getBoundingClientRect().right)
    .toBeLessThanOrEqual(innerWidth + 1)
  return view
}

function failure(status: number, message: string, references?: unknown[]) {
  return Response.json({ error: { message, references } }, { status })
}

it('uses official address resolution without sending the old provider base or a key', async () => {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body)) as Record<string, unknown>
      calls.push({ url, body })
      if (url.endsWith('/channel-addresses/resolve'))
        return Response.json({
          address_mode: 'provider_default',
          resolver_version: 1,
          directory_method: 'GET',
          directory_url: 'https://api.openai.com/v1/models',
          operation_targets: [
            {
              operation: 'chat',
              method: 'POST',
              url: 'https://api.openai.com/v1/chat/completions',
            },
          ],
          warnings: [],
        })
      return Response.json({
        ...legacy,
        ...body,
        id: 'new-channel',
        provider: 'openai',
        version: 1,
      })
    })
  )
  const saved = vi.fn()
  await show(<ChannelEditor close={vi.fn()} saved={saved} />)
  await page.getByRole('button', { name: 'OpenAI', exact: true }).click()
  await expect
    .element(page.getByLabelText('地址方式'))
    .toHaveTextContent('官方地址')
  await page.getByLabelText('地址方式').click()
  await expect
    .element(page.getByRole('option', { name: '官方地址', exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('option', { name: '自定义地址', exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('option', { name: '保留旧地址方式' }))
    .not.toBeInTheDocument()
  await page.getByRole('option', { name: '官方地址', exact: true }).click()
  await page.getByRole('button', { name: '预览最终地址' }).click()
  await expect
    .element(page.getByText('目录：GET https://api.openai.com/v1/models'))
    .toBeVisible()
  await page.screenshot({
    path: '__screenshots__/actvero-g1-03-editor-desktop.png',
  })
  expect(calls[0].body).toEqual(
    expect.objectContaining({
      provider: 'openai',
      connection: expect.objectContaining({ address_mode: 'provider_default' }),
    })
  )
  expect(JSON.stringify(calls[0].body)).not.toContain('api_key')
  expect(JSON.stringify(calls[0].body)).not.toContain(
    'https://api.openai.com/v1'
  )
  await page.getByLabelText('API Key', { exact: true }).fill('fake-secret')
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(calls[1].body).toEqual(
    expect.objectContaining({
      base_url: '',
      request_id: expect.any(String),
      manual_enabled: true,
      automatic_protection: { enabled: true },
    })
  )
})

it('shows saved compatibility connections as custom addresses without changing targets or credentials', async () => {
  const saved = vi.fn()
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body.connection).toEqual(legacy.connection)
    expect(body.base_url).toBe(legacy.base_url)
    expect(body.api_key).toBeUndefined()
    return Response.json({ ...legacy, version: 4 })
  })
  vi.stubGlobal('fetch', fetcher)
  await show(<ChannelEditor channel={legacy} close={vi.fn()} saved={saved} />)
  await expect
    .element(page.getByLabelText('API 基础 URL'))
    .toHaveValue(legacy.base_url)
  await expect
    .element(page.getByLabelText('地址方式'))
    .toHaveTextContent('自定义地址')
  await expect
    .element(page.getByText('旧地址方式', { exact: true }))
    .not.toBeInTheDocument()
  await page.getByLabelText('地址方式').click()
  await expect
    .element(page.getByRole('option', { name: '官方地址', exact: true }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('option', { name: '保留旧地址方式' }))
    .not.toBeInTheDocument()
  await page.getByRole('option', { name: '自定义地址', exact: true }).click()
  await page.getByLabelText('渠道名称').fill('新的渠道名称')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('preserves an explicit empty prefix on edit and requires no replacement key for metadata', async () => {
  const source: Detail = {
    ...legacy,
    provider: 'openai',
    base_url: 'https://proxy.test',
    connection: {
      address_mode: 'service_root',
      service_root: 'https://proxy.test',
      api_prefix: '',
      resolver_version: 1,
    },
  }
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body.connection).toEqual(source.connection)
    expect(body.api_key).toBeUndefined()
    expect(body.manual_enabled).toBe(false)
    expect(body.automatic_protection).toEqual({ enabled: false })
    return Response.json({ ...source, name: body.name, version: 4 })
  })
  vi.stubGlobal('fetch', fetcher)
  await show(<ChannelEditor channel={source} close={vi.fn()} saved={vi.fn()} />)
  await page.getByLabelText('渠道名称').fill('只改名称')
  await page.getByRole('tab', { name: '高级设置' }).click()
  await expect
    .element(page.getByRole('switch', { name: '自定义接口前缀' }))
    .toBeChecked()
  await expect
    .element(page.getByRole('textbox', { name: '接口前缀', exact: true }))
    .toHaveValue('')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => fetcher.mock.calls.length).toBe(1)
})

it('copies inventory and default into a new draft without copying credentials', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body.request_id).toEqual(expect.any(String))
    expect(body.models).toEqual([{ id: 'model-a' }])
    expect(body.test_defaults).toEqual(legacy.test_defaults)
    expect(body.api_key).toBe('new-fake-key')
    return Response.json({ ...legacy, ...body, id: 'copy-channel', version: 1 })
  })
  vi.stubGlobal('fetch', fetcher)
  const saved = vi.fn()
  await show(<ChannelEditor copyFrom={legacy} close={vi.fn()} saved={saved} />)
  await expect
    .element(page.getByLabelText('渠道名称'))
    .toHaveValue('旧渠道 副本')
  await expect
    .element(page.getByLabelText('API Key', { exact: true }))
    .toHaveValue('')
  await page.getByLabelText('API Key', { exact: true }).fill('new-fake-key')
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
})

it('holds an uncertain create for the receipt and never sends a second POST', async () => {
  let posts = 0
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes('/mutation-receipts/')) return failure(404, '未找到')
    if (options?.method === 'POST') {
      posts += 1
      return failure(503, '响应丢失')
    }
    return Response.json(legacy)
  })
  vi.stubGlobal('fetch', fetcher)
  await show(
    <ChannelEditor copyFrom={legacy} close={vi.fn()} saved={vi.fn()} />
  )
  await page.getByLabelText('API Key', { exact: true }).fill('new-fake-key')
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect.element(page.getByText('尚未确认保存结果')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '保存为新渠道' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '查询保存结果' }).click()
  await expect
    .element(page.getByRole('button', { name: '按原请求重试' }))
    .toBeVisible()
  expect(posts).toBe(1)
})

it('recovers a completed create receipt after a 5xx response without reposting', async () => {
  let posts = 0
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes('/mutation-receipts/'))
      return Response.json({
        scope: 'channel.create',
        request_id: 'same-request',
        resource_id: 'created-channel',
        state: 'completed',
      })
    if (url.endsWith('/channels/created-channel'))
      return Response.json({ ...legacy, id: 'created-channel' })
    if (options?.method === 'POST') {
      posts += 1
      return failure(503, '响应丢失')
    }
    throw new Error('unexpected request')
  })
  vi.stubGlobal('fetch', fetcher)
  const saved = vi.fn()
  await show(<ChannelEditor copyFrom={legacy} close={vi.fn()} saved={saved} />)
  await page.getByLabelText('API Key', { exact: true }).fill('new-fake-key')
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect.element(page.getByText('尚未确认保存结果')).toBeVisible()
  await page.getByRole('button', { name: '查询保存结果' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(posts).toBe(1)
})

it('clears a draft key and blocks writes when address preview loses admin permission', async () => {
  const fetcher = vi.fn(async () => failure(403, '仅管理员可操作'))
  vi.stubGlobal('fetch', fetcher)
  await show(
    <ChannelEditor copyFrom={legacy} close={vi.fn()} saved={vi.fn()} />
  )
  await page.getByLabelText('API Key', { exact: true }).fill('new-fake-key')
  await page.getByRole('button', { name: '预览最终地址' }).click()
  await expect.element(page.getByText('管理权限已变化')).toBeVisible()
  await expect
    .element(page.getByLabelText('API Key', { exact: true }))
    .toHaveValue('')
  await expect
    .element(page.getByRole('button', { name: '保存为新渠道' }))
    .toBeDisabled()
})

it('shows bound model references on an inventory removal conflict', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      failure(409, '渠道库存仍被使用', [
        {
          model_id: 'model-1',
          model_name: '团队模型',
          operation: 'chat',
          binding_id: 'binding-1',
        },
      ])
    )
  )
  await show(
    <ChannelEditor
      channel={{ ...legacy, test_defaults: null, test_defaults_status: null }}
      close={vi.fn()}
      saved={vi.fn()}
    />
  )
  await page.getByRole('button', { name: '移除 model-a' }).click()
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.element(page.getByText(/团队模型（chat）/)).toBeVisible()
})

it('keeps a stale edit draft until the admin explicitly adopts the current version', async () => {
  let puts = 0
  const latest = { ...legacy, name: '别人已修改', version: 4 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === 'GET') return Response.json(latest)
      const body = JSON.parse(String(options?.body))
      puts += 1
      if (puts === 1) {
        expect(body.version).toBe(3)
        return failure(409, '渠道已被修改')
      }
      expect(body.version).toBe(4)
      return Response.json({ ...latest, version: 5 })
    })
  )
  const saved = vi.fn()
  await show(<ChannelEditor channel={legacy} close={vi.fn()} saved={saved} />)
  await page.getByLabelText('渠道名称').fill('我的草稿')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.element(page.getByText('配置已被其他管理员修改')).toBeVisible()
  await expect.element(page.getByLabelText('渠道名称')).toHaveValue('我的草稿')
  await page.getByRole('button', { name: '加载最新并比较' }).click()
  await expect.element(page.getByText(/别人已修改/)).toBeVisible()
  await page.getByRole('button', { name: '舍弃草稿，采用最新配置' }).click()
  await expect
    .element(page.getByLabelText('渠道名称'))
    .toHaveValue('别人已修改')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
})

it('shows a dirty-exit confirmation and keeps advanced fields within a 390px sheet', async () => {
  await page.viewport(390, 844)
  await show(
    <ChannelEditor
      copyFrom={{
        ...legacy,
        base_url: 'https://proxy.test/v1',
        connection: {
          address_mode: 'service_root',
          service_root: 'https://proxy.test',
          api_prefix: '/v1',
          resolver_version: 1,
        },
      }}
      close={vi.fn()}
      saved={vi.fn()}
    />
  )
  await page.getByLabelText('渠道名称').fill('改名')
  await page.getByRole('tab', { name: '高级设置' }).click()
  await expect
    .element(page.getByRole('switch', { name: '自动保护' }))
    .toBeVisible()
  const dialog = page.getByRole('dialog', { name: '复制渠道配置' }).element()
  expect(dialog.getBoundingClientRect().right).toBeLessThanOrEqual(390)
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await page.screenshot({
    path: '__screenshots__/actvero-g1-03-editor-narrow.png',
  })
  const body = dialog.querySelector('.overflow-y-auto') as HTMLElement
  body.scrollTop = body.scrollHeight
  await expect
    .element(page.getByRole('textbox', { name: '接口前缀', exact: true }))
    .toBeVisible()
  await page.screenshot({
    path: '__screenshots__/actvero-g1-03-editor-narrow-bottom.png',
  })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect.element(page.getByText('放弃未保存的修改？')).toBeVisible()
})

it('saves a Chat stream default as configuration without starting diagnostics', async () => {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  const saved = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body))
      calls.push({ url, body })
      return Response.json({ ...legacy, ...body, version: 4 })
    })
  )
  await show(<ChannelEditor channel={legacy} close={vi.fn()} saved={saved} />)
  await page.getByRole('tab', { name: '高级设置' }).click()
  await page.getByRole('switch', { name: '默认流式测试' }).click()
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(calls).toHaveLength(1)
  expect(calls[0].url).not.toContain('/diagnostics')
  expect(calls[0].body.test_defaults).toEqual({
    upstream_id: 'model-a',
    operation: 'chat',
    endpoint: 'chat_completions',
    stream: true,
  })
})
