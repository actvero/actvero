import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { MemberUsage, Settlements } from '@/features/quota-policies/settlements'
import { runChatTest } from './chat-stream'
import type { Model } from './model-form'
import { ModelTest } from './model-test'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'csrf-test',
  }),
}))
const clients: QueryClient[] = []
async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
}
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((c) => c.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 900)
})
const model: Model = {
  display_order: 0,
  id: 'model',
  name: '团队对话',
  slug: 'team-chat',
  kind: 'chat',
  version: 1,
  archived: false,
  description: '',
  vendor: '',
  icon: '',
  icon_key: '',
  created_at: '2026-09-25T01:00:00Z',
  updated_at: '2026-09-25T01:00:00Z',
  capabilities: {
    streaming: 'supported',
    tools: 'supported',
    reasoning: 'supported',
    structured_output: 'unknown',
    vision: 'unknown',
  },
  reasoning_options: [{ type: 'effort', values: ['low', 'high'] }],
  context_window: 1000,
  max_output: 100,
  bindings: [
    {
      channel_id: 'channel',
      upstream_id: 'vendor-chat',
      enabled: true,
      priority: 0,
      weight: 100,
      compatibility_key: '',
    },
  ],
  binding_states: [
    {
      binding_id: '11596c90-21a3-4c7f-951d-31b523353cab',
      operation: 'chat',
      channel_id: 'channel',
      upstream_id: 'vendor-chat',
      channel_name: '测试渠道',
      state: 'registered',
    },
  ],
}
function stream(events: unknown[], done = true) {
  const encoded = new TextEncoder().encode(
    events.map((e) => 'data: ' + JSON.stringify(e) + '\n\n').join('') +
      (done ? 'data: [DONE]\n\n' : '')
  )
  return new Response(
    new ReadableStream({
      start(controller) {
        for (let i = 0; i < encoded.length; i += 7)
          controller.enqueue(encoded.slice(i, i + 7))
        controller.close()
      },
    }),
    { headers: { 'content-type': 'text/event-stream' } }
  )
}
const delta = (content: object) => ({ choices: [{ index: 0, delta: content }] })

it('tests a saved image model with a private preview and releases it when input changes', async () => {
  const calls: { url: string; body: unknown }[] = []
  const b64 =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jG2cAAAAASUVORK5CYII='
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        calls.push({ url, body: JSON.parse(String(init.body)) })
        return Response.json({
          id: 'call',
          created: 123,
          data: [
            {
              b64_json: b64,
              media_type: 'image/png',
              width: 1,
              height: 1,
              bytes: 68,
            },
          ],
          usage: { image_count: 1, input_tokens: null, output_tokens: null },
        })
      }
      return Response.json([])
    })
  )
  const revoke = vi.spyOn(URL, 'revokeObjectURL')
  await page.viewport(390, 844)
  await show(
    <ModelTest
      model={{ ...model, kind: 'image_generation' }}
      close={vi.fn()}
      restoreFocus={vi.fn()}
    />
  )
  await expect
    .element(page.getByLabelText('返回数量（选填）'))
    .not.toBeInTheDocument()
  await page.getByLabelText('图片提示词').fill('测试图片')
  await page.getByRole('button', { name: '开始测试', exact: true }).click()
  await expect.element(page.getByAltText('生成的测试图片')).toBeVisible()
  expect(calls).toHaveLength(1)
  expect(calls[0]).toMatchObject({
    body: { model: 'team-chat', prompt: '测试图片' },
  })
  expect(calls[0].url).toContain('/test/images?')
  const preview = page
    .getByAltText('生成的测试图片')
    .element() as HTMLImageElement
  expect(preview.src).toMatch(/^blob:/)
  await expect
    .element(page.getByRole('link', { name: '下载图片' }))
    .toHaveAttribute('download', 'actvero-image.png')
  await page.getByLabelText('图片提示词').fill('另一个提示词')
  await expect
    .element(page.getByAltText('生成的测试图片'))
    .not.toBeInTheDocument()
  expect(revoke).toHaveBeenCalled()
})

it('assembles fragmented UTF-8 text, tool arguments, reasoning and usage, and rejects an incomplete stream', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      stream([
        delta({ content: '你好', reasoning_content: '分析' }),
        delta({
          tool_calls: [
            {
              index: 0,
              id: 'tool-1',
              function: { name: 'lookup', arguments: '{"q":' },
            },
          ],
        }),
        delta({ tool_calls: [{ index: 0, function: { arguments: '"ok"}' } }] }),
        { choices: [], usage: { total_tokens: 110 } },
      ])
    )
  )
  const update = vi.fn()
  const body = {
    n: 1 as const,
    model: 'team-chat',
    messages: [{ role: 'user' as const, content: 'hi' }],
    stream: true,
  }
  await runChatTest(
    '/test',
    body,
    'csrf-test',
    new AbortController().signal,
    update
  )
  expect(update.mock.lastCall?.[0]).toEqual({
    content: '你好',
    reasoning: '分析',
    tools: { 0: { id: 'tool-1', name: 'lookup', arguments: '{"q":"ok"}' } },
    usage: { total_tokens: 110 },
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => stream([delta({ content: 'partial' })], false))
  )
  await expect(
    runChatTest(
      '/test',
      body,
      'csrf-test',
      new AbortController().signal,
      update
    )
  ).rejects.toThrow('事件流未完整结束')
})

