import { useForm } from 'react-hook-form'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { Button } from '@/components/ui/button'
import { Form } from '@/components/ui/form'
import { values, type ModelValues, type PriceKey } from './model-form'
import type { ReferenceModel } from './reference-models'
import { ReferencePicker } from './reference-picker'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-reference-test',
  }),
}))

const quote: ReferenceModel = {
  provider: 'openai',
  provider_name: 'OpenAI',
  model_id: 'priced-model',
  name: '公开报价模型',
  context_window: 128000,
  max_output: 8192,
  capabilities: {
    streaming: 'unknown',
    tools: 'unknown',
    vision: 'unknown',
    structured_output: 'unknown',
    reasoning: 'unknown',
  },
  reasoning_options: [],
  temperature: 'unknown',
  price: {
    metric: 'tokens',
    currency: 'USD',
    unit: 1000000,
    input: '3',
    output: '12',
    note: '',
  },
  price_importable: true,
  price_conditions: [],
  price_notes: [],
}
const complexQuote: ReferenceModel = {
  ...quote,
  price_importable: false,
  price_conditions: ['缓存写入时长未知'],
  quote_snapshot: {
    provider: 'openai',
    model_id: 'priced-model',
    fetched_at: '2026-10-06T00:00:00Z',
    source_updated_at: null,
    currency: 'USD',
    unit: 1000000,
    metric: 'tokens',
    source_url: null,
    raw_cost: {
      input: '3',
      output: '12',
      cache_write: '4',
      unknown_fee: { amount: '0.25' },
    },
    conditions: ['缓存写入时长未知'],
  },
  quote_items: [
    { key: 'input', value: '3', status: 'compatible', reason: '输入可采用' },
    { key: 'output', value: '12', status: 'compatible', reason: '输出可采用' },
    {
      key: 'cache_write',
      value: '4',
      status: 'needs_details',
      reason: '缺少时长',
    },
    {
      key: 'unknown_fee',
      value: '{"amount":"0.25"}',
      status: 'reference_only',
      reason: '仅参考',
    },
  ],
}

const clients: QueryClient[] = []
type PickerConfig = {
  mode?: 'metadata' | 'price'
  initial?: ModelValues
  target?: PriceKey
  channel?: { provider: string; name: string; base_url: string }
  requests?: string[]
  inspect?: (draft: ModelValues) => void
}
function Picker({ initial, target, mode = 'price', inspect }: PickerConfig) {
  const form = useForm<ModelValues>({ defaultValues: initial ?? values() })
  return (
    <Form {...form}>
      <ReferencePicker mode={mode} disabled={false} priceTarget={target} />
      <Button type='button' onClick={() => inspect?.(form.getValues())}>
        读取编辑草稿
      </Button>
    </Form>
  )
}

async function show(
  model: ReferenceModel,
  currency: string,
  config: PickerConfig = {}
) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      config.requests?.push(url)
      if (url.endsWith('/channels/channel-plan') && config.channel)
        return Response.json(config.channel)
      if (url.includes('/reference-models'))
        return Response.json({
          items: [model],
          total: 1,
          page_size: 20,
          fetched_at: '2026-10-04T00:00:00Z',
          stale: false,
          skipped: 0,
        })
      if (url.endsWith('/point-conversion'))
        return Response.json({ conversion: { currency } })
      if (url.endsWith('/reference-price-preview')) {
        expect(init?.method).toBe('POST')
        expect(init?.headers).toMatchObject({
          'X-CSRF-Token': 'csrf-reference-test',
        })
        const body = JSON.parse(String(init?.body)) as {
          target_currency: string
          fx_rate: string
          fx_date: string
        }
        if (body.fx_rate !== '2' || body.fx_date !== '2026-10-06')
          throw new Error('Unexpected FX input')
        return Response.json({
          price: {
            ...model.price,
            currency: body.target_currency,
            input: '6',
            output: '24',
          },
          fx_rate: body.fx_rate,
          fx_date: body.fx_date,
          rounding_notes: [],
        })
      }
      throw new Error('Unexpected request: ' + url)
    })
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <Picker {...config} />
    </QueryClientProvider>
  )
}

afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 900)
})

