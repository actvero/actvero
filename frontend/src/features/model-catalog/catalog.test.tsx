import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ModelEditor } from './model-editor'
import {
  modelInput,
  modelSchema,
  shiftDecimal,
  values,
  type Model,
} from './model-form'
import { ModelTest } from './model-test'
import { ModelCatalogPage } from './page'
import { importModel, type ReferenceModel } from './reference-models'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
    user: { id: 'admin' },
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
    <main className='flex min-w-0 flex-col gap-6 p-6'>
      <div className='flex items-center justify-between'>
        <h1>{title}</h1>
        {action}
      </div>
      {children}
    </main>
  ),
}))
const model: Model = {
  display_order: 0,
  kind: 'chat',
  id: 'model-1',
  icon: '',
  icon_key: '',
  name: '统一模型',
  slug: 'team-chat',
  vendor: '原有开发方',
  description: '原有模型说明',
  capabilities: {
    streaming: 'unknown',
    tools: 'supported',
    vision: 'unknown',
    structured_output: 'unknown',
    reasoning: 'unknown',
  },
  context_window: 32000,
  max_output: 8000,
  archived: false,
  version: 1,
  budget_price: {
    metric: 'tokens',
    currency: 'USD',
    unit: 1000000,
    input: '2',
    output: '8',
    cache_read: '0.2',
    note: '',
  },
  bindings: [
    {
      binding_id: 'bbf35b36-d5f6-4a19-a9e7-3ea4607a97d6',
      channel_id: 'channel-a',
      upstream_id: 'upstream-a',
      enabled: true,
      priority: 0,
      weight: 100,
      compatibility_key: '',
      price: {
        metric: 'tokens',
        currency: 'CNY',
        unit: 1000000,
        input: '1',
        output: '4',
        note: '原有采购备注',
      },
    },
  ],
  binding_states: [
    {
      binding_id: 'bbf35b36-d5f6-4a19-a9e7-3ea4607a97d6',
      operation: 'chat',
      channel_id: 'channel-a',
      channel_name: '团队渠道',
      upstream_id: 'upstream-a',
      state: 'registered',
    },
  ],
  created_at: '2026-09-24T00:00:00Z',
  updated_at: '2026-09-24T00:00:00Z',
}
// Read-only endpoint and price previews must not count as model configuration writes.
function stubFetch(handler: (url: string, init?: RequestInit) => unknown) {
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    if (url.endsWith('/endpoints'))
      return Promise.resolve(
        Response.json({
          model_id: model.id,
          version: model.version,
          slug: model.slug,
          member_authorization: 'not_evaluated',
          endpoints: [],
        })
      )
    if (url.endsWith('/point-prices/preview'))
      return Promise.resolve(Response.json({ status: 'ready' }))
    return handler(url, init)
  })
}
const clients: QueryClient[] = []
async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  const screen = await render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
  // Finish the sheet's entrance before interacting with tabs; its focus scope
  // and a previous dialog's focus restoration otherwise race the next click.
  await waitForAnimations()
  return screen
}
beforeEach(async () => {
  await page.viewport(1280, 900)
})
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((c) => c.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 800)
})

it('converts decimal units without losing tiny prices or turning unknown into free', () => {
  for (const value of ['2', '0.2', '0.000000000001', '1000000000', '0'])
    expect(shiftDecimal(shiftDecimal(value, -3), 3)).toBe(value)
  expect(shiftDecimal('', 3)).toBe('')
  expect(shiftDecimal('0.002', 3)).toBe('2')
  const draft = values(model)
  draft.budget_price.currency = ''
  expect(modelSchema.safeParse(draft).success).toBe(false)
  draft.budget_price.enabled = false
  draft.budget_price.note = 'x'.repeat(501)
  expect(modelSchema.safeParse(draft).success).toBe(true)
})

it('keeps binding identity through form validation and an upstream name edit', () => {
  const draft = values(model)
  draft.bindings[0].upstream_id = 'retargeted-model'
  const input = modelInput(modelSchema.parse(draft))
  expect(input.bindings?.[0]).toMatchObject({
    binding_id: model.bindings?.[0].binding_id,
    upstream_id: 'retargeted-model',
    enabled: true,
    price: model.bindings?.[0].price,
  })
})

