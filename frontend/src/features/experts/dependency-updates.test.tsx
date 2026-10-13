/** API fixtures only; concurrency and publication atomicity use real PostgreSQL tests. */
import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { SkillDetail } from '@/features/skills/detail'
import type { Skill } from '@/features/skills/shared'
import { DependencyRecoveryNotice } from './dependency-command'
import type { Expert } from './shared'
import { SkillExpertImpact } from './skill-impact'
import { SkillReferenceUpdateDialog } from './skill-reference-update-dialog'
import { useDependencyCommand } from './use-dependency-command'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'csrf',
  }),
}))
vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, to }: { children: ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({ children }: { children: ReactNode }) => (
    <main className='p-5'>{children}</main>
  ),
}))
beforeEach(() => sessionStorage.clear())
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  sessionStorage.clear()
})
const id = (n: number) =>
  `11111111-1111-4111-8111-${String(n).padStart(12, '0')}`
const change = {
  key: 'report',
  from_version_id: id(1),
  from_sha256: 'a'.repeat(64),
  to_version_id: id(2),
  to_sha256: 'b'.repeat(64),
}
function Commands({
  committed,
  unmount,
}: {
  committed: () => Promise<void>
  unmount?: () => void
}) {
  const command = useDependencyCommand(
    id(3),
    'expert.refresh_skills',
    committed
  )
  return (
    <>
      {!command.forbidden && <p>专家草稿内容</p>}
      <Button
        disabled={command.busy || !!command.pending || command.forbidden}
        onClick={() =>
          void command.execute({
            kind: 'expert.refresh_skills',
            revision: 4,
            changes: [change],
          })
        }
      >
        开始更新
      </Button>
      {unmount && <Button onClick={unmount}>离开页面</Button>}
      <DependencyRecoveryNotice command={command} />
    </>
  )
}
function wrapper(children: ReactNode) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  )
}
function impactRow(n: number): Schema['ExpertSkillImpact'] {
  return {
    id: id(10 + n),
    name: `专家${n}`,
    revision: n + 1,
    version: '1.0.0',
    draft_changes: [change],
    draft_versions: ['1.0.0'],
    published_versions: ['1.0.0'],
  }
}
function Impact() {
  const [selected, setSelected] = useState<Schema['ExpertDraftSelection'][]>([])
  const [denied, setDenied] = useState(false)
  return (
    <>
      <SkillExpertImpact
        skillId={id(4)}
        targetVersionId={id(2)}
        selected={selected}
        onChange={setSelected}
        onForbidden={() => {
          setDenied(true)
          if (selected.length) setSelected([])
        }}
        disabled={denied}
      />
      <output aria-label='所选编号'>
        {selected.map((s) => s.expert_id).join(',')}
      </output>
    </>
  )
}
it('分页和搜索保留精确选择，窄屏能滚动并清空选择', async () => {
  await page.viewport(390, 760)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const params = new URL(url, 'http://fixture').searchParams
      return Response.json({
        total: 21,
        page: Number(params.get('page')),
        page_size: 20,
        items:
          params.get('page') === '2' || params.get('q')
            ? [impactRow(21)]
            : Array.from({ length: 20 }, (_, i) => impactRow(i + 1)),
      })
    })
  )
  await render(wrapper(<Impact />))
  await page
    .getByRole('checkbox', { name: '更新 专家1 的草稿', exact: true })
    .click()
  await page.getByRole('button', { name: '下一页' }).click()
  await page
    .getByRole('checkbox', { name: '更新 专家21 的草稿', exact: true })
    .click()
  await page.getByRole('textbox', { name: '搜索受影响专家' }).fill('专家21')
  await expect
    .element(page.getByText('已选择 2 位专家（最多 50 位）'))
    .toBeVisible()
  await expect
    .element(page.getByRole('checkbox', { name: '更新 专家21 的草稿' }))
    .toBeChecked()
  await page.getByRole('button', { name: '清空选择' }).click()
  await expect
    .element(page.getByText('已选择 0 位专家（最多 50 位）'))
    .toBeVisible()
})
it('响应丢失后同编号查询回执，重新挂载不自动写入', async () => {
  const committed = vi.fn(async () => {})
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === 'POST') throw new Error('network interrupted')
    return Response.json({
      resource_id: id(3),
      action: 'expert.refresh_skills',
      updated_experts: [],
      request_id: url.split('/').slice(-1)[0],
      completed_at: '2026-10-05T00:00:00Z',
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const first = await render(wrapper(<Commands committed={committed} />))
  await page.getByRole('button', { name: '开始更新' }).click()
  await expect.element(page.getByText('更新结果待确认')).toBeVisible()
  const stored = JSON.parse(
    sessionStorage.getItem(
      `dependency-command:org:admin:expert.refresh_skills:${id(3)}`
    )!
  )
  expect(stored.changes).toEqual([change])
  expect(Object.keys(stored)).not.toContain('instructions')
  await first.unmount()
  await render(wrapper(<Commands committed={committed} />))
  await expect.element(page.getByText('更新结果待确认')).toBeVisible()
  expect(fetcher.mock.calls.filter((c) => c[1].method === 'POST')).toHaveLength(
    1
  )
  await page.getByRole('button', { name: '查询更新回执' }).click()
  await expect.poll(() => committed.mock.calls.length).toBe(1)
  expect(sessionStorage.length).toBe(0)
})
it('原编号重试保留完整精确请求且不重复生成命令', async () => {
  const committed = vi.fn(async () => {})
  let attempt = 0
  const fetcher = vi.fn(async () => {
    if (++attempt === 1) throw new Error('lost')
    return Response.json({})
  })
  vi.stubGlobal('fetch', fetcher)
  await render(wrapper(<Commands committed={committed} />))
  await page.getByRole('button', { name: '开始更新' }).click()
  await page.getByRole('button', { name: '按原编号重试' }).click()
  await expect.poll(() => committed.mock.calls.length).toBe(1)
  const bodies = fetcher.mock.calls.map((c) =>
    JSON.parse(String((c as unknown as [string, RequestInit])[1].body))
  )
  expect(bodies[0]).toEqual(bodies[1])
  expect(bodies[0].request_id).toMatch(/^[a-f0-9-]{36}$/)
})
it('存号失败不发送；错误保持可读', async () => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('denied')
  })
  await render(wrapper(<Commands committed={async () => {}} />))
  await page.getByRole('button', { name: '开始更新' }).click()
  await expect
    .element(
      page.getByText('浏览器无法保存更新编号；未发送更新，请检查存储后重试')
    )
    .toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
})
it('404回执保持待确认，不把尚未完成当作失败', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: RequestInit) => {
      if (init.method === 'POST') throw new Error('lost')
      return Response.json({ error: { message: '未找到' } }, { status: 404 })
    })
  )
  await render(wrapper(<Commands committed={async () => {}} />))
  await page.getByRole('button', { name: '开始更新' }).click()
  await page.getByRole('button', { name: '查询更新回执' }).click()
  await expect
    .element(
      page.getByText('尚无回执，原请求可能仍在完成。可稍后查询或按原编号重试。')
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '开始更新' }))
    .toBeDisabled()
})
it('实际403清除可见草稿并禁止后续重试，保留原号供获权后查询', async () => {
  const committed = vi.fn(async () => {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({ error: { message: '访问已撤销' } }, { status: 403 })
    )
  )
  await render(wrapper(<Commands committed={committed} />))
  await page.getByRole('button', { name: '开始更新' }).click()
  await expect.element(page.getByText('专家草稿内容')).not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '按原编号重试' }))
    .toBeDisabled()
  expect(committed).not.toHaveBeenCalled()
  expect(sessionStorage.length).toBe(1)
})
it('离开页面后迟到成功不应用结果；原命令仍可恢复', async () => {
  let resolve!: (value: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((r) => {
          resolve = r
        })
    )
  )
  const committed = vi.fn(async () => {})
  const result = await render(wrapper(<Commands committed={committed} />))
  await page.getByRole('button', { name: '开始更新' }).click()
  await expect.element(page.getByText('更新结果待确认')).toBeVisible()
  await result.unmount()
  resolve(Response.json({}))
  await new Promise((r) => setTimeout(r, 20))
  expect(committed).not.toHaveBeenCalled()
  expect(sessionStorage.length).toBe(1)
})
it('服务端409清待处理记录但保留错误，不自动更新或发布', async () => {
  const committed = vi.fn(async () => {})
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({ error: { message: '草稿已变化' } }, { status: 409 })
    )
  )
  await render(wrapper(<Commands committed={committed} />))
  await page.getByRole('button', { name: '开始更新' }).click()
  await expect.element(page.getByText('草稿已变化')).toBeVisible()
  expect(sessionStorage.length).toBe(0)
  expect(committed).not.toHaveBeenCalled()
})

