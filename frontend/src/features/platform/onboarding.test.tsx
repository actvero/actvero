import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ApplicationsPage } from './applications-page'
import { OrganizationInvitationsPage } from './invitations-page'
import { OrganizationOnboardingPage } from './organization-onboarding-page'
import { RegistrationSettingsPage } from './registration-settings-page'

const fixture = vi.hoisted(() => ({
  session: {
    authenticated: true,
    csrf: 'csrf',
    user: { id: 'user', name: '当前用户', email: 'current@example.com' } as {
      id: string
      name: string
      email: string
    } | null,
  },
}))
vi.mock('@/features/auth/session', () => ({
  useSession: () => ({ data: fixture.session }),
  loginUrl: (next: string, _switch: boolean, flow: string) =>
    `/api/v1/auth/login?next=${encodeURIComponent(next)}&switch=true&flow=${flow}`,
}))
vi.mock('@/features/auth/auth-layout', () => ({
  AuthLayout: ({ title, children }: { title: string; children: ReactNode }) => (
    <main>
      <h1>{title}</h1>
      {children}
    </main>
  ),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    children,
    action,
  }: {
    title: string
    children: ReactNode
    action?: ReactNode
  }) => (
    <main>
      <h1>{title}</h1>
      {action}
      {children}
    </main>
  ),
}))
vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children }: { to: string; children: ReactNode }) => (
    <a href={to}>{children}</a>
  ),
}))
const response = (body: unknown, status = 200) =>
  new Response(
    JSON.stringify(
      typeof body === 'object' &&
        body !== null &&
        'state' in body &&
        body.state === 'form'
        ? { account: fixture.session.user, ...body }
        : body
    ),
    {
      status,
      headers: { 'content-type': 'application/json' },
    }
  )
function mount(content: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={client}>{content}</QueryClientProvider>)
  return client
}
const testUrl = window.location.href
const flowId = '10000000-0000-4000-8000-000000000001'
beforeEach(() => {
  window.history.replaceState(window.history.state, '', `?flow=${flowId}`)
  fixture.session.authenticated = true
  fixture.session.user = {
    id: 'user',
    name: '当前用户',
    email: 'current@example.com',
  }
})
afterEach(() => {
  window.history.replaceState(window.history.state, '', testUrl)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
it('existing accounts enter only the organization name and submit a real application', async () => {
  let state = 'form'
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') state = 'pending'
    return response({
      state,
      mode: 'approval',
      organization_name: '',
      verify_email: false,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  mount(<OrganizationOnboardingPage />)
  await expect.element(page.getByText('current@example.com')).toBeVisible()
  expect(
    page.getByRole('textbox', { name: '邮箱', exact: true }).query()
  ).toBeNull()
  await page.getByRole('textbox', { name: '组织名称' }).fill('申请组织')
  await page.getByRole('button', { name: '提交申请', exact: true }).click()
  await expect
    .element(page.getByRole('heading', { name: '申请已提交' }))
    .toBeVisible()
  const call = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    organization_name: '申请组织',
    invitation: false,
    confirmed_user_id: 'user',
  })
})
it('a rejected registration clears its password and does not put it in mutation cache', async () => {
  fixture.session.authenticated = false
  fixture.session.user = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'POST'
        ? response({ error: { message: '请登录已有账号' } }, 409)
        : response({ state: 'form', mode: 'invite', verify_email: false })
    )
  )
  const client = mount(<OrganizationOnboardingPage invitation />)
  expect(page.getByRole('textbox', { name: '组织名称' }).query()).toBeNull()
  await page
    .getByRole('textbox', { name: '管理员姓名', exact: true })
    .fill('新用户')
  await page
    .getByRole('textbox', { name: '邮箱', exact: true })
    .fill('new@example.com')
  await page
    .getByLabelText('密码', { exact: true })
    .fill('Test-password-123456')
  await page.getByRole('button', { name: '创建账号并继续' }).click()
  await expect
    .element(page.getByText('请登录已有账号', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByLabelText('密码', { exact: true }))
    .toHaveValue('')
  expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain(
    'Test-password-123456'
  )
})
it('does not allow public modes without mail configuration', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      response({
        mode: 'invite',
        invitation_verify_email: false,
        mail_enabled: false,
      })
    )
  )
  mount(<RegistrationSettingsPage />)
  await expect
    .element(page.getByRole('radio', { name: '仅邀请开通' }))
    .toBeEnabled()
  await expect
    .element(page.getByRole('radio', { name: '申请审核开通' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('radio', { name: '自助开通' }))
    .toBeDisabled()
})
it('email invitations require a recipient and send it in the creation request', async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST')
      return response({
        invitation: { id: 'new' },
        invite_url: 'http://localhost/invite',
        mail_status: 'sent',
      })
    if (url.endsWith('/mail')) return response({ enabled: true })
    return response({ items: [], total: 0 })
  })
  vi.stubGlobal('fetch', fetcher)
  mount(<OrganizationInvitationsPage />)
  await page.getByRole('button', { name: '生成邀请', exact: true }).click()
  await page.getByRole('tab', { name: '邮件邀请' }).click()
  await page
    .getByRole('textbox', { name: '收件邮箱' })
    .fill('recipient@example.com')
  await page.getByRole('button', { name: '生成并发送' }).click()
  await expect
    .poll(() => fetcher.mock.calls.some(([, init]) => init?.method === 'POST'))
    .toBe(true)
  const call = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    expires_in_hours: 72,
    recipient_email: 'recipient@example.com',
  })
})
it('review requires confirmation and a reason when rejecting', async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === 'POST'
      ? response({ message: '已拒绝' })
      : response({
          items: [
            {
              id: 'application',
              organization_name: '申请组织',
              applicant_name: '申请人',
              applicant_email: 'applicant@example.com',
              status: 'pending',
              created_at: '2026-10-03T00:00:00Z',
            },
          ],
          total: 1,
        })
  )
  vi.stubGlobal('fetch', fetcher)
  mount(<ApplicationsPage />)
  await page.getByRole('button', { name: '拒绝', exact: true }).click()
  await page.getByRole('button', { name: '确认拒绝' }).click()
  await expect
    .element(page.getByText('请填写拒绝原因', { exact: true }))
    .toBeVisible()
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
    false
  )
  await page.getByRole('textbox', { name: '拒绝原因' }).fill('请使用公司名称')
  await page.getByRole('button', { name: '确认拒绝' }).click()
  await expect
    .poll(() => fetcher.mock.calls.some(([, init]) => init?.method === 'POST'))
    .toBe(true)
})