it('creates a model with explicit price currency and atomically saves only on submit', async () => {
  const calls = vi.fn(async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body))
    expect(body).toMatchObject({
      name: '新模型',
      slug: 'new-model',
      budget_price: {
        metric: 'tokens',
        currency: 'USD',
        unit: 1000,
        input: '0.002',
        output: '0.008',
        cache_read: null,
      },
      bindings: [],
    })
    return Response.json(model)
  })
  stubFetch(calls)
  const saved = vi.fn()
  await show(<ModelEditor close={vi.fn()} saved={saved} />)
  await expect.element(page.getByLabelText('展示名称')).toHaveFocus()
  await page.getByLabelText('展示名称').fill('新模型')
  await page.getByLabelText('技术名称').fill('new-model')
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('switch', { name: '配置价格' }).click()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect
    .element(page.getByText('请选择币种', { exact: true }).last())
    .toBeVisible()
  expect(calls).not.toHaveBeenCalled()
  await page.getByRole('combobox', { name: '币种' }).click()
  await page.getByRole('option', { name: 'USD', exact: true }).click()
  await page.getByLabelText('输入', { exact: true }).fill('2')
  await page.getByLabelText('输出', { exact: true }).fill('8')
  await page.getByRole('combobox', { name: '录入单位' }).click()
  await page.getByRole('option', { name: '每千 Token', exact: true }).click()
  await expect
    .element(page.getByLabelText('输入', { exact: true }))
    .toHaveValue('0.002')
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(calls).toHaveBeenCalledTimes(1)
})

it('preserves prices on conflict and requires explicitly adopting the current server version', async () => {
  let count = 0
  const calls = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'GET') return Response.json({ ...model, version: 2 })
    const body = JSON.parse(String(init?.body))
    expect(body.version).toBe(count === 0 ? 1 : 2)
    expect(body.vendor).toBe(model.vendor)
    expect(body.description).toBe(model.description)
    expect(body.bindings[0].binding_id).toBe(model.bindings?.[0].binding_id)
    expect(body.bindings[0].price).toMatchObject({
      currency: 'CNY',
      input: '1',
      output: '4',
      note: '原有采购备注',
    })
    if (count === 0) expect(body.budget_price).toBeNull()
    else expect(body.budget_price).toMatchObject(model.budget_price!)
    count++
    return count === 1
      ? Response.json(
          { error: { message: '模型已被修改，请关闭并重新打开配置' } },
          { status: 409 }
        )
      : Response.json(model)
  })
  stubFetch(calls)
  const saved = vi.fn()
  await show(<ModelEditor model={model} close={vi.fn()} saved={saved} />)
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('switch', { name: '配置价格' }).click()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect
    .element(page.getByText('模型已被修改，请关闭并重新打开配置'))
    .toBeVisible()
  await expect
    .element(page.getByRole('switch', { name: '配置价格' }))
    .not.toBeChecked()
  await page.getByRole('tab', { name: '基本信息' }).click()
  await expect.element(page.getByLabelText('展示名称')).toHaveValue('统一模型')
  await expect
    .element(page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }))
    .not.toBeInTheDocument()
  expect(count).toBe(1)
  await page.getByRole('button', { name: '加载最新并比较' }).click()
  await expect
    .element(page.getByText('服务器版本 2：', { exact: false }))
    .toBeVisible()
  await page.getByRole('button', { name: '放弃草稿，采用服务器配置' }).click()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
})

it('selects registered channel models and configures independent purchase prices', async () => {
  const writes: unknown[] = []
  stubFetch(
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        writes.push(JSON.parse(String(init.body)))
        return Response.json(model)
      }
      if (url.includes('/channels?'))
        return Response.json({
          total: 1,
          items: [{ id: 'channel-a', name: '团队渠道' }],
        })
      return Response.json({
        id: 'channel-a',
        name: '团队渠道',
        models: [{ id: 'upstream-a' }, { id: 'upstream-b' }],
      })
    })
  )
  await show(<ModelEditor close={vi.fn()} saved={vi.fn()} />)
  await page.getByLabelText('展示名称').fill('模型')
  await page.getByLabelText('技术名称').fill('model')
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await page.getByRole('button', { name: '添加渠道关联' }).click()
  await page.getByRole('combobox', { name: '渠道', exact: true }).click()
  await page.getByRole('option', { name: '团队渠道' }).click()
  await page.getByRole('combobox', { name: '上游模型', exact: true }).click()
  await page.getByRole('option', { name: 'upstream-a' }).click()
  await page.getByRole('button', { name: '加入草稿' }).click()
  await expect
    .element(page.getByText('技术名称 model → 上游模型名称 upstream-a'))
    .toBeVisible()
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('combobox', { name: '价格对象' }).click()
  await page
    .getByRole('option', { name: '团队渠道 / upstream-a · 采购价格' })
    .click()
  await page.getByRole('switch', { name: '配置价格' }).click()
  await page.getByRole('combobox', { name: '币种' }).click()
  await page.getByRole('option', { name: 'CNY', exact: true }).click()
  await page.getByLabelText('输入', { exact: true }).fill('1')
  await page.getByLabelText('输出', { exact: true }).fill('4')
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({
    budget_price: null,
    access: {
      enabled: false,
      channel_id: 'channel-a',
      upstream_id: 'upstream-a',
    },
    bindings: [
      {
        channel_id: 'channel-a',
        upstream_id: 'upstream-a',
        price: { currency: 'CNY', input: '1', output: '4', note: '' },
      },
    ],
  })
})

