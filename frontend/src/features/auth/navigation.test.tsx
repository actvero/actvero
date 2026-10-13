import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  RouterProvider,
  useSearch,
} from '@tanstack/react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { AccessGate, HomeRedirect, SessionBoundary } from './gate'
import { LoginPage } from './login'
import { loginReturnTo } from './return-to'
import { loginUrl } from './session'
import { SetupPage } from './setup'

const clients: QueryClient[] = []
const session = {
  authenticated: true,
  setup_complete: true,
  setup_account_created: true,
  user: { id: 'admin' },
  organization: {
    tenant_id: 'org',
    role: 'administrator',
    status: 'active',
    needs_login: false,
  },
}
function LoginCapture() {
  const search = useSearch({ strict: false })
  return <h1>{String(search.next)}</h1>
}
async function show(initial: string, capture = false, cached = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  if (cached) client.setQueryData(['session'], session)
  const root = createRootRoute({
    component: () => (
      <SessionBoundary>
        <Outlet />
      </SessionBoundary>
    ),
  })
  const guarded = createRoute({
    getParentRoute: () => root,
    id: '_authenticated',
    component: () => (
      <AccessGate>
        <Outlet />
      </AccessGate>
    ),
  })
  const channels = createRoute({
    getParentRoute: () => guarded,
    path: '/model-channels',
    validateSearch: (value) => value,
    component: () => (
      <>
        <h1>渠道管理</h1>
        <Link to='/my-models' search={{ q: '', operation: '', page: 1 }}>
          我的模型
        </Link>
      </>
    ),
  })
  const models = createRoute({
    getParentRoute: () => guarded,
    path: '/my-models',
    component: () => <h1>可用模型</h1>,
  })
  const users = createRoute({
    getParentRoute: () => guarded,
    path: '/users',
    component: () => <h1>成员管理</h1>,
  })
  const overview = createRoute({
    getParentRoute: () => guarded,
    path: '/overview',
    component: () => <h1>概览</h1>,
  })
  const home = createRoute({
    getParentRoute: () => root,
    path: '/console',
    component: HomeRedirect,
  })
  const login = createRoute({
    getParentRoute: () => root,
    path: '/login',
    validateSearch: (value) => ({
      error: typeof value.error === 'string' ? value.error : undefined,
      next: loginReturnTo(value.next),
    }),
    component: capture ? LoginCapture : LoginPage,
  })
  const setup = createRoute({
    getParentRoute: () => root,
    path: '/setup',
    component: SetupPage,
  })
  const router = createRouter({
    routeTree: root.addChildren([
      guarded.addChildren([channels, models, users, overview]),
      home,
      login,
      setup,
    ]),
    history: createMemoryHistory({ initialEntries: [initial] }),
  })
  await render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return { router, client }
}
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
})
function respond(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })
}
it('冷启动等待会话后保持目标地址，侧栏切换和重新加载仍留在目标页面', async () => {
  let resolve!: (response: Response) => void
  const delayed = new Promise<Response>((done) => {
    resolve = done
  })
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockReturnValueOnce(delayed)
      .mockImplementation(async () => respond(session))
  )
  const target = '/model-channels?page=2&q=test#results'
  const { router } = await show(target)
  expect(router.state.location.href).toBe(target)
  expect(page.getByRole('heading', { name: '初始化' }).query()).toBeNull()
  resolve(respond(session))
  await expect
    .element(page.getByRole('heading', { name: '渠道管理' }))
    .toBeVisible()
  expect(router.state.location.href).toBe(target)
  await page.getByRole('link', { name: '我的模型' }).click()
  await expect
    .element(page.getByRole('heading', { name: '可用模型' }))
    .toBeVisible()
  const next = router.state.location.href
  await cleanup()
  const refreshed = await show(next)
  await expect
    .element(page.getByRole('heading', { name: '可用模型' }))
    .toBeVisible()
  expect(refreshed.router.state.location.href).toBe(next)
})
it('定时会话检查失效时保留当前路径、筛选和锚点供登录返回', async () => {
  let current = session
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond(current))
  )
  const target = '/model-channels?page=2&q=test#results'
  const { router, client } = await show(target, true)
  await expect
    .element(page.getByRole('heading', { name: '渠道管理' }))
    .toBeVisible()
  current = { ...session, authenticated: false }
  await client.invalidateQueries({ queryKey: ['session'] })
  await expect
    .element(page.getByRole('heading', { name: target }))
    .toBeVisible()
  expect(router.state.location.pathname).toBe('/login')
  expect(router.state.location.search.next).toBe(target)
})
it('已登录进入登录页时返回原页面而不是成员管理', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond(session))
  )
  const target = '/model-channels?page=2&q=test#results'
  const { router } = await show('/login?next=' + encodeURIComponent(target))
  await expect
    .element(page.getByRole('heading', { name: '渠道管理' }))
    .toBeVisible()
  expect(router.state.location.href).toBe(target)
})
it('登录失败后的重试按钮继续携带原目标', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond({ ...session, authenticated: false }))
  )
  const target = '/model-channels?page=2#results'
  await show('/login?error=callback&next=' + encodeURIComponent(target))
  await expect
    .element(page.getByRole('link', { name: '重新登录' }))
    .toHaveAttribute('href', loginUrl(target, true))
})
it.each([
  'https://evil.test',
  '//evil.test',
  '/\\evil.test',
  '/%2f%2fevil.test',
  '/a/../api/logout',
  '/api/v1/auth/login',
  '/login?next=/models',
  '/models\r\nLocation:evil',
  '/models\t',
])('拒绝危险登录返回地址 %s', (target) => {
  expect(loginReturnTo(target)).toBe('/console')
  expect(loginUrl(target)).toBe('/api/v1/auth/login?next=%2Fconsole')
})
it('正常控制台仍保留管理员默认入口', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond(session))
  )
  const { router } = await show('/console')
  await expect
    .element(page.getByRole('heading', { name: '概览' }))
    .toBeVisible()
  expect(router.state.location.pathname).toBe('/overview')
})

