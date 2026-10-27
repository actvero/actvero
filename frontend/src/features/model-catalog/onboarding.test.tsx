import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ModelEditor } from './model-editor'
import { priceValues, values } from './model-form'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'onboarding' },
    csrf: 'csrf',
  }),
}))
let client: QueryClient
afterEach(async () => {
  await cleanup()
  await client?.cancelQueries()
  client?.clear()
  vi.unstubAllGlobals()
})

async function setup({
  stopped = false,
  missingPrice = false,
  points = 'ready',
} = {}) {
  const draft = values()
  Object.assign(draft, {
    name: '验收模型',
    slug: 'review-chat',
    context_window: '32000',
    max_output: '4000',
  })
  draft.budget_price = {
    ...priceValues(),
    enabled: !missingPrice,
    currency: 'USD',
    input: '1',
    output: '2',
  }
  draft.bindings = [
    {
      channel_id: 'source',
      upstream_id: 'upstream-chat',
      enabled: false,
      price: priceValues(),
      priority: '0',
      weight: '100',
      compatibility_key: '',
      chat_options: {
        reasoning_format: 'openai',
        output_parameter: 'max_completion_tokens',
      },
    },
  ]
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/llm/models') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        writes.push(body)
        return Response.json({ id: 'saved', ...body })
      }
      if (url.includes('/point-prices/preview'))
        return Response.json({ status: points })
      if (url.includes('/channels/source'))
        return Response.json({
          id: 'source',
          name: '来源渠道',
          manual_enabled: !stopped,
          archived: false,
        })
      return Response.json({ items: [], total: 0 })
    })
  )
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const saved = vi.fn()
  await render(
    <QueryClientProvider client={client}>
      <ModelEditor
        initialValues={draft}
        initialNames={{ source: '来源渠道' }}
        close={vi.fn()}
        saved={saved}
      />
    </QueryClientProvider>
  )
  await waitForAnimations()
  return { writes, saved }
}

it('enables the selected source, operation and model together without changing the audience or inventing procurement prices', async () => {
  const { writes, saved } = await setup()
  await page.getByRole('button', { name: '保存并启用' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes).toHaveLength(1)
  expect(writes[0]).toMatchObject({
    access: { enabled: true, audience: 'administrators' },
    operations: [
      {
        kind: 'chat',
        enabled: true,
        channel_id: 'source',
        upstream_id: 'upstream-chat',
        bindings: [{ enabled: true, price: null }],
      },
    ],
  })
})

it('keeps a draft closed and lets a disabled binding be selected as its fixed target', async () => {
  const { writes } = await setup()
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await page.getByRole('combobox', { name: '固定调用渠道' }).click()
  await page
    .getByRole('option', { name: '来源渠道 / upstream-chat（待启用）' })
    .click()
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({
    access: { enabled: false },
    operations: [
      { enabled: false, channel_id: 'source', bindings: [{ enabled: false }] },
    ],
  })
})

it('does not reactivate a globally stopped channel', async () => {
  const { writes } = await setup({ stopped: true })
  await page.getByRole('button', { name: '保存并启用' }).click()
  await expect
    .element(
      page.getByText('渠道“来源渠道”已停用或归档，请在渠道管理中恢复后重试。')
    )
    .toBeVisible()
  expect(writes).toHaveLength(0)
})

it('requires an explicit budget price and keeps unknown cost distinct from free', async () => {
  const { writes } = await setup({ missingPrice: true })
  await page.getByRole('button', { name: '保存并启用' }).click()
  await expect
    .element(
      page.getByText(
        '请先配置成员预算价格。未知价格不能按免费处理；如确实免费，请明确填写 0。'
      )
    )
    .toBeVisible()
  expect(writes).toHaveLength(0)
})

it('does not enable a model until organization point conversion is ready', async () => {
  const { writes } = await setup({ points: 'missing_conversion' })
  await page.getByRole('button', { name: '保存并启用' }).click()
  await expect
    .element(
      page.getByText(
        '成员预算价格尚未完成积分换算，请在价格配置中检查币种与组织积分换算。'
      )
    )
    .toBeVisible()
  expect(writes).toHaveLength(0)
})
