/** Read-only browser fixtures with real router navigation; never mounted in the app. */
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
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import catalog from '../../../../backend/app/modules/skills/assets/icons.json'
import { SkillsPage } from './page'
import type { Skill } from './shared'
import { categories } from './test-data/categories'

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
    <main className='flex min-w-0 flex-col gap-6 p-6 sm:p-8'>
      <div className='flex flex-wrap items-end justify-between gap-4'>
        <div>
          <h1 className='text-2xl font-bold'>{title}</h1>
          <p className='text-muted-foreground'>{description}</p>
        </div>
        {action}
      </div>
      {children}
    </main>
  ),
}))
afterEach(() => {
  document.documentElement.classList.remove('dark')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const skills: Skill[] = ['文档整理', '周报生成', '表格清理'].map((name, i) => ({
  id: `skill-${i}`,
  name: ['document-summary', 'weekly-report', 'sheet-cleaner'][i],
  category: 'office',
  category_name: '办公协同',
  display_name: name,
  icon:
    i === 0
      ? {
          source: 'library',
          image: catalog.items[0].image,
          sha256: 'fixture-icon',
        }
      : { source: 'fallback', image: '', sha256: '' },
  description: [
    '将长文档整理为带来源的摘要，保留关键结论和待办事项。',
    '整理本周进展与下周计划，生成可直接使用的团队周报。',
    '识别表格中的重复项和格式差异，生成清理建议。',
  ][i],
  audience: i === 0 ? 'organization' : i === 1 ? 'administrators' : 'selected',
  member_ids: [],
  revision: 1,
  default_version_id: i === 0 ? 'version-0' : null,
  downloads: 0,
  created_at: '2026-09-24T00:00:00Z',
  versions: [
    {
      id: `version-${i}`,
      version: '1.0.0',
      status: i === 0 ? 'published' : i === 1 ? 'draft' : 'withdrawn',
      package_icon: '',
      icon_warning: '',
      release_notes: '',
      uploader_name: '测试管理员',
      sha256: 'test',
      size: 2000,
      files: [],
      created_at: '2026-09-24T00:00:00Z',
      published_at: i === 0 ? '2026-09-24T00:00:00Z' : null,
    },
  ],
}))

async function show(items = skills) {
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url === '/api/v1/skills/categories') return Response.json(categories)
    if (options.method !== 'GET' || !url.startsWith('/api/v1/skills?'))
      throw new Error('Unexpected request')
    const params = new URL(url, location.origin).searchParams
    const filtered = items.filter(
      (skill) =>
        skill.display_name.includes(params.get('q') || '') &&
        (!params.get('status') ||
          (params.get('status') === 'published') ===
            !!skill.default_version_id) &&
        (!params.get('audience') ||
          skill.audience === params.get('audience')) &&
        (!params.get('category') || skill.category === params.get('category'))
    )
    const current = Number(params.get('page') || 1)
    return Response.json({
      items: filtered.slice((current - 1) * 20, current * 20),
      total: filtered.length,
      page: current,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const root = createRootRoute({ component: Outlet })
  const list = createRoute({
    getParentRoute: () => root,
    path: '/skills',
    component: SkillsPage,
  })
  const detail = createRoute({
    getParentRoute: () => root,
    path: '/skills/$skillId',
    component: () => <h1>技能详情</h1>,
  })
  const router = createRouter({
    routeTree: root.addChildren([list, detail]),
    history: createMemoryHistory({ initialEntries: ['/skills'] }),
  })
  await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  await expect.element(page.getByRole('table')).toBeVisible()
  return { router, fetcher }
}

it('整行和整卡打开正确技能，标题保留原生键盘链接，视图切换不写入', async () => {
  await page.viewport(1440, 1000)
  const { router, fetcher } = await show()
  await expect
    .element(page.getByRole('button', { name: '管理', exact: true }))
    .not.toBeInTheDocument()
  await page.screenshot({
    path: '../../../../.local/skills-qa/list-clickable.png',
  })
  // Click a non-link cell, then verify the real router changed to the row's detail.
  await userEvent.click(
    page.getByRole('cell', { name: '组织全员', exact: true })
  )
  await expect
    .poll(() => router.state.location.pathname)
    .toBe('/skills/skill-0')
  await router.navigate({ to: '/skills' })
  const title = page.getByRole('link', { name: '周报生成', exact: true })
  await expect.element(title).toHaveAttribute('href', '/skills/skill-1')
  title.element().focus()
  await userEvent.keyboard('{Enter}')
  await expect
    .poll(() => router.state.location.pathname)
    .toBe('/skills/skill-1')
  await router.navigate({ to: '/skills' })
  await userEvent.click(page.getByRole('tab', { name: '卡片', exact: true }))
  await expect.element(page.getByRole('table')).not.toBeInTheDocument()
  await expect
    .element(page.getByRole('link', { name: '查看技能：表格清理' }))
    .toHaveAttribute('href', '/skills/skill-2')
  await page.screenshot({
    path: '../../../../.local/skills-qa/cards-desktop.png',
  })
  await userEvent.click(page.getByText(skills[2].description, { exact: true }))
  await expect
    .poll(() => router.state.location.pathname)
    .toBe('/skills/skill-2')
  expect(
    fetcher.mock.calls.every(([, options]) => options.method === 'GET')
  ).toBe(true)
})

it('切换保留服务器分页、搜索和范围状态，过滤无结果可清空', async () => {
  await page.viewport(1200, 900)
  const items = Array.from({ length: 23 }, (_, i) => ({
    ...skills[0],
    id: `entry-${i}`,
    display_name: `周报技能 ${i + 1}`,
  }))
  const { fetcher } = await show(items)
  await userEvent.click(page.getByRole('combobox', { name: '发布状态' }))
  await userEvent.click(
    page.getByRole('option', { name: '生效中', exact: true })
  )
  await userEvent.click(page.getByRole('combobox', { name: '使用范围' }))
  await userEvent.click(
    page.getByRole('option', { name: '组织全员', exact: true })
  )
  await userEvent.fill(page.getByRole('textbox', { name: '搜索技能' }), '周报')
  await expect
    .poll(() =>
      fetcher.mock.calls.some(([url]) => url.includes('q=%E5%91%A8%E6%8A%A5'))
    )
    .toBe(true)
  await userEvent.click(page.getByRole('button', { name: '下一页' }))
  await expect.element(page.getByText('第 2 / 2 页')).toBeVisible()
  await userEvent.click(page.getByRole('tab', { name: '卡片', exact: true }))
  await expect.element(page.getByText('第 2 / 2 页')).toBeVisible()
  await expect
    .element(page.getByRole('link', { name: '查看技能：周报技能 21' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '搜索技能' }))
    .toHaveValue('周报')
  await expect
    .element(page.getByRole('combobox', { name: '发布状态' }))
    .toHaveTextContent('生效中')
  await expect
    .element(page.getByRole('combobox', { name: '使用范围' }))
    .toHaveTextContent('组织全员')
  await userEvent.click(page.getByRole('tab', { name: '列表', exact: true }))
  await expect.element(page.getByText('第 2 / 2 页')).toBeVisible()
  await userEvent.fill(
    page.getByRole('textbox', { name: '搜索技能' }),
    '不存在'
  )
  const empty = page.getByText('没有符合条件的技能，请尝试清空筛选')
  await expect.element(empty).toBeVisible()
  await userEvent.click(page.getByRole('tab', { name: '卡片', exact: true }))
  await expect.element(empty).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '下一页' }))
    .toBeDisabled()
  await userEvent.click(page.getByRole('button', { name: '清空筛选' }))
  await expect
    .element(
      page.getByRole('link', { name: '查看技能：周报技能 1', exact: true })
    )
    .toBeVisible()
})

