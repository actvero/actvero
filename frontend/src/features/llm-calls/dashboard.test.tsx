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
import type { Schema } from '@/lib/api'
import { OverviewPage } from '@/features/overview/page'
import { LlmUsagePage } from './dashboard-page'
import { readDashboardSearch, readPreferences } from './dashboard-search'
import { readCallSearch } from './search'

const member = '434e8eb9-dc0c-4981-ae77-6aaab6ca3afd'
const model = 'a5d59967-3324-4d20-ae8b-73249f1d2eed'
const channel = '8491f74a-2ef7-4874-a93d-08fc6d60e8fb'
let role = 'administrator'
let tenant = 'organization-one'
const clients: QueryClient[] = []
vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: tenant, name: '测试组织', role },
    user: { id: 'user-one' },
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    children,
    action,
  }: {
    title: string
    children: ReactNode
    action?: ReactNode
  }) => (
    <main className='flex h-dvh min-w-0 flex-col gap-5 overflow-y-auto p-4 sm:p-8'>
      <header className='flex flex-wrap gap-3'>
        <h1>{title}</h1>
        {action}
      </header>
      {children}
    </main>
  ),
}))
const metrics: Schema['MetricBucket'][] = [
  {
    metric: 'tokens',
    field: 'input_tokens',
    sum: '17',
    known_calls: 1,
    unknown_calls: 1,
  },
]
const group: Schema['DashboardGroup'] = {
  key: member,
  name: '成员甲',
  calls: 2,
  successes: 1,
  review: 1,
  settled_points: '1.234567890123',
  metrics,
}
const timeline: Schema['TimeBucket'][] = Array.from(
  { length: 4 },
  (_, index) => ({
    ...group,
    key: String(index),
    name: `时间${index}`,
    calls: index < 2 ? 1 : 0,
    from_time: `2026-10-01T0${index}:00:00Z`,
    to_time: `2026-10-01T0${index + 1}:00:00Z`,
    settled_points: index === 0 ? group.settled_points : '0',
    metrics: [
      {
        ...metrics[0],
        sum: index === 0 ? '17' : '0',
        known_calls: index === 0 ? 1 : 0,
        unknown_calls: index === 1 ? 1 : 0,
      },
    ],
  })
)
const data: Schema['UsageDashboard'] = {
  summary: {
    range: {
      from_time: timeline[0].from_time,
      to_time: timeline[3].to_time,
      timezone: 'UTC',
      as_of: '2026-10-01T04:00:00Z',
    },
    calls: 2,
    attempts: 3,
    result_counts: { success: 1, unknown: 1 },
    settlement_counts: { settled: 1, review: 1 },
    settled_points: group.settled_points ?? null,
    metrics,
    amounts_by_currency: [{ currency: 'USD', amount: '0.0123' }],
    by_operation: [
      {
        key: 'chat',
        name: '对话',
        calls: 2,
        attempts: 3,
        settled_points: group.settled_points ?? null,
      },
    ],
    by_model: [],
    current_held: {
      applicable: true,
      as_of: '2026-10-01T04:00:00Z',
      points: '4',
      scope: {
        member_id: null,
        model_id: null,
        operation: null,
        source: 'member',
      },
    },
  },
  granularity: 'hour',
  timeline,
  members: [group],
  models: [{ ...group, key: model, name: '团队模型' }],
  member_timelines: {},
  member_count: 1,
  other_members: {
    ...group,
    calls: 0,
    settled_points: '0',
    name: '其他成员',
    key: 'other',
  },
  flow: [
    {
      member_id: member,
      member_name: group.name,
      source: 'desktop',
      model_id: model,
      model_name: '团队模型',
      channel_id: channel,
      channel_name: '最终渠道甲',
      calls: 1,
    },
    {
      member_id: member,
      member_name: group.name,
      source: 'desktop',
      model_id: model,
      model_name: '团队模型',
      channel_id: null,
      channel_name: '未确定渠道',
      calls: 1,
    },
  ],
  other_flow_calls: 0,
  performance: {
    average_ms: 1230,
    p95_ms: 1230,
    samples: 1,
    calls: 2,
    rpm: 0.1,
  },
}
const overview: Schema['OrganizationOverview'] = {
  as_of: data.summary.range.as_of,
  models: { total: 8, enabled: 5 },
  channels: { total: 3, enabled: 2 },
  skills: { total: 4, enabled: 1 },
  mcp: { total: 7, enabled: 3 },
  members: { total: 15, enabled: 14 },
  review_calls: 3,
  mcp_calls: 10,
  skill_distributions: 2,
  mcp_checked: 1,
  mcp_failed: 1,
  mcp_unchecked: 1,
  activities: [],
}
const base =
  '/llm-usage?from=2026-10-01T00:00:00Z&to=2026-10-01T04:00:00Z&timezone=UTC'
