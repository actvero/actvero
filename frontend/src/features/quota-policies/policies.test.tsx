import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
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
  name: '标准额度',
  is_default: true,
  mode: 'limited',
  rules: [{ kind: 'fixed_hours', hours: 5, points: '1000' }],
  archived: false,
  version: 1,
  created_at: '2026-09-25T00:00:00Z',
  updated_at: '2026-09-25T00:00:00Z',
}
const unlimited: Policy = {
  ...base,
  id: 'unlimited',
  name: '团队不限额',
  is_default: false,
  mode: 'unlimited',
  rules: [],
}
const clients: QueryClient[] = []
async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  const view = await render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
  await waitForAnimations()
  return view
}
beforeEach(async () => {
  await page.viewport(1280, 900)
})
afterEach(async () => {
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 800)
})

it('keeps decimal and zero limits explicit and discards hidden limits in unlimited mode', () => {
  const draft = values(base)
  draft.rules[0].points = '0.000000000001'
  expect(policyInput(draft).rules?.[0].points).toBe('0.000000000001')
  draft.rules[0].points = '0'
  expect(policySchema.safeParse(draft).success).toBe(true)
  expect(policyInput(draft).mode).toBe('limited')
  draft.rules.push({ ...draft.rules[0] })
  expect(policySchema.safeParse(draft).success).toBe(false)
  const fresh = values()
  fresh.name = '不限额'
  fresh.mode = 'unlimited'
  expect(policySchema.safeParse(fresh).success).toBe(true)
  expect(policyInput(fresh)).toEqual({
    name: '不限额',
    mode: 'unlimited',
    is_default: false,
    rules: [],
  })
})

it('creates a reusable unlimited policy without member selection or priority fields', async () => {
  const sent: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      sent.push(JSON.parse(String(init?.body)))
      return Response.json(unlimited)
    })
  )
  const saved = vi.fn()
  await show(<PolicyEditor isDefault={false} close={vi.fn()} saved={saved} />)
  await page.getByRole('textbox', { name: '名称' }).fill('团队不限额')
  await page.getByRole('combobox', { name: '额度方式' }).click()
  await page.getByRole('option', { name: '不限额度', exact: true }).click()
  await expect
    .element(page.getByRole('textbox', { name: '积分上限' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByText('优先级', { exact: true }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByText('适用成员', { exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(sent).toEqual([
    { name: '团队不限额', is_default: false, mode: 'unlimited', rules: [] },
  ])
})

it('shows inherited and assigned policies and saves a versioned member assignment', async () => {
  let assigned = false
  const sent: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/assignment')) {
        sent.push(JSON.parse(String(init?.body)))
        assigned = true
        return Response.json({})
      }
      if (url.includes('/quota/matches'))
        return Response.json({
          items: [
            {
              member_id: 'member-one',
              name: '测试成员',
              email: 'member@example.com',
              role: 'administrator',
              status: 'active',
              avatar_url: null,
              assigned: assigned ? unlimited : null,
              assignment_version: assigned ? 4 : 3,
              selected: assigned ? unlimited : base,
              rules: assigned ? [] : base.rules,
            },
          ],
          total: 1,
          enforcement: 'active',
        })
      if (url.includes('/quota/policies'))
        return Response.json({
          items: [base, unlimited],
          total: 2,
          has_default: true,
        })
      if (url.includes('/members/member-one/quota'))
        return Response.json({
          status: 'unlimited',
          policy: { name: unlimited.name },
          windows: [],
        })
      throw new Error('Unexpected request ' + url)
    })
  )
  await show(<QuotaPoliciesPage />)
  await page.getByRole('tab', { name: '成员分配' }).click()
  await expect
    .element(page.getByText('继承默认', { exact: true }))
    .toBeVisible()
  await page.getByRole('button', { name: '分配策略', exact: true }).click()
  await page.getByRole('radio', { name: /团队不限额/ }).click()
  await page.getByRole('button', { name: '保存分配', exact: true }).click()
  await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
  expect(sent).toEqual([{ policy_id: 'unlimited', version: 3 }])
  await expect
    .element(page.getByText('指定策略', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('其他命中', { exact: true }))
    .not.toBeInTheDocument()
})

it('keeps the member assignment dialog open when a concurrent change is rejected', async () => {
  const { AssignmentButton } = await import('./assignment-dialog')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      init?.method === 'PUT'
        ? Response.json(
            { error: { message: '成员额度策略已被修改，请刷新后重试' } },
            { status: 409 }
          )
        : Response.json({
            items: [base, unlimited],
            total: 2,
            has_default: true,
          })
    )
  )
  await show(
    <AssignmentButton
      member={{
        member_id: 'm',
        name: '成员',
        email: null,
        role: 'member',
        status: 'active',
        avatar_url: null,
        assigned: null,
        selected: base,
        assignment_version: 2,
        rules: base.rules,
      }}
    />
  )
  await page.getByRole('button', { name: '分配策略', exact: true }).click()
  await page.getByRole('radio', { name: /团队不限额/ }).click()
  await page.getByRole('button', { name: '保存分配', exact: true }).click()
  await expect
    .element(
      page.getByText('成员额度策略已被修改，请刷新后重试', { exact: true })
    )
    .toBeVisible()
  await expect.element(page.getByRole('dialog')).toBeVisible()
})

it('lets a paused member return to inheritance without granting another policy', async () => {
  const { AssignmentButton } = await import('./assignment-dialog')
  const sent: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        sent.push(JSON.parse(String(init.body)))
        return Response.json({})
      }
      return Response.json({ items: [base, unlimited], total: 2, has_default: true })
    })
  )
  await show(
    <AssignmentButton
      member={{
        member_id: 'paused', name: '暂停成员', email: null, role: 'member',
        status: 'paused', avatar_url: null, assigned: unlimited, selected: unlimited,
        assignment_version: 5, rules: [],
      }}
    />
  )
  await page.getByRole('button', { name: '分配策略', exact: true }).click()
  await expect.element(page.getByRole('radio', { name: /团队不限额/ })).toBeDisabled()
  await expect.element(page.getByRole('button', { name: '保存分配' })).toBeDisabled()
  await page.getByRole('radio', { name: '继承组织默认策略' }).click()
  await page.getByRole('button', { name: '保存分配' }).click()
  await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
  expect(sent).toEqual([{ policy_id: null, version: 5 }])
})