it('窄屏卡片、键盘视图切换和筛选空态仍可使用', async () => {
  await page.viewport(390, 844)
  await show()
  page.getByRole('tab', { name: '列表', exact: true }).element().focus()
  await userEvent.keyboard('{ArrowRight}')
  await expect
    .element(page.getByRole('tab', { name: '卡片', exact: true }))
    .toHaveAttribute('aria-selected', 'true')
  await expect
    .element(page.getByRole('link', { name: '查看技能：文档整理' }))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth
  )
  await page.screenshot({
    path: '../../../../.local/skills-qa/cards-mobile.png',
  })
  document.documentElement.classList.add('dark')
  await page.screenshot({
    path: '../../../../.local/skills-qa/cards-mobile-dark.png',
  })
  await userEvent.fill(
    page.getByRole('textbox', { name: '搜索技能' }),
    '不存在'
  )
  await expect
    .element(page.getByText('没有符合条件的技能，请尝试清空筛选'))
    .toBeVisible()
})

it('类别筛选在切换视图后保留，清空后恢复目录', async () => {
  await page.viewport(1100, 800)
  const { fetcher } = await show()
  await userEvent.click(page.getByRole('combobox', { name: '技能类别' }))
  await userEvent.click(page.getByRole('option', { name: '设计创意' }))
  await expect
    .element(page.getByText('没有符合条件的技能，请尝试清空筛选'))
    .toBeVisible()
  await userEvent.click(page.getByRole('tab', { name: '卡片', exact: true }))
  expect(fetcher.mock.calls[fetcher.mock.calls.length - 1]?.[0]).toContain(
    'category=design'
  )
  await expect
    .element(page.getByRole('combobox', { name: '技能类别' }))
    .toHaveTextContent('设计创意')
  await userEvent.click(page.getByRole('button', { name: '清空筛选' }))
  await expect
    .element(page.getByRole('link', { name: '查看技能：文档整理' }))
    .toBeVisible()
})