function defaultResponse(url: string): Response {
  if (url.startsWith('/api/v1/llm/dashboard?')) {
    const params = new URLSearchParams(url.split('?')[1])
    return Response.json({
      ...data,
      member_timelines: params.get('selected_members')
        ? { [member]: timeline }
        : {},
    })
  }
  if (url === '/api/v1/overview') return Response.json(overview)
  if (url === '/api/v1/account/overview')
    return Response.json({
      from_time: data.summary.range.from_time,
      to_time: data.summary.range.to_time,
      calls: 2,
      settled_points: '1.2',
      review_calls: 1,
    })
  if (url === '/api/v1/account/llm/quota')
    return Response.json({ policy: null, status: 'unconfigured', windows: [] })
  if (url.startsWith('/api/v1/account/llm/models?'))
    return Response.json({
      items: [],
      total: 4,
      page: 1,
      page_size: 20,
      has_more: false,
    })
  if (url.startsWith('/api/v1/quota/policies?'))
    return Response.json({ default_timezone: 'Asia/Shanghai', items: [] })
  throw new Error(url)
}
async function show(initial = base, handler = defaultResponse) {
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      requests.push(url)
      return Promise.resolve(handler(url))
    })
  )
  const root = createRootRoute({ component: Outlet })
  const usage = createRoute({
    getParentRoute: () => root,
    path: '/llm-usage',
    validateSearch: readDashboardSearch,
    component: () => <LlmUsagePage search={usage.useSearch()} />,
  })
  const calls = createRoute({
    getParentRoute: () => root,
    path: '/llm-calls',
    validateSearch: readCallSearch,
    component: () => <h1>调用明细</h1>,
  })
  const ov = createRoute({
    getParentRoute: () => root,
    path: '/overview',
    component: OverviewPage,
  })
  const router = createRouter({
    routeTree: root.addChildren([usage, calls, ov]),
    history: createMemoryHistory({ initialEntries: [initial] }),
  })
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { requests, router, client }
}
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.removeItem('actvero:dashboard:v1:organization-one:user-one')
  role = 'administrator'
  tenant = 'organization-one'
  await page.viewport(1440, 1000)
})

