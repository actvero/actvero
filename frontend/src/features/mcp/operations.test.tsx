import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { ActivityPage } from './activity-page'
import { ServiceEditor } from './service-editor'
import type { Service } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'organization' },
    user: { id: 'member' },
    csrf: 'test',
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
    <main className='flex flex-col gap-6 p-6'>
      <div className='flex items-center justify-between'>
        <h1>{title}</h1>
        {action}
      </div>
      {children}
    </main>
  ),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
}
const service: Service = {
  id: 'service',
  audience: 'organization',
  auth_mode: 'none',
  display_name: '',
  enabled: false,
  icon: '',
  name: 'DeepWiki',
  description: '公开项目文档',
  transport: 'http',
  url: 'https://example.com/mcp',
  version: 1,
  configured: true,
  checked_at: '2026-09-24T12:00:00Z',
  error: null,
  protocol: '2025-11-25',
  counts: { tools: 3 },
  connection_options: {
    connect_timeout: 5,
    request_timeout: 60,
    total_timeout: 120,
    reset_on_progress: true,
    health_enabled: true,
    health_interval: 90,
  },
}
const item = {
  id: 'record',
  service_id: 'service',
  service_name: 'DeepWiki',
  actor_name: '测试成员',
  category: 'call',
  operation: 'tools',
  capability: 'read_wiki_structure',
  source: 'console',
  result: 'success',
  duration_ms: 1200,
  error_code: '',
  message: '',
  request_id: 'request-001',
  created_at: '2026-09-24T12:00:00Z',
}
it('高级设置回填、限制总超时并随同配置提交', async () => {
  const fetcher = vi.fn(async (_url: string, _options: RequestInit) =>
    Response.json(service)
  )
  vi.stubGlobal('fetch', fetcher)
  const page = await show(<ServiceEditor service={service} close={() => {}} />)
  await userEvent.click(page.getByRole('button', { name: '高级设置' }))
  await expect.element(page.getByLabelText('请求超时（秒）')).toHaveValue(60)
  await expect
    .element(page.getByRole('checkbox', { name: '启用健康检查与自动恢复' }))
    .toBeChecked()
  await userEvent.fill(page.getByLabelText('最大总耗时（秒）'), '30')
  await userEvent.click(page.getByRole('button', { name: '保存配置' }))
  await expect
    .element(page.getByText('最大总耗时不能小于连接超时或请求超时'))
    .toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
  await userEvent.fill(page.getByLabelText('最大总耗时（秒）'), '180')
  await userEvent.click(page.getByRole('button', { name: '保存配置' }))
  await expect.poll(() => fetcher.mock.calls.length).toBe(1)
  expect(
    JSON.parse(String(fetcher.mock.calls[0][1].body)).connection_options
  ).toEqual({ ...service.connection_options, total_timeout: 180 })
})
it('调用记录筛选、分页、详情和请求编号复制', async () => {
  const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  const fetcher = vi.fn(async (url: string) =>
    Response.json(
      url.includes('/activities?')
        ? {
            items: [item],
            total: 21,
            page: new URL('http://test' + url).searchParams.get('page') || 1,
            page_size: 20,
          }
        : { items: [service] }
    )
  )
  vi.stubGlobal('fetch', fetcher)
  const page = await show(<ActivityPage category='call' serviceId='service' />)
  await expect
    .element(page.getByText('read_wiki_structure', { exact: true }))
    .toBeVisible()
  expect(
    fetcher.mock.calls.some(([url]) => url.includes('service_id=service'))
  ).toBe(true)
  await userEvent.click(page.getByRole('button', { name: '下一页' }))
  await expect
    .poll(() => fetcher.mock.calls.some(([url]) => url.includes('page=2')))
    .toBe(true)
  await userEvent.click(page.getByRole('combobox', { name: '筛选结果' }))
  await userEvent.click(page.getByRole('option', { name: '超时', exact: true }))
  await expect
    .poll(() =>
      fetcher.mock.calls.some(
        ([url]) => url.includes('result=timeout') && url.includes('page=1')
      )
    )
    .toBe(true)
  await userEvent.fill(
    page.getByRole('textbox', { name: '搜索记录' }),
    'read_wiki'
  )
  await userEvent.click(page.getByRole('button', { name: '搜索', exact: true }))
  await expect
    .poll(() => fetcher.mock.calls.some(([url]) => url.includes('q=read_wiki')))
    .toBe(true)
  await userEvent.click(page.getByRole('button', { name: '详情' }))
  await expect.element(page.getByRole('dialog')).toBeVisible()
  await expect
    .element(page.getByText('request-001', { exact: true }))
    .toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '复制请求编号' }))
  expect(copy).toHaveBeenCalledWith('request-001')
})
it('连接日志使用独立类别并显示失败与恢复事件', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.includes('/activities?')
          ? {
              items: [
                {
                  ...item,
                  category: 'connection',
                  operation: 'recovered',
                  capability: '',
                  source: 'health',
                },
              ],
              total: 1,
              page: 1,
            }
          : { items: [service] }
      )
    )
  )
  const page = await show(<ActivityPage category='connection' />)
  await expect
    .element(page.getByText('连接恢复', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('后台检查', { exact: true }))
    .toBeVisible()
})
