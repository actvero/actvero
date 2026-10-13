import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ResourceCategoriesDialog } from '@/components/resource-categories-dialog'
import { ExpertEditor } from './editor'
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
    <main className='flex h-dvh min-w-0 flex-col gap-6 overflow-y-auto p-5'>
      <div className='flex flex-wrap items-center gap-3'>
        <h1>{title}</h1>
        {titleAfter}
      </div>
      <div>{action}</div>
      {children}
    </main>
  ),
}))
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children, to }: { children: ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
const expert: Expert = {
  id: 'expert',
  name: '周报专家',
  description: '整理真实工作记录',
  avatar: '',
  category: { id: 'office', name: '办公协同' },
  audience: 'administrators',
  revision: 1,
  metadata_revision: 1,
  current_release: null,
  has_changes: true,
  status: 'draft',
  dependency_issues: 0,
  content: {
    name: '周报专家',
    description: '整理真实工作记录',
    avatar: '',
    tags: ['周报'],
    instructions: '先核实成果，再整理周报。',
    conversation_starters: ['整理本周的工作'],
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
const categories = [
  { id: 'office', name: '办公协同', count: 1, revision: 1, system: false },
  {
    id: 'custom-team',
    name: '团队专属分类',
    count: 0,
    revision: 1,
    system: false,
  },
  { id: 'uncategorized', name: '未分类', count: 0, revision: 1, system: true },
]

async function show({
  fresh = false,
  fail = false,
  scope = false,
  dependencies = false,
  update = false,
  publishedIssues = false,
} = {}) {
  let current = structuredClone(expert)
  if (publishedIssues) {
    current.status = 'published'
    current.current_release = {
      id: 'release-old',
      version: '1.0.0',
      sha256: 'c'.repeat(64),
      publisher_name: '管理员',
      release_notes: '',
      created_at: '2026-10-01T00:00:00Z',
    }
    current.dependency_issues = 2
  }
  if (dependencies) {
    current.content.skills = [
      {
        key: 'report',
        label: '周报技能',
        required: true,
        load: 'always',
        skill_id: 'skill-a',
        version_id: 'version-a',
        sha256: 'a'.repeat(64),
      },
    ]
    current.content.connectors = [
      {
        key: 'lab',
        label: '资料助手',
        required: true,
        connector_id: 'connector-a',
      },
    ]
  }
  if (scope)
    current.check.dependencies = [
      {
        kind: 'skills',
        key: 'report',
        label: '周报技能',
        required: true,
        status: 'available',
        missing_members: 1,
        update_available: false,
      },
    ]
  if (update)
    current.check.dependencies = [
      {
        kind: 'skills',
        key: 'report',
        label: '周报技能',
        required: true,
        status: 'available',
        missing_members: 0,
        update_available: true,
        locked_version: '1.2.0',
      },
    ]
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url.includes('/categories')) return Response.json(categories)
    if (url.includes('/dependencies/connectors/'))
      return Response.json({
        id: 'connector-a',
        name: '资料助手',
        description: '搜索文档、读取资料和计算数字。',
        icon: '',
        status: 'available',
        tools_discovered: true,
        tools: [
          {
            key: 'search_documents',
            name: '搜索资料',
            description: '按关键词查询测试资料。',
            enabled: true,
          },
          {
            key: 'sum_numbers',
            name: '数字求和',
            description: '计算一组数字的总和。',
            enabled: true,
          },
          {
            key: 'disabled_tool',
            name: '平台关闭的工具',
            description: '当前不可用。',
            enabled: false,
          },
        ],
      })
    if (url.includes('/dependencies/skills/'))
      return Response.json({
        id: 'skill-a',
        name: '周报技能',
        description: '从工作记录整理成果和下一步行动。',
        icon: '',
        status: 'available',
        version: '1.2.0',
        update_available: update,
        version_id: 'version-a',
        sha256: 'a'.repeat(64),
      })
    if (url.includes('/dependencies?'))
      return Response.json({
        items: [
          {
            id: 'skill-a',
            name: '周报技能',
            description: '整理周报',
            version: '1.2.0',
            version_id: 'version-a',
            sha256: 'a'.repeat(64),
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      })
    if (init.method === 'GET') return Response.json(current)
    const body = JSON.parse(String(init.body))
    if (fail)
      return Response.json(
        { error: { message: '专家已被修改，请重新载入后重试' } },
        { status: 409 }
      )
    if (url.endsWith('/publish')) {
      current.current_release = {
        id: 'release',
        version: body.version,
        sha256: 'f'.repeat(64),
        publisher_name: '管理员',
        release_notes: body.release_notes,
        created_at: '2026-09-29T00:00:00Z',
      }
      current.status = 'published'
      current.has_changes = false
      current.releases = [current.current_release]
    } else if (url.endsWith('/scope')) {
      current.audience = body.audience
      current.member_ids = body.member_ids
    } else {
      current = {
        ...current,
        content: body.content,
        name: body.content.name,
        description: body.content.description,
        category: categories.find((c) => c.id === body.category)!,
      }
    }
    current.revision += 1
    return Response.json(current)
  })
  vi.stubGlobal('fetch', fetcher)
  await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ExpertEditor expertId={fresh ? undefined : 'expert'} />
    </QueryClientProvider>
  )
  await expect
    .element(page.getByLabelText('名称', { exact: true }))
    .toBeVisible()
  return fetcher
}

it('新建使用后台类别与真实依赖选择，保存确切引用且不自动发布', async () => {
  await page.viewport(1280, 1000)
  const fetcher = await show({ fresh: true })
  await userEvent.fill(page.getByLabelText('名称', { exact: true }), '研究专家')
  await userEvent.fill(
    page.getByLabelText('简介', { exact: true }),
    '整理研究材料'
  )
  await userEvent.click(page.getByLabelText('类别', { exact: true }))
  await userEvent.click(page.getByRole('option', { name: '团队专属分类' }))
  await userEvent.fill(
    page.getByLabelText('工作指令'),
    '核实来源后再输出结论。'
  )
  await userEvent.click(
    page.getByRole('button', { name: '添加技能', exact: true })
  )
  await userEvent.click(page.getByRole('button', { name: '选择周报技能' }))
  await userEvent.click(
    page.getByRole('button', { name: '保存草稿', exact: true })
  )
  await expect
    .poll(
      () =>
        fetcher.mock.calls.filter(([, init]) => init.method === 'POST').length
    )
    .toBe(1)
  const [, init] = fetcher.mock.calls.find(
    ([, init]) => init.method === 'POST'
  )!
  const body = JSON.parse(String(init.body))
  expect(body.category).toBe('custom-team')
  expect(body.content.skills[0]).toMatchObject({
    skill_id: 'skill-a',
    version_id: 'version-a',
    sha256: 'a'.repeat(64),
    required: true,
    load: 'always',
  })
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/publish'))).toBe(
    false
  )
})