it('shows the invalid purchase-price tab and explains exact estimates without saving', async () => {
  const calls = vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toContain('/llm/prices/estimate')
    const body = JSON.parse(String(init?.body))
    expect(body.usage.input).toBe(4000)
    return Response.json({
      currency: 'CNY',
      total: '0.004',
      items: [{ item: 'input', tokens: 4000, rate: '1', amount: '0.004' }],
    })
  })
  stubFetch(calls)
  const saved = vi.fn()
  const invalid = {
    ...model,
    bindings: [
      {
        ...model.bindings![0],
        price: { ...model.bindings![0].price!, output: '' },
      },
    ],
  }
  await show(<ModelEditor model={invalid} close={vi.fn()} saved={saved} />)
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect
    .element(page.getByRole('combobox', { name: '价格对象' }))
    .toHaveTextContent('采购价格')
  await page.getByLabelText('输出', { exact: true }).fill('4')
  await page.getByRole('button', { name: '费用试算' }).click()
  await page.getByLabelText('输入 Token', { exact: true }).fill('4000')
  await page.getByRole('button', { name: '计算费用' }).click()
  await expect.element(page.getByText('合计 CNY 0.004')).toBeVisible()
  expect(saved).not.toHaveBeenCalled()
  await page.getByLabelText('输入 Token', { exact: true }).fill('5000')
  await expect.element(page.getByText('合计 CNY 0.004')).not.toBeInTheDocument()
  await page.getByLabelText('输入 Token', { exact: true }).fill('4000')
  await page.getByRole('button', { name: '计算费用' }).click()
  await expect.element(page.getByText('合计 CNY 0.004')).toBeVisible()
  const dialog = page.getByRole('dialog', { name: '编辑模型' }).element()
  await Promise.all(dialog.getAnimations().map((a) => a.finished))
  ;(dialog.querySelector('.overflow-y-auto') as HTMLElement).scrollTop = 0
  await page.screenshot({ path: '__screenshots__/model-prices-desktop.png' })
})

it('keeps the narrow form scrollable and cancels without requests', async () => {
  const calls = vi.fn()
  stubFetch(calls)
  await page.viewport(390, 844)
  function Wrapper() {
    const [open, setOpen] = useState(true)
    return open ? (
      <ModelEditor model={model} close={() => setOpen(false)} saved={vi.fn()} />
    ) : (
      <p>已取消</p>
    )
  }
  await show(<Wrapper />)
  await page.getByRole('tab', { name: '价格配置' }).click()
  const dialog = page.getByRole('dialog', { name: '编辑模型' }).element()
  await Promise.all(dialog.getAnimations().map((a) => a.finished))
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  const scroll = dialog.querySelector('.overflow-y-auto') as HTMLElement
  expect(scroll.scrollHeight).toBeGreaterThan(scroll.clientHeight)
  await expect
    .element(page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/model-prices-narrow.png' })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect.element(page.getByText('已取消')).toBeVisible()
  expect(calls).not.toHaveBeenCalled()
})

it('distinguishes list load failure from empty state and archives and restores models', async () => {
  let failed = true
  let archived = false
  stubFetch(
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        archived = JSON.parse(String(init.body)).archived
        return Response.json({ ...model, archived })
      }
      if (failed) {
        failed = false
        return Response.json(
          { error: { message: '目录加载失败' } },
          { status: 503 }
        )
      }
      return Response.json({
        total: 1,
        items: [
          {
            ...model,
            archived: url.includes('state=archived') ? true : archived,
          },
        ],
      })
    })
  )
  const screen = await show(<ModelCatalogPage />)
  await expect.element(screen.getByText('目录加载失败')).toBeVisible()
  await screen.getByRole('button', { name: '重试' }).click()
  await expect
    .element(screen.getByRole('button', { name: '统一模型', exact: true }))
    .toBeVisible()
  await screen.getByRole('button', { name: '统一模型的更多操作' }).click()
  await page.getByRole('menuitem', { name: '归档模型' }).click()
  await page.getByRole('button', { name: '归档', exact: true }).click()
  await expect.poll(() => archived).toBe(true)
  await screen.getByRole('button', { name: '统一模型的更多操作' }).click()
  await page.getByRole('menuitem', { name: '恢复模型' }).click()
  await page.getByRole('button', { name: '恢复', exact: true }).click()
  await expect.poll(() => archived).toBe(false)
})

