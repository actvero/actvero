import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { QuotaPoliciesPage } from './page'
import { PolicyEditor } from './policy-editor'
import { policyInput, policySchema, values, type Policy } from './policy-form'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'csrf-test',
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    description,
    action,
    children,
  }: {
    title: string
    description: string
    action: ReactNode
    children: ReactNode
  }) => (
    <main className='flex min-w-0 flex-col gap-6 p-6'>
      <div className='flex flex-wrap items-center justify-between gap-4'>
        <h1>{title}</h1>
        {action}
      </div>
      <p>{description}</p>
      {children}
    </main>
  ),
}))
const base: Policy = {
  id: 'default',
  name: '默认',
  priority: 0,
  member_ids: [],
  rules: [
    { kind: 'fixed_hours', hours: 5, points: '1000' },
    {
      kind: 'calendar_week',
      points: '8000',
      timezone: 'Asia/Shanghai',
      week_start: 0,
    },
  ],
  archived: false,
  version: 1,
  created_at: '2026-09-25T00:00:00Z',
  updated_at: '2026-09-25T00:00:00Z',
}
const higher: Policy = {
  ...base,
  id: 'higher',
  name: '进阶',
  priority: 10,
  member_ids: ['admin-member'],
  rules: [{ kind: 'fixed_hours', hours: 5, points: '3000' }],
}
const member = {
  id: 'admin-member',
  name: '额度管理员',
  email: 'admin@example.com',
  role: 'administrator',
  status: 'active',
  source: 'invitation',
  version: 1,
  joined_at: base.created_at,
  is_self: true,
}
const clients: QueryClient[] = []
async function show(component: ReactNode, staleTime = 0) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime } },
  })
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
}
beforeEach(async () => {
  await page.viewport(1280, 900)
})
afterEach(async () => {
  clients.forEach((c) => c.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 800)
})

it('keeps decimal points exact, requires explicit weekly boundaries, and rejects duplicate windows', () => {
  const draft = values(base)
  draft.rules[0].points = '0.000000000001'
  expect(policyInput(draft).rules[0].points).toBe('0.000000000001')
  draft.rules[1].timezone = ''
  expect(policySchema.safeParse(draft).success).toBe(false)
  draft.rules[1].timezone = 'Asia/Shanghai'
  draft.rules.push({ ...draft.rules[0] })
  expect(policySchema.safeParse(draft).success).toBe(false)
  const newDefault = values(undefined, true)
  expect(newDefault.rules[0].points).toBe('')
  expect(newDefault.rules[0].hours).toBe('')
})

it('creates the default only on save and requires hours, points, timezone and weekly start', async () => {
  const calls = vi.fn(async (_url: string, init?: RequestInit) => {
    expect(JSON.parse(String(init?.body))).toEqual({
      name: '默认',
      priority: 0,
      member_ids: [],
      rules: [
        { kind: 'fixed_hours', hours: 5, points: '1000' },
        {
          kind: 'calendar_week',
          points: '8000',
          timezone: 'Asia/Shanghai',
          week_start: 0,
        },
      ],
    })
    return Response.json(base)
  })
  vi.stubGlobal('fetch', calls)
  const saved = vi.fn()
  await show(<PolicyEditor isDefault close={vi.fn()} saved={saved} />)
  await expect
    .element(page.getByLabelText('名称', { exact: true }))
    .toHaveFocus()
  await expect
    .element(page.getByLabelText('优先级'))
    .toHaveAttribute('readonly')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.element(page.getByText('填写 1–720 小时')).toBeVisible()
  expect(calls).not.toHaveBeenCalled()
  await page.getByLabelText('时长（小时）').fill('5')
  await page.getByLabelText('积分上限').fill('1000')
  await page.getByRole('button', { name: '周额度', exact: true }).click()
  await page.getByLabelText('积分上限').nth(1).fill('8000')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect
    .element(page.getByText('选择周起始日', { exact: true }).last())
    .toBeVisible()
  expect(calls).not.toHaveBeenCalled()
  await page.getByRole('combobox', { name: '周起始日' }).click()
  await page.getByRole('option', { name: '周一', exact: true }).click()
  await page.getByRole('combobox', { name: '时区' }).click()
  await page.getByRole('option', { name: 'Asia/Shanghai', exact: true }).click()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(calls).toHaveBeenCalledTimes(1)
})