it('renders real charts, exact quantities and separate unknown coverage', async () => {
  await show()
  await expect
    .element(page.getByText('用量趋势', { exact: true }))
    .toBeVisible()
  await expect.element(page.getByText('上游尝试 3 次')).toBeVisible()
  await expect
    .poll(() => document.querySelectorAll('.recharts-surface').length)
    .toBeGreaterThan(1)
  await page.screenshot({ path: '__screenshots__/actvero-dashboard-models.png' })
  await page.getByRole('combobox', { name: '统计指标' }).click()
  await page.getByRole('option', { name: '输入 Token', exact: true }).click()
  await page.getByRole('combobox', { name: '图表形式' }).click()
  await page.getByRole('option', { name: '数据表' }).click()
  await expect
    .element(page.getByText('未知用量 1 笔', { exact: false }))
    .toBeVisible()
  await expect
    .element(page.getByText('完整证据 0 笔 · 未知 1 笔'))
    .toBeVisible()
  await expect.element(page.getByText('暂无完整证据')).not.toBeInTheDocument()
})
it('flow conservation and precise known/unknown channel drill preserve range', async () => {
  const { router } = await show(base + '&tab=flow')
  await expect
    .element(page.getByRole('cell', { name: '未确定渠道', exact: true }))
    .toBeVisible()
  await expect
    .poll(() => document.querySelectorAll('.recharts-sankey-links').length)
    .toBeGreaterThan(0)
  await page.screenshot({ path: '__screenshots__/actvero-dashboard-flow.png' })
  const row = page.getByRole('row').filter({
    has: page.getByRole('cell', { name: '最终渠道甲', exact: true }),
  })
  await row.getByRole('button', { name: '看明细' }).click()
  await expect.poll(() => router.state.location.pathname).toBe('/llm-calls')
  const search = router.state.location.search as Record<string, unknown>
  expect(search.channel_id).toBe(channel)
  expect(search.member_id).toBe(member)
  expect(search.source).toBe('desktop')
  expect(search.from).toBe('2026-10-01T00:00:00.000Z')
  await router.navigate({
    to: '/llm-usage',
    search: readDashboardSearch({
      ...readCallSearch({
        from: data.summary.range.from_time,
        to: data.summary.range.to_time,
        timezone: 'UTC',
      }),
      tab: 'flow',
    }),
  })
  await page
    .getByRole('row')
    .filter({
      has: page.getByRole('cell', { name: '未确定渠道', exact: true }),
    })
    .getByRole('button', { name: '看明细' })
    .click()
  await expect
    .poll(
      () =>
        (router.state.location.search as Record<string, unknown>)
          .unknown_channel
    )
    .toBe(true)
})
it('member comparison uses stable IDs and survives URL navigation', async () => {
  const { router, requests } = await show(base + '&tab=members')
  await page.getByRole('button', { name: '比较趋势' }).click()
  await expect
    .poll(
      () =>
        (router.state.location.search as Record<string, unknown>)
          .selected_members
    )
    .toBe(member)
  await expect
    .poll(() =>
      requests.some((url) => url.includes(`selected_members=${member}`))
    )
    .toBe(true)
  await expect
    .element(page.getByText('所选成员趋势', { exact: true }))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/actvero-dashboard-members.png' })
  await page.getByRole('button', { name: '清除比较' }).click()
  await expect
    .element(page.getByText('所选成员趋势', { exact: true }))
    .not.toBeInTheDocument()
})
it('filter draft and cancel leave all charts on original range', async () => {
  const { requests, router } = await show()
  await expect
    .element(page.getByText('用量趋势', { exact: true }))
    .toBeVisible()
  const original = router.state.location.href
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await page.getByRole('button', { name: '近30天' }).click()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  expect(router.state.location.href).toBe(original)
  expect(
    requests.filter((url) => url.includes('/llm/dashboard?'))
  ).toHaveLength(1)
})
it('preferences isolate tenants and handle denied browser storage', async () => {
  localStorage.setItem(
    'actvero:dashboard:v1:organization-one:user-one',
    JSON.stringify({
      days: 30,
      metric: 'points',
      chart: 'table',
      granularity: 'day',
      top: 20,
    })
  )
  expect(readPreferences('actvero:dashboard:v1:other:user-one').days).toBe(7)
  const { router } = await show(base + '&chart=bar')
  await expect
    .element(page.getByText('用量趋势', { exact: true }))
    .toBeVisible()
  expect((router.state.location.search as Record<string, unknown>).chart).toBe(
    'bar'
  )
  await page.getByRole('button', { name: '偏好设置' }).click()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  await page.getByRole('button', { name: '保存偏好' }).click()
  await expect
    .element(page.getByText('浏览器未允许保存偏好，当前看板仍可使用。'))
    .toBeVisible()
})
it('403 refetch clears previous organization data and charts', async () => {
  let forbidden = false
  await show(base, (url) =>
    forbidden
      ? Response.json({ error: { message: '权限已撤销' } }, { status: 403 })
      : defaultResponse(url)
  )
  await expect
    .element(page.getByText('用量趋势', { exact: true }))
    .toBeVisible()
  forbidden = true
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect.element(page.getByText('权限已撤销')).toBeVisible()
  await expect
    .element(page.getByText('用量趋势', { exact: true }))
    .not.toBeInTheDocument()
  expect(document.querySelectorAll('.recharts-surface')).toHaveLength(0)
})
it('390px flow switches to accessible paths without page overflow', async () => {
  await page.viewport(390, 844)
  await show(base + '&tab=flow')
  await expect
    .element(page.getByRole('cell', { name: '未确定渠道', exact: true }))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '__screenshots__/actvero-dashboard-flow-390.png' })
})
it('administrator overview exposes scoped resources and recent24h trend', async () => {
  await show('/overview')
  await expect
    .element(page.getByText('近24小时调用趋势', { exact: true }))
    .toBeVisible()
  await expect.element(page.getByText('5 / 8', { exact: true })).toBeVisible()
  await expect
    .element(page.getByText('技能分发记录代表下载交付，不代表已安装。'))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/actvero-overview-admin.png' })
})
it('member overview requests only personal APIs and handles missing quota', async () => {
  role = 'member'
  const { requests } = await show('/overview')
  await expect
    .element(page.getByText('尚未配置模型额度，请联系组织管理员。'))
    .toBeVisible()
  await expect.element(page.getByText('4 个可见模型')).toBeVisible()
  expect(
    requests.some(
      (url) => url === '/api/v1/overview' || url.includes('/llm/dashboard?')
    )
  ).toBe(false)
  await page.viewport(390, 844)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({
    path: '__screenshots__/actvero-overview-member-390.png',
  })
})
it('overview hides all panels when one organization endpoint loses access', async () => {
  await show('/overview', (url) =>
    url === '/api/v1/overview'
      ? Response.json({ error: { message: '权限已撤销' } }, { status: 403 })
      : defaultResponse(url)
  )
  await expect.element(page.getByText('权限已撤销')).toBeVisible()
  await expect
    .element(page.getByText('近24小时调用趋势', { exact: true }))
    .not.toBeInTheDocument()
})

