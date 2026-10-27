import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { ModelCreate } from './model-create'
import type { ReferenceModel } from './reference-models'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'public-create-org' },
    csrf: 'csrf',
  }),
}))
const source: ReferenceModel = {
  provider: 'openai',
  provider_name: 'OpenAI',
  model_id: 'reference-chat',
  name: '公共对话模型',
  developer: 'openai',
  developer_name: 'OpenAI',
  context_window: 128000,
  max_output: 8192,
  capabilities: {
    streaming: 'unknown',
    tools: 'supported',
    vision: 'unsupported',
    structured_output: 'supported',
    reasoning: 'unknown',
  },
  reasoning_options: [],
  temperature: 'unknown',
  price_importable: false,
  price: null,
  price_notes: [],
  quote_snapshot: {
    provider: 'openai',
    model_id: 'reference-chat',
    fetched_at: '2026-10-26T00:00:00Z',
    source_updated_at: null,
    currency: 'USD',
    unit: 1000000,
    metric: 'tokens',
    source_url: null,
    raw_cost: { input: '3', output: '12' },
    conditions: [],
  },
}
const catalogue = (items = [source], extra = {}) => ({
  items,
  total: items.length,
  page_size: 20,
  fetched_at: '2026-10-26T00:00:00Z',
  stale: false,
  skipped: 0,
  facets: {
    providers: [{ id: 'openai', name: 'OpenAI' }],
    developers: [{ id: 'openai', name: 'OpenAI' }],
  },
  ...extra,
})
let client: QueryClient
const writes: Schema['CatalogInput'][] = []
const requests: string[] = []
async function show(
  response: (url: URL) => Response | Promise<Response> = () =>
    Response.json(catalogue())
) {
  writes.length = 0
  requests.length = 0
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      requests.push(url)
      if (url.includes('/reference-models'))
        return response(new URL(url, 'http://localhost'))
      if (url.endsWith('/models') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        writes.push(body)
        return Response.json({ id: 'created', ...body })
      }
      throw new Error('Unexpected request: ' + url)
    })
  )
  const saved = vi.fn(),
    close = vi.fn()
  await render(
    <QueryClientProvider client={client}>
      <ModelCreate saved={saved} close={close} />
    </QueryClientProvider>
  )
  await waitForAnimations()
  return { saved, close }
}
afterEach(async () => {
  await cleanup()
  await client?.cancelQueries()
  client?.clear()
  vi.unstubAllGlobals()
  await page.viewport(1280, 900)
})

it('searches the public library and creates an editable independent model without assigning costs or a channel', async () => {
  const { saved } = await show()
  await page.getByLabelText('搜索公开模型').fill('reference-chat')
  await expect
    .poll(() => requests.some((r) => r.includes('q=reference-chat')))
    .toBe(true)
  await page
    .getByRole('button', { name: /公共对话模型 reference-chat/ })
    .click()
  await expect.element(page.getByText('128,000', { exact: true })).toBeVisible()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '使用此模型' }).click()
  await expect.element(page.getByLabelText('展示名称')).toHaveValue(source.name)
  await expect
    .element(page.getByLabelText('技术名称'))
    .toHaveValue(source.model_id)
  await expect
    .element(page.getByLabelText('上下文上限（Token）'))
    .toHaveValue('128000')
  await expect
    .element(page.getByRole('combobox', { name: '流式输出' }))
    .toHaveTextContent('未知')
  await page.getByLabelText('展示名称').fill('团队模型')
  await page.getByLabelText('技术名称').fill('team-chat')
  await page.getByLabelText('最大输出（Token）').fill('4096')
  await page.getByRole('button', { name: '创建模型', exact: true }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes[0]).toMatchObject({
    name: '团队模型',
    slug: 'team-chat',
    reference: { provider: 'openai', model_id: 'reference-chat' },
    access: { enabled: false, channel_id: null, upstream_id: '' },
    operations: [
      {
        kind: 'chat',
        enabled: false,
        context_window: 128000,
        max_output: 4096,
        bindings: [],
        budget_price: null,
      },
    ],
    quote_snapshots: [source.quote_snapshot],
  })
  expect(
    requests.some((r) =>
      /channels|model-hint|import-preview|import-commit/.test(r)
    )
  ).toBe(false)
})

it('distinguishes identical IDs from different providers and keeps unknown limits empty', async () => {
  const alternate = {
    ...source,
    provider: 'other',
    provider_name: '另一家供应商',
    context_window: null,
    max_output: null,
    quote_snapshot: null,
  }
  const { saved } = await show(() =>
    Response.json(catalogue([source, alternate]))
  )
  await page
    .getByRole('button', { name: /公共对话模型 reference-chat 另一家供应商/ })
    .click()
  await page.getByRole('button', { name: '使用此模型' }).click()
  await expect
    .element(page.getByLabelText('上下文上限（Token）'))
    .toHaveValue('')
  await expect.element(page.getByLabelText('最大输出（Token）')).toHaveValue('')
  await page.getByRole('button', { name: '创建模型', exact: true }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes[0]).toMatchObject({
    reference: { provider: 'other', model_id: 'reference-chat' },
    quote_snapshots: [],
    operations: [
      { context_window: null, max_output: null, budget_price: null },
    ],
  })
})

