import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ChannelDetail } from './channel-detail'
import type { ProviderModule } from './provider-modules'
import type { Detail } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
    user: { id: 'admin' },
  }),
}))

const channel: Detail = {
  id: 'channel-id',
  version: 3,
  provider: 'openai-compatible',
  name: '代理渠道',
  description: '',
  icon: '',
  base_url: 'https://proxy.example/proxy/v1',
  connection: {
    address_mode: 'service_root',
    service_root: 'https://proxy.example/proxy',
    api_prefix: '/v1',
    resolver_version: 1,
  },
  manual_enabled: false,
  automatic_protection: { enabled: true },
  auth_mode: 'api_key',
  credential_configured: true,
  timeout_seconds: 20,
  declared_apis: ['chat_completions'],
  archived: false,
  model_count: 1,
  created_at: '2026-10-03T00:00:00Z',
  last_check: {
    at: '2026-10-03T01:00:00Z',
    ok: true,
    message: '模型目录读取成功',
    kind: 'check',
  },
  checks: [],
  models: [
    {
      id: 'test-model',
      source: 'discovery',
      registered_at: '2026-10-03T01:00:00Z',
    },
  ],
  health_summary: {
    state: 'unverified',
    health_counts: { unverified: 1 },
    as_of: '2026-10-03T02:00:00Z',
  },
  binding_references: [
    {
      model_id: 'model-id',
      model_name: '公共模型',
      operation: 'chat',
      binding_id: 'binding-id',
      upstream_model_id: 'test-model',
      binding_enabled: true,
      operation_enabled: true,
      model_enabled: true,
      model_archived: false,
      source_registered: true,
      health_state: 'unverified',
    },
  ],
  last_diagnostic: {
    at: '2026-10-03T01:30:00Z',
    ok: true,
    status: 'success',
    operation: 'chat',
    upstream_model_id: 'test-model',
    request_id: 'request-id',
    duration_ms: 100,
    stale: false,
  },
}
const provider = {
  id: 'openai-compatible',
  name: '自定义 OpenAI 兼容',
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
  test_operations: ['chat', 'embedding'],
} as ProviderModule

