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
    .element(page.getByRole('heading', { name: '下载 Actvero' }))
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
    .element(page.getByRole('link', { name: '下载 Windows x64' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=windows&architecture=x64'
    )
  await expect
    .element(page.getByRole('link', { name: '下载 Windows x64' }))
    .toHaveTextContent('下载 EXE')
})
it('各 Mac 架构直接下载，不显示更新日志或历史版本入口', async () => {
  await show(async () =>
    Response.json(catalog([asset('arm64', 'macos'), asset('x64', 'macos')]))
  )
  expect(page.getByRole('radio').query()).toBeNull()
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Apple 芯片' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=macos&architecture=arm64'
    )
  expect(
    page.getByRole('button', { name: '更新日志', exact: true }).query()
  ).toBeNull()
  expect(
    page.getByRole('button', { name: '历史版本', exact: true }).query()
  ).toBeNull()
  expect(document.body.textContent).not.toContain('unsafe()')
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Intel 芯片' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=macos&architecture=x64'
    )
  await page.screenshot({
    path: '__screenshots__/actvero-downloads-desktop.png',
  })
})
it('未推荐时不自行选择旧版本，下架刷新清除旧链接', async () => {
  let body = { ...catalog(), recommendations: [] }
  const client = await show(async () => Response.json(body))
  await expect
    .element(page.getByRole('button', { name: 'Windows x64未设置推荐版本' }))
    .toBeDisabled()
  expect(document.querySelector('a[href*="/file?"]')).toBeNull()
  body = { items: [], recommendations: [] }
  await client.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  await expect.element(page.getByText('客户端安装包暂未发布。')).toBeVisible()
  expect(document.querySelector('a[href*="/file?"]')).toBeNull()
})
it('390px 保持架构下载可读，无横向溢出', async () => {
  await page.viewport(390, 844)
  const body = catalog()
  body.items[0].assets[0].filename =
    'actvero-very-long-package-name-for-windows-x64-version-1.2.0.exe'
  await show(async () => Response.json(body))
  await expect
    .element(page.getByRole('link', { name: '下载 Windows x64' }))
    .toBeInTheDocument()
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
      .element(page.getByRole('link', { name: '下载 Windows x64' }))
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
    .element(page.getByRole('link', { name: '下载 Windows x64' }))
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
    .element(page.getByRole('link', { name: '下载 Windows x64' }))
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

it('品牌、推荐版本和文件元数据从接口读取，刷新后旧下载链接失效', async () => {
  let body = catalog([asset('arm64', 'macos')])
  body.items[0].version = '3.7.4'
  body.items[0].assets[0].filename = 'team-client.pkg'
  const client = await show(async (url) => {
    if (url.endsWith('/branding'))
      return Response.json({
        name: '团队助手',
        revision: 'brand-revision',
        assets: {},
        asset_ids: {},
        favicon_url: '/favicon.ico',
        apple_icon_url: '/favicon.ico',
      })
    return Response.json(body)
  })
  await expect
    .element(page.getByRole('heading', { name: '下载 团队助手' }))
    .toBeVisible()
  await expect
    .element(page.getByTestId('download-version'))
    .toHaveTextContent('v3.7.4')
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Apple 芯片' }))
    .toHaveTextContent('下载 PKG')
  expect(page.getByText('v0.1.15', { exact: true }).query()).toBeNull()
  body = catalog([asset('arm64', 'macos')])
  body.items[0].id = 'release-new'
  body.items[0].version = '3.8.0'
  body.recommendations[0].release_id = 'release-new'
  await client.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  await expect
    .element(page.getByTestId('download-version'))
    .toHaveTextContent('v3.8.0')
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Apple 芯片' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-new/file?platform=macos&architecture=arm64'
    )
  expect(document.querySelector('a[href*="release-a/file"]')).toBeNull()
})

it('预览版本不覆盖后台推荐，不同目标版本分别显示', async () => {
  const body = catalog([asset('arm64', 'macos')])
  body.items.unshift({
    ...release([asset()]),
    id: 'windows-old',
    version: '1.1.0',
  })
  body.items.unshift({
    ...release([asset('arm64', 'macos')]),
    id: 'preview',
    version: '9.0.0-preview.1',
  })
  body.recommendations.push({
    platform: 'windows',
    architecture: 'x64',
    release_id: 'windows-old',
  })
  await show(async () => Response.json(body))
  expect(page.getByTestId('download-version').query()).toBeNull()
  await expect.element(page.getByText('v1.2.0', { exact: true })).toBeVisible()
  await expect.element(page.getByText('v1.1.0', { exact: true })).toBeVisible()
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Apple 芯片' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=macos&architecture=arm64'
    )
  expect(page.getByText('v9.0.0-preview.1', { exact: true }).query()).toBeNull()
})