it('runs the saved chat route with selected reasoning and shows streamed results on narrow screens', async () => {
  await page.viewport(390, 844)
  const calls = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/test/chat')) {
      expect(init?.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-test' })
      expect(JSON.parse(String(init?.body))).toMatchObject({
        model: 'team-chat',
        stream: true,
        reasoning_effort: 'high',
        max_completion_tokens: 50,
        messages: [{ role: 'user', content: '写一个例子' }],
      })
      return stream([
        delta({ content: '测试回答', reasoning_content: '测试思考' }),
        { choices: [], usage: { total_tokens: 12 } },
      ])
    }
    if (url.endsWith('/calls') || url.endsWith('/routes'))
      return Response.json([])
    throw new Error(url)
  })
  vi.stubGlobal('fetch', calls)
  await show(<ModelTest model={model} close={vi.fn()} restoreFocus={vi.fn()} />)
  await page.getByLabelText('消息内容').fill('写一个例子')
  await page.getByLabelText('最大输出 Token（选填）').fill('50')
  await page.getByRole('combobox', { name: '思考强度' }).click()
  await page.getByRole('option', { name: 'high', exact: true }).click()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByLabelText('对话输出')).toHaveValue('测试回答')
  await page.getByRole('button', { name: '思考内容' }).click()
  await expect
    .element(page.getByLabelText('思考内容', { exact: true }))
    .toHaveValue('测试思考')
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '__screenshots__/chat-test-narrow.png' })
})

it('tests each operation with its own binding and clears results when switching', async () => {
  const requests: Array<{ url: string; body: unknown }> = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/test/embeddings')) {
        requests.push({ url, body: JSON.parse(String(init?.body)) })
        return Response.json({
          object: 'list',
          model: 'team-chat',
          data: [{ object: 'embedding', index: 0, embedding: [1, 2, 3] }],
          usage: { prompt_tokens: 7, total_tokens: 7 },
        })
      }
      if (url.endsWith('/calls') || url.endsWith('/routes'))
        return Response.json([])
      throw new Error(url)
    })
  )
  await show(
    <ModelTest
      model={{
        ...model,
        operations: [
          {
            kind: 'chat',
            enabled: true,
            upstream_id: 'vendor-chat',
            bindings: model.bindings,
          },
          {
            kind: 'embedding',
            enabled: false,
            upstream_id: 'vendor-embedding',
            bindings: [
              {
                ...model.bindings![0],
                channel_id: 'embedding-channel',
                upstream_id: 'vendor-embedding',
                enabled: false,
              },
            ],
          },
        ],
        binding_states: [
          ...model.binding_states,
          {
            binding_id: '990b4602-4cf1-457b-ac5f-d6e9277dc808',
            operation: 'embedding',
            channel_id: 'embedding-channel',
            upstream_id: 'vendor-embedding',
            channel_name: '向量渠道',
            state: 'registered',
          },
        ],
      }}
      close={vi.fn()}
      restoreFocus={vi.fn()}
    />
  )
  await page.getByRole('combobox', { name: '测试操作' }).click()
  await page.getByRole('option', { name: '向量', exact: true }).click()
  await expect
    .element(page.getByRole('combobox', { name: '测试渠道' }))
    .toHaveTextContent('向量渠道 / vendor-embedding')
  await page.getByLabelText('输入文本（每行一条）').fill('测试向量')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect
    .element(page.getByText('返回 1 条向量 · 3 维 · 输入用量 7'))
    .toBeVisible()
  expect(requests).toEqual([
    {
      url: '/api/v1/llm/models/model/test/embeddings?channel_id=embedding-channel&upstream_id=vendor-embedding',
      body: { model: 'team-chat', input: ['测试向量'] },
    },
  ])
  await page.getByRole('combobox', { name: '测试操作' }).click()
  await page.getByRole('option', { name: '对话', exact: true }).click()
  await expect.element(page.getByLabelText('消息内容')).toHaveValue('')
  await expect
    .element(page.getByText('返回 1 条向量 · 3 维 · 输入用量 7'))
    .not.toBeInTheDocument()
  expect(requests).toHaveLength(1)
})

