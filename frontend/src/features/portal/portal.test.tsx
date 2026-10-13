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
import { SessionBoundary, HomeRedirect } from '@/features/auth/gate'
import { loginUrl } from '@/features/auth/session'
import { defaultBrand } from '@/features/branding/data'
import { PortalPage } from './page'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function show({
  entry = '/',
  offline = false,
  role = '',
  setup = true,
} = {}) {
  const fetcher = vi.fn(async (_url: string) => {
    if (offline) throw new Error('offline')
    if (_url === '/api/v1/platform/branding') return Response.json(defaultBrand)
    return Response.json({
      authenticated: Boolean(role),
      setup_complete: setup,
      csrf: 'test',
      user: role ? { id: 'member' } : null,
      organization: role
        ? {
            tenant_id: 'org',
            role,
            status: 'active',
            name: '测试',
            needs_login: false,
          }
        : null,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const root = createRootRoute({
    component: () => (
      <SessionBoundary>
        <Outlet />
      </SessionBoundary>
    ),
  })
  const routes = [
    createRoute({
      getParentRoute: () => root,
      path: '/',
      component: PortalPage,
    }),
    createRoute({
      getParentRoute: () => root,
      path: '/console',
      component: HomeRedirect,
    }),
    ...['users', 'account', 'login', 'setup', 'overview'].map((path) =>
      createRoute({
        getParentRoute: () => root,
        path,
        component: () => <h1>{path}</h1>,
      })
    ),
  ]
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [entry] }),
  })
  await render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { fetcher, router, client }
}

it('身份服务失败时仍可浏览公开产品介绍', async () => {
  const { fetcher } = await show({ offline: true })
  await expect
    .element(page.getByRole('heading', { name: /让企业 AI/ }))
    .toBeVisible()
  await expect
    .element(
      page
        .getByRole('region', { name: /让企业 AI/ })
        .getByRole('link', { name: '登录', exact: true })
    )
    .toHaveAttribute('href', '/console')
  await expect
    .element(
      page.getByRole('heading', { name: /每一种模型，\s*都能各尽所长。/ })
    )
    .toBeInTheDocument()
  expect(fetcher.mock.calls.length).toBeGreaterThan(0)
})

it('侧边单组导航切换四项能力介绍，不请求私有业务接口', async () => {
  const { fetcher } = await show()
  await userEvent.click(page.getByRole('tab', { name: '专家', exact: true }))
  await expect
    .element(
      page.getByRole('heading', { name: /让专业经验，\s*成为团队的能力。/ })
    )
    .toBeVisible()
  await userEvent.click(page.getByRole('tab', { name: 'MCP 工具' }))
  await expect
    .element(
      page.getByRole('heading', { name: /连接业务系统，\s*让 AI 付诸行动。/ })
    )
    .toBeVisible()
  await userEvent.click(page.getByRole('tab', { name: 'Skills', exact: true }))
  await expect
    .element(page.getByRole('heading', { name: /把好方法，\s*交给每位成员。/ }))
    .toBeVisible()
  await userEvent.click(
    page.getByRole('tab', { name: '模型网关', exact: true })
  )
  await expect
    .element(
      page.getByRole('heading', { name: /每一种模型，\s*都能各尽所长。/ })
    )
    .toBeVisible()
  expect(document.querySelectorAll('[role="tablist"]')).toHaveLength(1)
  expect(document.querySelectorAll('[role="tab"]')).toHaveLength(4)
  expect(document.querySelector('table')).toBeNull()
  expect(
    fetcher.mock.calls.every((call) =>
      ['/api/v1/auth/session', '/api/v1/platform/branding'].includes(
        String(call[0])
      )
    )
  ).toBe(true)
})

it('纵向能力导航支持方向键与可见焦点', async () => {
  await show()
  await userEvent.click(
    page.getByRole('tab', { name: '模型网关', exact: true })
  )
  await userEvent.keyboard('{ArrowDown}')
  await expect
    .element(page.getByRole('tab', { name: '专家', exact: true }))
    .toHaveAttribute('aria-selected', 'true')
  await expect
    .element(page.getByRole('tab', { name: '专家', exact: true }))
    .toHaveFocus()
  await userEvent.keyboard('{End}')
  await expect
    .element(page.getByRole('tab', { name: 'Skills', exact: true }))
    .toHaveAttribute('aria-selected', 'true')
})

it('官网不公开部署命令或仓库入口，也不提供虚构安装包', async () => {
  await show()
  await expect
    .element(page.getByRole('link', { name: '查看客户端下载' }))
    .toHaveAttribute('href', '/download')
  await expect
    .element(page.getByRole('button', { name: /部署指南|使用文档/ }))
    .not.toBeInTheDocument()
  expect(document.body.textContent).not.toMatch(
    /Docker Compose|git clone|docker compose|交互演示|示例内容/
  )
  expect(
    document.querySelector('a[download], a[href*="github.com"]')
  ).toBeNull()
})

it('手机导航可打开关闭，FAQ 支持键盘，内容没有横向溢出', async () => {
  await page.viewport(390, 844)
  await show()
  await userEvent.click(page.getByRole('tab', { name: 'Skills', exact: true }))
  await expect
    .element(page.getByRole('heading', { name: /把好方法，\s*交给每位成员。/ }))
    .toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '打开导航' }))
  await expect
    .element(page.getByRole('navigation', { name: '移动导航' }))
    .toBeVisible()
  await userEvent.click(
    page
      .getByRole('navigation', { name: '移动导航' })
      .getByRole('link', { name: '能力', exact: true })
  )
  await expect
    .element(page.getByRole('navigation', { name: '移动导航' }))
    .not.toBeInTheDocument()
  await userEvent.click(
    page.getByRole('button', { name: '支持哪些 AI 能力？' })
  )
  await expect
    .element(page.getByText('视频和实时语音暂未提供。', { exact: false }))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth + 1
  )
})

it.each([
  ['', true, 'login'],
  ['', false, 'setup'],
  ['administrator', true, 'overview'],
  ['member', true, 'overview'],
])('控制台入口保留身份分流 %s %s', async (role, setup, destination) => {
  await show({ entry: '/console', role, setup })
  await expect
    .element(page.getByRole('heading', { name: destination, exact: true }))
    .toBeVisible()
})

it('身份服务失败时控制台仍被拦截', async () => {
  await show({ entry: '/console', offline: true })
  await expect
    .element(page.getByRole('heading', { name: '连接服务' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('heading', { name: 'users', exact: true }))
    .not.toBeInTheDocument()
})

it('登录回调默认进入控制台，邀请和重新登录保留显式目的地', () => {
  expect(loginUrl()).toBe('/api/v1/auth/login?next=%2Fconsole')
  expect(loginUrl('/join')).toBe('/api/v1/auth/login?next=%2Fjoin')
  expect(loginUrl('/console', true)).toContain('&switch=true')
})
