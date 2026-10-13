import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { ModelImport } from './model-import'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org' },
    user: { id: 'admin' },
    csrf: 'csrf',
  }),
}))
const channel = {
  id: '11111111-1111-4111-8111-111111111111',
  version: 1,
  name: '测试渠道',
  models: [
    { id: 'text-embedding-3-small' },
    { id: 'custom-model' },
    ...Array.from({ length: 49 }, (_, i) => ({ id: 'model-' + i })),
  ],
}
const storageKey = 'model-import:org:admin'
let client: QueryClient
let previewRequests: Schema['ImportInput'][]
let commits: Schema['ImportCommit'][]
let receipt: Schema['ImportResult'] | null
let lost: boolean
let version: number
let collision: boolean
let previewFailures: number
let commitFailure: number | null
let receiptFailureAfterCommit: boolean
let receiptReads: number
let targetQueries: string[]
beforeEach(() => {
  previewRequests = []
  commits = []
  receipt = null
  lost = false
  version = 1
  collision = false
  previewFailures = 0
  commitFailure = null
  receiptFailureAfterCommit = false
  receiptReads = 0
  targetQueries = []
  sessionStorage.removeItem(storageKey)
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null
      if (url.endsWith('/model-imports/preview')) {
        previewRequests.push(body)
        if (previewFailures > 0) {
          previewFailures -= 1
          return Response.json(
            { error: { message: '预览暂不可用' } },
            { status: 503 }
          )
        }
        const rows = (body as Schema['ImportInput']).items.map((item) => {
          const known = item.upstream_id === 'text-embedding-3-small'
          const conflict =
            collision &&
            item.action === 'create' &&
            (item.slug ?? item.upstream_id) === 'custom-model'
          return {
            ...item,
            name: item.name ?? item.upstream_id,
            slug: item.slug ?? item.upstream_id,
            kinds: item.kinds ?? (known ? ['embedding'] : []),
            errors: conflict ? ['技术名称已存在'] : [],
            status: conflict ? 'error' : item.action,
            hint: {
              kind: known ? 'embedding' : null,
              source: known ? 'litellm' : 'unknown',
              available_kinds: ['chat', 'embedding', 'rerank'],
            },
          }
        })
        return Response.json({
          revision: 'a'.repeat(64),
          items: rows,
          can_commit: !rows.some((r) => r.errors.length),
          create_count: rows.filter((r) => r.action === 'create').length,
          link_count: rows.filter((r) => r.action === 'link').length,
          binding_count: 1,
        })
      }
      if (url.endsWith('/model-imports/commit')) {
        commits.push(body)
        if (commitFailure)
          return Response.json(
            { error: { message: '提交失败' } },
            { status: commitFailure }
          )
        if (body.channel_version !== version)
          return Response.json(
            { error: { message: '渠道已更新，请重新预览' } },
            { status: 409 }
          )
        receipt = {
          request_id: body.request_id,
          items: body.items.map((item: Schema['ImportItem']) => ({
            upstream_id: item.upstream_id,
            slug: item.slug ?? item.upstream_id,
            model_id: 'saved',
            status: item.action === 'link' ? 'linked' : 'created',
          })),
        }
        if (lost) throw new TypeError('测试：响应丢失')
        return Response.json(receipt)
      }
      if (url.includes('/model-imports/')) {
        receiptReads += 1
        if (receiptFailureAfterCommit && commits.length)
          throw new TypeError('测试：回执查询中断')
        return Response.json({ committed: !!receipt, result: receipt })
      }
      if (url.includes('/models?')) {
        targetQueries.push(url)
        return Response.json({
          total: 1,
          items: [
            {
              id: '22222222-2222-4222-8222-222222222222',
              slug: 'existing',
              name: '已有向量模型',
              operations: [{ kind: 'embedding' }],
            },
          ],
        })
      }
      if (url.includes('/channels?'))
        return Response.json({ total: 1, items: [channel] })
      if (url.endsWith('/channels/' + channel.id))
        return Response.json({ ...channel, version })
      throw new Error('Unexpected request ' + url)
    })
  )
})
afterEach(async () => {
  await cleanup()
  await client.cancelQueries()
  client.clear()
  sessionStorage.removeItem(storageKey)
  vi.unstubAllGlobals()
  await page.viewport(1280, 900)
})
async function show(selectChannel = true) {
  const close = vi.fn()
  const view = await render(
    <QueryClientProvider client={client}>
      <ModelImport close={close} configure={vi.fn()} />
    </QueryClientProvider>
  )
  if (selectChannel) {
    await fits()
    await page.getByRole('combobox', { name: '渠道', exact: true }).click()
    await page.getByRole('option', { name: channel.name }).click()
  }
  return { close, view }
}
async function select(id: string) {
  await page.getByRole('checkbox', { name: '选择 ' + id, exact: true }).click()
}
async function choose(label: string, option: string) {
  await page.getByRole('combobox', { name: label, exact: true }).click()
  await page.getByRole('option', { name: option, exact: true }).click()
}
async function fits() {
  const dialog = page.getByRole('dialog').element()
  await expect
    .poll(() => dialog.getBoundingClientRect().left)
    .toBeGreaterThanOrEqual(0)
  await expect
    .poll(() => dialog.getBoundingClientRect().right)
    .toBeLessThanOrEqual(innerWidth + 1)
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
}