const reference: ReferenceModel = {
  provider: 'openai',
  provider_name: 'OpenAI',
  model_id: 'public-example',
  name: '公开模型样例',
  context_window: 128000,
  max_output: 16000,
  temperature: 'unknown',
  capabilities: {
    streaming: 'unknown',
    tools: 'unsupported',
    vision: 'supported',
    structured_output: 'unknown',
    reasoning: 'supported',
  },
  reasoning_options: [
    { type: 'toggle' },
    { type: 'effort', values: [null, 'none', 'low', 'high'] },
    { type: 'budget_tokens', min: -1, max: 8192 },
  ],
  price: {
    metric: 'tokens',
    currency: 'USD',
    unit: 1000000,
    input: '3',
    output: '12',
    cache_read: '0.3',
    note: '',
  },
  price_importable: true,
  price_conditions: [],
  price_notes: ['公开基础报价，实际采购请核对。'],
}
const referencePage = {
  items: [reference],
  total: 1,
  fetched_at: '2026-09-24T10:00:00Z',
  stale: false,
  skipped: 0,
  page_size: 20,
}

it('keeps manual data and prices on metadata import and preserves distinct reasoning controls', () => {
  const current = values(model)
  const merged = importModel(current, reference, false)
  expect(merged.name).toBe(model.name)
  expect(merged.context_window).toBe('32000')
  expect(merged.capabilities.tools).toBe('supported')
  expect(merged.capabilities.streaming).toBe('unknown')
  expect(merged.capabilities.reasoning).toBe('supported')
  expect(modelInput(merged).reasoning_options).toEqual(
    reference.reasoning_options
  )
  expect(merged.bindings).toEqual(current.bindings)
  expect(merged.budget_price).toEqual(current.budget_price)
  const replaced = importModel(current, reference, true)
  expect(replaced.name).toBe(reference.name)
  expect(replaced.capabilities.tools).toBe('unsupported')
  expect(replaced.budget_price).toEqual(current.budget_price)
})

it('imports public metadata as an unsaved draft and validates editable reasoning budgets', async () => {
  const calls = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/reference-models')) return Response.json(referencePage)
    if (url.endsWith('/channels/channel-a'))
      return Response.json({ provider: 'openai', name: '团队渠道' })
    const body = JSON.parse(String(init?.body))
    expect(body.name).toBe(model.name)
    expect(body.slug).toBe(model.slug)
    expect(body.reasoning_options).toEqual(reference.reasoning_options)
    expect(body.budget_price.input).toBe('2')
    return Response.json({ ...model, ...body })
  })
  stubFetch(calls)
  const saved = vi.fn()
  await show(<ModelEditor model={model} close={vi.fn()} saved={saved} />)
  await page.getByRole('button', { name: '从公开资料补全' }).click()
  await page
    .getByRole('button', { name: /公开模型样例 public-example/ })
    .click()
  await expect
    .element(page.getByRole('checkbox', { name: '导入模型资料' }))
    .toBeChecked()
  await expect
    .element(page.getByRole('checkbox', { name: '导入参考价格' }))
    .not.toBeChecked()
  await page.getByRole('button', { name: /预览修改/ }).click()
  await expect.element(page.getByText(/将修改 \d+ 项/)).toBeVisible()
  expect(saved).not.toHaveBeenCalled()
  await page.getByRole('button', { name: '确认应用到草稿' }).click()
  await expect.element(page.getByLabelText('展示名称')).toHaveValue(model.name)
  await expect
    .element(page.getByRole('checkbox', { name: '可开关', exact: true }))
    .toBeChecked()
  await expect
    .element(page.getByRole('checkbox', { name: '省略参数', exact: true }))
    .toBeChecked()
  await expect
    .element(page.getByRole('checkbox', { name: '关闭（none）', exact: true }))
    .toBeChecked()
  await page.screenshot({ path: '__screenshots__/model-reasoning-desktop.png' })
  await page.getByLabelText('预算上限（Token）').fill('10')
  await page.getByLabelText('预算下限（Token）').fill('100')
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.element(page.getByText('上限不能小于下限')).toBeVisible()
  expect(saved).not.toHaveBeenCalled()
  await page.getByLabelText('预算下限（Token）').fill('-1')
  await page.getByLabelText('预算上限（Token）').fill('8192')
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
})

