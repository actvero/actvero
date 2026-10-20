import { useState } from 'react'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ChannelDiagnosticBatch } from './diagnostic-batch'
import type { Detail } from './shared'
import type { TestOperation } from './test-operations'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
  }),
}))

const model = (id: string) => ({
  id,
  source: 'manual' as const,
  registered_at: '2026-10-04T00:00:00Z',
})
const detail: Detail = {
  id: 'channel-test',
  version: 7,
  provider: 'openai-compatible',
  name: '批量渠道',
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
  declared_apis: ['chat_completions', 'embeddings', 'rerank'],
  archived: false,
  model_count: 3,
  last_check: null,
  created_at: '2026-10-04T00:00:00Z',
  checks: [],
  models: [model('chat-a'), model('embed-a'), model('rerank-a')],
}
const result = (body: { request_id: string; operation: string }) => ({
  ok: true,
  operation: body.operation,
  request_id: body.request_id,
  message: '完成',
  output: '',
  tested_at: '2026-10-04T00:00:00Z',
  duration_ms: 20,
  usage_source: 'unknown',
  uncertain: false,
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
beforeEach(async () => {
  await page.viewport(1280, 900)
})
afterEach(async () => {
  await cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 800)
})
async function show(
  channel = detail,
  operations: TestOperation[] = ['chat', 'embedding', 'rerank'],
  onRefreshChannel?: () => void
) {
  return render(
    <ChannelDiagnosticBatch
      channel={channel}
      operations={operations}
      onRefreshChannel={onRefreshChannel}
    />
  )
}
async function openSelection() {
  await page.getByRole('button', { name: '选择已登记模型／操作' }).click()
  await expect
    .element(page.getByRole('dialog', { name: '选择批量诊断项' }))
    .toBeVisible()
}
async function addChat(id: string, prompt: string, count = '64') {
  await page.getByRole('checkbox', { name: `选择 ${id} 对话` }).click()
  await page.getByLabelText('测试提示词').fill(prompt)
  await page.getByLabelText('最大输出 Token').fill(count)
  await page.getByRole('button', { name: '保存参数' }).click()
}

it('sends mixed operation rows as independent nonstream diagnostics with exact inputs', async () => {
  const bodies: Array<Record<string, unknown>> = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body))
      bodies.push(body)
      return Response.json(result(body))
    })
  )
  await show()
  await openSelection()
  await addChat('chat-a', '请回答连接成功')
  await page.getByRole('checkbox', { name: '选择 embed-a 文本向量' }).click()
  await page.getByLabelText('输入文本（每行一条）').fill('第一条\n第二条')
  await page.getByLabelText('维度（选填）').fill('3')
  await page.getByRole('button', { name: '保存参数' }).click()
  await page.getByRole('button', { name: '确认 2 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect
    .element(page.getByText('完成 2/2 · 成功 2 · 失败 0 · 未确认 0 · 未发送 0'))
    .toBeVisible()
  expect(bodies).toHaveLength(2)
  expect(bodies.map((body) => body.operation).sort()).toEqual([
    'chat',
    'embedding',
  ])
  expect(bodies[0]).toMatchObject({
    version: 7,
    upstream_id: 'chat-a',
    operation: 'chat',
    endpoint: 'chat_completions',
    stream: false,
    certify_health: false,
    input: { prompt: '请回答连接成功', max_output_tokens: 64 },
  })
  expect(bodies[1]).toMatchObject({
    upstream_id: 'embed-a',
    operation: 'embedding',
    endpoint: 'embeddings',
    input: { input: ['第一条', '第二条'], dimensions: 3 },
  })
  expect(new Set(bodies.map((body) => body.request_id)).size).toBe(2)
})

