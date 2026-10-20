import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ChannelTest } from './channel-test'
import { runDiagnosticStream, type StreamProgress } from './diagnostic-stream'
import type { Detail } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
  }),
}))

const detail: Detail = {
  id: 'test-channel',
  version: 7,
  provider: 'openai-compatible',
  name: '测试渠道',
  description: '',
  icon: '',
  base_url: 'https://example.test/v1',
  connection: {
    address_mode: 'legacy_api_base',
    legacy_base_url: 'https://example.test/v1',
    resolver_version: 1,
  },
  manual_enabled: true,
  auth_mode: 'api_key',
  credential_configured: true,
  timeout_seconds: 20,
  declared_apis: ['chat_completions'],
  archived: false,
  model_count: 1,
  last_check: null,
  created_at: '2026-10-04T00:00:00Z',
  checks: [],
  models: [
    {
      id: 'upstream-a',
      source: 'manual',
      registered_at: '2026-10-04T00:00:00Z',
    },
  ],
  binding_references: [
    {
      binding_id: 'binding-a',
      model_id: 'model-a',
      model_name: '公开模型',
      model_version: 3,
      operation: 'chat',
      upstream_model_id: 'upstream-a',
      binding_enabled: false,
      model_archived: false,
      model_enabled: true,
      operation_enabled: true,
      source_registered: true,
      health_state: 'unverified',
    },
  ],
} as Detail

function Harness({
  channel = detail,
  initialBindingId,
}: {
  channel?: Detail
  initialBindingId?: string
}) {
  const [busy, setBusy] = useState(false)
  return (
    <ChannelTest
      channel={channel}
      operations={['chat']}
      busy={busy}
      setBusy={setBusy}
      initialBindingId={initialBindingId}
    />
  )
}

let client: QueryClient
beforeEach(async () => {
  await page.viewport(1280, 900)
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})
afterEach(async () => {
  await cleanup()
  await client.cancelQueries()
  client.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
async function show(channel = detail, initialBindingId?: string) {
  await render(
    <QueryClientProvider client={client}>
      <Harness channel={channel} initialBindingId={initialBindingId} />
    </QueryClientProvider>
  )
}

const response = (requestId: string) => ({
  request_id: requestId,
  operation: 'chat',
  ok: true,
  message: '对话测试成功',
  tested_at: '2026-10-04T00:00:00Z',
  duration_ms: 20,
  output: '连接成功',
  usage_source: 'unknown',
  uncertain: false,
  vectors: [],
  ranks: [],
  health_certification: 'not_requested',
  attempt: {
    sent: true,
    output_started: true,
    upstream_terminal: true,
    client_terminal: null,
    uncertain: false,
    usage_evidence: [],
  },
})

const sse = (events: { name: string; value: object }[]) =>
  events
    .map(
      ({ name, value }) =>
        `event: ${name}\r\ndata: ${JSON.stringify(value)}\r\n\r\n`
    )
    .join('')

const streamResponse = (source: string, splits?: number[]) => {
  const bytes = new TextEncoder().encode(source)
  const marks = [...(splits ?? []), bytes.length]
  let previous = 0
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const mark of marks) {
          controller.enqueue(bytes.slice(previous, mark))
          previous = mark
        }
        controller.close()
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } }
  )
}

it('sends a fresh nonstream diagnostic with business-only input and friendly evidence', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body).toMatchObject({
      version: 7,
      upstream_id: 'upstream-a',
      operation: 'chat',
      endpoint: 'chat_completions',
      stream: false,
      certify_health: false,
      input: { prompt: '连接确认', max_output_tokens: 64 },
    })
    expect(body.input).not.toHaveProperty('version')
    expect(body.input).not.toHaveProperty('id')
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/)
    return Response.json(response(body.request_id))
  })
  vi.stubGlobal('fetch', fetcher)
  await show()
  await page.getByLabelText('测试内容').fill('连接确认')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByText('客户端交付：未确认')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(String(fetcher.mock.calls[0][0])).toContain(
    '/llm/channels/test-channel/diagnostics'
  )
})