it('专家技能更新弹窗只提交勾选项；390px操作按钮可达', async () => {
  await page.viewport(390, 760)
  const expert: Expert = {
    id: id(3),
    name: '专家',
    description: '说明',
    avatar: '',
    category: { id: 'office', name: '办公' },
    audience: 'administrators',
    revision: 4,
    metadata_revision: 1,
    status: 'draft',
    current_release: null,
    has_changes: true,
    dependency_issues: 0,
    member_ids: [],
    releases: [],
    content: {
      name: '专家',
      description: '说明',
      instructions: '保留',
      avatar: '',
      skills: [1, 2].map((n) => ({
        key: 'key' + n,
        label: '技能' + n,
        required: true,
        load: 'always',
        skill_id: id(10 + n),
        version_id: id(20 + n),
        sha256: 'a'.repeat(64),
      })),
    },
    check: {
      can_publish: true,
      instruction_missing: false,
      audience_count: 1,
      dependencies: [],
    },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json({
        id: url.split('/').slice(-1)[0],
        name: '技能',
        description: '说明',
        status: 'available',
        version_id: id(30 + Number(url.slice(-1))),
        sha256: 'b'.repeat(64),
        version: '2.0.0',
      })
    )
  )
  const submit = vi.fn(async () => {})
  await render(
    wrapper(
      <SkillReferenceUpdateDialog
        expert={expert}
        disabled={false}
        close={() => {}}
        submit={submit}
      />
    )
  )
  await page.getByRole('checkbox', { name: '更新 技能2' }).click()
  await page.getByRole('button', { name: '更新所选引用到草稿' }).click()
  expect(submit).toHaveBeenCalledTimes(1)
  expect(
    (submit.mock.calls[0] as unknown as [Schema['ExactSkillChange'][]])[0]
  ).toEqual([
    {
      key: 'key2',
      from_version_id: id(22),
      from_sha256: 'a'.repeat(64),
      to_version_id: id(32),
      to_sha256: 'b'.repeat(64),
    },
  ])
  await page.screenshot({ path: '.local/dependency-update-mobile.png' })
})
it('技能发布弹窗携带所选草稿与原预览版本；发布后另行检查专家', async () => {
  await page.viewport(390, 760)
  let skill: Skill = {
    id: id(4),
    name: 'sample-skill',
    category: 'office',
    category_name: '办公',
    display_name: 'Sample Skill',
    description: '说明',
    audience: 'organization',
    member_ids: [],
    revision: 3,
    default_version_id: null,
    downloads: 0,
    created_at: '2026-10-05T00:00:00Z',
    versions: [
      {
        id: id(2),
        version: '2.0.0',
        status: 'draft',
        release_notes: '说明',
        uploader_name: '管理员',
        size: 20,
        sha256: 'b'.repeat(64),
        created_at: '2026-10-05T00:00:00Z',
        files: [],
        package_icon: '',
        icon_warning: '',
        published_at: null,
      },
    ],
  }
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (url.includes('/skill-impact?'))
      return Response.json({ total: 1, page: 1, items: [impactRow(1)] })
    if (url.endsWith('/overview'))
      return Response.json({ content: '# Sample Skill' })
    if (url.endsWith('/actions')) {
      skill = {
        ...skill,
        revision: 4,
        default_version_id: id(2),
        versions: skill.versions.map((v) => ({ ...v, status: 'published' })),
      }
      return Response.json(skill)
    }
    if (init.method === 'GET') return Response.json(skill)
    throw new Error('unexpected mutation')
  })
  vi.stubGlobal('fetch', fetcher)
  await render(wrapper(<SkillDetail skillId={id(4)} />))
  await page.getByRole('button', { name: '发布此版本' }).click()
  await page.getByRole('checkbox', { name: '更新 专家1 的草稿' }).click()
  await page.getByRole('button', { name: '发布并更新 1 位草稿' }).click()
  await expect.element(page.getByRole('alertdialog')).not.toBeInTheDocument()
  const post = fetcher.mock.calls.find((c) => c[1].method === 'POST')!
  const body = JSON.parse(String(post[1].body))
  expect(body.revision).toBe(3)
  expect(body.action).toBe('publish')
  expect(body.draft_updates).toEqual([
    { expert_id: id(11), revision: 2, changes: [change] },
  ])
  expect(fetcher.mock.calls.filter((c) => c[1].method === 'POST')).toHaveLength(
    1
  )
})
