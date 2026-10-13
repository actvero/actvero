import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { expect, it } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent, page as browserPage } from 'vitest/browser'
import { SidebarProvider } from '@/components/ui/sidebar'
import { navigation, platformNavigation } from './data/sidebar-data'
import { NavGroup } from './nav-group'

it('筛选记录路由自动展开 MCP，支持键盘折叠和展开', async () => {
  await browserPage.viewport(1280, 900)
  const root = createRootRoute({
    component: () => (
      <SidebarProvider>
        <NavGroup
          {...navigation(true).find((group) => group.title === '能力管理')!}
        />
      </SidebarProvider>
    ),
  })
  const route = createRoute({ getParentRoute: () => root, path: '/mcp-calls' })
  const router = createRouter({
    routeTree: root.addChildren([route]),
    history: createMemoryHistory({
      initialEntries: ['/mcp-calls?service=example'],
    }),
  })
  const screen = await render(<RouterProvider router={router} />)
  const toggle = screen.getByRole('button', { name: 'MCP', exact: true })
  await expect.element(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect
    .element(screen.getByRole('link', { name: '调用记录' }))
    .toHaveAttribute('data-active', 'true')
  await userEvent.click(toggle)
  await expect.element(toggle).toHaveAttribute('aria-expanded', 'false')
  await userEvent.keyboard('{Enter}')
  await expect.element(toggle).toHaveAttribute('aria-expanded', 'true')
  await expect
    .element(screen.getByRole('link', { name: '连接日志' }))
    .toBeVisible()
})

it('侧栏收起后仍可打开 MCP 子菜单', async () => {
  await browserPage.viewport(1280, 900)
  const root = createRootRoute({
    component: () => (
      <SidebarProvider defaultOpen={false}>
        <NavGroup
          {...navigation(true).find((group) => group.title === '能力管理')!}
        />
      </SidebarProvider>
    ),
  })
  const route = createRoute({ getParentRoute: () => root, path: '/mcp-calls' })
  const router = createRouter({
    routeTree: root.addChildren([route]),
    history: createMemoryHistory({ initialEntries: ['/mcp-calls'] }),
  })
  const screen = await render(<RouterProvider router={router} />)
  await userEvent.click(
    screen.getByRole('button', { name: 'MCP', exact: true })
  )
  await expect
    .element(screen.getByRole('menuitem', { name: '连接日志' }))
    .toBeVisible()
  const memberMcp = navigation(false)
    .flatMap((group) => group.items)
    .find((item) => item.title === 'MCP')
  expect(memberMcp?.items?.map((item) => item.title)).toEqual(['可用服务'])
  expect(memberMcp?.items?.map((item) => item.title)).not.toContain('服务管理')
})

it('普通成员侧栏包含 MCP，但不包含管理员入口', () => {
  const items = navigation(false).flatMap((group) => group.items)
  expect(items.some((item) => item.title === 'MCP')).toBe(true)
  expect(items.some((item) => item.title === '模型网关')).toBe(false)
  expect(items.some((item) => item.title === 'Skills')).toBe(false)
})

it('平台设置深链接展开父菜单，切换到组织邀请后高亮对应子项', async () => {
  await browserPage.viewport(1280, 900)
  const group = platformNavigation()[0]
  const root = createRootRoute({
    component: () => (
      <SidebarProvider>
        <NavGroup {...group} />
      </SidebarProvider>
    ),
  })
  const routes = group.items
    .flatMap((item) => item.items ?? [])
    .flatMap((item) =>
      typeof item.url === 'string'
        ? [createRoute({ getParentRoute: () => root, path: item.url })]
        : []
    )
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({
      initialEntries: ['/platform/settings/mail'],
    }),
  })
  const screen = await render(<RouterProvider router={router} />)
  await expect
    .element(screen.getByRole('button', { name: '设置', exact: true }))
    .toHaveAttribute('aria-expanded', 'true')
  await expect
    .element(screen.getByRole('link', { name: '邮件服务' }))
    .toHaveAttribute('data-active', 'true')
  await screen.getByRole('button', { name: '组织', exact: true }).click()
  await screen.getByRole('link', { name: '开通邀请' }).click()
  await expect
    .poll(() => router.state.location.pathname)
    .toBe('/platform/invitations')
  await expect
    .element(screen.getByRole('link', { name: '开通邀请' }))
    .toHaveAttribute('data-active', 'true')
  await expect
    .element(screen.getByRole('button', { name: '组织', exact: true }))
    .toHaveAttribute('aria-expanded', 'true')
})

it('站点与品牌独立展开，门户深链接高亮且品牌形象仍可导航', async () => {
  await browserPage.viewport(1280, 900)
  const group = platformNavigation()[0]
  const root = createRootRoute({
    component: () => (
      <SidebarProvider>
        <NavGroup {...group} />
      </SidebarProvider>
    ),
  })
  const routes = group.items
    .flatMap((item) => item.items ?? [])
    .map((item) =>
      createRoute({ getParentRoute: () => root, path: item.url as string })
    )
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({
      initialEntries: ['/platform/settings/portal'],
    }),
  })
  const screen = await render(<RouterProvider router={router} />)
  await expect
    .element(screen.getByRole('button', { name: '站点与品牌', exact: true }))
    .toHaveAttribute('aria-expanded', 'true')
  await expect
    .element(screen.getByRole('link', { name: '门户设置' }))
    .toHaveAttribute('data-active', 'true')
  await screen.getByRole('link', { name: '品牌形象' }).click()
  await expect
    .poll(() => router.state.location.pathname)
    .toBe('/platform/settings/general')
  await expect
    .element(screen.getByRole('link', { name: '品牌形象' }))
    .toHaveAttribute('data-active', 'true')
})