let client: QueryClient
beforeEach(async () => {
  await page.viewport(1280, 900)
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  client.setQueryData(['organization', 'test-org', 'llm-providers'], [provider])
  client.setQueryData(
    ['organization', 'test-org', 'model-channels', channel.id],
    channel
  )
})
afterEach(async () => {
  await cleanup()
  await client.cancelQueries()
  client.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
async function show(initialTab = 'connection') {
  const screen = await render(
    <QueryClientProvider client={client}>
      <ChannelDetail
        id={channel.id}
        initialTab={initialTab}
        close={() => undefined}
        changed={() => undefined}
        edit={() => undefined}
        restoreFocus={() => undefined}
      />
    </QueryClientProvider>
  )
  await waitForAnimations()
  return screen
}

it('keeps retired channels editable while hiding the copy action', async () => {
  client.setQueryData(
    ['organization', 'test-org', 'llm-providers'],
    [
      {
        ...provider,
        available_for_new_channels: false,
      },
    ]
  )
  const edit = vi.fn()
  await render(
    <QueryClientProvider client={client}>
      <ChannelDetail
        id={channel.id}
        initialTab='models'
        close={vi.fn()}
        changed={vi.fn()}
        edit={edit}
        copy={vi.fn()}
        restoreFocus={vi.fn()}
      />
    </QueryClientProvider>
  )
  await expect
    .element(page.getByText('此供应商预设已停止新增，此渠道仍可编辑和调用。'))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '复制', exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  expect(edit).toHaveBeenCalledWith(channel)
})

it('shows one BaseURL without fetching previews and keeps diagnostic history separate', async () => {
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      requests.push(url)
      if (url.endsWith('/channel-addresses/resolve')) {
        const input = JSON.parse(String(options?.body))
        expect(input.connection.service_root).toBe(
          'https://proxy.example/proxy'
        )
        expect(input.api_key).toBeUndefined()
        return Response.json({
          address_mode: 'service_root',
          resolver_version: 1,
          directory_method: 'GET',
          directory_url: 'https://proxy.example/proxy/v1/models',
          operation_targets: [
            {
              operation: 'chat',
              method: 'POST',
              url: 'https://proxy.example/proxy/v1/chat/completions',
              outbound_protocol: 'openai_compatible',
              sdk_provider: 'openai',
              sdk_api_base: 'https://proxy.example/proxy/v1',
              sdk_expected_url:
                'https://proxy.example/proxy/v1/chat/completions',
            },
          ],
          warnings: [],
        })
      }
      if (url.includes('/tests?')) return Response.json([])
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show()
  await expect
    .element(
      screen.getByText('https://proxy.example/proxy/v1', {
        exact: true,
      })
    )
    .toBeVisible()
  await expect.element(screen.getByText('最近调用诊断')).toBeVisible()
  await screen.getByRole('tab', { name: '健康' }).click()
  await expect.element(screen.getByText('公共模型 · chat')).toBeVisible()
  await expect
    .element(
      screen.getByText(
        '渠道已停用，成员调用仍被阻止；管理员可以显式选择渠道诊断。'
      )
    )
    .toBeVisible()
  expect(
    requests.filter((url) => url.endsWith('/channel-addresses/resolve'))
  ).toHaveLength(0)
})

it('surfaces a removal conflict with linked model instead of hiding the 409', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (
        url.endsWith('/channels/channel-id/models') &&
        options?.method === 'DELETE'
      ) {
        return Response.json(
          {
            error: {
              message: '模型仍被引用',
              references: [
                {
                  model_id: 'model-id',
                  model_name: '公共模型',
                  operation: 'chat',
                  binding_id: 'binding-id',
                },
              ],
            },
          },
          { status: 409 }
        )
      }
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('models')
  await screen.getByRole('button', { name: '移除 test-model' }).click()
  await screen.getByRole('button', { name: '移除登记' }).click()
  await expect
    .element(screen.getByText('模型仍被启用绑定引用，不能移除'))
    .toBeVisible()
  await expect
    .element(screen.getByRole('button', { name: '查看关联模型' }))
    .toBeVisible()
})

it('opens the existing import flow with this channel and selected inventory IDs', async () => {
  let input: {
    channel_id: string
    channel_version: number
    items: { upstream_id: string }[]
  } | null = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/model-imports/preview')) {
        input = JSON.parse(String(options?.body))
        return Response.json({
          revision: 'a'.repeat(64),
          items: [
            {
              upstream_id: 'test-model',
              action: 'create',
              name: 'test-model',
              slug: 'test-model',
              kinds: [],
              errors: [],
              status: 'create',
              hint: {
                kind: null,
                source: 'unknown',
                available_kinds: ['chat'],
              },
            },
          ],
          can_commit: true,
          create_count: 1,
          link_count: 0,
          binding_count: 1,
        })
      }
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('models')
  await screen.getByRole('button', { name: '导入', exact: true }).click()
  await expect
    .element(page.getByRole('dialog', { name: '从渠道批量导入' }))
    .toBeVisible()
  await expect.element(page.getByText('新建 1 个 · 关联 0 个')).toBeVisible()
  expect(input).toEqual({
    channel_id: channel.id,
    channel_version: channel.version,
    items: [{ upstream_id: 'test-model', action: 'create' }],
  })
})

it('disables inventory writes after authorization is lost', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/channels/channel-id/discover'))
        return Response.json(
          { error: { message: '无权管理渠道' } },
          { status: 403 }
        )
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('models')
  await screen.getByRole('button', { name: '从上游获取' }).click()
  await expect.element(screen.getByText('无权管理渠道')).toBeVisible()
  await expect
    .element(screen.getByRole('button', { name: '从上游获取' }))
    .toBeDisabled()
  await expect
    .element(screen.getByRole('button', { name: '批量导入平台模型' }))
    .toBeDisabled()
  await expect
    .element(screen.getByRole('button', { name: '移除 test-model' }))
    .toBeDisabled()
})

