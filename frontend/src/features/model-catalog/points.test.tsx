import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { ModelEditor } from './model-editor'
import type { Model } from './model-form'
import { PointConversionButton } from './point-conversion'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'csrf-test',
  }),
}))
const model: Model = {
  display_order: 0,
  id: 'model',
  name: '团队模型',
  slug: 'team-model',
  kind: 'chat',
  description: '',
  icon: '',
  icon_key: '',
  vendor: '',
  version: 1,
  archived: false,
  bindings: [],
  binding_states: [],
  budget_price: {
    currency: 'USD',
    input: '2',
    output: '8',
    cache_read: '0.2',
    metric: 'tokens',
    unit: 1000000,
    note: '',
  },
  created_at: '2026-09-25T00:00:00Z',
  updated_at: '2026-09-25T00:00:00Z',
}
const rule: Schema['PointConversionView'] = {
  id: 'rule',
  currency: 'USD',
  points_per_currency: '100',
  version: 1,
  created_at: model.created_at,
}
const prices: Schema['PointPrice'] = {
  status: 'ready',
  conversion: rule,
  currency: 'USD',
  unit: 1000000,
  metric: 'tokens',
  rates: {
    input: '200',
    output: '800',
    cache_read: '20',
    cache_write_5m: null,
    cache_write_1h: null,
  },
}
// Existing form/price assertions count writes separately from the new read-only endpoint view.
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
    return handler(url, init)
  })
}
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

it('connects model prices to points, refreshes after configuration, and does not submit the parent model form', async () => {
  let configured = false
  const saved = vi.fn()
  const calls = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/point-conversion')) {
      if (init?.method === 'PUT') {
        expect(JSON.parse(String(init.body))).toEqual({
          currency: 'USD',
          points_per_currency: '100',
          version: 0,
        })
        configured = true
      }
      return Response.json({ conversion: configured ? rule : null })
    }
    if (url.endsWith('/point-prices/preview')) {
      expect(JSON.parse(String(init?.body))).toMatchObject({
        currency: 'USD',
        input: '2',
      })
      return Response.json(
        configured ? prices : { status: 'unconfigured', rates: {} }
      )
    }
    if (url.endsWith('/prices/estimate')) {
      expect(JSON.parse(String(init?.body))).toMatchObject({
        include_points: true,
        usage: { input: 1000, output: 500, cache_read: 2000 },
      })
      return Response.json({
        currency: 'USD',
        total: '0.0064',
        items: [],
        points: { ...prices, total: '0.64' },
      })
    }
    throw new Error('Unexpected request: ' + url)
  })
  stubFetch(calls)
  await show(<ModelEditor model={model} close={vi.fn()} saved={saved} />)
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('button', { name: '积分单价', exact: true }).click()
  await expect
    .element(page.getByText('尚未设置积分换算', { exact: true }))
    .toBeVisible()
  await page.getByRole('button', { name: '积分换算', exact: true }).click()
  await expect
    .element(page.getByLabelText('每 1 单位货币对应积分'))
    .toHaveValue('')
  await page.getByRole('combobox', { name: '计价币种', exact: true }).click()
  await page.getByRole('option', { name: 'USD', exact: true }).click()
  await page.getByLabelText('每 1 单位货币对应积分').fill('100')
  await page.getByRole('button', { name: '保存换算' }).click()
  await expect
    .element(page.getByText('200 积分', { exact: true }))
    .toBeVisible()
  expect(saved).not.toHaveBeenCalled()
  expect(calls.mock.calls.some(([url]) => url.includes('/llm/models/'))).toBe(
    false
  )
  await page.getByRole('button', { name: '费用试算', exact: true }).click()
  await page.getByLabelText('输入 Token', { exact: true }).fill('1000')
  await page.getByLabelText('输出 Token', { exact: true }).fill('500')
  await page.getByLabelText('缓存读取 Token', { exact: true }).fill('2000')
  await page.getByRole('button', { name: '计算费用', exact: true }).click()
  await expect
    .element(page.getByText('积分消耗：0.64 积分（换算版本 1）'))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/model-points-desktop.png' })
})

it('shows a currency mismatch instead of a fabricated zero-point price', async () => {
  stubFetch(
    vi.fn(async () =>
      Response.json({
        status: 'currency_mismatch',
        currency: 'USD',
        conversion: { ...rule, currency: 'CNY' },
        rates: {},
      })
    )
  )
  await show(<ModelEditor model={model} close={vi.fn()} saved={vi.fn()} />)
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('button', { name: '积分单价', exact: true }).click()
  await expect
    .element(page.getByText('计价币种不一致，无法换算积分', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('0 积分', { exact: true }))
    .not.toBeInTheDocument()
})

it('requires an explicit ratio, preserves input on conflict, fits a narrow screen and restores focus', async () => {
  await page.viewport(390, 844)
  let writes = 0
  stubFetch(
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        writes++
        return Response.json(
          { error: { message: '积分换算已被修改，请关闭并重新打开' } },
          { status: 409 }
        )
      }
      return Response.json({ conversion: rule })
    })
  )
  await show(<PointConversionButton />)
  const trigger = page.getByRole('button', { name: '积分换算', exact: true })
  await trigger.click()
  const input = page.getByLabelText('每 1 单位货币对应积分')
  await input.fill('0')
  await page.getByRole('button', { name: '保存换算' }).click()
  expect(writes).toBe(0)
  await input.fill('200')
  await page.getByRole('button', { name: '保存换算' }).click()
  await expect
    .element(
      page.getByText('积分换算已被修改，请关闭并重新打开', { exact: true })
    )
    .toBeVisible()
  await expect.element(input).toHaveValue('200')
  const dialog = page.getByRole('dialog').element()
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await page.screenshot({ path: '__screenshots__/point-conversion-narrow.png' })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect.element(trigger).toHaveFocus()
  expect(writes).toBe(1)
})
