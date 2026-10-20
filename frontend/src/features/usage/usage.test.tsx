import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { navigation } from '@/components/layout/data/sidebar-data'
import { MyUsagePage } from './page'
import { QuotaWindow } from './quota-windows'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'self' },
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
      <div className='flex flex-wrap items-end justify-between gap-4'>
        <h1>{title}</h1>
        {action}
      </div>
      {children}
    </main>
  ),
}))
const clients: QueryClient[] = []
async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  const root = createRootRoute({ component: Outlet })
  const usage = createRoute({
    getParentRoute: () => root,
    path: '/my-usage',
    component: () => <>{component}</>,
  })
  const models = createRoute({
    getParentRoute: () => root,
    path: '/my-models',
    component: () => <h1>可用模型</h1>,
  })
  const keys = createRoute({
    getParentRoute: () => root,
    path: '/my-access-keys',
    component: () => <h1>访问密钥</h1>,
  })
  const router = createRouter({
    routeTree: root.addChildren([usage, models, keys]),
    history: createMemoryHistory({ initialEntries: ['/my-usage'] }),
  })
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
afterEach(async () => {
  await cleanup()
  clients.forEach((c) => c.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.documentElement.classList.remove('dark')
  await page.viewport(1280, 900)
})
const hour = {
  rule: { kind: 'fixed_hours', hours: 5, points: '100' },
  used: '12',
  reserved: '3',
  remaining: '85',
  started_at: '2026-09-25T00:00:00Z',
  resets_at: '2026-09-25T05:00:00Z',
}
const quota = {
  status: 'active',
  policy: { name: '研发额度' },
  windows: [
    hour,
    {
      ...hour,
      rule: { kind: 'calendar_week', points: '500' },
      remaining: '485',
    },
  ],
}
const entry = {
  id: 'request',
  member_id: 'self',
  member_name: '成员',
  model_name: '团队对话',
  kind: 'chat',
  metric: 'tokens',
  status: 'settled',
  result_status: 'success',
  settlement_status: 'settled',
  terminal_reason: null,
  version: 1,
  points: '0.00005156',
  reserved_points: '0',
  usage: { input_tokens: 25, output_tokens: 3 },
  created_at: '2026-09-25T00:00:00Z',
  settled_at: '2026-09-25T00:00:01Z',
  reason: '',
}

it('offers personal usage to members and shows only personal API results with usable progress', async () => {
  expect(
    navigation(false).find((g) => g.title === '个人')?.items
  ).toContainEqual(
    expect.objectContaining({ title: '我的用量', url: '/my-usage' })
  )
  let refreshed = false
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      if (url.endsWith('/account/llm/quota'))
        return Response.json(
          refreshed
            ? { ...quota, windows: [{ ...hour, remaining: '80', used: '17' }] }
            : quota
        )
      if (url.includes('/account/llm/usage?'))
        return Response.json({ items: [entry], total: 1 })
      throw new Error(url)
    })
  )
  await page.viewport(1440, 900)
  await show(<MyUsagePage />)
  await expect
    .element(page.getByRole('progressbar', { name: '5 小时剩余额度' }))
    .toHaveAttribute('aria-valuenow', '85')
  await expect
    .element(page.getByRole('progressbar', { name: '每周剩余额度' }))
    .toHaveAttribute('aria-valuenow', '97')
  await expect.element(page.getByText('当前策略 · 研发额度')).toBeVisible()
  await expect
    .element(page.getByText('团队对话', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('已记录数量，来源未记录').first())
    .toBeVisible()
  await page.getByLabelText('0.00005156 积分', { exact: true }).first().hover()
  await expect
    .element(page.getByRole('tooltip'))
    .toHaveTextContent('0.00005156 积分')
  await page.getByRole('heading', { name: '我的用量' }).hover()
  await page.screenshot({ path: '__screenshots__/my-usage-desktop.png' })
  await page.getByRole('combobox', { name: '结算状态' }).click()
  await page.getByRole('option', { name: '待核对', exact: true }).click()
  await expect
    .poll(() => calls.some((u) => u.includes('state=review')))
    .toBe(true)
  refreshed = true
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect
    .element(page.getByRole('progressbar', { name: '5 小时剩余额度' }))
    .toHaveAttribute('aria-valuenow', '80')
})

it('distinguishes confirmed, unattributed, and missing usage quantities', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url.endsWith('/quota')
        ? Response.json(quota)
        : Response.json({
            items: [
              {
                ...entry,
                id: 'raw',
                usage: { source: 'upstream', input: 12, output: 8 },
              },
              {
                ...entry,
                id: 'unattributed',
                usage: { source: 'unknown', input: 12, output: 8 },
              },
              { ...entry, id: 'missing', usage: { source: 'unknown' } },
            ],
            total: 3,
          })
    )
  )
  await show(<MyUsagePage />)
  await expect.element(page.getByText('已记录用量证据').first()).toBeVisible()
  await expect
    .element(page.getByText('已记录数量，来源待确认').first())
    .toBeVisible()
  await expect.element(page.getByText('用量未知').first()).toBeVisible()
})

