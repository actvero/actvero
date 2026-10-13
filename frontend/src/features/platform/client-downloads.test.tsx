import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import type { Release } from '@/features/client-downloads/data'
import { ClientDownloadsSettingsPage } from './client-downloads-page'
import { ClientReleaseEditor } from './client-release-editor'

vi.mock('@/features/auth/session', () => ({
  useSession: () => ({ data: { csrf: 'csrf-test' } }),
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
  await page.viewport(1280, 900)
})
function saved(status: Release['status'] = 'draft'): Release {
  return {
    id: 'e6cf47b7-e5c6-4c59-9839-6ea06a12d1dc',
    version: '1.2.0',
    release_date: '2026-10-06',
    notes: '原说明',
    assets: [
      {
        platform: 'windows',
        architecture: 'x64',
        url: 'https://files.example.com/setup.exe',
        filename: 'setup.exe',
        minimum_os: 'Windows 11',
        size_bytes: null,
        sha256: '',
      },
    ],
    status,
    revision: 1,
    created_at: '2026-10-06T00:00:00Z',
    updated_at: '2026-10-06T00:00:00Z',
  }
}
async function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return client
}
const error = (message: string, status = 503) =>
  Response.json({ error: { message } }, { status })
function editor(
  record: Release | null = saved(),
  denied = vi.fn(),
  close = vi.fn()
) {
  return (
    <ClientReleaseEditor
      saved={record}
      recommendations={[]}
      onClose={close}
      onChanged={async () => {}}
      onDenied={denied}
    />
  )
}
it('修改不会自动保存，保存草稿带修订与 CSRF，不发布', async () => {
  const writes: RequestInit[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        writes.push(init)
        return Response.json({
          ...saved(),
          ...JSON.parse(init.body as string),
          revision: 2,
        })
      }
      return Response.json([])
    })
  )
  await mount(editor())
  await page.getByRole('textbox', { name: '更新说明' }).fill('新说明')
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].headers).toMatchObject({ 'X-CSRF-Token': 'csrf-test' })
  expect(JSON.parse(writes[0].body as string)).toMatchObject({
    expected_revision: 1,
    notes: '新说明',
  })
  await expect.element(page.getByRole('dialog')).toBeVisible()
})
it('保存后发布用新修订，发布失败保留已经保存的草稿并可重试', async () => {
  let row = saved()
  let fail = true
  const revisions: number[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        row = {
          ...row,
          ...JSON.parse(init.body as string),
          revision: row.revision + 1,
        }
        return Response.json(row)
      }
      if (url.endsWith('/publish')) {
        revisions.push(JSON.parse(init?.body as string).expected_revision)
        if (fail) return error('发布失败，但草稿已保存')
        row = { ...row, status: 'published', revision: row.revision + 1 }
        return Response.json(row)
      }
      return Response.json([])
    })
  )
  await mount(editor())
  await page.getByRole('textbox', { name: '更新说明' }).fill('保存的说明')
  await page.getByRole('button', { name: '保存并发布' }).click()
  await expect.element(page.getByText('发布失败，但草稿已保存')).toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '更新说明' }))
    .toHaveValue('保存的说明')
  expect(revisions).toEqual([2])
  fail = false
  await page.getByRole('button', { name: '保存并发布' }).click()
  await expect
    .element(page.getByRole('button', { name: '保存说明' }))
    .toBeDisabled()
  expect(revisions).toEqual([2, 3])
  await expect
    .element(page.getByRole('textbox', { name: '下载链接（HTTPS）' }))
    .toBeDisabled()
})
it('提交时冻结重复操作、退出和字段，失败保留输入', async () => {
  let finish!: (r: Response) => void
  const close = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'PUT'
        ? new Promise<Response>((r) => {
            finish = r
          })
        : Response.json([])
    )
  )
  await mount(editor(saved(), vi.fn(), close))
  await page.getByRole('textbox', { name: '更新说明' }).fill('尚未保存')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: '关闭', exact: true }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('textbox', { name: '更新说明' }))
    .toBeDisabled()
  await userEvent.keyboard('{Escape}')
  expect(close).not.toHaveBeenCalled()
  finish(error('保存失败'))
  await expect
    .element(page.getByText('保存失败', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '更新说明' }))
    .toHaveValue('尚未保存')
})
it('新建响应丢失按同 UUID 回查，不自动覆盖草稿，采用记录后使用新修订', async () => {
  const urls: string[] = []
  const revisions: number[] = []
  let row: Release | null = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/events')) return Response.json([])
      if (init?.method === 'PUT') {
        urls.push(url)
        const draft = JSON.parse(init.body as string)
        revisions.push(draft.expected_revision)
        row = {
          ...saved(),
          ...draft,
          id: url.split('/').slice(-1)[0],
          revision: draft.expected_revision + 1,
        }
        if (urls.length === 1) throw new Error('连接中断')
        return Response.json(row)
      }
      return Response.json(row)
    })
  )
  await mount(editor(null))
  await page.getByRole('textbox', { name: '版本号' }).fill('2.0.0')
  await page.getByRole('textbox', { name: '更新说明' }).fill('第一份草稿')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect.element(page.getByText('连接中断')).toBeVisible()
  await page.getByRole('textbox', { name: '更新说明' }).fill('本地后来修改')
  await page.getByRole('button', { name: '读取服务器记录' }).click()
  await expect.element(page.getByText(/服务器记录：v2.0.0/)).toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '更新说明' }))
    .toHaveValue('本地后来修改')
  await page.getByRole('button', { name: '使用服务器记录' }).click()
  await expect
    .element(page.getByRole('textbox', { name: '更新说明' }))
    .toHaveValue('第一份草稿')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect.poll(() => urls.length).toBe(2)
  expect(urls[0]).toBe(urls[1])
  expect(revisions).toEqual([0, 1])
})
it('并发冲突保留本地修改，服务器记录须主动采用', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') return error('版本已被其他运营修改', 409)
      if (url.endsWith('/events')) return Response.json([])
      return Response.json({ ...saved(), revision: 2, notes: '其他运营的说明' })
    })
  )
  await mount(editor())
  await page.getByRole('textbox', { name: '更新说明' }).fill('我的修改')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await page.getByRole('button', { name: '读取服务器记录' }).click()
  await expect
    .element(page.getByText('其他运营的说明', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '更新说明' }))
    .toHaveValue('我的修改')
})
it('重复目标和 HTTP 链接阻止发送，草稿可以缺少发布必填字段', async () => {
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') writes++
      return Response.json([])
    })
  )
  await mount(editor())
  await page
    .getByRole('textbox', { name: '下载链接（HTTPS）' })
    .fill('http://files.example.com/setup.exe')
  await expect
    .element(page.getByRole('button', { name: '保存草稿', exact: true }))
    .toBeDisabled()
  await page.getByRole('textbox', { name: '下载链接（HTTPS）' }).fill('')
  await expect
    .element(page.getByRole('button', { name: '保存草稿', exact: true }))
    .toBeEnabled()
  await page.getByRole('button', { name: '添加安装包' }).click()
  await expect
    .element(page.getByRole('button', { name: '保存草稿', exact: true }))
    .toBeDisabled()
  await expect
    .element(page.getByText('同一系统和架构只能有一个安装包'))
    .toBeVisible()
  expect(writes).toBe(0)
})
it('撤销运营权限后关闭编辑、清列表与历史缓存，不能继续写', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') return error('仅限平台运营人员', 403)
      if (url.endsWith('/events')) return Response.json([])
      return Response.json({ items: [saved()], total: 1, recommendations: [] })
    })
  )
  const client = await mount(<ClientDownloadsSettingsPage />)
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByRole('textbox', { name: '更新说明' }).fill('无权修改')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect.element(page.getByText('仅限平台运营人员')).toBeVisible()
  expect(page.getByRole('dialog').query()).toBeNull()
  await expect
    .poll(
      () =>
        client
          .getQueriesData({ queryKey: ['platform', 'client-downloads'] })
          .filter(([, data]) => data !== undefined).length
    )
    .toBe(0)
  expect(
    client.getQueriesData({ queryKey: ['platform', 'release-events'] })
  ).toHaveLength(0)
  await expect
    .element(page.getByRole('button', { name: '新建版本' }))
    .toBeDisabled()
})
it('历史接口拒绝权限也清除编辑器，普通历史失败可重试', async () => {
  const denied = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => error('权限已撤销', 403))
  )
  await mount(editor(saved(), denied))
  await expect.poll(() => denied.mock.calls.length).toBe(1)
  expect(page.getByRole('textbox', { name: '版本号' }).query()).toBeNull()
})
it('390px 列表改为卡片，编辑器内容滚动、底部保存可达', async () => {
  await page.viewport(390, 844)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url.endsWith('/events')
        ? Response.json([])
        : Response.json({ items: [saved()], total: 1, recommendations: [] })
    )
  )
  await mount(<ClientDownloadsSettingsPage />)
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: '保存草稿', exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '保存并发布' }))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth
  )
  await page.screenshot({
    path: '/private/tmp/actvero-download-editor-390.png',
  })
})