it.each([undefined, '/', '/#product'])(
  '默认登录目标%s进入后台而不进入门户',
  (target) => {
    expect(loginReturnTo(target)).toBe('/console')
    expect(loginUrl(target)).toBe('/api/v1/auth/login?next=%2Fconsole')
  }
)

it('有效会话恢复旧回调错误页，返回原业务页面', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond(session))
  )
  const target = '/model-channels?page=2&q=test#results'
  const { router } = await show(
    '/login?error=callback&next=' + encodeURIComponent(target)
  )
  await expect
    .element(page.getByRole('heading', { name: '渠道管理' }))
    .toBeVisible()
  expect(router.state.location.href).toBe(target)
})

it('旧回调错误页默认恢复后台概览', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond(session))
  )
  const { router } = await show('/login?error=callback&next=%2F')
  await expect
    .element(page.getByRole('heading', { name: '概览' }))
    .toBeVisible()
  expect(router.state.location.pathname).toBe('/overview')
})

it('缓存中的旧登录身份须等本次会话验证，已失效时保留重试入口', async () => {
  let resolve!: (value: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done
        })
    )
  )
  const { router } = await show('/login?error=callback&next=%2F', false, true)
  expect(router.state.location.pathname).toBe('/login')
  expect(page.getByRole('heading', { name: '概览' }).query()).toBeNull()
  resolve(respond({ ...session, authenticated: false }))
  await expect
    .element(page.getByRole('link', { name: '重新登录' }))
    .toBeVisible()
  expect(router.state.location.pathname).toBe('/login')
})

it('取消切换账号仍解释取消，不使用原身份静默进入后台', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond(session))
  )
  const { router } = await show('/login?error=cancelled')
  await expect.element(page.getByText('登录已取消。')).toBeVisible()
  expect(router.state.location.pathname).toBe('/login')
})

it('已完成初始化后直接进入后台概览', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => respond(session))
  )
  const { router } = await show('/setup')
  await expect
    .element(page.getByRole('heading', { name: '概览' }))
    .toBeVisible()
  expect(router.state.location.pathname).toBe('/overview')
})