it('includes administrators in policy assignments and preserves the draft on conflict', async () => {
  const writes: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/members')) {
        expect(url).not.toContain('role=member')
        return Response.json({ items: [member], total: 1, page: 1 })
      }
      writes.push(JSON.parse(String(init?.body)))
      return Response.json(
        { error: { message: '优先级已被其他策略使用' } },
        { status: 409 }
      )
    })
  )
  await show(<PolicyEditor isDefault={false} close={vi.fn()} saved={vi.fn()} />)
  await page.getByLabelText('名称', { exact: true }).fill('研发档位')
  await page.getByLabelText('优先级').fill('10')
  await page.getByLabelText('时长（小时）').fill('5')
  await page.getByLabelText('积分上限').fill('5000')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.element(page.getByText('至少选择一名成员')).toBeVisible()
  expect(writes).toHaveLength(0)
  await page
    .getByRole('checkbox', { name: '选择 额度管理员', exact: true })
    .click()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.element(page.getByText('优先级已被其他策略使用')).toBeVisible()
  expect(writes).toEqual([
    {
      name: '研发档位',
      priority: 10,
      member_ids: ['admin-member'],
      rules: [{ kind: 'fixed_hours', hours: 5, points: '5000' }],
    },
  ])
  await expect
    .element(page.getByLabelText('名称', { exact: true }))
    .toHaveValue('研发档位')
  await expect
    .element(
      page.getByRole('checkbox', { name: '选择 额度管理员', exact: true })
    )
    .toBeChecked()
})

it('shows highest-policy results from the API and updates them after an archive', async () => {
  let archived = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/archive')) {
        archived = true
        return Response.json({ ...higher, archived: true })
      }
      if (url.includes('/llm/members/'))
        return Response.json({ status: 'active', windows: [] })
      if (url.includes('/quota/matches')) {
        const chosen = archived ? base : higher
        return Response.json({
          items: [
            {
              member_id: member.id,
              name: member.name,
              email: member.email,
              role: member.role,
              selected: chosen,
              matched: archived ? [base] : [higher, base],
              rules: chosen.rules,
            },
          ],
          total: 1,
          enforcement: 'active',
        })
      }
      expect(init?.method).toBe('GET')
      return Response.json({
        items: archived ? [base] : [higher, base],
        total: archived ? 1 : 2,
        has_default: true,
        enforcement: 'active',
      })
    })
  )
  await show(<QuotaPoliciesPage />)
  await expect
    .element(page.getByRole('button', { name: '进阶', exact: true }))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/quota-policies-desktop.png' })
  await page.getByRole('tab', { name: '成员匹配', exact: true }).click()
  await expect
    .element(page.getByText('优先级 10', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('每周 · 8000 积分', { exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('tab', { name: '策略', exact: true }).click()
  await page.getByRole('button', { name: '进阶的更多操作' }).click()
  await page.getByRole('menuitem', { name: '归档', exact: true }).click()
  await expect
    .element(page.getByText('归档「进阶」后，成员将采用下一条适用策略。'))
    .toBeVisible()
  await page.getByRole('button', { name: '归档', exact: true }).click()
  await expect.element(page.getByRole('alertdialog')).not.toBeInTheDocument()
  await page.getByRole('tab', { name: '成员匹配', exact: true }).click()
  await expect
    .element(page.getByText('优先级 0', { exact: true }))
    .toBeVisible()
})

it.each(['save', 'archive', 'restore'] as const)(
  'refreshes cached member balances after policy %s without a manual refresh',
  async (action) => {
    let archived = action === 'restore'
    let current = structuredClone(higher)
    let reads = 0
    const chosen = () => (archived ? base : current)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/archive')) {
          archived = JSON.parse(String(init?.body)).archived
          return Response.json({ ...current, archived })
        }
        if (url.endsWith('/quota/policies/higher') && init?.method === 'PUT') {
          current = { ...current, ...JSON.parse(String(init.body)) }
          return Response.json(current)
        }
        if (url.endsWith(`/llm/members/${member.id}/quota`)) {
          reads++
          return Response.json({
            status: 'active',
            policy: chosen(),
            windows: [
              {
                rule: chosen().rules[0],
                used: '12',
                reserved: '0',
                remaining: String(
                  Math.max(0, Number(chosen().rules[0].points) - 12)
                ),
                started_at: base.created_at,
                resets_at: '2026-09-25T05:00:00Z',
              },
            ],
          })
        }
        if (url.includes('/quota/matches')) {
          return Response.json({
            items: [
              {
                member_id: member.id,
                name: member.name,
                email: member.email,
                role: member.role,
                selected: chosen(),
                matched: archived ? [base] : [current, base],
                rules: chosen().rules,
              },
            ],
            total: 1,
          })
        }
        if (url.includes('/members'))
          return Response.json({ items: [member], total: 1, page: 1 })
        if (url.includes('/quota/policies?')) {
          const items = url.includes('state=archived')
            ? archived
              ? [{ ...current, archived }]
              : []
            : archived
              ? [base]
              : [current, base]
          return Response.json({
            items,
            total: items.length,
            has_default: true,
          })
        }
        throw new Error(url)
      })
    )
    // Keep the cached balance fresh so only the mutation's invalidation can reload it.
    await show(<QuotaPoliciesPage />, Infinity)
    await page.getByRole('tab', { name: '成员匹配', exact: true }).click()
    await expect
      .element(page.getByRole('progressbar', { name: '5 小时剩余额度' }))
      .toHaveAttribute(
        'aria-valuetext',
        `剩余 ${archived ? 988 : 2988} / ${archived ? 1000 : 3000} 积分；已用 12；预占 0`
      )
    expect(reads).toBe(1)
    await page.getByRole('tab', { name: '策略', exact: true }).click()
    if (action === 'save') {
      await page.getByRole('button', { name: '进阶', exact: true }).click()
      await page.getByLabelText('积分上限').fill('0')
      await page.getByRole('button', { name: '保存', exact: true }).click()
      await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
    } else {
      if (action === 'restore') {
        await page.getByRole('combobox', { name: '状态' }).click()
        await page.getByRole('option', { name: '已归档', exact: true }).click()
      }
      const label = action === 'archive' ? '归档' : '恢复'
      await page.getByRole('button', { name: '进阶的更多操作' }).click()
      await page.getByRole('menuitem', { name: label, exact: true }).click()
      await page.getByRole('button', { name: label, exact: true }).click()
      await expect
        .element(page.getByRole('alertdialog'))
        .not.toBeInTheDocument()
    }
    await page.getByRole('tab', { name: '成员匹配', exact: true }).click()
    const remaining = action === 'save' ? 0 : action === 'archive' ? 988 : 2988
    await expect
      .element(page.getByRole('progressbar', { name: '5 小时剩余额度' }))
      .toHaveAttribute(
        'aria-valuetext',
        `剩余 ${remaining} / ${action === 'save' ? 0 : action === 'archive' ? 1000 : 3000} 积分；已用 12；预占 0`
      )
    expect(reads).toBe(2)
  }
)

