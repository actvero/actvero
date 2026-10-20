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
import { SessionBoundary } from '@/features/auth/gate'
import { ClientDownloadsPage } from './page'

const clients: QueryClient[] = []
afterEach(async () => {
  await cleanup()
  clients.splice(0).forEach((c) => c.clear())
  vi.unstubAllGlobals()
  await page.viewport(1280, 900)
})
const asset = (architecture = 'x64', platform = 'windows') => ({
  platform,
  architecture,
  filename: platform === 'windows' ? 'actvero.exe' : architecture + '.dmg',
  url: 'https://files.example.com/' + architecture,
  minimum_os: platform === 'windows' ? 'Windows 11' : 'macOS 14',
  size_bytes: null,
  sha256: 'a'.repeat(64),
})
const release = (assets = [asset()]) => ({
  id: 'release-a',
  version: '1.2.0',
  release_date: '2026-10-06',
  notes: '<script>unsafe()</script>\n修复登录',
  assets,
})
const catalog = (assets = [asset()]) => ({
  items: [release(assets)],
  recommendations: assets.map((a) => ({
    platform: a.platform,
    architecture: a.architecture,
    release_id: 'release-a',
  })),
})

async function show(
  fetcher: (url: string, init?: RequestInit) => Promise<Response>,
  gated = false
) {
  vi.stubGlobal('fetch', vi.fn(fetcher))
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  if (gated) {
    const root = createRootRoute({
      component: () => (
        <SessionBoundary>
          <Outlet />
        </SessionBoundary>
      ),
    })
    const child = createRoute({
      getParentRoute: () => root,
      path: '/download',
      component: ClientDownloadsPage,
    })
    const router = createRouter({
      routeTree: root.addChildren([child]),
      history: createMemoryHistory({ initialEntries: ['/download'] }),
    })
    await render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    )
  } else
    await render(
      <QueryClientProvider client={client}>
        <ClientDownloadsPage />
      </QueryClientProvider>
    )
  return client
}
it('公开下载无需登录，身份服务不可用也展示真实未发布状态', async () => {
  await show(async (url) => {
    if (url.includes('/auth/session')) throw new Error('identity offline')
    if (url.includes('/public'))
      return Response.json({ items: [], recommendations: [] })
    throw new Error('unexpected ' + url)
  }, true)
  await expect
    .element(page.getByRole('heading', { name: '下载 Actvero 桌面端' }))
    .toBeVisible()
  await expect.element(page.getByText('客户端安装包暂未发布。')).toBeVisible()
  expect(document.querySelector('a[href*="/file?"]')).toBeNull()
  expect(document.body.textContent).not.toContain('获取内测')
})
it('读取失败可重试，不把失败显示成未发布', async () => {
  let fail = true
  await show(async () =>
    fail
      ? Response.json({ error: { message: '读取下载失败' } }, { status: 503 })
      : Response.json(catalog())
  )
  await expect.element(page.getByText('读取下载失败')).toBeVisible()
  expect(page.getByText('客户端安装包暂未发布。').query()).toBeNull()
  fail = false
  await page.getByRole('button', { name: '重试' }).click()
  await expect
    .element(page.getByRole('link', { name: '下载 Windows 版' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=windows&architecture=x64'
    )
  await expect.element(page.getByText('Windows 11 · 大小未提供')).toBeVisible()
})
it('多个 Mac 架构须选择，切换同步下载目标、文件名和校验，不执行说明中的 HTML', async () => {
  await show(async () =>
    Response.json(catalog([asset('arm64', 'macos'), asset('x64', 'macos')]))
  )
  await expect
    .element(page.getByRole('button', { name: '下载 macOS 版' }))
    .toBeDisabled()
  const selector = page.getByRole('combobox', { name: 'macOS 架构' })
  await selector.click()
  await page.getByRole('option', { name: 'Apple Silicon (ARM64)' }).click()
  await expect
    .element(page.getByRole('link', { name: '下载 macOS 版' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=macos&architecture=arm64'
    )
  await expect
    .element(page.getByText('arm64.dmg', { exact: true }))
    .toBeVisible()
  await page.getByRole('button', { name: '更新说明与文件校验' }).click()
  await expect.element(page.getByText(/<script>unsafe/)).toBeVisible()
  expect(
    document.querySelector('script:not([src])')?.textContent
  ).not.toContain('unsafe()')
  await selector.click()
  await page.getByRole('option', { name: 'Intel (x64)' }).click()
  await expect
    .element(page.getByRole('link', { name: '下载 macOS 版' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=macos&architecture=x64'
    )
  await expect.element(page.getByText('x64.dmg', { exact: true })).toBeVisible()
  expect(page.getByText('arm64.dmg', { exact: true }).query()).toBeNull()
  await page.screenshot({ path: '__screenshots__/actvero-downloads-desktop.png' })
})
it('未推荐时不自行选择旧版本，历史版本仍可查看；下架刷新清除旧链接', async () => {
  let body = { ...catalog(), recommendations: [] }
  const client = await show(async () => Response.json(body))
  await expect
    .element(page.getByRole('button', { name: '下载 Windows 版' }))
    .toBeDisabled()
  await expect
    .element(page.getByText('该架构暂未设置推荐安装包，可在已发布版本中查看。'))
    .toBeVisible()
  await page.getByRole('button', { name: '已发布版本与更新说明' }).click()
  await expect
    .element(page.getByRole('link', { name: '下载 Windows · x64' }))
    .toBeVisible()
  body = { items: [], recommendations: [] }
  await client.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  await expect.element(page.getByText('客户端安装包暂未发布。')).toBeVisible()
  expect(document.querySelector('a[href*="/file?"]')).toBeNull()
})
it('390px 保持下载、架构选择、更新说明与校验可读，无横向溢出', async () => {
  await page.viewport(390, 844)
  const body = catalog()
  body.items[0].assets[0].filename =
    'actvero-very-long-package-name-for-windows-x64-version-1.2.0.exe'
  await show(async () => Response.json(body))
  await expect
    .element(page.getByRole('link', { name: '下载 Windows 版' }))
    .toBeInTheDocument()
  await page.getByRole('button', { name: '更新说明与文件校验' }).click()
  await expect.element(page.getByText('SHA256', { exact: true })).toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth
  )
  await page.screenshot({ path: '__screenshots__/actvero-downloads-390.png' })
})

it.each([true, false])(
  '门户开关为 %s 时下载仍公开，导航按首页状态展示',
  async (enabled) => {
    await show(async (url) => {
      if (url.includes('/auth/session'))
        return Response.json({ authenticated: false, setup_complete: true })
      if (url.endsWith('/platform/site'))
        return Response.json({ portal_enabled: enabled })
      if (url.includes('/downloads/public')) return Response.json(catalog())
      throw new Error('unexpected ' + url)
    }, true)
    await expect
      .element(page.getByRole('link', { name: '下载 Windows 版' }))
      .toBeVisible()
    await expect
      .element(page.getByRole('link', { name: '登录', exact: true }))
      .toHaveAttribute('href', '/console')
    if (enabled) {
      await expect
        .element(page.getByRole('link', { name: '产品', exact: true }))
        .toBeVisible()
      await expect
        .element(page.getByRole('link', { name: '能力', exact: true }))
        .toBeVisible()
    } else {
      await expect
        .element(page.getByRole('link', { name: '产品', exact: true }))
        .not.toBeInTheDocument()
      await expect
        .element(page.getByRole('link', { name: '能力', exact: true }))
        .not.toBeInTheDocument()
    }
  }
)

it('首页设置读取失败不阻止下载，也不显示已关闭门户的链接', async () => {
  await show(async (url) => {
    if (url.endsWith('/platform/site'))
      return Response.json(
        { error: { message: '首页设置不可用' } },
        { status: 503 }
      )
    if (url.includes('/auth/session')) throw new Error('identity offline')
    return Response.json(catalog())
  }, true)
  await expect
    .element(page.getByRole('link', { name: '下载 Windows 版' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('link', { name: '产品', exact: true }))
    .not.toBeInTheDocument()
  expect(document.body.textContent).not.toContain('首页设置不可用')
})

it('首页设置尚未响应时仍能下载，390px菜单也隐藏门户入口', async () => {
  await page.viewport(390, 844)
  let finish!: (response: Response) => void
  await show(async (url) => {
    if (url.endsWith('/platform/site'))
      return new Promise<Response>((resolve) => {
        finish = resolve
      })
    return Response.json(catalog())
  })
  await expect
    .element(page.getByRole('link', { name: '下载 Windows 版' }))
    .toBeInTheDocument()
  finish(Response.json({ portal_enabled: false }))
  await page.getByRole('button', { name: '打开导航' }).click()
  await expect
    .element(page.getByRole('navigation', { name: '移动导航' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('link', { name: '产品', exact: true }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('link', { name: '能力', exact: true }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('link', { name: '下载', exact: true }).last())
    .toHaveAttribute('href', '/download')
})
