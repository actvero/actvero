import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
  useParams,
} from '@tanstack/react-router'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ExpertEditor } from './editor'
import { ExpertsPage } from './page'
import type { Expert } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'csrf',
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    titleAfter,
    action,
    children,
  }: {
    title: string
    titleAfter: ReactNode
    action: ReactNode
    children: ReactNode
  }) => (
    <main className='flex h-dvh min-w-0 flex-col gap-4 overflow-y-auto p-4'>
      <div className='flex flex-wrap items-center gap-3'>
        <h1>{title}</h1>
        {titleAfter}
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
const expert: Expert = {
  id: 'expert-a',
  name: '周报专家',
  description: '整理真实工作记录',
  avatar: '',
  category: { id: 'office', name: '办公协同' },
  audience: 'administrators',
  revision: 3,
  metadata_revision: 1,
  current_release: {
    id: 'release',
    version: '1.0.0',
    sha256: 'a'.repeat(64),
    release_notes: '',
    publisher_name: '管理员',
    created_at: '2026-09-29T00:00:00Z',
  },
  has_changes: false,
  status: 'published',
  dependency_issues: 0,
  content: {
    avatar: '',
    name: '周报专家',
    description: '整理真实工作记录',
    instructions: '核实后整理周报',
    skills: [],
    connectors: [],
  },
  member_ids: [],
  releases: [],
  check: {
    can_publish: true,
    instruction_missing: false,
    audience_count: 1,
    dependencies: [],
  },
}
async function show({ fail = false, paginated = false, detail = false } = {}) {
  let exists = true
  let current = structuredClone(expert)
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url.includes('/categories'))
      return Response.json([
        {
          id: 'office',
          name: '办公协同',
          count: 1,
          revision: 1,
          system: false,
        },
      ])
    if (init.method === 'DELETE') {
      if (fail)
        return Response.json(
          { error: { message: '专家已被修改，请重新载入后重试' } },
          { status: 409 }
        )
      exists = false
      return Response.json({ message: '专家已删除' })
    }
    if (url.endsWith('/withdraw')) {
      current = {
        ...current,
        status: 'withdrawn',
        current_release: null,
        revision: 4,
      }
      return Response.json(current)
    }
    if (url.includes('/experts?')) {
      const n = Number(
        new URL(url, 'http://localhost').searchParams.get('page')
      )
      return Response.json({
        items: exists || (paginated && n === 1) ? [current] : [],
        total: paginated ? (exists ? 21 : 20) : exists ? 1 : 0,
        page: n,
        page_size: 20,
      })
    }
    return exists
      ? Response.json(current)
      : Response.json(
          { error: { message: '专家不存在或无权访问' } },
          { status: 404 }
        )
  })
  vi.stubGlobal('fetch', fetcher)
  const root = createRootRoute()
  const list = createRoute({
    getParentRoute: () => root,
    path: '/experts',
    component: ExpertsPage,
  })
  const edit = createRoute({
    getParentRoute: () => root,
    path: '/experts/$expertId',
    component: Detail,
  })
  function Detail() {
    return <ExpertEditor expertId={useParams({ strict: false }).expertId} />
  }
  const router = createRouter({
    routeTree: root.addChildren([list, edit]),
    history: createMemoryHistory({
      initialEntries: [detail ? '/experts/expert-a' : '/experts'],
    }),
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
  await expect
    .element(
      page.getByRole('heading', {
        name: detail ? '周报专家' : '专家',
        exact: true,
      })
    )
    .toBeVisible()
  if (!detail)
    await expect
      .element(page.getByRole('link', { name: '打开专家 周报专家' }))
      .toBeVisible()
  return { fetcher, router }
}

it('整行点击进入维护，头像名称区和编辑入口保留真实路由链接', async () => {
  await page.viewport(1280, 900)
  const { router } = await show()
  await expect
    .element(page.getByRole('link', { name: '打开专家 周报专家' }))
    .toHaveAttribute('href', '/experts/expert-a')
  await expect
    .element(page.getByRole('link', { name: '编辑专家 周报专家' }))
    .toHaveAttribute('href', '/experts/expert-a')
  await userEvent.click(
    page.getByRole('cell', { name: '办公协同', exact: true })
  )
  await expect
    .poll(() => router.state.location.pathname)
    .toBe('/experts/expert-a')
  await expect
    .element(page.getByLabelText('工作指令'))
    .toHaveValue('核实后整理周报')
})

it('更多操作不触发行导航，取消不删除，确认后以修订号删除并刷新列表', async () => {
  const { router, fetcher } = await show()
  await userEvent.click(
    page.getByRole('button', { name: '更多专家操作 周报专家' })
  )
  await userEvent.click(page.getByRole('menuitem', { name: '删除专家' }))
  const dialog = page.getByRole('alertdialog')
  await expect.element(dialog).toBeVisible()
  expect(router.state.location.pathname).toBe('/experts')
  await expect
    .element(
      dialog.getByText(
        '将永久删除草稿和全部发布版本，无法撤销。专家将立即不可用，已有会话的后续受控调用也会停止。关联的技能和连接器会保留。'
      )
    )
    .toBeVisible()
  await userEvent.click(dialog.getByRole('button', { name: '取消' }))
  expect(fetcher.mock.calls.some(([, init]) => init.method === 'DELETE')).toBe(
    false
  )
  await userEvent.click(
    page.getByRole('button', { name: '更多专家操作 周报专家' })
  )
  await userEvent.click(page.getByRole('menuitem', { name: '删除专家' }))
  await userEvent.click(
    page.getByRole('alertdialog').getByRole('button', { name: '删除专家' })
  )
  await expect
    .element(page.getByText('还没有专家，点击“创建专家”开始。'))
    .toBeVisible()
  const [url, init] = fetcher.mock.calls.find(
    ([, init]) => init.method === 'DELETE'
  )!
  expect(url).toBe('/api/v1/experts/expert-a')
  expect(JSON.parse(String(init.body))).toEqual({ revision: 3 })
})

it('删除冲突保留确认弹窗和列表，窄屏操作可达', async () => {
  await page.viewport(390, 844)
  await show({ fail: true })
  await userEvent.click(
    page.getByRole('button', { name: '更多专家操作 周报专家' })
  )
  await userEvent.click(page.getByRole('menuitem', { name: '删除专家' }))
  await userEvent.click(
    page.getByRole('alertdialog').getByRole('button', { name: '删除专家' })
  )
  await expect
    .element(
      page.getByRole('alertdialog').getByText('专家已被修改，请重新载入后重试')
    )
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(391)
  await page.screenshot({
    path: '../../../../.local/experts-qa/delete-mobile.png',
  })
  await userEvent.click(
    page.getByRole('alertdialog').getByRole('button', { name: '取消' })
  )
  await expect
    .element(page.getByRole('link', { name: '编辑专家 周报专家' }))
    .toBeVisible()
})

it('删除当前页最后一条后回到前一页', async () => {
  await page.viewport(1280, 900)
  const { fetcher } = await show({ paginated: true })
  await userEvent.click(
    page.getByRole('button', { name: '下一页', exact: true })
  )
  await expect.element(page.getByText('第 2 / 2 页')).toBeVisible()
  await userEvent.click(
    page.getByRole('button', { name: '更多专家操作 周报专家' })
  )
  await userEvent.click(page.getByRole('menuitem', { name: '删除专家' }))
  await userEvent.click(
    page.getByRole('alertdialog').getByRole('button', { name: '删除专家' })
  )
  await expect.element(page.getByText('第 1 / 1 页')).toBeVisible()
  expect(
    fetcher.mock.calls.filter(([, init]) => init.method === 'DELETE')
  ).toHaveLength(1)
})

it('列表下架会刷新状态，详情删除会返回列表', async () => {
  const { router } = await show()
  await userEvent.click(
    page.getByRole('button', { name: '更多专家操作 周报专家' })
  )
  await userEvent.click(page.getByRole('menuitem', { name: '下架专家' }))
  await userEvent.click(
    page.getByRole('alertdialog').getByRole('button', { name: '确认下架' })
  )
  await expect.element(page.getByText('已下架', { exact: true })).toBeVisible()
  await userEvent.click(page.getByRole('link', { name: '编辑专家 周报专家' }))
  await expect.element(page.getByLabelText('工作指令')).toBeVisible()
  await userEvent.click(
    page.getByRole('button', { name: '更多专家操作 周报专家' })
  )
  await userEvent.click(page.getByRole('menuitem', { name: '删除专家' }))
  await userEvent.click(
    page.getByRole('alertdialog').getByRole('button', { name: '删除专家' })
  )
  await expect.poll(() => router.state.location.pathname).toBe('/experts')
  await expect
    .element(page.getByText('还没有专家，点击“创建专家”开始。'))
    .toBeVisible()
})