it('selected members without calls show an empty comparison instead of total trend', async () => {
  await show(base + `&tab=members&selected_members=${member}`, (url) =>
    url.includes('/llm/dashboard?') ? Response.json(data) : defaultResponse(url)
  )
  await expect
    .element(page.getByText('所选成员在当前筛选范围没有调用。'))
    .toBeVisible()
  await expect
    .element(page.getByText('所选成员趋势', { exact: true }))
    .not.toBeInTheDocument()
})

it('800px指标保持单行且只在卡片区域内滚动，最后一项仍可读取', async () => {
  await page.viewport(800, 900)
  await show()
  await expect
    .element(page.getByRole('region', { name: '看板指标' }))
    .toBeVisible()
  const strip = document.querySelector('[aria-label="看板指标"]') as HTMLElement
  const cards = [...strip.querySelectorAll('[data-slot="card"]')]
  expect(
    new Set(cards.map((card) => Math.round(card.getBoundingClientRect().top)))
      .size
  ).toBe(1)
  expect(strip.clientHeight).toBeGreaterThan(100)
  expect(strip.scrollWidth).toBeGreaterThan(strip.clientWidth)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(800)
  strip.scrollLeft = strip.scrollWidth
  await expect.element(page.getByText('当前筛选内的调用')).toBeVisible()
  await page.screenshot({
    path: '__screenshots__/actvero-dashboard-metrics-800.png',
  })
})

it('中等宽度概览指标及资源都保持一行，390px恢复竖排且无溢出', async () => {
  await page.viewport(900, 900)
  await show('/overview')
  await expect
    .element(page.getByRole('region', { name: '概览指标' }))
    .toBeVisible()
  for (const name of ['概览指标', '组织资源']) {
    const strip = document.querySelector(
      `[aria-label="${name}"]`
    ) as HTMLElement
    expect(strip.clientHeight).toBeGreaterThan(80)
    const cards = [...strip.querySelectorAll('[data-slot="card"]')]
    expect(
      new Set(cards.map((card) => Math.round(card.getBoundingClientRect().top)))
        .size
    ).toBe(1)
  }
  await page.screenshot({
    path: '__screenshots__/actvero-overview-metrics-900.png',
  })
  await page.viewport(390, 844)
  const strip = document.querySelector('[aria-label="概览指标"]') as HTMLElement
  const cards = [...strip.querySelectorAll('[data-slot="card"]')]
  expect(
    new Set(cards.map((card) => Math.round(card.getBoundingClientRect().top)))
      .size
  ).toBe(4)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
})