it('imports reference prices only into the chosen channel price and clears unsupported cache rates', async () => {
  const importedNote =
    '公开参考（非实际结算价）：models.dev | openai/public-example | 抓取于 2026-09-24T10:00:00Z'
  const calls = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/reference-models')) return Response.json(referencePage)
    if (url.endsWith('/channels/channel-a'))
      return Response.json({ provider: 'openai', name: '团队渠道' })
    const body = JSON.parse(String(init?.body))
    expect(body.budget_price.input).toBe('2')
    expect(body.bindings[0].price).toMatchObject({
      metric: 'tokens',
      currency: 'USD',
      unit: 1000000,
      input: '3',
      output: '12',
      cache_read: '0.3',
      cache_write_5m: null,
      cache_write_1h: null,
      note: importedNote,
    })
    return Response.json({ ...model, ...body })
  })
  stubFetch(calls)
  const saved = vi.fn()
  await show(<ModelEditor model={model} close={vi.fn()} saved={saved} />)
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('combobox', { name: '价格对象' }).click()
  await page.getByRole('option', { name: /采购价格/ }).click()
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await page
    .getByRole('textbox', { name: '搜索公开模型' })
    .fill('public-example')
  await page.getByRole('checkbox', { name: '仅看有报价' }).click()
  await expect
    .poll(() =>
      calls.mock.calls.some(
        ([url]) =>
          url.includes('/reference-models?') &&
          url.includes('q=public-example') &&
          url.includes('price=available') &&
          url.includes('preferred_provider=openai')
      )
    )
    .toBe(true)
  await page
    .getByRole('button', { name: /公开模型样例 public-example/ })
    .click()
  await expect
    .element(page.getByText(/公开基础报价，实际采购请核对/))
    .toBeVisible()
  await expect
    .element(page.getByRole('checkbox', { name: '导入模型资料' }))
    .not.toBeChecked()
  await expect
    .element(page.getByRole('button', { name: /预览修改/ }))
    .toBeDisabled()
  await page
    .getByRole('checkbox', {
      name: '已核对该渠道的供应商、套餐和实际采购单价',
    })
    .click()
  await page.getByRole('button', { name: /预览修改/ }).click()
  await expect.element(page.getByText(/缓存写入/).first()).toBeVisible()
  await expect
    .element(page.getByText('价格备注', { exact: true }))
    .toBeVisible()
  await expect.element(page.getByText('当前：原有采购备注')).toBeVisible()
  await expect.element(page.getByText(`修改为：${importedNote}`)).toBeVisible()
  await expect.element(page.getByText(/将修改 \d+ 项/)).toBeVisible()
  await page.getByRole('button', { name: '确认应用到草稿' }).click()
  await expect
    .element(page.getByLabelText('输入', { exact: true }))
    .toHaveValue('3')
  expect(saved).not.toHaveBeenCalled()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
})

it('shows catalog errors and stale state, fits a narrow screen and cancels without saving', async () => {
  let failed = true
  stubFetch(
    vi.fn(async (url: string) => {
      if (url.endsWith('/channels/channel-a'))
        return Response.json({ provider: 'openai', name: '团队渠道' })
      return failed
        ? Response.json(
            { error: { message: '公开目录暂不可用' } },
            { status: 503 }
          )
        : Response.json({ ...referencePage, stale: true })
    })
  )
  await page.viewport(390, 844)
  const saved = vi.fn()
  await show(<ModelEditor close={vi.fn()} saved={saved} />)
  await page.getByRole('button', { name: '从公开资料补全' }).click()
  await expect.element(page.getByText('公开目录暂不可用')).toBeVisible()
  failed = false
  await page.getByRole('button', { name: '重试' }).click()
  await page
    .getByRole('button', { name: /公开模型样例 public-example/ })
    .click()
  await page.getByRole('button', { name: '返回结果' }).click()
  await expect
    .element(page.getByRole('button', { name: /公开模型样例 public-example/ }))
    .toHaveAttribute('aria-pressed', 'true')
  await page
    .getByRole('button', { name: /公开模型样例 public-example/ })
    .click()
  await expect
    .element(page.getByText('同步失败，正在使用旧资料。'))
    .toBeVisible()
  const dialog = page.getByRole('dialog', {
    name: '选择公开模型资料与报价',
  })
  expect(dialog.element().scrollWidth).toBeLessThanOrEqual(
    dialog.element().clientWidth + 1
  )
  await page.screenshot({ path: '__screenshots__/model-reference-narrow.png' })
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await expect.element(page.getByLabelText('展示名称')).toHaveValue('')
  expect(saved).not.toHaveBeenCalled()
})