it('Windows ARM64 直接下载，未发布系统不提供假链接', async () => {
  await show(async () => Response.json(catalog([asset('arm64', 'windows')])))
  expect(
    page.getByRole('link', { name: '下载 Windows x64' }).query()
  ).toBeNull()
  await expect
    .element(page.getByRole('link', { name: '下载 Windows ARM64' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=windows&architecture=arm64'
    )
  expect(page.getByRole('link', { name: /^下载 macOS/ }).query()).toBeNull()
  await expect
    .element(page.getByText('暂未发布', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('link', { name: '下载 Windows ARM64' }))
    .toHaveTextContent('下载 EXE')
})

it('刷新下架架构时移除其入口，其他架构保留准确的下载链接', async () => {
  let body = catalog([asset('arm64', 'macos'), asset('x64', 'macos')])
  const client = await show(async () => Response.json(body))
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Intel 芯片' }))
    .toBeVisible()
  body = catalog([asset('arm64', 'macos')])
  await client.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Intel 芯片' }))
    .not.toBeInTheDocument()
  expect(document.querySelector('a[href*="architecture=x64"]')).toBeNull()
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Apple 芯片' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=macos&architecture=arm64'
    )
})

it('完全未发布时只有一次空状态，没有示例版本、架构或安装说明', async () => {
  await show(async () => Response.json({ items: [], recommendations: [] }))
  await expect.element(page.getByText('客户端安装包暂未发布。')).toBeVisible()
  expect(
    page.getByRole('region', { name: 'macOS', exact: true }).query()
  ).toBeNull()
  expect(page.getByRole('radio').query()).toBeNull()
  expect(page.getByTestId('download-version').query()).toBeNull()
  expect(page.getByText('安装与登录', { exact: true }).query()).toBeNull()
  expect(
    page.getByRole('button', { name: '历史版本', exact: true }).query()
  ).toBeNull()
})

it('唯一架构被替换后，新入口明确标注 CPU 并移除旧链接', async () => {
  let body = catalog([asset('x64', 'windows')])
  const client = await show(async () => Response.json(body))
  await expect
    .element(page.getByRole('link', { name: '下载 Windows x64' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=windows&architecture=x64'
    )
  body = catalog([asset('arm64', 'windows')])
  await client.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  await expect
    .element(page.getByRole('link', { name: '下载 Windows x64' }))
    .not.toBeInTheDocument()
  expect(document.querySelector('a[href*="architecture=x64"]')).toBeNull()
  await expect
    .element(page.getByRole('link', { name: '下载 Windows ARM64' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=windows&architecture=arm64'
    )
})

it('通用版入口只在后台真实发布时出现', async () => {
  let body = catalog([asset('arm64', 'macos')])
  const client = await show(async () => Response.json(body))
  await expect
    .element(page.getByRole('link', { name: '下载 macOS Apple 芯片' }))
    .toBeVisible()
  expect(
    page.getByRole('link', { name: '下载 macOS 通用版' }).query()
  ).toBeNull()
  body = catalog([asset('universal', 'macos')])
  await client.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  await expect
    .element(page.getByRole('link', { name: '下载 macOS 通用版' }))
    .toHaveAttribute(
      'href',
      '/api/v1/platform/downloads/release-a/file?platform=macos&architecture=universal'
    )
})

it('桌面双平台布局紧凑，所有架构在首屏直接下载', async () => {
  await page.viewport(1280, 800)
  await show(async () =>
    Response.json(
      catalog([
        asset('arm64', 'macos'),
        asset('x64', 'macos'),
        asset('x64', 'windows'),
        asset('arm64', 'windows'),
      ])
    )
  )
  await expect
    .element(page.getByRole('link', { name: '下载 Windows ARM64' }))
    .toBeVisible()
  expect(
    document.querySelector('header')!.getBoundingClientRect().height
  ).toBeLessThanOrEqual(66)
  expect(
    parseFloat(getComputedStyle(document.querySelector('h1')!).fontSize)
  ).toBeLessThanOrEqual(32)
  const cards = [...document.querySelectorAll('main [role="region"]')]
  expect(cards).toHaveLength(2)
  for (const card of cards) {
    expect(card.getBoundingClientRect().height).toBeLessThanOrEqual(240)
    expect(card.getBoundingClientRect().bottom).toBeLessThan(700)
  }
  const links = [...document.querySelectorAll('main a[href*="/file?"]')]
  expect(links).toHaveLength(4)
  for (const link of links) {
    expect(link.getBoundingClientRect().height).toBe(44)
  }
})