it('保存冲突保留输入，未保存修改阻止发布', async () => {
  await page.viewport(1280, 1000)
  await show({ fail: true })
  await userEvent.fill(page.getByLabelText('工作指令'), '需要保留的草稿修改')
  await expect
    .element(page.getByRole('button', { name: '发布', exact: true }))
    .toBeDisabled()
  await userEvent.click(
    page.getByRole('button', { name: '保存草稿', exact: true })
  )
  await expect
    .element(page.getByText('专家已被修改，请重新载入后重试'))
    .toBeVisible()
  await expect
    .element(page.getByLabelText('工作指令'))
    .toHaveValue('需要保留的草稿修改')
})

it('发布确认使用已保存的修订号，并展示真实权限缺口', async () => {
  const fetcher = await show({ scope: true })
  await userEvent.click(page.getByRole('button', { name: '发布', exact: true }))
  const dialog = page.getByRole('dialog')
  await expect.poll(() => getComputedStyle(dialog.element()).opacity).toBe('1')
  await page.screenshot({
    path: '../../../../.local/experts-qa/publish-desktop.png',
  })
  await expect
    .element(dialog.getByText('1 位所选成员没有此能力的使用权限。'))
    .toBeVisible()
  await userEvent.fill(page.getByLabelText('版本号'), '1.0.0')
  await userEvent.fill(page.getByLabelText('更新说明'), '首次发布')
  await userEvent.click(page.getByRole('button', { name: '确认发布' }))
  await expect
    .poll(() => fetcher.mock.calls.some(([url]) => url.endsWith('/publish')))
    .toBe(true)
  const [, init] = fetcher.mock.calls.find(([url]) => url.endsWith('/publish'))!
  expect(JSON.parse(String(init.body))).toEqual({
    version: '1.0.0',
    release_notes: '首次发布',
    revision: 1,
  })
})