it('configures embeddings without chat fields, output pricing or accidental publication', async () => {
  const calls = vi.fn(async (_url: string, init?: RequestInit) => {
    if (!init?.body)
      return Response.json(
        _url.includes('/routes') ? [] : { items: [], total: 0 }
      )
    const body = JSON.parse(String(init?.body))
    expect(body).toMatchObject({
      operations: [
        { kind: 'chat', enabled: false },
        {
          kind: 'embedding',
          enabled: false,
          retrieval: { dimensions: 1024, embedding_space: 'bge-v1' },
          budget_price: { input: '0.3', output: null, metric: 'tokens' },
        },
      ],
      access: { enabled: false },
    })
    return Response.json({ ...model, ...body })
  })
  stubFetch(calls)
  const saved = vi.fn()
  await show(<ModelEditor saved={saved} close={vi.fn()} />)
  await page.getByLabelText('展示名称').fill('向量模型')
  await page.getByLabelText('技术名称').fill('team-embed')
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await page.getByRole('button', { name: '高级：多个用途与独立开关' }).click()
  await page.getByRole('combobox', { name: '添加接口' }).click()
  await page.getByRole('option', { name: '向量', exact: true }).click()
  await expect.element(page.getByLabelText('默认维度')).toBeVisible()
  await expect
    .element(page.getByText('思考模式', { exact: true }))
    .not.toBeInTheDocument()
  await page.getByLabelText('默认维度').fill('1024')
  await page.getByLabelText('向量空间标识').fill('bge-v1')
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('switch', { name: '配置价格' }).click()
  await page.getByRole('combobox', { name: '币种' }).click()
  await page.getByRole('option', { name: 'USD', exact: true }).click()
  await page.getByLabelText('输入', { exact: true }).fill('0.3')
  await expect
    .element(page.getByLabelText('输出', { exact: true }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '导入参考价格' }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
})

it('changes rerank pricing units exactly and catches access errors in the correct tab', async () => {
  stubFetch((url) =>
    Response.json(url.endsWith('/routes') ? [] : { total: 0, items: [] })
  )
  const rerank: Model = {
    ...model,
    kind: 'rerank',
    budget_price: {
      currency: 'USD',
      metric: 'search_units',
      unit: 1000000,
      input: '3',
      output: null,
      note: '',
    },
    access: {
      enabled: false,
      channel_id: '',
      upstream_id: '',
      audience: 'administrators',
      member_ids: [],
    },
  }
  await show(<ModelEditor model={rerank} saved={vi.fn()} close={vi.fn()} />)
  await page.getByRole('tab', { name: '价格配置' }).click()
  await expect.element(page.getByLabelText('搜索单位单价')).toHaveValue('3')
  await page.getByRole('combobox', { name: '录入单位' }).click()
  await page.getByRole('option', { name: '每千 搜索单位' }).click()
  await expect.element(page.getByLabelText('搜索单位单价')).toHaveValue('0.003')
  await page.getByRole('tab', { name: '调用设置' }).click()
  await page.getByRole('switch', { name: '启用模型' }).click()
  await page.getByRole('tab', { name: '基本信息' }).click()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect
    .element(page.getByText('请选择调用渠道', { exact: true }))
    .toBeVisible()
})

it('tests a saved embedding route, shows unknown usage and invalidates stale results', async () => {
  const embedding: Model = {
    ...model,
    kind: 'embedding',
    access: {
      enabled: false,
      audience: 'administrators',
      channel_id: 'channel-a',
      upstream_id: 'upstream-a',
      member_ids: [],
    },
  }
  stubFetch(
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/calls') || url.endsWith('/routes'))
        return Response.json([])
      expect(JSON.parse(String(init?.body))).toEqual({
        model: model.slug,
        input: ['first', 'second'],
      })
      return Response.json({
        object: 'list',
        model: model.slug,
        data: [
          { index: 0, embedding: [0.1, 0.2, 0.3] },
          { index: 1, embedding: [0.2, 0.1, 0.4] },
        ],
        usage: { prompt_tokens: null },
      })
    })
  )
  await page.viewport(390, 844)
  await show(
    <ModelTest model={embedding} close={vi.fn()} restoreFocus={vi.fn()} />
  )
  await page.getByLabelText('输入文本（每行一条）').fill('first\nsecond')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect
    .element(page.getByText(/返回 2 条向量 · 3 维 · 输入用量 未知/))
    .toBeVisible()
  const dialog = page.getByRole('dialog')
  expect(dialog.element().scrollWidth).toBeLessThanOrEqual(
    dialog.element().clientWidth + 1
  )
  await page.screenshot({ path: '__screenshots__/embedding-test-narrow.png' })
  await page.getByLabelText('输入文本（每行一条）').fill('changed')
  await expect.element(page.getByText(/返回 2 条向量/)).not.toBeInTheDocument()
  await page.getByRole('tab', { name: '最近调用' }).click()
  await expect.element(page.getByText('暂无调用记录')).toBeVisible()
})

