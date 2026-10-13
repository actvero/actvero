import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { ModelEndpointsPanel } from './model-endpoints'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({ organization: { tenant_id: 'endpoints-org' } }),
}))
const model = { id: 'model-id', version: 2 }
const projection: Schema['ModelEndpoints'] = {
  model_id: model.id,
  version: model.version,
  slug: 'team-chat',
  member_authorization: 'not_evaluated',
  endpoints: [
    {
      operation: 'chat',
      method: 'POST',
      path: '/api/llm/v1/chat/completions',
      inbound_protocol: 'openai_compatible',
      stream: true,
      tools: true,
      stream_declaration: 'unknown',
      tools_declaration: 'supported',
      open: true,
      reasons: [],
      example: {
        model: 'team-chat',
        messages: [{ role: 'user', content: '你好' }],
      },
    },
    {
      operation: 'embedding',
      method: 'POST',
      path: '/api/llm/v1/embeddings',
      inbound_protocol: 'openai_compatible',
      stream: false,
      tools: false,
      open: false,
      reasons: ['operation_not_configured'],
      example: { model: 'team-chat', input: '示例' },
    },
  ],
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
async function show(
  props: { model?: typeof model; dirty?: boolean; configuredOnly?: boolean } = {
    model,
  }
) {
  return render(
    <QueryClientProvider client={client}>
      <ModelEndpointsPanel {...props} />
    </QueryClientProvider>
  )
}

it('does not infer endpoints or send requests for an unsaved draft', async () => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  await show({})
  await expect
    .element(page.getByText('保存模型后可查看调用端点。'))
    .toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
})

it('shows saved public paths and copies only the exact public model example', async () => {
  const fetcher = vi.fn(async (url: string) => {
    expect(url).toBe('/api/v1/llm/models/model-id/endpoints')
    return Response.json(projection)
  })
  vi.stubGlobal('fetch', fetcher)
  const copied = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  await show()
  await expect
    .element(page.getByRole('textbox', { name: '对话端点', exact: true }))
    .toHaveValue('POST /api/llm/v1/chat/completions')
  await expect.element(page.getByText('流式：模型能力待确认')).toBeVisible()
  await expect
    .element(
      page.getByText('实际调用还需满足当前成员权限与额度。', { exact: false })
    )
    .toBeVisible()
  await page.getByRole('button', { name: '对话请求示例', exact: true }).click()
  await page
    .getByRole('button', { name: '复制对话请求示例', exact: true })
    .click()
  expect(JSON.parse(copied.mock.calls[0][0])).toEqual(
    projection.endpoints[0].example
  )
  expect(document.body.textContent).not.toContain('/v1/responses')
  expect(document.body.textContent).not.toContain('复制向量请求示例')
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('labels dirty state and hides request examples rather than applying draft changes', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json(projection))
  )
  await show({ model, dirty: true })
  await expect
    .element(page.getByText('当前修改尚未保存，以下仍为已保存配置的端点。'))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '对话端点', exact: true }))
    .toHaveValue('POST /api/llm/v1/chat/completions')
  expect(document.body.textContent).not.toContain('对话请求示例')
})

it('does not show another model version as the current configuration', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ ...projection, version: 3 }))
  )
  await show()
  await expect
    .element(page.getByText('模型配置已更新。', { exact: false }))
    .toBeVisible()
  expect(document.querySelector('[aria-label="对话请求 JSON"]')).toBeNull()
  expect(document.body.textContent).not.toContain('配置就绪')
})

it('removes cached endpoint details when authorization is lost on refresh', async () => {
  let denied = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      denied
        ? Response.json(
            { error: { message: '仅管理员可查看' } },
            { status: 403 }
          )
        : Response.json(projection)
    )
  )
  await show()
  await expect
    .element(page.getByText('配置就绪', { exact: true }))
    .toBeVisible()
  denied = true
  await page.getByRole('button', { name: '刷新端点状态' }).click()
  await expect.element(page.getByText('仅管理员可查看')).toBeVisible()
  expect(document.body.textContent).not.toContain('配置就绪')
})

it('shows unavailable reasons and read-only paths without overflow at 390px', async () => {
  await page.viewport(390, 844)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({
        ...projection,
        endpoints: [
          {
            ...projection.endpoints[0],
            open: false,
            reasons: ['manual_disabled', 'source_missing'],
          },
        ],
      })
    )
  )
  await show()
  await expect.element(page.getByText('渠道已停用')).toBeVisible()
  await expect.element(page.getByText('上游模型已从渠道移除')).toBeVisible()
  expect(document.querySelector<HTMLInputElement>('input')?.readOnly).toBe(true)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  expect(document.body.textContent).not.toContain('对话请求示例')
  await page.screenshot({ path: '/private/tmp/actvero-g2-endpoints-390.png' })
})

it('shows only saved configured interfaces in the editor detail', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json(projection))
  )
  await show({ model, configuredOnly: true })
  await expect
    .element(page.getByRole('textbox', { name: '对话端点', exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '向量端点', exact: true }))
    .not.toBeInTheDocument()
})