it('requires an explicit binding before health certification and carries its model version', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body).toMatchObject({
      certify_health: true,
      model_id: 'model-a',
      model_version: 3,
      binding_id: 'binding-a',
    })
    return Response.json({
      ...response(body.request_id),
      health_certification: 'certified',
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await show()
  await page.getByRole('combobox', { name: '测试方式' }).click()
  await page.getByRole('option', { name: '指定绑定健康认证' }).click()
  await expect
    .element(page.getByRole('button', { name: '开始测试' }))
    .toBeDisabled()
  await page.getByRole('combobox', { name: '认证绑定' }).click()
  await page.getByRole('option', { name: /公开模型/ }).click()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByText('绑定健康已认证')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('opens a recovery target from its binding ID without silently choosing another route', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body))
      expect(body).toMatchObject({
        upstream_id: 'upstream-a',
        operation: 'chat',
        certify_health: true,
        binding_id: 'binding-a',
      })
      return Response.json(response(body.request_id))
    })
  )
  await show(detail, 'binding-a')
  await expect
    .element(page.getByRole('combobox', { name: '认证绑定' }))
    .toBeVisible()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByLabelText('测试输出')).toHaveValue('连接成功')
})

it('keeps an invalid saved default unselected and asks for both dimensions', async () => {
  vi.stubGlobal('fetch', vi.fn())
  await show({
    ...detail,
    test_defaults: {
      upstream_id: 'upstream-a',
      operation: 'chat',
      endpoint: 'chat_completions',
      stream: false,
    },
    test_defaults_status: { valid: false, reason: 'model_missing' },
  } as Detail)
  await expect
    .element(
      page.getByText('保存的默认测试项已失效，请明确重新选择模型和测试接口。')
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '开始测试' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('combobox', { name: '测试接口' }))
    .toBeVisible()
})

it('stops waiting and only looks up the same request; a new POST needs an explicit new test', async () => {
  let postId = ''
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      const body = JSON.parse(String(options.body))
      postId = body.request_id
      return new Promise<Response>((_resolve, reject) => {
        options.signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError'))
        )
      })
    }
    expect(url).toContain(`/llm/diagnostics/${postId}`)
    return Response.json({
      channel_id: detail.id,
      media_available: false,
      record: {
        request_id: postId,
        model: 'upstream-a',
        operation: 'chat',
        tested_at: '2026-10-04T00:00:00Z',
        status: 'unconfirmed',
        record_version: 'attempt_v1',
        uncertain: true,
        attempt: {
          sent: true,
          output_started: false,
          upstream_terminal: false,
          client_terminal: null,
          uncertain: true,
          usage_evidence: [],
        },
      },
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await show()
  await page.getByRole('button', { name: '开始测试' }).click()
  await page.getByRole('button', { name: '停止等待（上游可能已收费）' }).click()
  await expect
    .element(
      page.getByText('本次结果尚未确认。请按请求号回查；不会自动重新发送。')
    )
    .toBeVisible()
  await page.getByRole('button', { name: '回查本次记录' }).click()
  await expect
    .element(page.getByText('回查仅恢复元数据和执行证据，正文与媒体不可恢复。'))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '开始测试' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '另起新测试（新请求号）' }))
    .toBeEnabled()
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it.each([401, 403])(
  'stops lookup and clears returned evidence on HTTP %i',
  async (status) => {
    let lookupCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, options?: RequestInit) => {
        if (options?.method === 'POST') {
          return Response.json(
            { error: { message: '结果待确认' } },
            { status: 500 }
          )
        }
        lookupCount += 1
        if (lookupCount === 1)
          return Response.json({
            channel_id: detail.id,
            media_available: false,
            record: {
              request_id: 'test',
              model: 'upstream-a',
              operation: 'chat',
              tested_at: '2026-10-04T00:00:00Z',
              status: 'unconfirmed',
              record_version: 'attempt_v1',
              uncertain: true,
              attempt: {
                sent: true,
                output_started: false,
                upstream_terminal: false,
                client_terminal: null,
                uncertain: true,
                usage_evidence: [],
              },
            },
          })
        return Response.json(
          { error: { message: '读取权限已撤销' } },
          { status }
        )
      })
    )
    await show()
    await page.getByRole('button', { name: '开始测试' }).click()
    await page.getByRole('button', { name: '回查本次记录' }).click()
    await expect.element(page.getByText('发送：已发送')).toBeVisible()
    await page.getByRole('button', { name: '回查本次记录' }).click()
    await expect.element(page.getByText('读取权限已撤销')).toBeVisible()
    await expect.element(page.getByText('发送：已发送')).not.toBeInTheDocument()
    await expect
      .element(page.getByRole('button', { name: '回查本次记录' }))
      .toBeDisabled()
    await expect
      .element(page.getByRole('button', { name: '另起新测试（新请求号）' }))
      .not.toBeInTheDocument()
  }
)