it('keeps selection through pagination and search, limits batches, and never writes on cancel', async () => {
  const { close } = await show()
  await page.getByRole('checkbox', { name: '本页全选' }).click()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await page.getByRole('checkbox', { name: '本页全选' }).click()
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect
    .element(page.getByRole('checkbox', { name: '本页全选' }))
    .toBeDisabled()
  await page.getByLabelText('搜索上游模型').fill('text-embedding-3-small')
  await expect
    .element(
      page.getByRole('checkbox', { name: '选择 text-embedding-3-small' })
    )
    .toBeChecked()
  await expect.element(page.getByText('已选 40 / 50')).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await expect.element(page.getByRole('alertdialog')).toBeVisible()
  expect(commits).toHaveLength(0)
  expect(previewRequests).toHaveLength(0)
  await page
    .getByRole('alertdialog')
    .getByRole('button', { name: '关闭', exact: true })
    .click()
  expect(close).toHaveBeenCalledOnce()
})

it('previews known and unknown types, invalidates edited plans, and fits a narrow viewport', async () => {
  await page.viewport(390, 844)
  await show()
  await select('text-embedding-3-small')
  await select('custom-model')
  await fits()
  await page.screenshot({
    path: '__screenshots__/model-import-selection-390.png',
  })
  await page.getByRole('button', { name: '预览导入' }).click()
  await expect
    .element(page.getByRole('combobox', { name: '接口类型' }).nth(0))
    .toHaveTextContent('向量')
  await expect
    .element(page.getByRole('combobox', { name: '接口类型' }).nth(1))
    .toHaveTextContent('稍后配置')
  expect(commits).toHaveLength(0)
  await fits()
  await page.screenshot({ path: '__screenshots__/model-import-narrow.png' })
  await page.getByLabelText('技术名称').nth(1).fill('team-custom')
  await expect
    .element(page.getByRole('button', { name: '确认导入' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '更新预览' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认导入' }))
    .toBeEnabled()
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect
    .element(page.getByText('导入结果', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('本次整批已提交 · 请求号', { exact: false }))
    .toBeVisible()
  await fits()
  await page.screenshot({ path: '__screenshots__/model-import-result-390.png' })
  expect(commits).toHaveLength(1)
  expect(commits[0].items[1]).toMatchObject({ slug: 'team-custom', kinds: [] })
  expect(sessionStorage.getItem(storageKey)).toBeNull()
})

it('resolves a name conflict by linking only a selected existing interface', async () => {
  collision = true
  await show()
  await select('custom-model')
  await page.getByRole('button', { name: '预览导入' }).click()
  await expect.element(page.getByText('技术名称已存在')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认导入' }))
    .toBeDisabled()
  await choose('处理方式', '关联现有模型')
  await page.getByRole('textbox', { name: '搜索目标模型' }).fill('existing')
  await expect
    .poll(() => targetQueries.some((url) => url.includes('q=existing')))
    .toBe(true)
  await choose('目标模型', '已有向量模型 · existing')
  await choose('接口类型', '向量')
  await page.getByRole('button', { name: '更新预览' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认导入' }))
    .toBeEnabled()
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect
    .element(page.getByText('导入结果', { exact: true }))
    .toBeVisible()
  expect(commits[0].items[0]).toMatchObject({
    action: 'link',
    target_id: '22222222-2222-4222-8222-222222222222',
    kinds: ['embedding'],
  })
})

it('recovers a lost commit response from the receipt without another commit', async () => {
  lost = true
  await show()
  await select('custom-model')
  await page.getByRole('button', { name: '预览导入' }).click()
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect
    .element(page.getByText('导入结果', { exact: true }))
    .toBeVisible()
  expect(commits).toHaveLength(1)
})

it('recovers the exact pending command after reopening, and checks receipt before retry', async () => {
  const requestId = crypto.randomUUID()
  sessionStorage.setItem(
    storageKey,
    JSON.stringify({
      channel_id: channel.id,
      channel_version: 1,
      request_id: requestId,
      revision: 'a'.repeat(64),
      items: [{ upstream_id: 'custom-model', action: 'create' }],
    })
  )
  await show(false)
  await page.getByRole('button', { name: '重试原提交' }).click()
  await expect
    .element(page.getByText('导入结果', { exact: true }))
    .toBeVisible()
  expect(commits[0].request_id).toBe(requestId)
  expect(previewRequests).toHaveLength(0)
})

it('preserves row edits after a version conflict and requires a refreshed preview', async () => {
  await show()
  await select('custom-model')
  await page.getByRole('button', { name: '预览导入' }).click()
  version = 2
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect.element(page.getByText('渠道已更新，请重新预览')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认导入' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '更新预览' }).click()
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect
    .element(page.getByText('导入结果', { exact: true }))
    .toBeVisible()
  expect(commits[1].channel_version).toBe(2)
})

it('retains every reviewed row after a 409 and retries only after re-preview', async () => {
  await show()
  await select('custom-model')
  await select('text-embedding-3-small')
  await page.getByRole('button', { name: '预览导入' }).click()
  await page.getByLabelText('技术名称').nth(0).fill('team-custom')
  await page.getByLabelText('展示名称').nth(1).fill('团队向量')
  await page.getByRole('button', { name: '更新预览' }).click()
  version = 2
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect.element(page.getByText('渠道已更新，请重新预览')).toBeVisible()
  await expect
    .element(page.getByLabelText('技术名称').nth(0))
    .toHaveValue('team-custom')
  await expect
    .element(page.getByLabelText('展示名称').nth(1))
    .toHaveValue('团队向量')
  expect(sessionStorage.getItem(storageKey)).toBeNull()
  await expect
    .element(page.getByRole('button', { name: '确认导入' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '更新预览' }).click()
  await page.getByRole('button', { name: '确认导入' }).click()
  expect(commits[1].items).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ slug: 'team-custom' }),
      expect.objectContaining({ name: '团队向量' }),
    ])
  )
})

it('keeps the exact pending command on 403 and disables further writes', async () => {
  commitFailure = 403
  await show()
  await select('custom-model')
  await page.getByRole('button', { name: '预览导入' }).click()
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect.element(page.getByText('提交失败')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '重试原提交' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '查询结果' }))
    .toBeDisabled()
  expect(commits).toHaveLength(1)
  const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null')
  expect(saved).toMatchObject({
    version: 1,
    tenant_id: 'org',
    user_id: 'admin',
  })
  expect(saved.command.request_id).toBe(commits[0].request_id)
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await expect.element(page.getByRole('alertdialog')).toBeVisible()
  expect(sessionStorage.getItem(storageKey)).not.toBeNull()
})

it('holds a 5xx response and uncertain receipt, then retries the same payload', async () => {
  commitFailure = 503
  receiptFailureAfterCommit = true
  await show()
  await select('custom-model')
  await page.getByRole('button', { name: '预览导入' }).click()
  await page.getByRole('button', { name: '确认导入' }).click()
  await expect
    .element(page.getByText('提交结果待确认，请查询结果或重试原提交。'))
    .toBeVisible()
  const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null')
  expect(saved.command).toEqual(commits[0])
  await page.getByRole('button', { name: '重试原提交' }).click()
  expect(commits).toHaveLength(1)
  receiptFailureAfterCommit = false
  commitFailure = null
  await page.getByRole('button', { name: '重试原提交' }).click()
  await expect
    .element(page.getByText('导入结果', { exact: true }))
    .toBeVisible()
  expect(commits).toHaveLength(2)
  expect(commits[1]).toEqual(commits[0])
  expect(receiptReads).toBeGreaterThanOrEqual(3)
})

it('does not execute a valid command copied from another organization without explicit discard', async () => {
  sessionStorage.setItem(
    storageKey,
    JSON.stringify({
      version: 1,
      tenant_id: 'another-org',
      user_id: 'another-admin',
      command: {
        channel_id: channel.id,
        channel_version: 1,
        request_id: crypto.randomUUID(),
        revision: 'a'.repeat(64),
        items: [{ upstream_id: 'custom-model', action: 'create' }],
      },
    })
  )
  await show(false)
  await expect
    .element(page.getByText('本地待确认导入记录无法安全读取', { exact: false }))
    .toBeVisible()
  expect(commits).toHaveLength(0)
  expect(previewRequests).toHaveLength(0)
  await page.getByRole('button', { name: '丢弃本地记录' }).click()
  await expect
    .element(page.getByText('导入可能已经完成。', { exact: false }))
    .toBeVisible()
  expect(sessionStorage.getItem(storageKey)).not.toBeNull()
  await page
    .getByRole('alertdialog')
    .getByRole('button', { name: '仍要丢弃' })
    .click()
  expect(sessionStorage.getItem(storageKey)).toBeNull()
})

it('blocks a malformed stored command and leaves it untouched for recovery', async () => {
  const raw = JSON.stringify({
    request_id: crypto.randomUUID(),
    items: 'invalid',
  })
  sessionStorage.setItem(storageKey, raw)
  await show(false)
  await expect
    .element(page.getByText('本地待确认导入记录无法安全读取', { exact: false }))
    .toBeVisible()
  expect(sessionStorage.getItem(storageKey)).toBe(raw)
  expect(commits).toHaveLength(0)
  expect(receiptReads).toBe(0)
})

it('retries the original channel and IDs when the initial preview fails', async () => {
  previewFailures = 1
  await render(
    <QueryClientProvider client={client}>
      <ModelImport
        initialSource={channel as unknown as Schema['ChannelDetail']}
        initialIds={['custom-model']}
        close={vi.fn()}
        configure={vi.fn()}
      />
    </QueryClientProvider>
  )
  await expect.element(page.getByText('预览暂不可用')).toBeVisible()
  await expect
    .element(page.getByText('预览未完成，原选择仍保留。'))
    .toBeVisible()
  await page.getByRole('button', { name: '重试预览' }).click()
  await expect
    .element(page.getByText('新建 1 个 · 关联 0 个', { exact: false }))
    .toBeVisible()
  expect(previewRequests).toHaveLength(2)
  expect(previewRequests[1].items).toEqual(previewRequests[0].items)
})

it.each([409, 422])(
  'restores all saved rows after reload and a definitive %i rejection',
  async (status) => {
    commitFailure = status
    const oldRequestId = crypto.randomUUID()
    const rows = [
      {
        upstream_id: 'custom-model',
        action: 'create',
        slug: 'team-custom',
        name: '团队模型',
        kinds: [],
      },
      {
        upstream_id: 'text-embedding-3-small',
        action: 'create',
        slug: 'team-embed',
        name: '团队向量',
        kinds: ['embedding'],
      },
    ]
    sessionStorage.setItem(
      storageKey,
      JSON.stringify({
        channel_id: channel.id,
        channel_version: 1,
        request_id: oldRequestId,
        revision: 'a'.repeat(64),
        items: rows,
      })
    )
    await show(false)
    await page.getByRole('button', { name: '重试原提交' }).click()
    await expect.element(page.getByText('提交失败')).toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '重新预览保留的行' }))
      .toBeVisible()
    expect(sessionStorage.getItem(storageKey)).toBeNull()
    await page.getByRole('button', { name: '重新预览保留的行' }).click()
    await expect
      .element(page.getByLabelText('技术名称').nth(0))
      .toHaveValue('team-custom')
    await expect
      .element(page.getByLabelText('展示名称').nth(1))
      .toHaveValue('团队向量')
    expect(previewRequests[0].items).toEqual(rows)
    commitFailure = null
    await page.getByRole('button', { name: '确认导入' }).click()
    await expect
      .element(page.getByText('导入结果', { exact: true }))
      .toBeVisible()
    expect(commits[1].items).toEqual(rows)
    expect(commits[1].request_id).not.toBe(oldRequestId)
  }
)