it('配置未保存时可切换和保存范围，保留两边输入并用新修订号保存草稿', async () => {
  const fetcher = await show()
  expect(
    page
      .getByRole('tab')
      .elements()
      .map((el) => el.textContent)
  ).toEqual(['配置', '使用范围', '版本记录'])
  await userEvent.fill(
    page.getByLabelText('工作指令'),
    '切换页签后需要保留的指令'
  )
  await userEvent.click(page.getByRole('tab', { name: '使用范围' }))
  await userEvent.click(page.getByLabelText('谁可以使用这位专家'))
  await userEvent.click(
    page.getByRole('option', { name: '组织全员', exact: true })
  )
  await userEvent.click(page.getByRole('tab', { name: '版本记录' }))
  await expect.element(page.getByText('尚未发布版本')).toBeVisible()
  await userEvent.click(page.getByRole('tab', { name: '使用范围' }))
  await expect
    .element(page.getByLabelText('谁可以使用这位专家'))
    .toHaveTextContent('组织全员')
  await userEvent.click(page.getByRole('button', { name: '保存范围' }))
  await expect
    .poll(
      () =>
        fetcher.mock.calls.filter(
          ([url, init]) => url.endsWith('/scope') && init.method === 'PUT'
        ).length
    )
    .toBe(1)
  await expect
    .element(page.getByRole('tab', { name: '使用范围' }))
    .toHaveAttribute('aria-selected', 'true')
  await expect
    .element(page.getByRole('button', { name: '保存草稿' }))
    .toBeEnabled()
  await userEvent.click(page.getByRole('button', { name: '保存草稿' }))
  await expect
    .poll(
      () =>
        fetcher.mock.calls.filter(
          ([url, init]) =>
            url.endsWith('/experts/expert') && init.method === 'PUT'
        ).length
    )
    .toBe(1)
  const [, init] = fetcher.mock.calls.find(
    ([url, init]) => url.endsWith('/experts/expert') && init.method === 'PUT'
  )!
  expect(JSON.parse(String(init.body))).toMatchObject({
    revision: 2,
    content: { instructions: '切换页签后需要保留的指令' },
  })
  await userEvent.click(page.getByRole('tab', { name: '配置' }))
  await expect
    .element(page.getByLabelText('工作指令'))
    .toHaveValue('切换页签后需要保留的指令')
})

it('范围保存冲突不丢失配置草稿和范围选择', async () => {
  await show({ fail: true })
  await userEvent.fill(page.getByLabelText('工作指令'), '尚未保存的指令')
  await userEvent.click(page.getByRole('tab', { name: '使用范围' }))
  await userEvent.click(page.getByLabelText('谁可以使用这位专家'))
  await userEvent.click(
    page.getByRole('option', { name: '组织全员', exact: true })
  )
  await userEvent.click(page.getByRole('button', { name: '保存范围' }))
  await expect
    .element(page.getByText('专家已被修改，请重新载入后重试'))
    .toBeVisible()
  await expect
    .element(page.getByLabelText('谁可以使用这位专家'))
    .toHaveTextContent('组织全员')
  await userEvent.click(page.getByRole('tab', { name: '配置' }))
  await expect
    .element(page.getByLabelText('工作指令'))
    .toHaveValue('尚未保存的指令')
})

it('窄屏编辑与预览无横向溢出，标签与开场问题有长度校验', async () => {
  await page.viewport(390, 844)
  await show()
  await userEvent.fill(
    page.getByLabelText('标签'),
    '一,二,三,四,五,六,七,八,九'
  )
  await userEvent.click(
    page.getByRole('button', { name: '保存草稿', exact: true })
  )
  await expect
    .element(page.getByText('最多 8 个标签，每个不超过 30 字'))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(391)
  await page.screenshot({
    path: '../../../../.local/experts-qa/editor-mobile.png',
  })
})

it('专家类别管理调用独立专家接口，Skills 字典不受影响', async () => {
  const fetcher = vi.fn(async (_url: string, init: RequestInit) =>
    Response.json(
      init.method === 'GET'
        ? categories
        : [
            ...categories,
            {
              id: 'new',
              name: '客户服务',
              count: 0,
              revision: 1,
              system: false,
            },
          ]
    )
  )
  vi.stubGlobal('fetch', fetcher)
  await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ResourceCategoriesDialog
        resource='experts'
        noun='专家'
        close={() => {}}
      />
    </QueryClientProvider>
  )
  await expect
    .element(page.getByRole('list', { name: '专家类别列表' }))
    .toBeVisible()
  await userEvent.fill(page.getByLabelText('新增类别'), '客户服务')
  await userEvent.click(page.getByRole('button', { name: '新增', exact: true }))
  await expect
    .poll(() =>
      fetcher.mock.calls.some(
        ([url, init]) =>
          url === '/api/v1/experts/categories' && init.method === 'POST'
      )
    )
    .toBe(true)
  expect(fetcher.mock.calls.some(([url]) => url.includes('/skills/'))).toBe(
    false
  )
})