it('shows complex price conditions but blocks importing their base quote', async () => {
  await show(
    {
      ...quote,
      price_importable: false,
      price_conditions: ['超过阈值后按阶梯计费'],
    },
    'USD'
  )
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  await page.getByRole('tab', { name: '参考报价' }).click()
  await expect
    .element(page.getByText('超过阈值后按阶梯计费', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('可保存原始报价；生效价格需逐项核对'))
    .toBeVisible()
  await expect
    .element(page.getByText(/这份报价暂不能直接导入：超过阈值后按阶梯计费/))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: /预览修改/ }))
    .toBeDisabled()
})

it.each(['复杂报价', '预算币种不符', '采购未确认', '套餐渠道'] as const)(
  '%s does not block explicitly previewing metadata, and preserves every price and binding',
  async (reason) => {
    if (reason === '复杂报价') await page.viewport(390, 844)
    const initial = values()
    initial.name = '已有名称'
    initial.slug = 'local-model'
    initial.budget_price = {
      ...initial.budget_price,
      enabled: true,
      currency: 'CNY',
      input: '5',
      output: '20',
      cache_write_5m: '1',
      note: '原预算备注',
    }
    const procurement = reason === '采购未确认' || reason === '套餐渠道'
    if (procurement)
      initial.bindings.push({
        binding_id: null,
        channel_id: 'channel-plan',
        upstream_id: 'priced-model',
        enabled: true,
        priority: '7',
        weight: '80',
        compatibility_key: '',
        chat_options: {
          reasoning_format: 'openai',
          output_parameter: 'max_completion_tokens',
        },
        price: { ...initial.budget_price, currency: 'USD', note: '原采购备注' },
      })
    const inspect = vi.fn()
    await show(
      reason === '复杂报价'
        ? {
            ...quote,
            price_importable: false,
            price_conditions: ['独立思考费率未适配'],
          }
        : quote,
      reason === '预算币种不符' ? 'CNY' : 'USD',
      {
        initial,
        inspect,
        mode: 'metadata',
        target: procurement ? 'bindings.0.price' : 'budget_price',
        channel: {
          provider: 'openai-compatible',
          name: '采购渠道',
          base_url:
            reason === '套餐渠道'
              ? 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1'
              : 'https://upstream.example.com/v1',
        },
      }
    )
    await page
      .getByRole('button', { name: '从公开资料补全', exact: true })
      .click()
    await page
      .getByRole('button', { name: /公开报价模型 priced-model/ })
      .click()
    await page.getByRole('checkbox', { name: '覆盖已有资料' }).click()
    await page
      .getByRole('checkbox', { name: '导入参考价格', exact: true })
      .click()
    const metadataPreview = page.getByRole('button', { name: /仅预览资料/ })
    await expect.element(metadataPreview).toBeEnabled()
    await metadataPreview.click()
    await expect
      .element(
        page.getByText(
          '本次仅导入模型资料，成员预算价格与渠道采购价格均保持不变。'
        )
      )
      .toBeVisible()
    await expect.element(page.getByText(/价格对象：/)).not.toBeInTheDocument()
    if (reason === '复杂报价') {
      const footer = page
        .getByRole('button', { name: '确认应用到草稿' })
        .element()
        .getBoundingClientRect()
      expect(footer.bottom).toBeLessThanOrEqual(844)
      expect(footer.right).toBeLessThanOrEqual(390)
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
    }
    await page.getByRole('button', { name: '返回调整' }).click()
    await expect
      .element(
        page.getByRole('checkbox', { name: '导入参考价格', exact: true })
      )
      .not.toBeChecked()
    await page.getByRole('button', { name: /预览修改/ }).click()
    await page.getByRole('button', { name: '确认应用到草稿' }).click()
    await page.getByRole('button', { name: '读取编辑草稿' }).click()
    const draft = inspect.mock.calls[0][0] as ModelValues
    expect(draft.name).toBe(quote.name)
    expect(draft.context_window).toBe(String(quote.context_window))
    expect(draft.budget_price).toEqual(initial.budget_price)
    expect(draft.bindings).toEqual(initial.bindings)
    expect(draft.access).toEqual(initial.access)
    expect(draft.routing).toEqual(initial.routing)
  }
)

