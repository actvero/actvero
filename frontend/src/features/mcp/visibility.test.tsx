import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ServiceEditor } from './service-editor'
import type { Service } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'test',
  }),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
const members = Array.from({ length: 25 }, (_, i) => ({
  id: `member-${i}`,
  name: `成员 ${String(i).padStart(2, '0')}`,
  email: `member${i}@example.com`,
  status: 'active',
  role: 'member',
}))
const service: Service = {
  counts: {},
  error: null,
  protocol: '',
  id: 'service',
  name: 'DeepWiki',
  display_name: '',
  icon: '',
  description: '测试服务',
  transport: 'http',
  url: 'https://example.com/mcp',
  auth_mode: 'none',
  audience: 'organization',
  enabled: false,
  version: 1,
  configured: true,
  checked_at: '2026-09-24T00:00:00Z',
}
function mockApi() {
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url.includes('/members')) {
      const params =
        options.method === 'POST'
          ? JSON.parse(String(options.body))
          : Object.fromEntries(new URL('http://test' + url).searchParams)
      const filtered = members.filter(
        (m) =>
          (!params.member_ids || params.member_ids.includes(m.id)) &&
          (!params.q || `${m.name} ${m.email}`.includes(params.q))
      )
      return Response.json({
        items: filtered.slice(
          (Number(params.page) - 1) * 20,
          Number(params.page) * 20
        ),
        total: filtered.length,
        page: Number(params.page),
        page_size: 20,
      })
    }
    return Response.json(service)
  })
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}
async function show(component: ReactNode) {
  await page.viewport(1100, 1000)
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {component}
    </QueryClientProvider>
  )
}
async function scope(value: string) {
  await userEvent.click(page.getByRole('combobox', { name: '可使用成员' }))
  await userEvent.click(page.getByRole('option', { name: value, exact: true }))
}
it('跨页搜索保留选择，已选筛选，切换范围保留草稿并保存', async () => {
  const fetcher = mockApi()
  await show(<ServiceEditor service={service} close={() => {}} />)
  await scope('指定成员')
  await userEvent.click(
    page.getByRole('checkbox', { name: '选择 成员 00', exact: true })
  )
  await userEvent.click(
    page.getByRole('button', { name: '下一页', exact: true })
  )
  await userEvent.click(
    page.getByRole('checkbox', { name: '选择 成员 20', exact: true })
  )
  await userEvent.fill(
    page.getByRole('textbox', { name: '搜索成员' }),
    'member24@'
  )
  await expect.element(page.getByText('共 1 人 · 第 1 / 1 页')).toBeVisible()
  await userEvent.click(
    page.getByRole('button', { name: '选择本页', exact: true })
  )
  await expect.element(page.getByText('已选择 3 人')).toBeVisible()
  await userEvent.fill(page.getByRole('textbox', { name: '搜索成员' }), '')
  await userEvent.click(page.getByRole('tab', { name: '已选成员' }))
  await expect.element(page.getByText('共 3 人 · 第 1 / 1 页')).toBeVisible()
  await scope('仅管理员')
  await scope('指定成员')
  await expect.element(page.getByText('已选择 3 人')).toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '保存配置' }))
  await expect
    .poll(() => fetcher.mock.calls.find(([, o]) => o.method === 'PUT'))
    .toBeTruthy()
  expect(
    JSON.parse(
      String(fetcher.mock.calls.find(([, o]) => o.method === 'PUT')![1].body)
    )
  ).toMatchObject({
    audience: 'selected',
    member_ids: ['member-0', 'member-20', 'member-24'],
  })
})
it('空指定成员阻止提交；仅管理员保存空名单且回填正确', async () => {
  const fetcher = mockApi()
  await show(
    <ServiceEditor
      service={{ ...service, audience: 'selected', member_ids: [] }}
      close={() => {}}
    />
  )
  await expect
    .element(page.getByRole('combobox', { name: '可使用成员' }))
    .toHaveTextContent('仅管理员')
  await scope('指定成员')
  await userEvent.click(page.getByRole('button', { name: '保存配置' }))
  await expect
    .element(page.getByText('请选择至少一名成员，或改为仅管理员'))
    .toBeVisible()
  expect(fetcher.mock.calls.some(([, o]) => o.method === 'PUT')).toBe(false)
  await scope('仅管理员')
  await userEvent.click(page.getByRole('button', { name: '保存配置' }))
  await expect
    .poll(() => fetcher.mock.calls.find(([, o]) => o.method === 'PUT'))
    .toBeTruthy()
  expect(
    JSON.parse(
      String(fetcher.mock.calls.find(([, o]) => o.method === 'PUT')![1].body)
    )
  ).toMatchObject({ audience: 'selected', member_ids: [] })
})
it('本页取消不清空其他页；名单固定高度，窄屏可用', async () => {
  mockApi()
  await show(
    <ServiceEditor
      service={{ ...service, audience: 'selected', member_ids: ['member-24'] }}
      close={() => {}}
    />
  )
  await userEvent.click(
    page.getByRole('button', { name: '选择本页', exact: true })
  )
  await expect.element(page.getByText('已选择 21 人')).toBeVisible()
  await userEvent.click(
    page.getByRole('button', { name: '取消本页选择', exact: true })
  )
  await expect.element(page.getByText('已选择 1 人')).toBeVisible()
  const viewport = document.querySelector('[data-slot="scroll-area-viewport"]')!
  expect(viewport.getBoundingClientRect().height).toBeLessThanOrEqual(300)
  expect(viewport.scrollHeight).toBeGreaterThan(viewport.clientHeight)
  expect(
    page.getByRole('group', { name: '共享给成员', exact: true }).element()
      .scrollTop
  ).toBe(0)
  await expect
    .element(page.getByRole('textbox', { name: '搜索成员' }))
    .toBeVisible()
  await page
    .getByRole('combobox', { name: '可使用成员' })
    .element()
    .scrollIntoView({ block: 'start' })
  await page.screenshot({ path: '/tmp/actvero-visibility-desktop.png' })
  await page.viewport(390, 844)
  await expect
    .element(page.getByRole('textbox', { name: '搜索成员' }))
    .toBeVisible()
  const dialog = page.getByRole('dialog').element()
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await page.screenshot({ path: '/tmp/actvero-visibility-mobile.png' })
})