it('keeps resumed opening explicit and binds submission to the displayed account', async () => {
  let completed = false
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/submit?')) {
      completed = true
      expect(JSON.parse(String(init?.body))).toMatchObject({
        confirmed_user_id: 'user',
        organization_name: '保留的草稿',
      })
    }
    return response({
      state: completed ? 'completed' : 'form',
      mode: 'invite',
      organization_name: '保留的草稿',
      resume: true,
      organization_id: completed ? 'new-org' : null,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const client = mount(<OrganizationOnboardingPage invitation />)
  await expect
    .element(page.getByRole('textbox', { name: '组织名称' }))
    .toHaveValue('保留的草稿')
  await client.invalidateQueries({ queryKey: ['organization-opening'] })
  expect(fetcher.mock.calls.some(([url]) => url.includes('/submit?'))).toBe(
    false
  )
  await page.getByRole('button', { name: '开通组织', exact: true }).click()
  await expect
    .element(page.getByRole('heading', { name: '组织已开通' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '进入组织' }))
    .toBeVisible()
})

it('puts existing-account login alongside registration and clears the password when switching', async () => {
  fixture.session.authenticated = false
  fixture.session.user = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response({ state: 'form', mode: 'invite' }))
  )
  mount(<OrganizationOnboardingPage invitation />)
  await page
    .getByLabelText('密码', { exact: true })
    .fill('private-test-password')
  await page.getByRole('tab', { name: '使用已有账号' }).click()
  await expect
    .element(page.getByRole('link', { name: '登录并继续' }))
    .toHaveAttribute(
      'href',
      `/api/v1/auth/login?next=%2Forganization-invite&switch=true&flow=${flowId}`
    )
  expect(page.getByRole('textbox', { name: '管理员姓名' }).query()).toBeNull()
  await userEvent.keyboard('{ArrowLeft}')
  await expect
    .element(page.getByLabelText('密码', { exact: true }))
    .toHaveValue('')
})

it('shows the mismatched recipient and current account without an opening action', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      response({
        state: 'mismatch',
        recipient_email: 'invited@example.com',
        account: fixture.session.user,
      })
    )
  )
  mount(<OrganizationOnboardingPage invitation />)
  await expect.element(page.getByText('current@example.com')).toBeVisible()
  await expect
    .element(
      page.getByText('请使用受邀邮箱 invited@example.com 对应的账号登录。')
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '使用其他账号' }))
    .toBeVisible()
  expect(
    page.getByRole('button', { name: '开通组织', exact: true }).query()
  ).toBeNull()
})

it('keeps the invitation token until a context is created and isolates requests by flow', async () => {
  window.history.replaceState(
    window.history.state,
    '',
    '#invitation-token-1234567890'
  )
  let attempts = 0
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/flows')) {
      attempts++
      expect(JSON.parse(String(init?.body))).toMatchObject({
        token: 'invitation-token-1234567890',
        invitation: true,
      })
      if (attempts === 1)
        return response({ error: { message: '暂时不可用' } }, 503)
      return response({ flow_id: 'second-flow' })
    }
    expect(url).toContain('flow=second-flow')
    return response({ state: 'form', mode: 'invite' })
  })
  vi.stubGlobal('fetch', fetcher)
  mount(<OrganizationOnboardingPage invitation />)
  await expect
    .element(page.getByText('暂时不可用', { exact: true }))
    .toBeVisible()
  expect(window.location.hash).toBe('#invitation-token-1234567890')
  await page.getByRole('button', { name: '重试' }).click()
  await expect
    .element(page.getByRole('textbox', { name: '组织名称' }))
    .toBeVisible()
  expect(window.location.hash).toBe('')
  expect(window.location.search).toBe('?flow=second-flow')
})

it('shows an existing account and organization form without overflow at 390px', async () => {
  await page.viewport(390, 844)
  try {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        response({
          state: 'form',
          mode: 'invite',
          account: {
            ...fixture.session.user,
            email: 'a-very-long-administrator-address@organization.example.com',
          },
        })
      )
    )
    mount(<OrganizationOnboardingPage invitation />)
    await expect
      .element(page.getByRole('button', { name: '开通组织', exact: true }))
      .toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '使用其他账号' }))
      .toBeVisible()
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
      window.innerWidth
    )
  } finally {
    await page.viewport(1280, 900)
  }
})
