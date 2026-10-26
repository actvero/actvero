import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { MembersPage } from './page'

const { search, navigate } = vi.hoisted(() => ({
  search: { tab: 'invitations', page: 1, q: '', role: '', status: '' },
  navigate: vi.fn(),
}))
vi.mock('@tanstack/react-router', () => ({
  getRouteApi: () => ({
    useSearch: () => search,
    useNavigate: () => navigate,
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({ title, children }: { title: string; children: ReactNode }) => (
    <main className='p-6'>
      <h1>{title}</h1>
      {children}
    </main>
  ),
}))

const invitation: Schema['InvitationView'] = {
  id: 'invitation-one',
  email: 'invitee@example.com',
  name: '',
  status: 'pending',
  mail_status: 'submitted',
  created_at: '2026-01-01T00:00:00Z',
  expires_at: '2026-01-02T00:00:00Z',
  last_sent_at: '2026-01-01T00:00:00Z',
}
const session = {
  user: { id: 'admin', email: 'admin@example.com' },
  organization: { tenant_id: 'organization-one' },
  csrf: 'csrf-before-refresh',
  invitations_enabled: true,
}
const listKey = [
  'organization',
  'organization-one',
  'admin',
  '/enterprises/organization-one',
  search,
]
const clients: QueryClient[] = []
async function show() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity, refetchOnMount: false },
      mutations: { retry: false },
    },
  })
  clients.push(client)
  client.setQueryData(['session'], session)
  client.setQueryData(listKey, { items: [invitation], total: 1 })
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/auth/session')) return Response.json(session)
    if (init?.method === 'POST')
      return Response.json({ ...invitation, status: 'revoked' })
    return Response.json({ items: [invitation], total: 1 })
  })
  vi.stubGlobal('fetch', fetcher)
  await render(
    <QueryClientProvider client={client}>
      <MembersPage />
    </QueryClientProvider>
  )
  return { client, fetcher }
}
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.splice(0).forEach((client) => client.clear())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('keeps the invitation menu and trigger mounted through session and list refreshes', async () => {
  const { client, fetcher } = await show()
  const trigger = page.getByRole('button', {
    name: '管理邀请 invitee@example.com',
  })
  const original = trigger.element()
  await userEvent.hover(trigger)
  await trigger.click()
  await expect.element(page.getByRole('menu')).toBeVisible()
  await waitForAnimations()
  await userEvent.hover(page.getByRole('menuitem', { name: '重发邀请' }))

  client.setQueryData(['session'], { ...session, csrf: 'csrf-after-refresh' })
  await expect.poll(() => original.isConnected).toBe(true)
  client.setQueryData(listKey, {
    items: [{ ...invitation, expires_at: '2026-01-03T00:00:00Z' }],
    total: 1,
  })
  await expect.element(page.getByText(/2026\/1\/3/)).toBeInTheDocument()
  expect(original.isConnected).toBe(true)
  await expect.element(page.getByRole('menu')).toBeVisible()
  await userEvent.keyboard('{Escape}')
  await expect.element(page.getByRole('menu')).not.toBeInTheDocument()
  await expect.element(trigger).toHaveFocus()
  expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
    false
  )
})

it('keeps confirmation attached to its invitation when refreshed rows are reordered', async () => {
  const { client, fetcher } = await show()
  await page
    .getByRole('button', { name: '管理邀请 invitee@example.com' })
    .click()
  await page.getByRole('menuitem', { name: '撤销邀请' }).click()
  const confirmation = page.getByRole('alertdialog', { name: '撤销邀请？' })
  await expect.element(confirmation).toBeVisible()
  await waitForAnimations()

  client.setQueryData(listKey, {
    items: [
      { ...invitation, id: 'invitation-two', email: 'other@example.com' },
      invitation,
    ],
    total: 2,
  })
  await expect
    .element(page.getByText('other@example.com', { exact: true }))
    .toBeInTheDocument()
  await expect.element(confirmation).toBeVisible()
  await expect.element(confirmation).toHaveTextContent('invitee@example.com')
  await expect.element(confirmation).not.toHaveTextContent('other@example.com')
  client.setQueryData(['session'], { ...session, csrf: 'csrf-after-refresh' })
  await confirmation.getByRole('button', { name: '确认', exact: true }).click()
  await expect
    .poll(
      () =>
        fetcher.mock.calls.filter(([, init]) => init?.method === 'POST').length
    )
    .toBe(1)
  const write = fetcher.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(write[0]).toBe(
    '/api/v1/enterprises/organization-one/invitations/invitation-one/revoke'
  )
  expect(write[1]?.headers).toMatchObject({
    'X-CSRF-Token': 'csrf-after-refresh',
  })
})
