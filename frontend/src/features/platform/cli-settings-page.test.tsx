import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { toast } from 'sonner'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { PlatformCliSettingsPage } from './cli-settings-page'

vi.mock('@/features/auth/session', () => ({
  useSession: () => ({ data: { csrf: 'csrf-test' } }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({ title, children }: { title: string; children: ReactNode }) => (
    <main>
      <h1>{title}</h1>
      {children}
    </main>
  ),
}))
const initial = {
  enabled: false,
  source: 'environment',
  server_url: 'https://platform.example.com',
  client_id: 'actvero-cli',
  issuer: 'https://identity.example.com/realms/platform',
}
const clients: QueryClient[] = []
async function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <PlatformCliSettingsPage />
    </QueryClientProvider>
  )
  return client
}
afterEach(async () => {
  await cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 900)
})

it('requires saving the switch before enabling copy and persists only the enabled field', async () => {
  let enabled = false
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-test' })
      expect(JSON.parse(init.body as string)).toEqual({ enabled: true })
      enabled = true
    }
    return Response.json({
      ...initial,
      enabled,
      source: enabled ? 'platform' : 'environment',
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const client = await show()
  const copy = page.getByRole('button', { name: '复制给 Agent' })
  await expect.element(copy).toBeDisabled()
  await page.getByRole('switch', { name: '开启 CLI 接入' }).click()
  await expect.element(copy).toBeDisabled()
  expect(fetcher.mock.calls.every(([, init]) => init?.method !== 'PUT')).toBe(
    true
  )
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect.element(copy).toBeEnabled()
  expect(client.getQueryData(['platform', 'cli'])).toMatchObject({
    enabled: true,
    source: 'platform',
  })
})

it('copies the canonical platform, fixed version and selected scope with human login and organization selection', async () => {
  const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ ...initial, enabled: true }))
  )
  await show()
  await page.getByRole('button', { name: '复制给 Agent' }).click()
  const read = copy.mock.calls[0][0]
  expect(read).toContain('https://platform.example.com')
  expect(read).toContain('@actvero/cli@0.2.0-dev.1')
  expect(read).not.toContain('--write')
  expect(read).toContain('本人在浏览器完成登录')
  expect(read).toContain('多个可用组织')
  expect(read).toContain('不自动创建、发布或删除')
  expect(read).not.toContain('csrf-test')
  await page.getByRole('radio', { name: '读写管理' }).click()
  await page.getByRole('button', { name: '复制给 Agent' }).click()
  expect(copy.mock.calls[1][0]).toContain(
    'auth login --server <平台地址> --write'
  )
  expect(copy.mock.calls[1][0]).toContain('auth logout --server <平台地址>')
  expect(copy.mock.calls[1][0]).toContain('不代表我已经授权所有业务操作')
})

it('preserves a failed draft and stops further actions after permission is revoked', async () => {
  let finish!: (value: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'PUT'
        ? new Promise<Response>((resolve) => {
            finish = resolve
          })
        : Response.json(initial)
    )
  )
  await show()
  await page.getByRole('switch', { name: '开启 CLI 接入' }).click()
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect
    .element(page.getByRole('button', { name: '保存中…' }))
    .toBeDisabled()
  await expect.element(page.getByRole('switch')).toBeDisabled()
  finish(
    Response.json({ error: { message: '仅限平台运营人员' } }, { status: 403 })
  )
  await expect.element(page.getByText('仅限平台运营人员')).toBeVisible()
  await expect.element(page.getByRole('switch')).toBeChecked()
  await expect.element(page.getByRole('switch')).toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '复制给 Agent' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '保存设置' }))
    .toBeDisabled()
})

it('allows loading retry and manual copy when the clipboard is unavailable on a narrow screen', async () => {
  let fail = true
  const errorToast = vi.spyOn(toast, 'error')
  vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(
    new Error('denied')
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      fail
        ? Response.json({ error: { message: '读取失败' } }, { status: 503 })
        : Response.json({ ...initial, enabled: true })
    )
  )
  await page.viewport(390, 844)
  await show()
  await expect.element(page.getByText('读取失败')).toBeVisible()
  expect(page.getByRole('switch').query()).toBeNull()
  fail = false
  await page.getByRole('button', { name: '重试' }).click()
  await page.getByRole('button', { name: '复制给 Agent' }).click()
  expect(errorToast).toHaveBeenCalledWith(
    '无法访问剪贴板，请选中下方指令手动复制'
  )
  await expect
    .element(page.getByRole('textbox', { name: '接入指令预览' }))
    .toHaveValue(expect.stringContaining('https://platform.example.com'))
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth
  )
})