it('does not offer a metadata escape when no metadata fields were selected', async () => {
  await show({ ...quote, price_importable: false }, 'USD', { mode: 'metadata' })
  await page
    .getByRole('button', { name: '从公开资料补全', exact: true })
    .click()
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  for (const name of [
    '名称、开发方与图标',
    '上下文与输出上限',
    '能力声明与思考参数',
  ])
    await page.getByRole('checkbox', { name }).click()
  await page
    .getByRole('checkbox', { name: '导入参考价格', exact: true })
    .click()
  await expect
    .element(page.getByRole('button', { name: /仅预览资料/ }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: /预览修改/ }))
    .toBeDisabled()
})

it('blocks a USD public quote when the organization budgets in CNY', async () => {
  await show(quote, 'CNY')
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  await expect.element(page.getByText(/组织使用 CNY，报价为 USD/)).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: /预览修改/ }))
    .toBeDisabled()
})

it('blocks purchase-price import for a compatible channel pointing at the Token Plan host', async () => {
  const initial = values()
  initial.bindings.push({
    binding_id: null,
    channel_id: 'channel-plan',
    upstream_id: 'priced-model',
    enabled: true,
    priority: '0',
    weight: '100',
    compatibility_key: '',
    chat_options: {
      reasoning_format: 'openai',
      output_parameter: 'max_completion_tokens',
    },
    price: { ...initial.budget_price },
  })
  await show(quote, 'USD', {
    initial,
    target: 'bindings.0.price',
    channel: {
      provider: 'openai-compatible',
      name: '自定义兼容套餐渠道',
      base_url: 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1',
    },
  })
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  await expect
    .element(
      page.getByText('此渠道使用套餐计费，公开按量报价不能作为套餐采购单价。')
    )
    .toBeVisible()
  await page
    .getByRole('checkbox', {
      name: '已核对该渠道的供应商、套餐和实际采购单价',
    })
    .click()
  await expect
    .element(page.getByRole('button', { name: /预览修改/ }))
    .toBeDisabled()
})

it('switches reference search context between bindings without changing the price target', async () => {
  const initial = values()
  const binding = (upstream_id: string): ModelValues['bindings'][number] => ({
    binding_id: null,
    channel_id: 'channel-plan',
    upstream_id,
    enabled: true,
    priority: '0',
    weight: '100',
    compatibility_key: '',
    chat_options: {
      reasoning_format: 'openai',
      output_parameter: 'max_completion_tokens',
    },
    price: { ...initial.budget_price },
  })
  initial.bindings.push(binding('first-model'), binding('second-model'))
  const requests: string[] = []
  await show(quote, 'USD', {
    initial,
    requests,
    channel: {
      provider: 'openai',
      name: '共享渠道',
      base_url: 'https://api.openai.com/v1',
    },
  })
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await expect
    .element(page.getByRole('textbox', { name: '搜索公开模型' }))
    .toHaveValue('first-model')
  await page.getByRole('combobox', { name: '参考渠道' }).click()
  await page.getByRole('option', { name: '渠道 / second-model' }).click()
  await expect
    .element(page.getByRole('textbox', { name: '搜索公开模型' }))
    .toHaveValue('second-model')
  await expect
    .poll(() =>
      requests.some(
        (url) =>
          url.includes('/reference-models?') &&
          url.includes('q=second-model') &&
          url.includes('preferred_model=second-model')
      )
    )
    .toBe(true)
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  await expect
    .element(page.getByRole('combobox', { name: '导入价格对象' }))
    .toHaveTextContent('成员预算价格')
})

it('saves a complex raw quote without changing either active tariff', async () => {
  const initial = values()
  initial.budget_price = {
    ...initial.budget_price,
    enabled: true,
    currency: 'USD',
    input: '9',
    output: '19',
  }
  const inspect = vi.fn()
  await show(complexQuote, 'USD', { initial, inspect })
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  await expect
    .element(page.getByRole('checkbox', { name: /保存原始参考报价快照/ }))
    .toBeChecked()
  await expect.element(page.getByText(/缓存写入时长未知/).first()).toBeVisible()
  await page.getByRole('button', { name: /仅预览资料与报价/ }).click()
  await expect.element(page.getByText(/参考报价快照/)).toBeVisible()
  await page.getByRole('button', { name: '确认应用到草稿' }).click()
  await page.getByRole('button', { name: '读取编辑草稿' }).click()
  const draft = inspect.mock.calls[0][0] as ModelValues
  expect(draft.budget_price).toEqual(initial.budget_price)
  expect(draft.quote_snapshots[0]?.raw_cost).toEqual(
    complexQuote.quote_snapshot?.raw_cost
  )
})