it('clears the selected model when searching or paginating and forwards filters', async () => {
  await show((url) =>
    Response.json(
      catalogue([source], { total: url.searchParams.get('q') ? 1 : 21 })
    )
  )
  await page
    .getByRole('button', { name: /公共对话模型 reference-chat/ })
    .click()
  await expect
    .element(page.getByRole('button', { name: '使用此模型' }))
    .toBeEnabled()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect.poll(() => requests.some((r) => r.includes('page=2'))).toBe(true)
  await expect
    .element(page.getByRole('button', { name: '使用此模型' }))
    .toBeDisabled()
  await page.getByLabelText('搜索公开模型').fill('reference-chat')
  await expect
    .poll(() => requests.some((r) => r.includes('q=reference-chat&page=1')))
    .toBe(true)
  await page.getByRole('combobox', { name: 'API 供应商', exact: true }).click()
  await page.getByRole('option', { name: 'OpenAI', exact: true }).click()
  await expect
    .poll(() => requests.some((r) => r.includes('provider=openai')))
    .toBe(true)
  expect(writes).toHaveLength(0)
})

it('offers manual creation on empty results and does not request channels', async () => {
  const { saved } = await show(() => Response.json(catalogue([])))
  await expect
    .element(page.getByText('没有找到匹配的模型，可调整搜索条件或手动创建。'))
    .toBeVisible()
  await page.getByRole('button', { name: '改为手动创建' }).click()
  await page.getByLabelText('展示名称').fill('自定义向量')
  await page.getByLabelText('技术名称').fill('custom-embedding')
  await page.getByRole('combobox', { name: '模型类型' }).click()
  await page.getByRole('option', { name: '向量', exact: true }).click()
  await page.getByLabelText('默认维度').fill('1024')
  await page.getByRole('combobox', { name: '模型类型' }).click()
  await page.getByRole('option', { name: '对话', exact: true }).click()
  await page.getByRole('combobox', { name: '模型类型' }).click()
  await page.getByRole('option', { name: '向量', exact: true }).click()
  await expect.element(page.getByLabelText('默认维度')).toHaveValue('1024')
  await expect
    .element(page.getByLabelText('展示名称'))
    .toHaveValue('自定义向量')
  await page.getByRole('button', { name: '创建模型', exact: true }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes[0].operations).toHaveLength(1)
  expect(writes[0]).toMatchObject({
    name: '自定义向量',
    access: { enabled: false },
    operations: [
      {
        kind: 'embedding',
        enabled: false,
        bindings: [],
        retrieval: { dimensions: 1024 },
      },
    ],
  })
  expect(requests.some((r) => r.includes('channels'))).toBe(false)
})

it('recovers a public library error and labels stale catalogue data', async () => {
  let failing = true
  await show(() =>
    failing
      ? Response.json({ error: { message: '公共库暂不可用' } }, { status: 503 })
      : Response.json(catalogue([source], { stale: true }))
  )
  await expect
    .element(page.getByText('公共库暂不可用', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '手动创建', exact: true }))
    .toBeEnabled()
  failing = false
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect
    .element(page.getByText('公共库暂时无法更新，当前显示缓存资料。'))
    .toBeVisible()
  await page
    .getByRole('button', { name: /公共对话模型 reference-chat/ })
    .click()
  await expect
    .element(page.getByRole('button', { name: '使用此模型' }))
    .toBeEnabled()
})

it('keeps the narrow search, detail, and imported form within the viewport', async () => {
  await page.viewport(390, 844)
  await show()
  const fits = async () => {
    await waitForAnimations()
    const dialog = page.getByRole('dialog').element()
    expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
    expect(dialog.getBoundingClientRect().right).toBeLessThanOrEqual(
      window.innerWidth + 1
    )
  }
  await fits()
  await page
    .getByRole('button', { name: /公共对话模型 reference-chat/ })
    .click()
  await fits()
  await expect
    .element(page.getByRole('button', { name: '返回搜索结果' }))
    .toBeVisible()
  await page.getByRole('button', { name: '返回搜索结果' }).click()
  await expect.element(page.getByLabelText('搜索公开模型')).toBeVisible()
  await page.getByRole('button', { name: '使用此模型' }).click()
  await fits()
  await page.getByLabelText('技术名称').fill('edited-draft')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect.element(page.getByText('放弃未保存的模型修改？')).toBeVisible()
  await page.getByRole('button', { name: '继续编辑' }).click()
  await expect
    .element(page.getByLabelText('技术名称'))
    .toHaveValue('edited-draft')
  expect(writes).toHaveLength(0)
})