it('keeps result and settlement independent, hides internal reasons, and clears old data after access loss', async () => {
  const review = {
    ...entry,
    id: 'review-call',
    status: 'review',
    result_status: 'success',
    settlement_status: 'review',
    terminal_reason: 'secret_channel_credential',
    reason: '管理员内部核对依据 SECRET',
    points: null,
    reserved_points: '7',
    usage: { source: 'unknown' },
  }
  let revoked = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/account/llm/quota')) return Response.json(quota)
      if (url.includes('/account/llm/usage?'))
        return revoked
          ? Response.json(
              { error: { message: '成员权限已失效' } },
              { status: 403 }
            )
          : Response.json({ items: [review], total: 1 })
      throw new Error(url)
    })
  )
  await page.viewport(390, 844)
  await show(<MyUsagePage />)
  await expect.element(page.getByText('结果：成功').last()).toBeVisible()
  await expect.element(page.getByText('结算：待核对').last()).toBeVisible()
  await expect
    .element(page.getByText('占用', { exact: false }).last())
    .toBeVisible()
  await expect.element(page.getByText('用量未知').last()).toBeVisible()
  await expect.element(page.getByText('终止原因待确认').last()).toBeVisible()
  await expect
    .element(page.getByText('SECRET', { exact: false }))
    .not.toBeInTheDocument()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '__screenshots__/actvero-g6-04-usage-390.png' })
  revoked = true
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect.element(page.getByText('成员权限已失效')).toBeVisible()
  await expect
    .element(page.getByText('结果：成功').first())
    .not.toBeInTheDocument()
  await expect
    .element(page.getByText('当前策略 · 研发额度'))
    .not.toBeInTheDocument()
})

it('keeps zero limits, small balances and reservations explicit in narrow and dark layouts', async () => {
  await page.viewport(390, 844)
  document.documentElement.classList.add('dark')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url.endsWith('/quota')
        ? Response.json({
            ...quota,
            windows: [
              {
                ...hour,
                rule: { ...hour.rule, points: '0' },
                remaining: '0',
                used: '0',
                reserved: '3',
              },
              {
                ...hour,
                rule: { kind: 'calendar_week', points: '1' },
                remaining: '0.99994844',
                used: '0.00005156',
                reserved: '0',
              },
            ],
          })
        : Response.json({ items: [], total: 0 })
    )
  )
  await show(<MyUsagePage />)
  await expect.element(page.getByText('零额度')).toBeVisible()
  await expect
    .element(page.getByRole('progressbar', { name: '5 小时剩余额度' }))
    .toHaveAttribute('aria-valuenow', '0')
  await expect.element(page.getByText('剩余 > 99.9%')).toBeVisible()
  await expect.element(page.getByText('≈ 0.9999')).toBeVisible()
  await expect.element(page.getByText('暂无调用记录').last()).toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '__screenshots__/my-usage-narrow-dark.png' })
})

it('distinguishes missing policies from zero balance and supports retry without fake values', async () => {
  let failed = true
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/quota'))
        return failed
          ? Response.json(
              { error: { message: '额度读取失败' } },
              { status: 503 }
            )
          : Response.json({ status: 'unconfigured', policy: null, windows: [] })
      return Response.json({ items: [], total: 0 })
    })
  )
  await show(<MyUsagePage />)
  await expect.element(page.getByText('额度读取失败')).toBeVisible()
  failed = false
  await page.getByRole('button', { name: '重试' }).click()
  await expect
    .element(page.getByText('尚未配置额度策略，请联系管理员。'))
    .toBeVisible()
  await expect.element(page.getByRole('progressbar')).not.toBeInTheDocument()
})

it('shows first-use timing and clamps overspent windows without dividing by zero', async () => {
  await show(
    <QuotaWindow
      window={{
        ...hour,
        used: '101',
        remaining: '0',
        reserved: '0',
        started_at: null,
        resets_at: null,
      }}
    />
  )
  await expect.element(page.getByText('首次使用后起算')).toBeVisible()
  await expect
    .element(page.getByRole('progressbar'))
    .toHaveAttribute('aria-valuenow', '0')
  await expect.element(page.getByLabelText('101 积分')).toBeVisible()
})

it('renders three independent quota windows in three desktop columns and stacks them on narrow screens', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.endsWith('/quota')
          ? {
              ...quota,
              windows: [
                hour,
                {
                  ...hour,
                  rule: { kind: 'fixed_hours', hours: 24, points: '200' },
                  remaining: '185',
                },
                quota.windows[1],
              ],
            }
          : { items: [], total: 0 }
      )
    )
  )
  await page.viewport(1440, 900)
  await show(<MyUsagePage />)
  await expect
    .element(page.getByRole('progressbar', { name: '24 小时剩余额度' }))
    .toHaveAttribute('aria-valuenow', '92.5')
  await expect
    .element(page.getByRole('progressbar', { name: '每周剩余额度' }))
    .toHaveAttribute('aria-valuenow', '97')
  const bars = () =>
    Array.from(document.querySelectorAll('[role="progressbar"]')).map((el) =>
      el.getBoundingClientRect()
    )
  expect(bars()).toHaveLength(3)
  expect(new Set(bars().map((r) => Math.round(r.top))).size).toBe(1)
  await page.screenshot({ path: '__screenshots__/my-usage-three-windows.png' })
  await page.viewport(390, 844)
  await expect
    .poll(() => new Set(bars().map((r) => Math.round(r.top))).size)
    .toBe(3)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
})