it('explicitly adopts compatible base rates only for the internal budget tariff', async () => {
  const initial = values()
  initial.budget_price = {
    ...initial.budget_price,
    cache_read: '2',
    cache_write_5m: '5',
  }
  const inspect = vi.fn()
  await show(complexQuote, 'USD', { initial, inspect })
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  await page
    .getByRole('checkbox', { name: /仅采用基础输入\/输出作组织内部预算价/ })
    .click()
  await page.getByRole('button', { name: /预览修改/ }).click()
  await expect.element(page.getByText(/组织内部简化预算价/)).toBeVisible()
  await expect.element(page.getByText('清空（未提供）').first()).toBeVisible()
  await page.getByRole('button', { name: '确认应用到草稿' }).click()
  await page.getByRole('button', { name: '读取编辑草稿' }).click()
  const draft = inspect.mock.calls[0][0] as ModelValues
  expect(draft.budget_price.input).toBe('3')
  expect(draft.budget_price.output).toBe('12')
  expect(draft.budget_price.cache_read).toBe('')
  expect(draft.budget_price.cache_write_5m).toBe('')
  expect(draft.budget_price.note).toContain('内部预算简化价')
  expect(draft.quote_snapshots[0]?.raw_cost).toEqual(
    complexQuote.quote_snapshot?.raw_cost
  )
})

it('requires a server-checked explicit FX rate and date before budget import', async () => {
  const inspect = vi.fn()
  await show({ ...quote, quote_snapshot: complexQuote.quote_snapshot }, 'CNY', {
    inspect,
  })
  await page.getByRole('button', { name: '导入参考价格' }).click()
  await page.getByRole('button', { name: /公开报价模型 priced-model/ }).click()
  await page.getByRole('textbox', { name: '汇率', exact: true }).fill('2')
  await page.getByLabelText('汇率日期').fill('2026-10-06')
  await page.getByRole('button', { name: '核对换算结果' }).click()
  await expect
    .element(page.getByText(/已核对：输入 6、输出 24 CNY/))
    .toBeVisible()
  await page.getByRole('button', { name: /预览修改/ }).click()
  await expect.element(page.getByText(/汇率 2，日期 2026-10-06/)).toBeVisible()
  await page.getByRole('button', { name: '确认应用到草稿' }).click()
  await page.getByRole('button', { name: '读取编辑草稿' }).click()
  const draft = inspect.mock.calls[0][0] as ModelValues
  expect(draft.budget_price.currency).toBe('CNY')
  expect(draft.budget_price.input).toBe('6')
  expect(draft.budget_price.note).toContain('汇率 1 USD = 2 CNY（2026-10-06）')
})

it.each([
  'embedding',
  'rerank',
  'image_generation',
  'speech',
  'transcription',
] as const)(
  'keeps a %s quote as reference without changing its operation tariff',
  async (kind) => {
    const initial = values()
    initial.kind = kind
    initial.budget_price = {
      ...initial.budget_price,
      input: '7',
      output: '',
      metric: kind === 'image_generation' ? 'images' : 'tokens',
    }
    const inspect = vi.fn()
    await show(complexQuote, 'USD', { initial, inspect })
    await page.getByRole('button', { name: '导入参考价格' }).click()
    await page
      .getByRole('button', { name: /公开报价模型 priced-model/ })
      .click()
    await expect
      .element(page.getByText(/生效计量与这份 Token 输入\/输出报价不匹配/))
      .toBeVisible()
    await page.getByRole('button', { name: /仅预览资料与报价/ }).click()
    await page.getByRole('button', { name: '确认应用到草稿' }).click()
    await page.getByRole('button', { name: '读取编辑草稿' }).click()
    const draft = inspect.mock.calls[0][0] as ModelValues
    expect(draft.budget_price).toEqual(initial.budget_price)
    expect(draft.quote_snapshots).toHaveLength(1)
  }
)