it('reloads binding projections after an inventory mutation', async () => {
  let reads = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (
        url.endsWith('/channels/channel-id/models') &&
        options?.method === 'POST'
      )
        return Response.json({ ...channel, version: 4, binding_references: [] })
      if (url.endsWith('/channels/channel-id') && options?.method === 'GET') {
        reads += 1
        return Response.json({ ...channel, version: 4 })
      }
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('models')
  await screen.getByRole('button', { name: '手动登记模型' }).click()
  await screen.getByRole('textbox', { name: '模型 ID' }).fill('new-model')
  await screen.getByRole('button', { name: '登记模型', exact: true }).click()
  await expect.poll(() => reads).toBe(1)
  await screen.getByRole('tab', { name: '健康' }).click()
  await expect.element(screen.getByText('公共模型 · chat')).toBeVisible()
})

it('prefills an explicit binding diagnostic and keeps history available without test operations', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/tests?')) return Response.json([])
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('health')
  await screen.getByRole('button', { name: '诊断此绑定' }).click()
  await expect
    .element(screen.getByRole('tab', { name: '测试与历史' }))
    .toHaveAttribute('data-state', 'active')
  await expect
    .element(screen.getByRole('combobox', { name: '测试模型' }))
    .toHaveTextContent('test-model')

  client.setQueryData(
    ['organization', 'test-org', 'llm-providers'],
    [{ ...provider, test_operations: [] }]
  )
  await expect
    .element(screen.getByText('此供应商尚未接入调用测试。'))
    .toBeVisible()
  await screen.getByRole('tab', { name: '历史记录' }).click()
  await expect.element(screen.getByText('暂无测试记录')).toBeVisible()
})

it('fits the four-tab detail on a narrow screen', async () => {
  await page.viewport(390, 844)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/tests?')) return Response.json([])
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('models')
  await expect
    .element(screen.getByText('test-model', { exact: true }).first())
    .toBeVisible()
  await new Promise((resolve) => setTimeout(resolve, 450))
  await page.screenshot({ path: '__screenshots__/actvero-g104-detail-390.png' })
})