it('requires valid explicit row input and discards an unconfirmed selection and template', async () => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  await show()
  await openSelection()
  await page.getByRole('checkbox', { name: '选择 chat-a 对话' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认 1 项' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '保存参数' }).click()
  await expect.element(page.getByText('请输入测试内容')).toBeVisible()
  await page.getByRole('button', { name: '取消选择' }).click()
  await expect.element(page.getByText('已选 0/50')).toBeVisible()
  await openSelection()
  await expect
    .element(page.getByRole('button', { name: '确认 0 项' }))
    .toBeEnabled()
  await expect
    .element(page.getByRole('checkbox', { name: '选择 chat-a 对话' }))
    .not.toBeChecked()
  expect(fetcher).not.toHaveBeenCalled()
})

it('caps UI selection at 50 distinct registered combinations', async () => {
  vi.stubGlobal('fetch', vi.fn())
  const models = Array.from({ length: 51 }, (_, index) =>
    model(`item-${String(index).padStart(2, '0')}`)
  )
  await show({ ...detail, models, model_count: 51 }, ['chat'])
  await openSelection()
  for (const item of models.slice(0, 50))
    await page.getByRole('checkbox', { name: `选择 ${item.id} 对话` }).click()
  await expect
    .element(page.getByText('本次选择 50/50 · 50 项参数待配置或无效'))
    .toBeVisible()
  await expect
    .element(page.getByRole('checkbox', { name: '选择 item-50 对话' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '确认 50 项' }))
    .toBeDisabled()
}, 30000)

it('shows the local 10-per-minute wait without auto-resuming a server 429', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    return Response.json(result(body))
  })
  vi.stubGlobal('fetch', fetcher)
  const models = Array.from({ length: 11 }, (_, index) =>
    model(`limit-${index}`)
  )
  await show({ ...detail, models, model_count: 11 }, ['chat'])
  await openSelection()
  for (const item of models)
    await page.getByRole('checkbox', { name: `选择 ${item.id} 对话` }).click()
  await page.getByRole('button', { name: '编辑模板' }).click()
  await page.getByLabelText('测试提示词').fill('本地限速')
  await page.getByLabelText('最大输出 Token').fill('32')
  await page.getByRole('button', { name: '保存参数' }).click()
  await page.getByRole('button', { name: '应用到所选对话项' }).click()
  await page.getByRole('button', { name: '确认 11 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect.element(page.getByText(/本地 10\/60 限速窗口已满/)).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(10)
  await page.getByRole('button', { name: '停止派发与等待' }).click()
}, 30000)

