import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { KeyList } from './key-list'

const clients: QueryClient[] = []
const rules = { version: 0, enabled: true, max_days: 30 }
const llm: Schema['KeyResource'] = {
  id: '11111111-1111-4111-8111-111111111111',
  kind: 'llm',
  name: '团队对话',
  identifier: 'team-chat',
  endpoint: 'http://localhost/api/llm/v1',
}
const item: Schema['KeyView'] = {
  id: '33333333-3333-4333-8333-333333333333',
  member_id: 'member',
  member_name: '测试成员',
  name: '本地 Agent',
  hint: 'avk_test…abcd',
  can_reveal: false,
  managed_disabled: false,
  scope_mode: 'selected',
  grants: [
    {
      kind: 'llm',
      resource_id: llm.id,
      actions: ['read', 'invoke'],
      name: llm.name,
      identifier: llm.identifier,
    },
  ],
  status: 'active',
  version: 1,
  created_at: '2026-09-25T01:00:00Z',
  expires_at: '2026-10-25T01:00:00Z',
  last_used_at: null,
}
async function show(admin = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>
      <div className='p-4'>
        <KeyList identity='test-member' csrf='test-csrf' admin={admin} />
      </div>
    </QueryClientProvider>
  )
}
afterEach(async () => {
  clients.forEach((c) => c.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 900)
})

it('空列表和组织禁用状态不伪造密钥', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.endsWith('/policy')
          ? { ...rules, enabled: false }
          : { items: [], total: 0, page: 1 }
      )
    )
  )
  const screen = await show()
  await expect.element(screen.getByText('尚无访问密钥')).toBeVisible()
  await expect
    .element(screen.getByRole('button', { name: '创建密钥' }))
    .toBeDisabled()
  await expect
    .element(screen.getByText('组织已关闭个人访问密钥。'))
    .toBeVisible()
})

it('只填名称即可创建，无资源请求，创建后展示完整密钥且不进入查询缓存', async () => {
  let body: Schema['KeyCreate'] | null = null
  const secret = 'avk_test_fixture_only_never_a_real_key'
  const createdItem = {
    ...item,
    scope_mode: 'member',
    grants: [],
    expires_at: null,
  }
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (options.method === 'POST') {
      body = JSON.parse(String(options.body))
      return Response.json({
        key: createdItem,
        secret,
        llm_base_url: llm.endpoint,
      })
    }
    if (url.endsWith('/policy')) return Response.json(rules)
    return Response.json({
      items: body ? [createdItem] : [],
      total: body ? 1 : 0,
      page: 1,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const screen = await show()
  await screen.getByRole('button', { name: '创建密钥' }).click()
  const dialog = screen.getByRole('dialog')
  expect(dialog.getByRole('textbox').all()).toHaveLength(1)
  await dialog.getByRole('button', { name: '创建密钥', exact: true }).click()
  await expect.element(dialog.getByText('请输入名称')).toBeVisible()
  expect(body).toBeNull()
  await dialog.getByLabelText('名称').fill('本地 Agent')
  await page.screenshot({ path: '__screenshots__/key-editor-desktop.png' })
  await page.viewport(390, 844)
  await page.screenshot({ path: '__screenshots__/key-editor-narrow.png' })
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await dialog.getByRole('button', { name: '创建密钥', exact: true }).click()
  await expect
    .element(screen.getByRole('dialog', { name: '密钥已创建' }))
    .toBeVisible()
  const sent = body as unknown as Schema['KeyCreate']
  expect(sent).toEqual({ name: '本地 Agent', creation_id: expect.any(String) })
  expect(fetcher.mock.calls.some(([url]) => url.includes('/resources'))).toBe(
    false
  )
  expect(
    fetcher.mock.calls.find(([, o]) => o.method === 'POST')?.[1].headers
  ).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
  await expect.element(screen.getByLabelText('API Key')).toHaveValue(secret)
  expect(
    JSON.stringify(
      clients[0]
        .getQueryCache()
        .getAll()
        .map((q) => q.state.data)
    )
  ).not.toContain(secret)
  expect(clients[0].getMutationCache().getAll()).toHaveLength(0)
  await screen.getByRole('button', { name: '已保存，关闭' }).click()
  expect(document.body.textContent).not.toContain(secret)
  await expect
    .element(screen.getByText('本地 Agent', { exact: true }))
    .toBeVisible()
  await expect.element(screen.getByText(item.hint)).toBeVisible()
  await expect
    .element(screen.getByRole('button', { name: '创建密钥' }))
    .toHaveFocus()
})

it('撤销需确认且失败保留窗口，成功更新状态；管理员停用不能由本人恢复', async () => {
  let attempts = 0
  let revoked = false
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (options.method === 'PATCH') {
      attempts++
      if (attempts === 1)
        return Response.json(
          { error: { message: '暂时无法撤销' } },
          { status: 503 }
        )
      revoked = true
      return Response.json({ ...item, status: 'revoked', version: 2 })
    }
    return Response.json(
      url.endsWith('/policy')
        ? rules
        : {
            items: [
              {
                ...item,
                status: revoked ? 'revoked' : 'disabled',
                managed_disabled: true,
              },
            ],
            total: 1,
            page: 1,
          }
    )
  })
  vi.stubGlobal('fetch', fetcher)
  const screen = await show()
  await screen.getByRole('button', { name: '管理 本地 Agent' }).click()
  expect(
    screen.getByRole('menuitem', { name: '启用', exact: true }).all()
  ).toHaveLength(0)
  await screen.getByRole('menuitem', { name: '撤销', exact: true }).click()
  await screen.getByRole('button', { name: '取消', exact: true }).click()
  expect(attempts).toBe(0)
  await screen.getByRole('button', { name: '管理 本地 Agent' }).click()
  await screen.getByRole('menuitem', { name: '撤销', exact: true }).click()
  const confirm = screen.getByRole('alertdialog')
  await confirm.getByRole('button', { name: '撤销', exact: true }).click()
  await expect.element(confirm.getByText('暂时无法撤销')).toBeVisible()
  await confirm.getByRole('button', { name: '撤销', exact: true }).click()
  await expect
    .element(screen.getByText('已撤销', { exact: true }))
    .toBeVisible()
  await expect.element(confirm).not.toBeInTheDocument()
  const sent = fetcher.mock.calls.find(([, o]) => o.method === 'PATCH')!
  expect(JSON.parse(String(sent[1].body))).toEqual({
    action: 'revoke',
    version: 1,
  })
  await page.screenshot({ path: '__screenshots__/keys-desktop.png' })
})