it('stops the batch when leaving its tab and reopens without continuing queued calls', async () => {
  const models = ['first', 'second', 'third'].map((id) => ({
    id,
    source: 'manual' as const,
    registered_at: '2026-10-04T00:00:00Z',
  }))
  client.setQueryData(
    ['organization', 'test-org', 'model-channels', channel.id],
    { ...channel, model_count: 3, models }
  )
  const sent: AbortSignal[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, options?: RequestInit) => {
      if (url.endsWith('/diagnostics') && options?.method === 'POST') {
        const signal = options.signal as AbortSignal
        sent.push(signal)
        return new Promise<Response>((_, reject) =>
          signal.addEventListener(
            'abort',
            () => reject(new DOMException('Stopped waiting', 'AbortError')),
            { once: true }
          )
        )
      }
      if (url.includes('/tests?')) return Promise.resolve(Response.json([]))
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('test')
  await screen.getByRole('tab', { name: '批量测试', exact: true }).click()
  await screen.getByRole('button', { name: '选择已登记模型／操作' }).click()
  for (const id of ['first', 'second', 'third'])
    await page
      .getByRole('checkbox', { name: `选择 ${id} 对话`, exact: true })
      .click()
  await page.getByRole('button', { name: '收起参数' }).click()
  await page.getByRole('button', { name: '编辑模板' }).click()
  await page.getByRole('textbox', { name: '测试提示词' }).fill('Reply ok')
  await page.getByRole('textbox', { name: '最大输出 Token' }).fill('64')
  await page.getByRole('button', { name: '保存参数' }).click()
  await page.getByRole('button', { name: '应用到所选对话项' }).click()
  await page.getByRole('button', { name: '确认 3 项' }).click()
  await screen.getByRole('button', { name: '开始批量诊断' }).click()
  await expect.poll(() => sent.length).toBe(2)
  client.setQueryData(
    ['organization', 'test-org', 'model-channels', channel.id],
    { ...channel, version: 4, model_count: 0, models: [] }
  )
  await expect.element(screen.getByText('批量执行中')).toBeVisible()
  expect(sent.every((signal) => signal.aborted)).toBe(false)
  await page.screenshot({
    path: '__screenshots__/actvero-g5-02-detail-desktop.png',
  })
  await screen.getByRole('tab', { name: '历史记录', exact: true }).click()
  await expect.poll(() => sent.every((signal) => signal.aborted)).toBe(true)
  await expect.element(screen.getByText('暂无测试记录')).toBeVisible()
  client.setQueryData(
    ['organization', 'test-org', 'model-channels', channel.id],
    { ...channel, version: 4, model_count: 3, models }
  )
  await screen.getByRole('tab', { name: '批量测试', exact: true }).click()
  await expect.element(screen.getByText('已选 0/50')).toBeVisible()
  expect(sent).toHaveLength(2)
  await expect
    .element(screen.getByRole('button', { name: '开始批量诊断' }))
    .toBeDisabled()
})

it.each([
  { operation: 'embedding', endpoint: 'embeddings', omitted: 'dimensions' },
  { operation: 'rerank', endpoint: 'rerank', omitted: 'top_n' },
] as const)(
  'submits valid saved $operation defaults without invented numeric parameters',
  async ({ operation, endpoint, omitted }) => {
    client.setQueryData(
      ['organization', 'test-org', 'llm-providers'],
      [{ ...provider, test_operations: ['chat', 'embedding', 'rerank'] }]
    )
    client.setQueryData(
      ['organization', 'test-org', 'model-channels', channel.id],
      {
        ...channel,
        test_defaults: {
          operation,
          endpoint,
          upstream_id: 'test-model',
          stream: false,
        },
        test_defaults_status: { valid: true, reason: 'ready' },
      }
    )
    let sent: Record<string, unknown> | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, options?: RequestInit) => {
        if (
          url.endsWith('/channels/channel-id/diagnostics') &&
          options?.method === 'POST'
        ) {
          sent = JSON.parse(String(options.body))
          return Response.json({
            ok: true,
            operation,
            duration_ms: 10,
            message: '完成',
            request_id: 'probe',
          })
        }
        if (url.endsWith('/channels/channel-id')) return Response.json(channel)
        throw new Error('Unexpected request: ' + url)
      })
    )
    const screen = await show('test')
    await screen.getByRole('button', { name: '开始测试' }).click()
    await expect.poll(() => sent).not.toBeNull()
    expect(sent).toMatchObject({
      operation,
      endpoint,
      upstream_id: 'test-model',
      stream: false,
      certify_health: false,
    })
    expect((sent as Record<string, unknown> | null)?.input).not.toHaveProperty(
      omitted
    )
    if (operation === 'rerank')
      expect(sent).toMatchObject({
        input: {
          query: '中国的首都在哪里？',
          documents: ['北京是中国的首都。', '上海位于中国东部。'],
        },
      })
  }
)

it('cancels a Chat stream reader on tab exit and does not start another POST', async () => {
  client.setQueryData(
    ['organization', 'test-org', 'llm-providers'],
    [{ ...provider, test_operations: ['chat'] }]
  )
  let sent = 0
  let cancelled = 0
  let signal: AbortSignal | undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/channels/channel-id/diagnostics')) {
        sent += 1
        signal = options?.signal ?? undefined
        const requestId = JSON.parse(String(options?.body)).request_id
        const encoder = new TextEncoder()
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(
                encoder.encode(
                  `event: accepted\ndata: ${JSON.stringify({ request_id: requestId, attempt_id: requestId, operation: 'chat', channel_version: 3 })}\n\n` +
                    `event: delta\ndata: ${JSON.stringify({ request_id: requestId, delta: { content: '部分片段' } })}\n\n`
                )
              )
            },
            cancel() {
              cancelled += 1
            },
          }),
          { headers: { 'Content-Type': 'text/event-stream' } }
        )
      }
      if (url.endsWith('/channels/channel-id')) return Response.json(channel)
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('test')
  await screen.getByRole('switch', { name: '流式接收对话' }).click()
  await screen.getByRole('button', { name: '开始测试' }).click()
  await expect
    .element(screen.getByLabelText('流式输出'))
    .toHaveValue('部分片段')
  await page.screenshot({
    path: '__screenshots__/actvero-g5-stream-detail-desktop.png',
  })
  await screen.getByLabelText('流式输出').click()
  await page.screenshot({
    path: '__screenshots__/actvero-g5-stream-detail-output.png',
  })
  await expect.element(screen.getByRole('tab', { name: '健康' })).toBeEnabled()
  await screen.getByRole('tab', { name: '健康' }).click()
  await expect.poll(() => signal?.aborted).toBe(true)
  await expect.poll(() => cancelled).toBe(1)
  expect(sent).toBe(1)
})

