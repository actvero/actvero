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
import { LlmCallsPage } from './page'
import { readCallSearch } from './search'
import { LlmUsagePage } from './usage-page'

const callId = '69fc6575-7066-4bd1-a4f7-0a8705ee6d71'
const modelId = 'a5d59967-3324-4d20-ae8b-73249f1d2eed'
const memberId = '434e8eb9-dc0c-4981-ae77-6aaab6ca3afd'
const call: Schema['LogicalCallView'] = {
  id: callId,
  created_at: '2026-10-04T00:30:00Z',
  member_id: memberId,
  member_name: '测试成员',
  model_id: modelId,
  model_name: '团队模型',
  operation: 'chat',
  source: 'desktop',
  result_status: 'unknown',
  settlement_status: 'review',
  attempt_count: 1,
  duration_ms: null,
  terminal_reason: 'connection_lost',
  points: null,
  reserved_points: '2',
}
const attempt: Schema['CallAttemptView'] = {
  attempt_id: 'b1c019b2-3353-4517-8f36-8fe6fe9cc82d',
  binding_id: null,
  certainly_unused: false,
  channel_id: null,
  channel_name: '本地模拟渠道',
  channel_version: 4,
  client_terminal: null,
  config_version: 7,
  duration_ms: null,
  error_code: 'connection_lost',
  error_scope: 'transport',
  evidence_version: 1,
  first_output_ms: null,
  number: 1,
  operation: 'chat',
  output_started: true,
  retry_after_seconds: null,
  retry_reason: null,
  retryable_hint: null,
  sent: true,
  started_at: call.created_at,
  status: 'unknown',
  uncertain: true,
  upstream_id:
    'provider/model/long-upstream-identifier-that-must-wrap-within-the-narrow-sheet',
  upstream_status: null,
  upstream_terminal: null,
  usage_evidence: [
    {
      attempt_id: 'b1c019b2-3353-4517-8f36-8fe6fe9cc82d',
      complete: false,
      evidence_version: 1,
      field: 'input_tokens',
      metric: 'tokens',
      phase: 'partial',
      source: 'upstream',
      value: 17,
    },
  ],
}
const detail: Schema['CallDetail'] = {
  call,
  settlement: {
    id: callId,
    status: 'review',
    version: 2,
    points: null,
    reserved_points: '2',
    amount: null,
    reserved_amount: '0.02',
    currency: 'USD',
    ratio: '100',
    created_at: call.created_at,
    settled_at: null,
    budget_price: null,
    conversion_id: null,
    policy: null,
    windows: [],
  },
  attempts: [attempt],
  audits: [],
}
const summary: Schema['UsageSummary'] = {
  range: {
    from_time: '2026-10-01T00:00:00Z',
    to_time: '2026-10-04T00:00:00Z',
    timezone: 'Asia/Shanghai',
    as_of: '2026-10-04T01:00:00Z',
  },
  calls: 1,
  attempts: 1,
  result_counts: { unknown: 1 },
  settlement_counts: { review: 1 },
  settled_points: '3',
  amounts_by_currency: [],
  metrics: [
    {
      metric: 'tokens',
      field: 'input_tokens',
      sum: '0',
      known_calls: 0,
      unknown_calls: 1,
    },
  ],
  by_operation: [
    { key: 'chat', name: '对话', calls: 1, attempts: 1, settled_points: '3' },
  ],
  by_model: [
    {
      key: modelId,
      name: '团队模型',
      calls: 1,
      attempts: 1,
      settled_points: '3',
    },
    {
      key: 'unknown',
      name: '无平台模型',
      calls: 1,
      attempts: 1,
      settled_points: null,
    },
  ],
  current_held: {
    points: '2',
    as_of: '2026-10-04T01:00:00Z',
    applicable: true,
    scope: {
      member_id: memberId,
      model_id: modelId,
      operation: 'chat',
      source: 'desktop',
    },
  },
}

