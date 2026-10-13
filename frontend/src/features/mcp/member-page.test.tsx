import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { MemberMcpPage } from './member-page'

vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({ title, children }: { title: string; children: ReactNode }) => (
    <main>
      <h1>{title}</h1>
      {children}
    </main>
  ),
}))

vi.mock('@/features/auth/session', () => ({
  useSession: () => ({
    data: {
      organization: { tenant_id: 'organization', role: 'member' },
      user: { id: 'member' },
      csrf: 'csrf-token',
    },
  }),
  useOrganization: () => ({
    organization: { tenant_id: 'organization' },
    user: { id: 'member' },
    csrf: 'csrf-token',
  }),
}))

const services = [
  {
    id: 'recruit-bridge',
    name: 'RecruitBridge',
    display_name: '示例招聘助手',
    description: '招聘岗位工具',
    icon: '',
    examples: [],
    audience: 'organization',
    transport: 'http',
    url: 'https://example.com/mcp',
    version: 1,
    configured: false,
    checked_at: null,
    error: null,
    protocol: '',
    counts: { tools: 17 },
    enabled: true,
    auth_mode: 'personal',
    credential_fields: [
      {
        key: 'token',
        label: 'Odoo API Key',
        header: 'Authorization',
        bearer: true,
      },
    ],
  },
  {
    id: 'disabled',
    name: 'Disabled',
    display_name: '',
    description: '',
    icon: '',
    examples: [],
    audience: 'organization',
    transport: 'http',
    url: 'https://example.com/disabled',
    version: 1,
    configured: false,
    checked_at: null,
    error: null,
    protocol: '',
    counts: { tools: 2 },
    enabled: false,
    auth_mode: 'personal',
    credential_fields: [
      { key: 'token', label: 'API Key', header: 'Authorization', bearer: true },
    ],
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function show(fetcher: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetcher)
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemberMcpPage />
    </QueryClientProvider>
  )
}

it('只展示已启用的组织服务和工具数量', async () => {
  const fetcher = vi.fn(async () => Response.json({ items: services }))
  await show(fetcher)
  await expect.element(page.getByText('示例招聘助手')).toBeVisible()
  await expect.element(page.getByText('工具 17')).toBeVisible()
  await expect.element(page.getByText('Disabled')).not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '配置个人凭据' }))
    .toBeVisible()
})

it('保存个人凭据后立即调用 discover，且不回显 Key 或 Bearer', async () => {
  let calls = 0
  type ListedService = Omit<(typeof services)[number], 'checked_at'> & {
    checked_at: string | null
  }
  let listed: ListedService[] = services
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url.endsWith('/mcp/services') && options.method === 'GET')
      return Response.json({ items: listed })
    if (url.endsWith('/connection')) return Response.json({ message: 'saved' })
    if (url.endsWith('/discover')) {
      calls++
      listed = services.map((service) => ({
        ...service,
        configured: service.id === 'recruit-bridge' ? true : service.configured,
        checked_at:
          service.id === 'recruit-bridge'
            ? '2026-09-30T00:00:00Z'
            : service.checked_at,
      }))
      return Response.json({
        items: [],
        protocol: '',
        negotiated: {},
        checked_at: '2026-09-30T00:00:00Z',
        error: null,
      })
    }
    return Response.json({ items: services })
  })
  await show(fetcher)
  await userEvent.click(page.getByRole('button', { name: '配置个人凭据' }))
  const input = page.getByLabelText('Odoo API Key', { exact: true })
  await expect.element(input).toHaveValue('')
  await userEvent.fill(input, 'wang-huan-secret')
  await userEvent.click(page.getByRole('button', { name: '保存凭据' }))
  await expect.poll(() => calls).toBe(1)
  await expect.element(page.getByRole('status')).toHaveTextContent('已连接')
  const connection = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith('/connection')
  )
  expect(connection?.[1]).toMatchObject({
    method: 'PUT',
    headers: { 'X-CSRF-Token': 'csrf-token' },
  })
  expect(JSON.parse(String(connection?.[1].body))).toEqual({
    values: { token: 'wang-huan-secret' },
  })
  expect(JSON.stringify(document.body.textContent)).not.toContain(
    'Bearer wang-huan-secret'
  )
  await expect.element(input).not.toBeInTheDocument()
})