it('管理员只能治理密钥，保存规则携带版本和 CSRF', async () => {
  let saved = false
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (options.method === 'PUT') {
      saved = true
      return Response.json({
        ...rules,
        version: 1,
        enabled: false,
        max_days: 7,
      })
    }
    return Response.json(
      url.endsWith('/policy') ? rules : { items: [item], total: 1, page: 1 }
    )
  })
  vi.stubGlobal('fetch', fetcher)
  const screen = await show(true)
  expect(screen.getByRole('button', { name: '创建密钥' }).all()).toHaveLength(0)
  await screen.getByRole('button', { name: '密钥规则' }).click()
  const dialog = screen.getByRole('dialog')
  await dialog.getByRole('switch').click()
  await dialog.getByLabelText('最长有效期（天）').fill('7')
  await dialog.getByRole('button', { name: '保存规则' }).click()
  await expect.poll(() => saved).toBe(true)
  const sent = fetcher.mock.calls.find(([, o]) => o.method === 'PUT')!
  expect(sent[0]).toBe('/api/v1/access-keys/policy')
  expect(sent[1].headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
  expect(JSON.parse(String(sent[1].body))).toEqual({
    version: 0,
    enabled: false,
    max_days: 7,
  })
})

it.each([false, true])(
  '精简密钥列表保留治理操作，不加载资源或用量（admin=%s）',
  async (admin) => {
    const fetcher = vi.fn(async (url: string) =>
      Response.json(
        url.endsWith('/policy')
          ? rules
          : {
              items: [{ ...item, scope_mode: 'member', grants: [] }],
              total: 1,
              page: 1,
            }
      )
    )
    vi.stubGlobal('fetch', fetcher)
    const screen = await show(admin)
    await expect
      .element(screen.getByText('本地 Agent', { exact: true }))
      .toBeVisible()
    expect(
      Array.from(document.querySelectorAll('th')).map((el) => el.textContent)
    ).toEqual(
      admin
        ? ['名称', '密钥', '成员', '状态', '操作']
        : ['名称', '密钥', '状态', '操作']
    )
    await expect
      .element(screen.getByRole('columnheader', { name: '范围', exact: true }))
      .not.toBeInTheDocument()
    await expect
      .element(screen.getByRole('button', { name: '本地 Agent', exact: true }))
      .not.toBeInTheDocument()
    await screen.getByRole('button', { name: '管理 本地 Agent' }).click()
    await expect
      .element(screen.getByRole('menuitem', { name: '停用', exact: true }))
      .toBeVisible()
    await expect
      .element(screen.getByRole('menuitem', { name: '撤销', exact: true }))
      .toBeVisible()
    await expect
      .element(screen.getByRole('menuitem', { name: '资源与使用记录' }))
      .not.toBeInTheDocument()
    expect(
      fetcher.mock.calls.every(
        ([url]) => !url.includes('/usage') && !url.includes('/resources')
      )
    ).toBe(true)
  }
)

