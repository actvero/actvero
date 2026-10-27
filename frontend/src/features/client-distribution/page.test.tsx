import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ObjectStoragePage } from '@/features/object-storage/page'
import { ClientDistributionPage } from './page'

vi.mock('@/features/auth/session', () => ({
  useSession: () => ({ data: { csrf: 'test-csrf' } }),
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
const clients: QueryClient[] = []
afterEach(async () => {
  await cleanup()
  clients.splice(0).forEach((c) => c.clear())
  vi.unstubAllGlobals()
})
async function show(component: ReactNode = <ClientDistributionPage />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
}
const release = {
  id: '98c807fb-86b6-49d0-9f5a-e559ef915777',
  version: '1.2.0',
  channel: 'latest',
  notes: '修复问题',
  status: 'draft',
  revision: 4,
  minimum_os: { 'win-x64': 'Windows 10' },
  artifacts: [
    {
      id: '70fb1869-51ad-47d1-9df1-cd809e083bb2',
      filename: 'app.exe',
      target: 'win-x64',
      role: 'payload',
      size_bytes: 100,
      status: 'ready',
    },
  ],
}

it('publishes only after checking a plan and a separate confirmation', async () => {
  const writes: { url: string; body: Record<string, unknown> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
        writes.push({ url, body: JSON.parse(init.body as string) })
        if (url.endsWith('/plan'))
          return Response.json({
            id: 'ab098bcb-10b1-45f0-b01e-42127d4779c8',
            release_id: release.id,
            release_revision: 4,
            targets: { 'win-x64': 0 },
            expires_at: '2099-01-01T00:00:00Z',
          })
        return Response.json({ ...release, status: 'published' })
      }
      return Response.json({
        items: url.endsWith('/releases') ? [release] : [],
      })
    })
  )
  await show()
  await page.getByRole('button', { name: '检查并发布' }).click()
  expect(writes).toHaveLength(0)
  await waitForAnimations()
  await page.getByRole('button', { name: '检查发布条件' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认发布' }))
    .toBeVisible()
  expect(writes).toHaveLength(1)
  expect(writes[0].body).toEqual({ expected_revision: 4, targets: ['win-x64'] })
  await page.getByRole('button', { name: '确认发布' }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].body).toEqual({
    plan_id: 'ab098bcb-10b1-45f0-b01e-42127d4779c8',
  })
})

it('keeps failed publication visible and does not offer confirmation after failed checks', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url.endsWith('/plan')
        ? Response.json(
            { error: { message: 'blockmap 尚未校验完成' } },
            { status: 422 }
          )
        : Response.json({ items: url.endsWith('/releases') ? [release] : [] })
    )
  )
  await show()
  await page.getByRole('button', { name: '检查并发布' }).click()
  await waitForAnimations()
  await page.getByRole('button', { name: '检查发布条件' }).click()
  await expect.element(page.getByText('blockmap 尚未校验完成')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认发布' }))
    .not.toBeInTheDocument()
})

it('shows an access failure without retaining release controls', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json(
        { error: { message: '此操作仅限平台运营人员' } },
        { status: 403 }
      )
    )
  )
  await show()
  await expect.element(page.getByText('此操作仅限平台运营人员')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '新建版本' }))
    .toBeDisabled()
})

it('guides missing default storage to settings and hides technical upload inputs', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json({ items: url.endsWith('/releases') ? [release] : [] })
    )
  )
  await show()
  await page.getByRole('button', { name: '添加文件' }).click()
  await waitForAnimations()
  await expect
    .element(page.getByRole('link', { name: '前往设置' }))
    .toHaveAttribute('href', '/platform/settings/storage')
  await expect
    .element(page.getByRole('button', { name: '提交文件' }))
    .toBeDisabled()
  await expect.element(page.getByLabelText('文件用途')).not.toBeInTheDocument()
  await expect.element(page.getByLabelText('存储位置')).not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '刷新' }))
    .not.toBeInTheDocument()
})

it.each(['Windows x64', 'Windows ARM64'])(
  'uploads %s package and blockmap together with automatic roles and default storage',
  async (architecture) => {
    const writes: Record<string, unknown>[] = []
    const row = { ...release, artifacts: [] }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/object-storage'))
          return Response.json({
            items: [{ id: release.id, enabled: true, is_default: true }],
          })
        if (url.endsWith('/releases')) return Response.json({ items: [row] })
        if (url.endsWith('/heads')) return Response.json({ items: [] })
        if (url.endsWith('/releases/' + row.id)) return Response.json(row)
        if (url.includes('/artifacts/')) {
          writes.push(JSON.parse(String(init?.body)))
          return Response.json({})
        }
        if (url.endsWith('/start'))
          return Response.json({
            status: 'uploading',
            part_count: 1,
            part_size: 16 * 1024 * 1024,
            parts: {},
          })
        if (url.includes('/parts/')) {
          expect(init?.body).toBeInstanceOf(Blob)
          return Response.json({ number: 1, etag: 'part' })
        }
        return Response.json({ status: 'completed' })
      })
    )
    await show()
    await page.getByRole('button', { name: '添加文件' }).click()
    await waitForAnimations()
    if (architecture === 'Windows ARM64') {
      await page.getByRole('combobox', { name: '系统与架构' }).click()
      await page
        .getByRole('option', { name: 'Windows ARM64', exact: true })
        .click()
      await waitForAnimations()
    }
    await userEvent.upload(page.getByLabelText('构建文件', { exact: true }), [
      new File(['installer'], 'app.exe'),
      new File(['map'], 'app.exe.blockmap'),
    ])
    await page.getByRole('button', { name: '提交文件' }).click()
    await expect.poll(() => writes.length).toBe(2)
    expect(writes.map((w) => w.role)).toEqual(['payload', 'blockmap'])
    expect(
      writes.every(
        (w) =>
          w.target ===
          (architecture === 'Windows ARM64' ? 'win-arm64' : 'win-x64')
      )
    ).toBe(true)
    expect(
      writes.every((w) => w.storage_id === release.id && w.url === null)
    ).toBe(true)
    await expect.element(page.getByRole('dialog')).not.toBeInTheDocument()
  }
)

it('saves shared private storage without a public URL', async () => {
  let saved: Record<string, unknown> | undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        saved = JSON.parse(String(init.body))
        return Response.json(saved)
      }
      return Response.json({ items: [] })
    })
  )
  await show(<ObjectStoragePage />)
  await page.getByRole('button', { name: '添加存储' }).click()
  await waitForAnimations()
  await page.getByLabelText('名称', { exact: true }).fill('默认存储')
  await page.getByLabelText('S3 服务地址').fill('https://s3.example.com')
  await page.getByLabelText('Bucket', { exact: true }).fill('client-builds')
  await page.getByLabelText('访问密钥', { exact: true }).fill('example-access')
  await page.getByLabelText('秘密密钥', { exact: true }).fill('example-secret')
  await page.getByRole('button', { name: '保存存储' }).click()
  await expect.poll(() => saved?.public_url).toBe('')
  expect(saved?.is_default).toBe(true)
})