it('keeps the original stream request visible when a 409 refresh empties inventory', async () => {
  client.setQueryData(
    ['organization', 'test-org', 'llm-providers'],
    [{ ...provider, test_operations: ['chat'] }]
  )
  let requestId = ''
  let posts = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/channels/channel-id/diagnostics')) {
        posts += 1
        requestId = JSON.parse(String(options?.body)).request_id
        return Response.json(
          { error: { message: '渠道配置已更新' } },
          { status: 409 }
        )
      }
      if (url.includes(`/diagnostics/${requestId}`))
        return Response.json({
          channel_id: channel.id,
          media_available: false,
          record: {
            request_id: requestId,
            model: 'test-model',
            operation: 'chat',
            tested_at: '2026-10-04T00:00:00Z',
            status: 'failure',
            record_version: 'attempt_v1',
            uncertain: false,
            attempt: {
              sent: false,
              output_started: false,
              upstream_terminal: false,
              client_terminal: null,
              uncertain: false,
              usage_evidence: [],
            },
          },
        })
      if (url.includes('/tests?')) return Response.json([])
      throw new Error('Unexpected request: ' + url)
    })
  )
  const screen = await show('test')
  await screen.getByRole('switch', { name: '流式接收对话' }).click()
  await screen.getByRole('button', { name: '开始测试' }).click()
  await expect.element(screen.getByText(/本次请求号：/)).toBeVisible()
  client.setQueryData(
    ['organization', 'test-org', 'model-channels', channel.id],
    { ...channel, version: 4, model_count: 0, models: [] }
  )
  await expect
    .element(screen.getByText(`本次请求号：${requestId}`))
    .toBeVisible()
  await screen.getByRole('button', { name: '回查本次记录' }).click()
  await expect.element(screen.getByText('发送：未发送')).toBeVisible()
  expect(posts).toBe(1)
})

it('takes an explicit health row to the certification form without sending a request', async () => {
  client.setQueryData(
    ['organization', 'test-org', 'model-channels', channel.id],
    {
      ...channel,
      binding_references: channel.binding_references?.map((item) => ({
        ...item,
        model_version: 4,
      })),
    }
  )
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      calls.push(options?.method ?? 'GET')
      if (url.includes('/tests?')) return Response.json([])
      return Response.json(channel)
    })
  )
  const screen = await show('health')
  await screen.getByRole('button', { name: '验证此绑定', exact: true }).click()
  await expect
    .element(screen.getByRole('combobox', { name: '测试方式' }))
    .toHaveTextContent('指定绑定健康认证')
  await expect
    .element(screen.getByRole('combobox', { name: '认证绑定' }))
    .toHaveTextContent('公共模型')
  await expect
    .element(screen.getByRole('button', { name: '开始测试', exact: true }))
    .toBeEnabled()
  expect(calls).not.toContain('POST')
})

it('shares the cached directory across detail tabs without contacting the upstream', async () => {
  const fetcher = vi.fn(() => {
    throw new Error('No request expected')
  })
  vi.stubGlobal('fetch', fetcher)
  client.setQueryData(
    ['organization', 'test-org', 'model-channels', channel.id],
    {
      ...channel,
      model_directory: {
        snapshot_id: 'cached-snapshot',
        fetched_at: '2026-10-26T01:00:00Z',
        candidates: [{ id: 'cached-model' }, { id: 'test-model' }],
        partial: false,
      },
    }
  )
  await show('models')
  await expect
    .element(page.getByRole('checkbox', { name: 'cached-model' }))
    .toBeVisible()
  await expect.element(page.getByText('1 个待登记')).toBeVisible()
  await page.getByRole('tab', { name: '连接信息' }).click()
  await page.getByRole('tab', { name: '上游模型（1）' }).click()
  await expect
    .element(page.getByRole('checkbox', { name: 'cached-model' }))
    .toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
})