it('本人密钥可重新查看复制，关闭后清空且不进入查询缓存', async () => {
  const secret = 'avk_reveal_fixture_only_not_real'
  const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
  const fetcher = vi.fn(async (url: string, _options: RequestInit) => {
    if (url.endsWith('/reveal')) return Response.json({ secret })
    return Response.json(
      url.endsWith('/policy')
        ? rules
        : {
            items: [{ ...item, can_reveal: true }],
            total: 1,
            page: 1,
          }
    )
  })
  vi.stubGlobal('fetch', fetcher)
  const screen = await show()
  const reveal = screen.getByRole('button', { name: '查看密钥 本地 Agent' })
  await reveal.click()
  await expect.element(screen.getByLabelText('API Key')).toHaveValue(secret)
  await screen.getByRole('button', { name: '复制密钥' }).click()
  expect(copy).toHaveBeenCalledWith(secret)
  const sent = fetcher.mock.calls.find(([url]) => url.endsWith('/reveal'))!
  expect(sent[1].method).toBe('POST')
  expect(JSON.parse(String(sent[1].body))).toEqual({ version: 1 })
  expect(sent[1].headers).toMatchObject({ 'X-CSRF-Token': 'test-csrf' })
  expect(
    JSON.stringify(
      clients[0]
        .getQueryCache()
        .getAll()
        .map((q) => q.state.data)
    )
  ).not.toContain(secret)
  expect(clients[0].getMutationCache().getAll()).toHaveLength(0)
  await page.viewport(390, 844)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '__screenshots__/key-reveal-narrow.png' })
  await screen.getByRole('button', { name: '关闭', exact: true }).click()
  expect(screen.getByLabelText('API Key').all()).toHaveLength(0)
  await expect.element(reveal).toHaveFocus()
  await reveal.click()
  await expect.element(screen.getByLabelText('API Key')).toHaveValue(secret)
  expect(
    fetcher.mock.calls.filter(([url]) => url.endsWith('/reveal'))
  ).toHaveLength(2)
})

it.each([false, true])(
  '已撤销密钥仍可删除，取消不提交，删除后移出列表（admin=%s）',
  async (admin) => {
    let deleted = false
    const fetcher = vi.fn(async (url: string, options: RequestInit) => {
      if (options.method === 'PATCH') {
        deleted = true
        return Response.json({ ...item, status: 'revoked', version: 2 })
      }
      return Response.json(
        url.endsWith('/policy')
          ? rules
          : {
              items: deleted
                ? []
                : [{ ...item, status: 'revoked', can_reveal: false }],
              total: deleted ? 0 : 1,
              page: 1,
            }
      )
    })
    vi.stubGlobal('fetch', fetcher)
    const screen = await show(admin)
    await screen.getByRole('button', { name: '管理 本地 Agent' }).click()
    expect(
      screen.getByRole('menuitem', { name: '启用', exact: true }).all()
    ).toHaveLength(0)
    await screen.getByRole('menuitem', { name: '删除', exact: true }).click()
    await screen.getByRole('button', { name: '取消', exact: true }).click()
    expect(deleted).toBe(false)
    await screen.getByRole('button', { name: '管理 本地 Agent' }).click()
    await screen.getByRole('menuitem', { name: '删除', exact: true }).click()
    await screen
      .getByRole('alertdialog')
      .getByRole('button', { name: '删除', exact: true })
      .click()
    await expect.element(screen.getByText('尚无访问密钥')).toBeVisible()
    const sent = fetcher.mock.calls.find(([, o]) => o.method === 'PATCH')!
    expect(JSON.parse(String(sent[1].body))).toEqual({
      action: 'delete',
      version: 1,
    })
  }
)