it('configures automatic routing and validates weights on the routing tab at narrow width', async () => {
  const saved = vi.fn()
  let submitted: Record<string, unknown> | undefined
  const embedding: Model = {
    ...model,
    kind: 'embedding',
    retrieval: {
      dimensions: 3,
      embedding_space: 'space-v1',
      max_batch_size: 32,
      max_input_characters: 20000,
    },
    budget_price: null,
    bindings: [{ ...model.bindings![0], price: null }],
  }
  stubFetch(
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        submitted = JSON.parse(String(init.body)) as Record<string, unknown>
        return Response.json({ ...embedding, ...submitted, version: 2 })
      }
      if (url.endsWith('/routes'))
        return Response.json([
          {
            channel_id: 'channel-a',
            upstream_id: 'upstream-a',
            state: 'unverified',
            failures: 0,
          },
        ])
      return Response.json({ items: [], total: 0 })
    })
  )
  await page.viewport(390, 844)
  await show(<ModelEditor model={embedding} saved={saved} close={vi.fn()} />)
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await page.getByRole('combobox', { name: '调度方式' }).click()
  await page.getByRole('option', { name: '自动调度', exact: true }).click()
  await page.getByRole('button', { name: '高级：失败回退与冷却' }).click()
  await page.getByRole('switch', { name: '失败回退', exact: true }).click()
  await expect
    .element(page.getByLabelText('最多尝试（含首次）'))
    .toHaveValue('3')
  await expect
    .element(page.getByRole('switch', { name: /超时／中断/ }))
    .not.toBeChecked()
  await page.getByRole('button', { name: '高级：请求参数与兼容设置' }).click()
  await page.getByLabelText('优先级', { exact: true }).fill('20')
  await page.getByLabelText('权重', { exact: true }).fill('0')
  await page.getByLabelText('确认向量空间').fill('space-v1')
  await page.getByRole('tab', { name: '基本信息' }).click()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await page.getByRole('button', { name: '高级：请求参数与兼容设置' }).click()
  await expect.element(page.getByText('填写 1 至 10000 的整数')).toBeVisible()
  expect(saved).not.toHaveBeenCalled()
  await page.getByLabelText('权重', { exact: true }).fill('50')
  const dialog = page.getByRole('dialog')
  expect(dialog.element().scrollWidth).toBeLessThanOrEqual(
    dialog.element().clientWidth + 1
  )
  await page.screenshot({ path: '__screenshots__/routing-narrow.png' })
  await page.getByRole('tab', { name: '调用设置' }).click()
  await expect
    .element(page.getByRole('combobox', { name: '调用渠道' }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(submitted?.routing).toMatchObject({
    mode: 'auto',
    fallback: true,
    retry_uncertain: false,
    max_attempts: 3,
  })
  expect(submitted?.bindings).toEqual([
    expect.objectContaining({
      enabled: true,
      priority: 20,
      weight: 50,
      compatibility_key: 'space-v1',
    }),
  ])
})

it('separates channel tests from route tests and expands per-attempt costs', async () => {
  const requests: string[] = []
  const embedding: Model = {
    ...model,
    kind: 'embedding',
    routing: {
      mode: 'auto',
      fallback: true,
      max_attempts: 3,
      connect_timeout_seconds: 10,
      first_response_timeout_seconds: 180,
      stream_idle_timeout_seconds: 180,
      total_timeout_seconds: 60,
      retry_uncertain: false,
      failure_threshold: 3,
      cooldown_seconds: 30,
      model_revision: '',
    },
  }
  stubFetch(
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/routes')) return Response.json([])
      if (url.endsWith('/calls'))
        return Response.json([
          {
            id: 'call-1',
            source: 'admin_route_test',
            kind: 'embedding',
            status: 'succeeded',
            created_at: '2026-09-24T12:00:00Z',
            duration_ms: 42,
            error_code: null,
            termination_code: null,
            usage: { input_tokens: 10 },
            estimates: {},
            attempts: [
              {
                number: 1,
                channel_name: '主渠道',
                upstream_id: 'upstream-a',
                status: 'failed',
                duration_ms: 20,
                upstream_status: 429,
                error_code: 'upstream_rate_limited',
                retry_reason: 'upstream_rate_limited',
                usage: {},
                estimates: {},
              },
              {
                number: 2,
                channel_name: '备用渠道',
                upstream_id: 'upstream-b',
                status: 'succeeded',
                duration_ms: 22,
                usage: { input_tokens: 10 },
                estimates: {
                  procurement: {
                    status: 'estimate',
                    currency: 'USD',
                    amount: '0.00001',
                  },
                },
              },
            ],
          },
        ])
      if (init?.method === 'POST') requests.push(url)
      return Response.json({
        model: model.slug,
        data: [{ index: 0, embedding: [1, 2, 3] }],
        usage: { prompt_tokens: 10 },
      })
    })
  )
  await show(
    <ModelTest model={embedding} close={vi.fn()} restoreFocus={vi.fn()} />
  )
  await page.getByLabelText('输入文本（每行一条）').fill('hello')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toContain('channel_id=channel-a&upstream_id=upstream-a')
  await page.getByRole('combobox', { name: '测试方式' }).click()
  await page.getByRole('option', { name: '路由测试', exact: true }).click()
  await expect
    .element(page.getByRole('combobox', { name: '测试渠道' }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.poll(() => requests.length).toBe(2)
  expect(requests[1]).toMatch(/\/test\/embeddings$/)
  await page.getByRole('tab', { name: '最近调用' }).click()
  await page.getByRole('button', { name: '2 次尝试' }).click()
  await expect.element(page.getByText('#1 主渠道 / upstream-a')).toBeVisible()
  await expect.element(page.getByText('#2 备用渠道 / upstream-b')).toBeVisible()
  await expect
    .element(page.getByText('回退原因：upstream_rate_limited'))
    .toBeVisible()
  await expect
    .element(page.getByText('Token：10 · 采购：USD 0.00001'))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/routing-attempts.png' })
})