const entry = {
  id: 'call',
  member_id: 'member',
  member_name: '测试成员',
  model_name: '团队对话',
  kind: 'chat',
  metric: 'tokens',
  status: 'review',
  version: 2,
  points: null,
  reserved_points: '0.28',
  usage: {},
  created_at: '2026-09-25T01:00:00Z',
  settled_at: null,
  reason: '',
}
it('previews explicit quantities, refreshes a conflict and releases held quota only after confirmation', async () => {
  await page.viewport(1280, 900)
  let release = false
  const writes = vi.fn(async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body))
    expect(body.version).toBe(2)
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/)
    if (body.action === 'settle') {
      expect(body.usage).toEqual({
        metric: 'tokens',
        input_tokens: 80,
        output_tokens: 10,
        cache_read_tokens: 20,
      })
      return Response.json(
        { error: { message: '记录已处理，请刷新' } },
        { status: 409 }
      )
    }
    expect(body).toMatchObject({
      version: 2,
      action: 'release',
      reason: '核对上游账单',
    })
    expect(body.usage).toBeUndefined()
    release = true
    return Response.json({ items: [], total: 0 })
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/reconciliation'))
        return Response.json({
          settlement: entry,
          price: {
            currency: 'USD',
            metric: 'tokens',
            unit: 1000000,
            input: '1',
            output: '2',
            cache_read: '0.5',
          },
          ratio: '100',
          currency: 'USD',
          required_fields: [
            'input_tokens',
            'output_tokens',
            'cache_read_tokens',
          ],
          eligible: true,
          available_after: null,
        })
      if (url.endsWith('/reconcile/preview')) {
        const body = JSON.parse(String(init?.body))
        return Response.json({
          call_id: entry.id,
          version: 2,
          action: body.action,
          metric: 'tokens',
          usage: body.usage
            ? { input_tokens: 80, output_tokens: 10, cache_read_tokens: 20 }
            : {},
          amount: body.action === 'release' ? '0' : '0.00011',
          points: body.action === 'release' ? '0' : '0.011',
          currency: 'USD',
        })
      }
      if (init?.method === 'POST') return writes(url, init)
      if (url.endsWith('/llm/members/member/quota'))
        return Response.json({
          status: 'active',
          windows: [
            {
              rule: { kind: 'fixed_hours', hours: 5, points: '1' },
              used: '0',
              reserved: release ? '0' : '0.28',
              remaining: release ? '1' : '0.72',
              resets_at: '2026-09-25T06:00:00Z',
            },
          ],
        })
      return Response.json({
        items: release ? [] : [entry],
        total: release ? 0 : 1,
      })
    })
  )
  await show(
    <>
      <MemberUsage memberId='member' />
      <Settlements />
    </>
  )
  await expect
    .element(page.getByRole('progressbar'))
    .toHaveAttribute('aria-valuetext', '剩余 0.72 / 1 积分；已用 0；预占 0.28')
  await page.getByRole('button', { name: '核对', exact: true }).click()
  await page.getByLabelText('核对依据').fill('核对上游账单')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  expect(writes).not.toHaveBeenCalled()
  await page.getByLabelText('输入 Token *', { exact: true }).fill('80')
  await page.getByLabelText('输出 Token *', { exact: true }).fill('10')
  await page.getByLabelText('缓存读取 Token *', { exact: true }).fill('20')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await page.getByRole('button', { name: '确认结算', exact: true }).click()
  await expect.element(page.getByText('记录已处理，请刷新')).toBeVisible()
  await expect
    .element(page.getByLabelText('输入 Token *', { exact: true }))
    .toHaveValue('80')
  await page.getByRole('button', { name: '刷新服务端记录' }).click()
  await page.getByRole('combobox', { name: '处理方式' }).click()
  await page.getByRole('option', { name: '确认无使用，释放预占' }).click()
  await page
    .getByRole('checkbox', { name: '已依据外部记录确认没有使用量' })
    .click()
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await page.getByRole('button', { name: '确认释放', exact: true }).click()
  await expect.element(page.getByText('暂无结算记录')).toBeVisible()
  await expect
    .element(page.getByRole('progressbar'))
    .toHaveAttribute('aria-valuetext', '剩余 1 / 1 积分；已用 0；预占 0')
})

it('loads actual member windows automatically as progress bars', async () => {
  const calls = vi.fn(async () =>
    Response.json({
      status: 'active',
      policy: { name: '默认' },
      windows: [
        {
          rule: { kind: 'fixed_hours', hours: 5, points: '100' },
          used: '12',
          reserved: '3',
          remaining: '85',
          started_at: '2026-09-25T01:00:00Z',
          resets_at: '2026-09-25T06:00:00Z',
        },
      ],
    })
  )
  vi.stubGlobal('fetch', calls)
  await show(<MemberUsage memberId='member' />)
  await expect
    .element(page.getByRole('progressbar'))
    .toHaveAttribute('aria-valuenow', '85')
  expect(calls.mock.calls.length).toBe(1)
})