it('applies a valid same-operation template and permits a per-row override', async () => {
  const bodies: Array<Record<string, unknown>> = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body))
      bodies.push(body)
      return Response.json(result(body))
    })
  )
  await show()
  await openSelection()
  await page.getByRole('checkbox', { name: '选择 chat-a 对话' }).click()
  await page.getByRole('checkbox', { name: '选择 embed-a 对话' }).click()
  await page.getByRole('button', { name: '编辑模板' }).click()
  await page.getByLabelText('测试提示词').fill('共同模板')
  await page.getByLabelText('最大输出 Token').fill('32')
  await page.getByRole('button', { name: '保存参数' }).click()
  await page.getByRole('button', { name: '应用到所选对话项' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认 2 项' }))
    .toBeEnabled()
  await page.getByRole('button', { name: '查看／编辑参数' }).first().click()
  await page.getByLabelText('测试提示词').fill('单项覆盖')
  await page.getByRole('button', { name: '保存参数' }).click()
  await page.getByRole('button', { name: '确认 2 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect
    .element(page.getByText('完成 2/2 · 成功 2 · 失败 0 · 未确认 0 · 未发送 0'))
    .toBeVisible()
  expect(
    bodies.map((body) => (body.input as { prompt: string }).prompt).sort()
  ).toEqual(['共同模板', '单项覆盖'].sort())
})

it('blocks confirmation while a saved row or template has unsaved edits', async () => {
  vi.stubGlobal('fetch', vi.fn())
  await show(detail, ['chat'])
  await openSelection()
  await addChat('chat-a', '已保存内容')
  await expect
    .element(page.getByRole('button', { name: '确认 1 项' }))
    .toBeEnabled()
  await page.getByRole('button', { name: '查看／编辑参数' }).click()
  await page.getByLabelText('测试提示词').fill('尚未保存的内容')
  await expect
    .element(page.getByRole('button', { name: '确认 1 项' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '取消编辑' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认 1 项' }))
    .toBeEnabled()
  await page.getByRole('button', { name: '编辑模板' }).click()
  await page.getByLabelText('测试提示词').fill('尚未保存的模板')
  await expect
    .element(page.getByRole('button', { name: '确认 1 项' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '取消编辑' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认 1 项' }))
    .toBeEnabled()
})

it('stops queued work, aborts two in flight, and does not resume after remount', async () => {
  const fetcher = vi.fn(
    (_url: string, options?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError'))
        )
      })
  )
  vi.stubGlobal('fetch', fetcher)
  function Harness() {
    const [open, setOpen] = useState(true)
    return (
      <div>
        <button type='button' onClick={() => setOpen(!open)}>
          {open ? '关闭批量页' : '重新打开批量页'}
        </button>
        {open && (
          <ChannelDiagnosticBatch channel={detail} operations={['chat']} />
        )}
      </div>
    )
  }
  await render(<Harness />)
  await openSelection()
  await addChat('chat-a', '第一项')
  await addChat('embed-a', '第二项')
  await addChat('rerank-a', '第三项')
  await page.getByRole('button', { name: '确认 3 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect.poll(() => fetcher.mock.calls.length).toBe(2)
  await page.getByRole('button', { name: '停止派发与等待' }).click()
  await expect
    .element(page.getByText('完成 3/3 · 成功 0 · 失败 0 · 未确认 2 · 未发送 1'))
    .toBeVisible()
  await page.getByRole('button', { name: '关闭批量页' }).click()
  await page.getByRole('button', { name: '重新打开批量页' }).click()
  await expect.element(page.getByText('已选 0/50')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('pauses after 429 and resumes only queued rows by explicit action', async () => {
  let sent = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body))
      sent += 1
      if (sent === 1)
        return Response.json(
          { error: { message: '稍后重试' } },
          {
            status: 429,
            headers: { 'Retry-After': '0' },
          }
        )
      return Response.json(result(body))
    })
  )
  await show(detail, ['chat'])
  await openSelection()
  await addChat('chat-a', '第一项')
  await addChat('embed-a', '第二项')
  await addChat('rerank-a', '第三项')
  await page.getByRole('button', { name: '确认 3 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect.element(page.getByText(/服务端限流：请求受限/)).toBeVisible()
  expect(sent).toBe(2)
  await expect
    .element(page.getByRole('button', { name: '明确继续未发送项' }))
    .toBeEnabled()
  await page.getByRole('button', { name: '明确继续未发送项' }).click()
  await expect
    .element(page.getByText('完成 3/3 · 成功 2 · 失败 1 · 未确认 0 · 未发送 0'))
    .toBeVisible()
  expect(sent).toBe(3)
})

it('keeps sent request IDs visible when a 409 refresh removes all inventory', async () => {
  let sent = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      sent += 1
      if (sent === 1)
        return Response.json(
          { error: { message: '配置已变化' } },
          { status: 409 }
        )
      return new Promise<Response>((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError'))
        )
      })
    })
  )
  function Harness() {
    const [current, setCurrent] = useState(detail)
    return (
      <ChannelDiagnosticBatch
        channel={current}
        operations={current.models.length ? ['chat'] : []}
        onFinished={() =>
          setCurrent({ ...detail, models: [], model_count: 0, version: 8 })
        }
      />
    )
  }
  await render(<Harness />)
  await openSelection()
  await addChat('chat-a', '第一项')
  await addChat('embed-a', '第二项')
  await page.getByRole('button', { name: '确认 2 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect.element(page.getByText('配置变化，已冻结')).toBeVisible()
  await expect.element(page.getByText(/启动时渠道配置 v7/)).toBeVisible()
  await expect
    .element(page.getByText('当前渠道没有已登记模型或可用的批量诊断操作。'))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '按原请求号回查' }))
    .toBeVisible()
  expect(sent).toBe(2)
  await page.getByRole('button', { name: '停止派发与等待' }).click()
})

it('keeps a frozen batch visible but blocks reconfiguration with the stale channel version', async () => {
  const refresh = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({ error: { message: '配置已变化' } }, { status: 409 })
    )
  )
  await show(detail, ['chat'], refresh)
  await openSelection()
  await addChat('chat-a', '版本检查')
  await page.getByRole('button', { name: '确认 1 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect.element(page.getByText('配置变化，已冻结')).toBeVisible()
  await expect
    .element(
      page.getByText(
        '当前仍显示启动时的渠道版本；请关闭并重新打开详情或刷新渠道配置。'
      )
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '配置新批次' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '刷新渠道配置' }).click()
  expect(refresh).toHaveBeenCalledOnce()
  await expect
    .element(page.getByRole('button', { name: '按原请求号回查' }))
    .toBeVisible()
  await page.getByRole('button', { name: '停止派发与等待' }).click()
  await expect
    .element(page.getByRole('button', { name: '配置新批次' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '刷新渠道配置' }))
    .toBeVisible()
})

it('looks up details by the original request and hides prior evidence after 403', async () => {
  let sent = 0
  let reads = 0
  let original = ''
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === 'POST') {
        sent += 1
        const body = JSON.parse(String(options.body))
        original = body.request_id
        return Response.json(result(body))
      }
      expect(url).toContain(`/llm/diagnostics/${original}`)
      reads += 1
      if (reads === 1)
        return Response.json({
          channel_id: detail.id,
          media_available: false,
          record: {
            request_id: original,
            model: 'chat-a',
            operation: 'chat',
            tested_at: '2026-10-04T00:00:00Z',
            status: 'success',
            record_version: 'attempt_v1',
            uncertain: false,
            attempt: {
              sent: true,
              output_started: true,
              upstream_terminal: true,
              client_terminal: null,
              uncertain: false,
              usage_evidence: [
                {
                  field: 'input_tokens',
                  value: 12,
                  source: 'upstream',
                  complete: true,
                  phase: 'terminal',
                  metric: 'tokens',
                },
              ],
            },
          },
        })
      return Response.json(
        { error: { message: '权限已撤销' } },
        { status: 403 }
      )
    })
  )
  await show(detail, ['chat'])
  await openSelection()
  await addChat('chat-a', '测试证据')
  await page.getByRole('button', { name: '确认 1 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect.element(page.getByText('发送：已发送')).toBeVisible()
  await page.getByRole('button', { name: '按原请求号回查' }).click()
  await expect
    .element(page.getByText('已按原请求号回查；正文与媒体不可恢复。'))
    .toBeVisible()
  await expect
    .element(page.getByText('输入 Token：12 · 上游原始 · 完整'))
    .toBeVisible()
  await page.getByRole('button', { name: '按原请求号回查' }).click()
  await expect
    .element(
      page.getByText('权限已失效，结果已从当前视图清除；不能继续派发或回查。')
    )
    .toBeVisible()
  await expect.element(page.getByText('发送：已发送')).not.toBeInTheDocument()
  expect(sent).toBe(1)
})

it('keeps selection and progress within a 390px sheet', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body))
      return Response.json(result(body))
    })
  )
  await page.viewport(390, 844)
  await show(detail, ['chat'])
  await page.getByRole('button', { name: '选择已登记模型／操作' }).click()
  await expect
    .element(page.getByRole('dialog', { name: '选择批量诊断项' }))
    .toBeVisible()
  const sheet = page.getByRole('dialog', { name: '选择批量诊断项' }).element()
  expect(sheet.scrollWidth).toBeLessThanOrEqual(sheet.clientWidth + 1)
  await addChat('chat-a', '窄屏测试')
  await page.screenshot({
    path: '__screenshots__/actvero-g5-02-batch-selection-390.png',
  })
  await page.getByRole('button', { name: '确认 1 项' }).click()
  await page.getByRole('button', { name: '开始批量诊断' }).click()
  await expect
    .element(page.getByText('完成 1/1 · 成功 1 · 失败 0 · 未确认 0 · 未发送 0'))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(391)
  await page.screenshot({
    path: '__screenshots__/actvero-g5-02-batch-progress-390.png',
  })
})