it('fits narrow screens and cancellation does not write configuration', async () => {
  await page.viewport(390, 844)
  const writes = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (!url.includes('/members')) writes()
      return Response.json({ items: [member], total: 1, page: 1 })
    })
  )
  const close = vi.fn()
  await show(
    <PolicyEditor
      policy={higher}
      isDefault={false}
      close={close}
      saved={vi.fn()}
    />
  )
  await expect
    .element(
      page.getByRole('checkbox', { name: '选择 额度管理员', exact: true })
    )
    .toBeVisible()
  await page.getByRole('button', { name: '周额度', exact: true }).click()
  const dialog = page.getByRole('dialog').element()
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await expect
    .element(page.getByRole('button', { name: '保存', exact: true }))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/quota-editor-narrow.png' })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  expect(close).toHaveBeenCalledTimes(1)
  expect(writes).not.toHaveBeenCalled()
})

it('does not fabricate a default policy in the empty state and offers retry on read failure', async () => {
  let count = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      count++
      return count === 1
        ? Response.json({ error: { message: '读取失败' } }, { status: 503 })
        : Response.json({
            items: [],
            total: 0,
            has_default: false,
            enforcement: 'active',
          })
    })
  )
  await show(<QuotaPoliciesPage />)
  await expect
    .element(page.getByText('读取失败', { exact: true }))
    .toBeVisible()
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect.element(page.getByText('尚未设置默认策略')).toBeVisible()
  await page.getByRole('button', { name: '设置默认策略', exact: true }).click()
  await expect.element(page.getByLabelText('积分上限')).toHaveValue('')
  expect(count).toBe(2)
})