it('成员查询失败可重试，组织全员保存时清空名单', async () => {
  const fetcher = mockApi()
  fetcher.mockImplementationOnce(async () =>
    Response.json({ error: { message: '成员加载失败' } }, { status: 503 })
  )
  await show(
    <ServiceEditor
      service={{ ...service, audience: 'selected', member_ids: ['member-0'] }}
      close={() => {}}
    />
  )
  await expect.element(page.getByText('成员加载失败')).toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '重试', exact: true }))
  await expect
    .element(page.getByRole('checkbox', { name: '选择 成员 00', exact: true }))
    .toBeChecked()
  expect(fetcher.mock.calls.some(([, o]) => o.method === 'PUT')).toBe(false)
  await userEvent.click(page.getByRole('tab', { name: '已选成员' }))
  await expect.element(page.getByText('共 1 人 · 第 1 / 1 页')).toBeVisible()
  expect(
    document.querySelector('[data-slot="scroll-area-viewport"]')!.clientHeight
  ).toBeLessThan(150)
  document.documentElement.classList.add('dark')
  try {
    await page.screenshot({ path: '/tmp/actvero-visibility-dark.png' })
  } finally {
    document.documentElement.classList.remove('dark')
  }
  await scope('组织全员')
  await userEvent.click(page.getByRole('button', { name: '保存配置' }))
  await expect
    .poll(() => fetcher.mock.calls.find(([, o]) => o.method === 'PUT'))
    .toBeTruthy()
  expect(
    JSON.parse(
      String(fetcher.mock.calls.find(([, o]) => o.method === 'PUT')![1].body)
    )
  ).toMatchObject({ audience: 'organization', member_ids: [] })
})
