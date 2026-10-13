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
import { SessionBoundary, HomeRedirect, AccessGate } from '@/features/auth/gate'
import { HomePage } from './home-page'

const clients: QueryClient[] = []
afterEach(async () => {
  await cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.unstubAllGlobals()
})
async function show({
  enabled = false,
  authenticated = false,
  operator = false,
  organization = false,
  setup = true,
  initial = '/',
  siteFail = false,
  identityFail = false,
  siteBody,
  waitSite,
  cached,
}: {
  enabled?: boolean
  authenticated?: boolean
  operator?: boolean
  organization?: boolean
  setup?: boolean
  initial?: string
  siteFail?: boolean
  identityFail?: boolean
  siteBody?: unknown
  waitSite?: Promise<Response>
  cached?: boolean
} = {}) {
  let fail = siteFail
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith('/platform/site')) {
      if (waitSite) return waitSite
      return fail
        ? Response.json(
            { error: { message: '首页配置不可用' } },
            { status: 503 }
          )
        : Response.json(siteBody ?? { portal_enabled: enabled })
    }
    if (!url.endsWith('/auth/session'))
      throw new Error('Unexpected request: ' + url)
    if (identityFail)
      return Response.json(
        { error: { message: '身份服务不可用' } },
        { status: 503 }
      )
    return Response.json({
      authenticated,
      setup_complete: setup,
      csrf: 'test',
      platform_operator: operator,
      platform_edition: 'saas',
      platform_name: 'Actvero',
      user: authenticated ? { id: 'u' } : null,
      organization: organization
        ? {
            tenant_id: 'org',
            role: 'member',
            status: 'active',
            needs_login: false,
            name: '测试组织',
          }
        : null,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  if (cached !== undefined)
    client.setQueryData(['public', 'site'], { portal_enabled: cached })
  const root = createRootRoute({
    component: () => (
      <SessionBoundary>
        <Outlet />
      </SessionBoundary>
    ),
  })
  const routes = [
    createRoute({ getParentRoute: () => root, path: '/', component: HomePage }),
    createRoute({
      getParentRoute: () => root,
      path: '/console',
      component: HomeRedirect,
    }),
    createRoute({
      getParentRoute: () => root,
      path: '/models',
      component: () => (
        <AccessGate>
          <h1>模型页面</h1>
        </AccessGate>
      ),
    }),
    ...[
      'login',
      'setup',
      'overview',
      'organization-onboarding',
      'platform/organizations',
      'organization-invite',
      'desktop/authorize',
    ].map((path) =>
      createRoute({
        getParentRoute: () => root,
        path,
        component: () => <h1>{path}</h1>,
      })
    ),
  ]
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: [initial] }),
  })
  await render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return {
    router,
    fetcher,
    retry: () => {
      fail = false
    },
  }
}

it.each([
  { name: '未登录', target: '/login' },
  {
    name: '组织成员',
    authenticated: true,
    organization: true,
    target: '/overview',
  },
  {
    name: '平台运营',
    authenticated: true,
    operator: true,
    target: '/platform/organizations',
  },
  {
    name: '待开通用户',
    authenticated: true,
    target: '/organization-onboarding',
  },
  { name: '未初始化', setup: false, target: '/setup' },
])('关闭门户时$name复用既有入口', async ({ target, ...options }) => {
  const { router } = await show(options)
  await expect.poll(() => router.state.location.pathname).toBe(target)
  expect(page.getByRole('heading', { name: /让企业 AI/ }).query()).toBeNull()
})

it.each([false, true])(
  '开启门户时已登录=%s保留产品介绍',
  async (authenticated) => {
    const { router } = await show({
      enabled: true,
      authenticated,
      organization: authenticated,
    })
    await expect
      .element(page.getByRole('heading', { name: /让企业 AI/ }))
      .toBeVisible()
    expect(router.state.location.pathname).toBe('/')
  }
)

it('开启门户时身份服务失败仍能展示产品介绍', async () => {
  await show({ enabled: true, identityFail: true })
  await expect
    .element(page.getByRole('heading', { name: /让企业 AI/ }))
    .toBeVisible()
})

it('首页设置失败明确重试，不猜测门户状态', async () => {
  const state = await show({ siteFail: true })
  await expect
    .element(page.getByRole('heading', { name: '无法加载首页' }))
    .toBeVisible()
  expect(state.router.state.location.pathname).toBe('/')
  state.retry()
  await page.getByRole('button', { name: '重试' }).click()
  await expect.poll(() => state.router.state.location.pathname).toBe('/login')
})

it('首页配置字段缺失时显示失败，不能误当关闭', async () => {
  const { router } = await show({ siteBody: {} })
  await expect
    .element(page.getByText('首页设置暂时不可用，请重试'))
    .toBeVisible()
  expect(router.state.location.pathname).toBe('/')
})

it('等待首页设置时不闪出门户，也不提前跳登录', async () => {
  let finish!: (response: Response) => void
  const waitSite = new Promise<Response>((resolve) => {
    finish = resolve
  })
  const { router } = await show({ waitSite })
  await expect
    .element(page.getByRole('status', { name: '正在加载' }))
    .toBeVisible()
  expect(router.state.location.pathname).toBe('/')
  expect(page.getByRole('heading', { name: /让企业 AI/ }).query()).toBeNull()
  finish(Response.json({ portal_enabled: false }))
  await expect.poll(() => router.state.location.pathname).toBe('/login')
})

it.each(['/organization-invite#token', '/desktop/authorize?flow=test'])(
  '门户关闭不拦截独立入口%s',
  async (initial) => {
    const { router, fetcher } = await show({ initial })
    await expect.element(page.getByRole('heading')).toBeVisible()
    expect(router.state.location.href).toBe(initial)
    expect(
      fetcher.mock.calls.some(([url]) => url.endsWith('/platform/site'))
    ).toBe(false)
  }
)

it('门户关闭不覆盖受保护深链接的查询和锚点', async () => {
  const { router } = await show({ initial: '/models?q=deepseek#binding' })
  await expect.poll(() => router.state.location.pathname).toBe('/login')
  expect(router.state.location.search).toMatchObject({
    next: '/models?q=deepseek#binding',
  })
})

it.each([false, true])(
  '首页旧缓存=%s时仍等待并采用最新配置',
  async (cached) => {
    let finish!: (response: Response) => void
    const waitSite = new Promise<Response>((resolve) => {
      finish = resolve
    })
    const { router } = await show({ waitSite, cached })
    await expect
      .element(page.getByRole('status', { name: '正在加载' }))
      .toBeVisible()
    expect(router.state.location.pathname).toBe('/')
    finish(Response.json({ portal_enabled: !cached }))
    if (cached)
      await expect.poll(() => router.state.location.pathname).toBe('/login')
    else
      await expect
        .element(page.getByRole('heading', { name: /让企业 AI/ }))
        .toBeVisible()
  }
)
