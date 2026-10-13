import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { PlatformPortalSettingsPage } from './portal-settings-page'

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
const clients: QueryClient[] = []
async function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <PlatformPortalSettingsPage />
    </QueryClientProvider>
  )
  return client
}
afterEach(async () => {
  await cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.unstubAllGlobals()
  await page.viewport(1280, 900)
})

it('only saves explicitly and refreshes homepage policy after a successful save', async () => {
  let enabled = false
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      expect(init.headers).toMatchObject({ 'X-CSRF-Token': 'csrf-test' })
      enabled = JSON.parse(init.body as string).portal_enabled
    }
    return Response.json({ portal_enabled: enabled })
  })
  vi.stubGlobal('fetch', fetcher)
  const client = await show()
  const toggle = page.getByRole('switch', { name: '开启门户首页' })
  const save = page.getByRole('button', { name: '保存设置' })
  await expect.element(toggle).not.toBeChecked()
  await expect.element(save).toBeDisabled()
  await userEvent.click(toggle)
  expect(fetcher.mock.calls.every(([, init]) => init?.method !== 'PUT')).toBe(
    true
  )
  await userEvent.click(save)
  await expect.element(save).toBeDisabled()
  expect(client.getQueryData(['public', 'site'])).toEqual({
    portal_enabled: true,
  })
  expect(enabled).toBe(true)
})

it('keeps a failed draft and disables repeat submission while saving', async () => {
  let finish!: (response: Response) => void
  let fail = true
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'PUT' && fail)
      return new Promise<Response>((resolve) => {
        finish = resolve
      })
    return Response.json({ portal_enabled: init?.method === 'PUT' })
  })
  vi.stubGlobal('fetch', fetcher)
  await show()
  const toggle = page.getByRole('switch', { name: '开启门户首页' })
  await userEvent.click(toggle)
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect
    .element(page.getByRole('button', { name: '保存中…' }))
    .toBeDisabled()
  await expect.element(toggle).toBeDisabled()
  finish(Response.json({ error: { message: '保存暂时失败' } }, { status: 503 }))
  await expect.element(page.getByText('保存暂时失败')).toBeVisible()
  await expect.element(toggle).toBeChecked()
  fail = false
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect
    .element(page.getByRole('button', { name: '保存设置' }))
    .toBeDisabled()
})

it('prevents further changes after the server revokes permission', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'PUT'
        ? Response.json(
            { error: { message: '仅限平台运营人员' } },
            { status: 403 }
          )
        : Response.json({ portal_enabled: false })
    )
  )
  await show()
  const toggle = page.getByRole('switch', { name: '开启门户首页' })
  await toggle.click()
  await page.getByRole('button', { name: '保存设置' }).click()
  await expect.element(page.getByText('仅限平台运营人员')).toBeVisible()
  await expect.element(toggle).toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '保存设置' }))
    .toBeDisabled()
})

it('retries loading and keeps switch, description and save usable on a narrow screen', async () => {
  let fail = true
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      fail
        ? Response.json({ error: { message: '读取设置失败' } }, { status: 503 })
        : Response.json({ portal_enabled: true })
    )
  )
  await page.viewport(390, 844)
  await show()
  await expect.element(page.getByText('读取设置失败')).toBeVisible()
  expect(page.getByRole('switch').query()).toBeNull()
  fail = false
  await page.getByRole('button', { name: '重试' }).click()
  const toggle = page.getByRole('switch', { name: '开启门户首页' })
  await expect.element(toggle).toBeChecked()
  await userEvent.click(toggle)
  await userEvent.keyboard('{Space}')
  await expect.element(toggle).toBeChecked()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth
  )
})