it.each([401, 403])(
  'locks further writes after HTTP %i authentication loss',
  async (status) => {
    const fetcher = vi.fn(async () =>
      Response.json({ error: { message: '权限已撤销' } }, { status })
    )
    vi.stubGlobal('fetch', fetcher)
    await show()
    await page.getByRole('button', { name: '开始测试' }).click()
    await expect.element(page.getByText('权限已撤销')).toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '开始测试' }))
      .toBeDisabled()
    expect(fetcher).toHaveBeenCalledTimes(1)
  }
)

it('treats a version conflict as an unknown attempt and queries its original request ID', async () => {
  let original = ''
  let posts = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === 'POST') {
        posts += 1
        original = JSON.parse(String(options.body)).request_id
        return Response.json(
          { error: { message: '渠道配置已更新' } },
          { status: 409 }
        )
      }
      expect(url).toContain(`/llm/diagnostics/${original}`)
      return Response.json({
        channel_id: detail.id,
        media_available: false,
        record: {
          request_id: original,
          model: 'upstream-a',
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
    })
  )
  await show()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect
    .element(
      page.getByText(
        '渠道配置已更新。请按请求号回查，并刷新渠道后再发起新测试。'
      )
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '开始测试' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '回查本次记录' }).click()
  await expect.element(page.getByText('发送：未发送')).toBeVisible()
  expect(posts).toBe(1)
})

it('fits a narrow viewport with the endpoint and evidence in the same flow', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body))
      return Response.json(response(body.request_id))
    })
  )
  await page.viewport(390, 844)
  await show()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByText('上游终态：已观察')).toBeVisible()
  await page.screenshot({
    path: '__screenshots__/actvero-g5-01-diagnostic-390.png',
  })
})

it('streams Chat with split UTF-8 and CRLF, and requires the successful result event', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body.stream).toBe(true)
    const events = sse([
      {
        name: 'accepted',
        value: {
          request_id: body.request_id,
          attempt_id: body.request_id,
          operation: 'chat',
          channel_version: 7,
        },
      },
      {
        name: 'delta',
        value: {
          request_id: body.request_id,
          delta: {
            content: '你好',
            reasoning_content: '检查中',
            tool_calls: [
              {
                index: 0,
                function: { name: 'search', arguments: '{"secret":1}' },
              },
            ],
          },
        },
      },
      {
        name: 'usage',
        value: {
          request_id: body.request_id,
          input_tokens: 2,
          output_tokens: 3,
          usage_source: 'upstream',
          attempt: {},
        },
      },
      {
        name: 'result',
        value: {
          request_id: body.request_id,
          status: 'success',
          result: { ...response(body.request_id), stream: true },
        },
      },
    ])
    const utf8 = new TextEncoder().encode(events)
    const split = utf8.findIndex((byte) => byte === 0xe4)
    return streamResponse(events, [split + 1, split + 2, split + 17])
  })
  vi.stubGlobal('fetch', fetcher)
  await show()
  await page.getByRole('switch', { name: '流式接收对话' }).click()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByLabelText('流式输出')).toHaveValue('你好')
  await expect.element(page.getByLabelText('思考内容')).toHaveValue('检查中')
  await expect.element(page.getByText('工具调用 1：search')).toBeVisible()
  await expect
    .element(page.getByText('上游用量：输入 2、输出 3 Token'))
    .toBeVisible()
  await expect.element(page.getByText(/对话测试成功/)).toBeVisible()
  await expect.element(page.getByLabelText('测试输出')).not.toBeInTheDocument()
  await page.viewport(390, 844)
  await page.screenshot({ path: '__screenshots__/actvero-g5-stream-390.png' })
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('inherits stream only from a valid saved default, not an explicit binding', async () => {
  const withDefault = {
    ...detail,
    test_defaults: {
      upstream_id: 'upstream-a',
      operation: 'chat',
      endpoint: 'chat_completions',
      stream: true,
    },
    test_defaults_status: { valid: true, reason: 'ready' },
  } as Detail
  vi.stubGlobal('fetch', vi.fn())
  await show(withDefault)
  await expect
    .element(page.getByRole('switch', { name: '流式接收对话' }))
    .toBeChecked()
  await cleanup()
  await show(withDefault, 'binding-a')
  await expect
    .element(page.getByRole('switch', { name: '流式接收对话' }))
    .not.toBeChecked()
})