const dashboard: Schema['UsageDashboard'] = {
  summary,
  granularity: 'hour',
  timeline: [],
  members: [],
  models: [],
  member_timelines: {},
  member_count: 0,
  other_members: {
    key: 'other',
    name: '其他成员',
    calls: 0,
    successes: 0,
    review: 0,
    settled_points: '0',
    metrics: [],
  },
  flow: [],
  other_flow_calls: 0,
  performance: {
    average_ms: null,
    p95_ms: null,
    samples: 0,
    calls: 1,
    rpm: 0.1,
  },
}

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    user: { id: 'test-admin' },
    csrf: 'test-csrf',
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    children,
    title,
    description,
    action,
  }: {
    children: ReactNode
    title: string
    description: string
    action: ReactNode
  }) => (
    <main className='flex min-w-0 flex-col gap-5 p-4 sm:p-8'>
      <header>
        <h1>{title}</h1>
        <p>{description}</p>
        {action}
      </header>
      {children}
    </main>
  ),
}))
const clients: QueryClient[] = []
async function show(
  initial = '/llm-calls',
  handler: (url: string) => Response = (url) => {
    if (url.startsWith('/api/v1/quota/policies?'))
      return Response.json({
        items: [],
        total: 0,
        has_default: true,
        enforcement: 'active',
        default_timezone: 'Asia/Shanghai',
      })
    if (url.startsWith('/api/v1/llm/calls?'))
      return Response.json({ items: [call], total: 1, page: 1, page_size: 20 })
    if (url === `/api/v1/llm/calls/${callId}`) return Response.json(detail)
    if (url === `/api/v1/llm/settlements/${callId}/reconciliation`)
      return Response.json(
        { error: { message: '权限已撤销' } },
        { status: 403 }
      )
    if (url.startsWith('/api/v1/llm/dashboard?'))
      return Response.json(dashboard)
    throw new Error(`Unexpected API ${url}`)
  }
) {
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      requests.push(url)
      return Promise.resolve(handler(url))
    })
  )
  const root = createRootRoute({ component: Outlet })
  const calls = createRoute({
    getParentRoute: () => root,
    path: '/llm-calls',
    validateSearch: readCallSearch,
    component: () => <LlmCallsPage search={calls.useSearch()} />,
  })
  const usage = createRoute({
    getParentRoute: () => root,
    path: '/llm-usage',
    validateSearch: readCallSearch,
    component: () => <LlmUsagePage search={usage.useSearch()} />,
  })
  const router = createRouter({
    routeTree: root.addChildren([calls, usage]),
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
  return { requests, router }
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

it('blocks calls when the organization timezone lookup fails and allows retry', async () => {
  let fail = true
  const { requests } = await show('/llm-calls', (url) => {
    if (url.startsWith('/api/v1/quota/policies?')) {
      if (fail)
        return Response.json(
          { error: { message: '策略暂不可用' } },
          { status: 500 }
        )
      return Response.json({
        items: [],
        total: 0,
        has_default: true,
        enforcement: 'active',
        default_timezone: 'Asia/Shanghai',
      })
    }
    if (url.startsWith('/api/v1/llm/calls?'))
      return Response.json({ items: [call], total: 1, page: 1, page_size: 20 })
    throw new Error(url)
  })
  await expect.element(page.getByText('策略暂不可用')).toBeVisible()
  expect(requests.filter((url) => url.includes('/llm/calls?'))).toHaveLength(0)
  fail = false
  await page.getByRole('button', { name: '重试' }).click()
  await expect
    .element(page.getByText('团队模型', { exact: false }).first())
    .toBeVisible()
  expect(requests.find((url) => url.includes('/llm/calls?'))).toContain(
    'timezone=Asia%2FShanghai'
  )
})

it('uses separate result and settlement states and clears the detail after reconciliation access loss', async () => {
  const { requests } = await show()
  await expect.element(page.getByText('结果：未知')).toBeVisible()
  await expect.element(page.getByText('结算：待核对')).toBeVisible()
  await page.screenshot({
    path: '/private/tmp/actvero-g6-03-calls-desktop.png',
  })
  await page.getByRole('button', { name: '查看详情' }).click()
  await expect
    .element(page.getByText('历史预占 2 积分', { exact: false }))
    .toBeVisible()
  expect(requests).toContain(`/api/v1/llm/calls/${callId}`)
  await page.getByRole('button', { name: '核对用量' }).click()
  await expect.element(page.getByText('权限已撤销')).toBeVisible()
  await expect
    .element(page.getByText('历史预占 2 积分', { exact: false }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '查看详情' }))
    .not.toBeInTheDocument()
})

it('keeps an explicitly cleared list range empty instead of silently restoring seven days', async () => {
  await page.viewport(390, 844)
  const { requests } = await show()
  await expect
    .element(page.getByRole('button', { name: '查看详情' }))
    .toBeVisible()
  await page.getByRole('button', { name: '筛选调用' }).click()
  let sheet = page.getByRole('dialog', { name: '筛选调用' })
  await sheet.getByLabelText('开始时间').fill('2026-10-01T00:00')
  await sheet.getByLabelText('结束时间（不包含）').fill('2026-10-02T00:00')
  await sheet.getByRole('button', { name: '应用筛选' }).click()
  await expect
    .poll(() =>
      requests.some(
        (url) => url.includes('/llm/calls?') && url.includes('from=')
      )
    )
    .toBe(true)
  await page.getByRole('button', { name: '筛选调用' }).click()
  sheet = page.getByRole('dialog', { name: '筛选调用' })
  await sheet.getByLabelText('开始时间').fill('')
  await sheet.getByLabelText('结束时间（不包含）').fill('')
  await sheet.getByRole('button', { name: '应用筛选' }).click()
  await expect
    .poll(() =>
      [...requests].reverse().find((url) => url.includes('/llm/calls?'))
    )
    .toContain('timezone=Asia%2FShanghai')
  const latest =
    [...requests].reverse().find((url) => url.includes('/llm/calls?')) ?? ''
  expect(latest).not.toContain('from=')
  expect(latest).not.toContain('to=')
})

it('keeps current held scope and exact summary instants in drill-down while unknown usage stays unknown', async () => {
  await page.viewport(1440, 1000)
  const { router, requests } = await show(
    '/llm-usage?source=desktop&from=2026-10-01T00:00:00Z&to=2026-10-04T00:00:00Z'
  )
  await expect
    .element(page.getByText('暂无完整证据', { exact: false }))
    .toBeVisible()
  await expect.element(page.getByText('已确认小计 0')).not.toBeInTheDocument()
  await page.screenshot({
    path: '/private/tmp/actvero-g6-03-usage-desktop.png',
  })
  await page.getByRole('button', { name: '看占用明细' }).click()
  await expect.poll(() => router.state.location.pathname).toBe('/llm-calls')
  const held = [...requests]
    .reverse()
    .find((url) => url.includes('/llm/calls?'))
  expect(held).toContain('source=desktop')
  expect(held).toContain('held=true')
  expect(held).not.toContain('from=')
  expect(held).not.toContain('settlement_status=')
  expect(held).not.toContain('result_status=')
  await router.navigate({
    to: '/llm-usage',
    search: readCallSearch({
      source: 'desktop',
      from: '2026-10-01T00:00:00Z',
      to: '2026-10-04T00:00:00Z',
    }),
  })
  await expect
    .element(page.getByRole('region', { name: '按操作' }))
    .toBeVisible()
  await page
    .getByRole('region', { name: '按操作' })
    .getByRole('button', { name: /看明细/ })
    .click()
  await expect.poll(() => router.state.location.pathname).toBe('/llm-calls')
  const drill = [...requests]
    .reverse()
    .find((url) => url.includes('/llm/calls?'))
  expect(drill).toContain('from=2026-10-01T00%3A00%3A00.000Z')
  expect(drill).toContain('to=2026-10-04T00%3A00%3A00.000Z')
  expect(drill).toContain('operation=chat')
})

it('blocks summary on timezone lookup failure and renders a narrow list and detail without overflow', async () => {
  let fail = true
  const { requests } = await show('/llm-usage', (url) => {
    if (url.startsWith('/api/v1/quota/policies?')) {
      if (fail)
        return Response.json(
          { error: { message: '默认时区读取失败' } },
          { status: 500 }
        )
      return Response.json({
        items: [],
        total: 0,
        has_default: false,
        enforcement: 'active',
        default_timezone: null,
      })
    }
    if (url.startsWith('/api/v1/llm/dashboard?'))
      return Response.json({
        ...dashboard,
        summary: { ...summary, range: { ...summary.range, timezone: 'UTC' } },
      })
    if (url.startsWith('/api/v1/llm/calls?'))
      return Response.json({ items: [call], total: 1, page: 1, page_size: 20 })
    if (url === `/api/v1/llm/calls/${callId}`) return Response.json(detail)
    throw new Error(url)
  })
  await expect
    .element(page.getByText('默认时区读取失败', { exact: true }))
    .toBeVisible()
  expect(requests.filter((url) => url.includes('/dashboard?'))).toHaveLength(0)
  fail = false
  await page.getByRole('button', { name: '重试' }).click()
  await expect
    .element(page.getByText('UTC（组织未配置默认周策略时区', { exact: false }))
    .toBeVisible()
  await page.viewport(390, 844)
  await page.screenshot({ path: '/private/tmp/actvero-g6-03-usage-390.png' })
  await page.getByRole('link', { name: '调用记录' }).click()
  await expect
    .element(page.getByRole('button', { name: '查看详情' }))
    .toBeVisible()
  await page.screenshot({ path: '/private/tmp/actvero-g6-03-calls-390.png' })
  await page.getByRole('button', { name: '查看详情' }).click()
  await expect
    .element(page.getByText('历史预占 2 积分', { exact: false }))
    .toBeVisible()
  await expect
    .poll(
      () =>
        page
          .getByRole('dialog', { name: '调用详情' })
          .element()
          .getBoundingClientRect().left
    )
    .toBeLessThanOrEqual(1)
  await page.screenshot({ path: '/private/tmp/actvero-g6-03-detail-390.png' })
  const detailBody = page
    .getByRole('dialog', { name: '调用详情' })
    .element()
    .querySelector('.overflow-y-auto') as HTMLElement
  detailBody.scrollTop = detailBody.scrollHeight
  await expect
    .element(page.getByText('请求已发送，缺少完整终止证据', { exact: false }))
    .toBeVisible()
  await expect
    .element(page.getByText('输入 Token：17', { exact: false }))
    .toBeVisible()
  await page.screenshot({ path: '/private/tmp/actvero-g6-03-attempt-390.png' })
  const width = document.documentElement.scrollWidth
  expect(width).toBeLessThanOrEqual(390)
})
