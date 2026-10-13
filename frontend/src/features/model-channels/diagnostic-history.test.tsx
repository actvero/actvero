import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ChannelTestHistory } from './channel-test-history'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
  }),
}))
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
async function show() {
  return render(
    <QueryClientProvider client={client}>
      <ChannelTestHistory
        id='channel-a'
        revision={1}
        busy={false}
        initialOpen
      />
    </QueryClientProvider>
  )
}
const record = {
  request_id: 'a684b678-0cfc-430a-a08d-e15c57ce520f',
  model: 'vendor-model',
  operation: 'speech',
  tested_at: '2026-10-04T00:00:00Z',
  status: 'unconfirmed',
  channel_version: 2,
  stale: true,
  uncertain: true,
  record_version: 'legacy_audit',
  health_certification: 'not_requested',
  attempt: null,
}

it('filters on the server and resets pagination after each filter', async () => {
  const paths: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      paths.push(url)
      return Response.json(
        Array.from({ length: 20 }, (_, i) => ({
          ...record,
          request_id: record.request_id + i,
        }))
      )
    })
  )
  const screen = await show()
  await expect
    .element(screen.getByText('vendor-model · 语音合成').first())
    .toBeVisible()
  await screen.getByRole('button', { name: '下一页' }).click()
  await expect.poll(() => paths[paths.length - 1]).toContain('page=2')
  await screen.getByRole('combobox', { name: '操作' }).click()
  await page.getByRole('option', { name: '语音合成', exact: true }).click()
  await expect
    .poll(() => paths[paths.length - 1])
    .toContain('page=1&operation=speech')
  await screen.getByRole('combobox', { name: '结果' }).click()
  await page.getByRole('option', { name: '结果未确认', exact: true }).click()
  await expect
    .poll(() => paths[paths.length - 1])
    .toContain('status=unconfirmed')
  await screen.getByLabelText('配置版本').fill('2')
  await screen.getByRole('button', { name: '筛选版本' }).click()
  await expect
    .poll(() => paths[paths.length - 1])
    .toContain('channel_version=2')
  const count = paths.length
  await screen.getByLabelText('配置版本').fill('-2')
  await screen.getByRole('button', { name: '筛选版本' }).click()
  await expect
    .element(screen.getByText('请输入正整数版本号，留空查看全部。'))
    .toBeVisible()
  expect(paths.length).toBe(count)
})

it('opens legacy metadata at narrow width without replaying expired media', async () => {
  await page.viewport(390, 844)
  const paths: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      expect(options?.method ?? 'GET').toBe('GET')
      paths.push(url)
      return Response.json(
        url.includes('/diagnostics/')
          ? { channel_id: 'channel-a', record, media_available: false }
          : [record]
      )
    })
  )
  const screen = await show()
  await screen.getByRole('button', { name: '查看结果' }).click()
  await expect
    .element(page.getByRole('dialog', { name: '测试结果详情' }))
    .toBeVisible()
  await expect
    .element(
      page.getByText(
        '历史媒体已过期。这里只保存测试元数据，无法重新预览或下载。'
      )
    )
    .toBeVisible()
  await expect
    .element(page.getByText('此记录只有历史审计信息，没有完整的执行阶段证据。'))
    .toBeVisible()
  expect(
    paths.some((url) => url.endsWith('/diagnostics/' + record.request_id))
  ).toBe(true)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await Promise.all(
    document.getAnimations().map((animation) => animation.finished)
  )
  await page.screenshot({ path: '/private/tmp/actvero-g5-history-mobile.png' })
})

it('hides cached history and blocks refresh after detail permission is revoked', async () => {
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(url)
      return url.includes('/diagnostics/')
        ? Response.json({ error: { message: '无管理权限' } }, { status: 403 })
        : Response.json([record])
    })
  )
  const screen = await show()
  await screen.getByRole('button', { name: '查看结果' }).click()
  await expect
    .element(page.getByRole('dialog').getByRole('alert'))
    .toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: 'Close' }).click()
  await expect
    .element(screen.getByRole('button', { name: '刷新记录' }))
    .toBeDisabled()
  await expect
    .element(page.getByText('vendor-model · 语音合成'))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '下一页' }))
    .toBeDisabled()
  expect(requests).toHaveLength(2)
})

it('shows complete attempt metadata and certification without stored outputs', async () => {
  const current = {
    ...record,
    operation: 'chat',
    status: 'success',
    record_version: 'attempt_v1',
    uncertain: false,
    health_certification: 'certified',
    attempt: {
      sent: true,
      output_started: true,
      upstream_terminal: true,
      client_terminal: null,
      usage_evidence: [
        { field: 'input_tokens', value: 0, source: 'upstream', complete: true },
      ],
    },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.includes('/diagnostics/')
          ? { channel_id: 'channel-a', record: current, media_available: false }
          : [current]
      )
    )
  )
  const screen = await show()
  await screen.getByRole('button', { name: '查看结果' }).click()
  await expect.element(page.getByText('绑定健康已认证')).toBeVisible()
  await expect
    .element(page.getByText('输入 Token：0 · 上游原始 · 完整'))
    .toBeVisible()
  await expect.element(page.getByText('客户端交付：未确认')).toBeVisible()
  await Promise.all(
    document.getAnimations().map((animation) => animation.finished)
  )
  await page.screenshot({ path: '/private/tmp/actvero-g5-history-desktop.png' })
})

it('distinguishes a streaming receipt from a legacy record with unknown mode', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json([
        {
          ...record,
          request_id: 'stream-id',
          operation: 'chat',
          stream: true,
          record_version: 'attempt_v1',
        },
        { ...record, request_id: 'legacy-id', stream: null },
      ])
    )
  )
  const screen = await show()
  await expect
    .element(screen.getByText('流式测试', { exact: true }))
    .toBeVisible()
  expect(
    screen.getByText('非流式测试', { exact: true }).elements()
  ).toHaveLength(0)
})