it('keeps the original UUID for lookup after stream EOF and never reposts', async () => {
  let id = ''
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === 'POST') {
      id = JSON.parse(String(options.body)).request_id
      return streamResponse(
        sse([
          {
            name: 'accepted',
            value: {
              request_id: id,
              attempt_id: id,
              operation: 'chat',
              channel_version: 7,
            },
          },
          {
            name: 'delta',
            value: { request_id: id, delta: { content: '部分内容' } },
          },
        ])
      )
    }
    expect(url).toContain(`/llm/diagnostics/${id}`)
    return Response.json({
      channel_id: detail.id,
      media_available: false,
      record: {
        request_id: id,
        model: 'upstream-a',
        operation: 'chat',
        tested_at: '2026-10-04T00:00:00Z',
        status: 'unconfirmed',
        record_version: 'attempt_v1',
        uncertain: true,
        attempt: null,
      },
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await show()
  await page.getByRole('switch', { name: '流式接收对话' }).click()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByLabelText('流式输出')).toHaveValue('部分内容')
  await expect
    .element(page.getByText('诊断流未收到终态，请按请求号回查。'))
    .toBeVisible()
  await page.getByRole('button', { name: '回查本次记录' }).click()
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it.each([401, 403])(
  'clears streamed text on an in-band %i and blocks further requests',
  async (status) => {
    const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
      const id = JSON.parse(String(options?.body)).request_id
      return streamResponse(
        sse([
          {
            name: 'accepted',
            value: {
              request_id: id,
              attempt_id: id,
              operation: 'chat',
              channel_version: 7,
            },
          },
          {
            name: 'delta',
            value: { request_id: id, delta: { content: '仅内存片段' } },
          },
          {
            name: 'error',
            value: {
              request_id: id,
              status_code: status,
              error_code: 'forbidden',
              message: '权限已撤销',
              uncertain: false,
            },
          },
        ])
      )
    })
    vi.stubGlobal('fetch', fetcher)
    await show()
    await page.getByRole('switch', { name: '流式接收对话' }).click()
    await page.getByRole('button', { name: '开始测试' }).click()
    await expect.element(page.getByText('权限已撤销')).toBeVisible()
    await expect
      .element(page.getByLabelText('流式输出'))
      .not.toBeInTheDocument()
    await expect
      .element(page.getByRole('button', { name: '开始测试' }))
      .toBeDisabled()
    expect(fetcher).toHaveBeenCalledTimes(1)
  }
)

it('parses multiline data and ignores events after a terminal result', async () => {
  const id = 'same-request'
  const accepted = JSON.stringify({
    request_id: id,
    attempt_id: id,
    operation: 'chat',
    channel_version: 7,
  })
  const comma = accepted.indexOf(',') + 1
  const wire =
    `event: accepted\r\ndata: ${accepted.slice(0, comma)}\r\ndata: ${accepted.slice(comma)}\r\n\r\n` +
    sse([
      {
        name: 'result',
        value: {
          request_id: id,
          status: 'success',
          result: { ...response(id), stream: true },
        },
      },
      {
        name: 'error',
        value: { request_id: id, status_code: 403, message: 'must be ignored' },
      },
    ])
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => streamResponse(wire, [18, 19, 30]))
  )
  const outcome = await runDiagnosticStream(
    '/llm/channels/x/diagnostics',
    { version: 7 },
    'csrf',
    id,
    new AbortController().signal,
    () => undefined
  )
  expect(outcome.status).toBe('success')
})

it('rejects another request ID and bounds partial output without accepting EOF', async () => {
  const id = 'same-request'
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      streamResponse(
        sse([
          {
            name: 'accepted',
            value: {
              request_id: id,
              attempt_id: id,
              operation: 'chat',
              channel_version: 7,
            },
          },
          {
            name: 'delta',
            value: {
              request_id: 'other-request',
              delta: { content: 'foreign' },
            },
          },
        ])
      )
    )
  )
  await expect(
    runDiagnosticStream(
      '/llm/channels/x/diagnostics',
      { version: 7 },
      'csrf',
      id,
      new AbortController().signal,
      () => undefined
    )
  ).rejects.toThrow('请求号不匹配')

  const progress: StreamProgress[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      streamResponse(
        sse([
          {
            name: 'accepted',
            value: {
              request_id: id,
              attempt_id: id,
              operation: 'chat',
              channel_version: 7,
            },
          },
          {
            name: 'delta',
            value: { request_id: id, delta: { content: '字'.repeat(33_000) } },
          },
        ])
      )
    )
  )
  await expect(
    runDiagnosticStream(
      '/llm/channels/x/diagnostics',
      { version: 7 },
      'csrf',
      id,
      new AbortController().signal,
      (value) => {
        progress.push(value)
      }
    )
  ).rejects.toThrow('未收到终态')
  expect(progress[progress.length - 1]?.content.length).toBe(32_000)
  expect(progress[progress.length - 1]?.truncated).toBe(true)
})