it('依赖卡片解释选项，工具选择仅保存当前专家并在切换页签后保留', async () => {
  await page.viewport(1280, 1000)
  const fetcher = await show({ dependencies: true })
  await expect
    .element(page.getByText('从工作记录整理成果和下一步行动。'))
    .toBeVisible()
  await expect.element(page.getByText('v1.2.0')).toBeVisible()
  await userEvent.click(page.getByLabelText('周报技能的加载方式'))
  await userEvent.click(
    page.getByRole('option', { name: '按需加载', exact: true })
  )
  await expect.element(page.getByText('需要时再读取技能指令。')).toBeVisible()
  await userEvent.click(
    page.getByRole('button', { name: '资料助手的工具设置' })
  )
  const sum = page.getByRole('switch', { name: '资料助手：数字求和' })
  await expect.element(sum).toBeChecked()
  await expect
    .element(page.getByRole('switch', { name: '资料助手：平台关闭的工具' }))
    .toBeDisabled()
  await userEvent.click(sum)
  await expect.element(sum).not.toBeChecked()
  expect(
    fetcher.mock.calls.filter(([, init]) => init.method !== 'GET')
  ).toHaveLength(0)
  await userEvent.click(page.getByRole('tab', { name: '使用范围' }))
  await userEvent.click(page.getByRole('tab', { name: '配置' }))
  await expect.element(sum).not.toBeChecked()
  await userEvent.click(
    page.getByRole('button', { name: '保存草稿', exact: true })
  )
  await expect
    .poll(
      () =>
        fetcher.mock.calls.filter(([, init]) => init.method === 'PUT').length
    )
    .toBe(1)
  const [, init] = fetcher.mock.calls.find(([, init]) => init.method === 'PUT')!
  expect(JSON.parse(String(init.body)).content.connectors[0].tools).toEqual([
    'search_documents',
  ])
  expect(JSON.parse(String(init.body)).content.skills[0].load).toBe('on_demand')
  expect(fetcher.mock.calls.some(([url]) => url.includes('/policy'))).toBe(
    false
  )
})

it('窄屏工具列表搜索和全部关闭可用，无横向溢出', async () => {
  await page.viewport(390, 844)
  const fetcher = await show({ dependencies: true })
  await userEvent.click(
    page.getByRole('button', { name: '资料助手的工具设置' })
  )
  await userEvent.fill(page.getByLabelText('搜索资料助手的工具'), '求和')
  await expect
    .element(page.getByRole('switch', { name: '资料助手：数字求和' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('switch', { name: '资料助手：搜索资料' }))
    .not.toBeInTheDocument()
  await userEvent.fill(page.getByLabelText('搜索资料助手的工具'), '')
  await userEvent.click(page.getByRole('button', { name: '全部关闭' }))
  await expect
    .element(page.getByRole('switch', { name: '资料助手：数字求和' }))
    .not.toBeChecked()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(391)
  await page.screenshot({
    path: '../../../../.local/experts-qa/dependencies-mobile.png',
  })
  await userEvent.click(
    page.getByRole('button', { name: '保存草稿', exact: true })
  )
  await expect
    .poll(
      () =>
        fetcher.mock.calls.filter(([, init]) => init.method === 'PUT').length
    )
    .toBe(1)
  const [, init] = fetcher.mock.calls.find(([, init]) => init.method === 'PUT')!
  expect(JSON.parse(String(init.body)).content.connectors[0].tools).toEqual([])
})

it('有新版单独提示，锁定的有效旧版不阻止发布也不自动更新', async () => {
  await page.viewport(1280, 1000)
  const fetcher = await show({ dependencies: true, update: true })
  await expect.element(page.getByText('有新版，可保留此版本')).toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '发布', exact: true }))
  await expect
    .element(page.getByRole('dialog'))
    .toHaveTextContent('当前锁定 v1.2.0 仍可使用')
  await userEvent.fill(page.getByLabelText('版本号'), '1.0.0')
  await expect
    .element(page.getByRole('button', { name: '确认发布' }))
    .toBeEnabled()
  expect(fetcher.mock.calls.every(([, init]) => init.method === 'GET')).toBe(
    true
  )
})

it('已发布依赖问题独立提示，重新发布说明所选工具定义锁定规则', async () => {
  await page.viewport(390, 900)
  const fetcher = await show({ publishedIssues: true })
  await expect
    .element(page.getByText('当前发布有 2 项依赖需要检查'))
    .toBeVisible()
  await expect
    .element(
      page.getByText('必需依赖未就绪会阻止准备，可选依赖可以跳过。', {
        exact: false,
      })
    )
    .toBeVisible()
  await userEvent.click(page.getByRole('button', { name: '发布', exact: true }))
  await expect
    .element(
      page.getByText('本次发布锁定所选工具及当时开放的提示词、资源和资源模板', { exact: false })
    )
    .toBeVisible()
  await expect
    .poll(
      () =>
        getComputedStyle(
          document.querySelector('[data-slot="dialog-content"]')!
        ).opacity
    )
    .toBe('1')
  await page.screenshot({ path: '.local/mcp-dependency-mobile.png' })
  expect(fetcher.mock.calls.some(([, init]) => init.method === 'POST')).toBe(
    false
  )
})