it('keeps operation drafts separate, shares model access and saves new operations closed', async () => {
  const captured: Record<string, unknown>[] = []
  stubFetch(
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (!init?.body)
        return Response.json(
          _url.includes('/routes') ? [] : { items: [], total: 0 }
        )
      const body = JSON.parse(String(init?.body))
      captured.push(body)
      return Response.json({ ...model, ...body })
    })
  )
  const saved = vi.fn()
  await page.viewport(390, 844)
  await show(<ModelEditor model={model} saved={saved} close={vi.fn()} />)
  await page.getByLabelText('展示名称').fill('多操作模型')
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await page.getByRole('combobox', { name: '添加接口' }).click()
  await page.getByRole('option', { name: '向量', exact: true }).click()
  await page.getByRole('tab', { name: '调用设置' }).click()
  await expect
    .element(page.getByRole('switch', { name: '启用向量接口' }))
    .not.toBeChecked()
  await page.getByRole('tab', { name: '基本信息' }).click()
  await expect
    .element(page.getByLabelText('展示名称'))
    .toHaveValue('多操作模型')
  await page.getByLabelText('默认维度').fill('1024')
  await page.getByLabelText('向量空间标识').fill('separate-space')
  await page.getByRole('tab', { name: '价格配置' }).click()
  await expect
    .element(page.getByRole('switch', { name: '配置价格' }))
    .not.toBeChecked()
  await page.getByRole('button', { name: '配置', exact: true }).first().click()
  await expect
    .element(page.getByLabelText('输入', { exact: true }))
    .toHaveValue('2')
  await page.getByRole('button', { name: '配置', exact: true }).nth(1).click()
  await page.getByRole('tab', { name: '基本信息' }).click()
  await expect.element(page.getByLabelText('默认维度')).toHaveValue('1024')
  const dialog = page.getByRole('dialog')
  expect(dialog.element().scrollWidth).toBeLessThanOrEqual(
    dialog.element().clientWidth + 1
  )
  await page.screenshot({ path: '__screenshots__/model-operations-narrow.png' })
  await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(captured[0]).toMatchObject({
    name: '多操作模型',
    operations: [
      {
        kind: 'chat',
        enabled: true,
        budget_price: { input: '2', output: '8' },
        bindings: [{ channel_id: 'channel-a' }],
      },
      {
        kind: 'embedding',
        enabled: false,
        budget_price: null,
        bindings: [],
        retrieval: { dimensions: 1024, embedding_space: 'separate-space' },
      },
    ],
  })
})

it.each(['fixed', 'auto'] as const)(
  'edits visible request limits in %s routing without enabling fallback',
  async (mode) => {
    const saved = vi.fn()
    let submitted: Record<string, unknown> | undefined
    const configuredModel = {
      ...model,
      routing: {
        ...(modelInput(values(model)).routing as NonNullable<Model['routing']>),
        mode,
        fallback: false,
      },
      access: {
        enabled: false,
        audience: 'administrators' as const,
        member_ids: [],
        channel_id: mode === 'fixed' ? 'channel-a' : null,
        upstream_id: mode === 'fixed' ? 'upstream-a' : '',
      },
    }
    stubFetch(async (url, init) => {
      if (init?.method === 'PUT') {
        submitted = JSON.parse(String(init.body)) as Record<string, unknown>
        return Response.json({ ...configuredModel, ...submitted, version: 2 })
      }
      if (url.endsWith('/routes')) return Response.json([])
      return Response.json({ items: [], total: 0 })
    })
    await show(
      <ModelEditor model={configuredModel} saved={saved} close={vi.fn()} />
    )
    await page.getByRole('tab', { name: '渠道与路由' }).click()
    await page.getByRole('button', { name: '高级：超时设置' }).click()
    await expect
      .element(page.getByLabelText('连接超时（秒）'))
      .toHaveValue('10')
    await expect
      .element(page.getByLabelText('首个响应等待（秒）'))
      .toHaveValue('180')
    await expect
      .element(page.getByLabelText('输出停滞超时（秒）'))
      .toHaveValue('180')
    await expect
      .element(page.getByLabelText('总时长上限（秒）'))
      .toHaveValue('1800')
    await page.getByLabelText('连接超时（秒）').fill('15')
    await page.getByLabelText('首个响应等待（秒）').fill('300')
    await page.getByLabelText('输出停滞超时（秒）').fill('240')
    await page.getByLabelText('总时长上限（秒）').fill('7200')
    await page.getByRole('button', { name: /^(保存配置|保存草稿)$/ }).click()
    await expect.poll(() => saved.mock.calls.length).toBe(1)
    expect(submitted?.routing).toMatchObject({
      mode,
      fallback: false,
      connect_timeout_seconds: 15,
      first_response_timeout_seconds: 300,
      stream_idle_timeout_seconds: 240,
      total_timeout_seconds: 7200,
    })
    expect(submitted?.operations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          routing: expect.objectContaining({ total_timeout_seconds: 7200 }),
        }),
      ])
    )
  }
)
