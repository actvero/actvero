import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ModelCreate } from './model-create'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({ organization: { tenant_id: 'org' }, csrf: 'csrf' }),
}))
const channel = {
  id: 'channel',
  version: 1,
  name: '已配置渠道',
  models: [
    { id: 'text-embedding-3-small' },
    { id: 'custom-model' },
    { id: 'image-model' },
  ],
}
const alternate = {
  id: 'alternate',
  version: 1,
  name: '其他渠道',
  models: [{ id: 'custom-model' }],
}
const empty = {
  id: 'empty',
  version: 1,
  name: '空库存渠道',
  models: [],
}
let client: QueryClient
const writes: Record<string, unknown>[] = []
async function show(imageAvailable = false) {
  writes.length = 0
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        writes.push(body)
        return Response.json({ id: 'new', ...body })
      }
      if (url.includes('/model-hint')) {
        const known = url.includes('text-embedding-3-small')
        const image = url.includes('image-model')
        return Response.json({
          source: known || image ? 'litellm' : 'unknown',
          mode: known ? 'embedding' : image ? 'image_generation' : null,
          kind: known
            ? 'embedding'
            : image && imageAvailable
              ? 'image_generation'
              : null,
          available_kinds: [
            'chat',
            'embedding',
            'rerank',
            ...(imageAvailable ? ['image_generation'] : []),
          ],
        })
      }
      return Response.json(
        url.includes('/channels?')
          ? { total: 3, items: [channel, alternate, empty] }
          : url.includes('/channels/alternate')
            ? alternate
            : url.includes('/channels/empty')
              ? empty
              : channel
      )
    })
  )
  const saved = vi.fn(),
    close = vi.fn()
  await render(
    <QueryClientProvider client={client}>
      <ModelCreate close={close} saved={saved} />
    </QueryClientProvider>
  )
  await page.getByRole('button', { name: '从已有渠道快捷创建' }).click()
  await page.getByRole('combobox', { name: '渠道', exact: true }).click()
  await page.getByRole('option', { name: channel.name }).click()
  return { saved, close }
}
async function select(name: string) {
  await page.getByRole('combobox', { name: '上游模型', exact: true }).click()
  await page.getByRole('option', { name, exact: true }).click()
}
async function expectDialogFits() {
  const dialog = page.getByRole('dialog').element()
  await Promise.all(
    dialog
      .getAnimations({ subtree: true })
      .map((animation) => animation.finished)
  )
  const bounds = dialog.getBoundingClientRect()
  expect(bounds.left).toBeGreaterThanOrEqual(0)
  expect(bounds.right).toBeLessThanOrEqual(window.innerWidth + 1)
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
}
afterEach(async () => {
  await cleanup()
  await client?.cancelQueries()
  client?.clear()
  vi.unstubAllGlobals()
  await page.viewport(1280, 900)
})

it('registers metadata without source or operation, then saves a closed draft', async () => {
  await page.viewport(1440, 900)
  writes.length = 0
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        writes.push(body)
        return Response.json({ id: 'new', ...body })
      }
      return Response.json({ items: [], total: 0 })
    })
  )
  const saved = vi.fn()
  await render(
    <QueryClientProvider client={client}>
      <ModelCreate close={vi.fn()} saved={saved} />
    </QueryClientProvider>
  )
  await expect
    .element(
      page.getByText(
        '尚未配置调用接口。可先登记模型资料并保存；模型不会开放调用。'
      )
    )
    .toBeVisible()
  await page.getByLabelText('展示名称').fill('团队草稿')
  await page.getByLabelText('技术名称').fill('team-draft')
  await page.getByLabelText('显示排序').fill('25')
  expect(window.innerWidth).toBe(1440)
  await expectDialogFits()
  await page.screenshot({ path: '__screenshots__/actvero-me-profile-desktop.png' })
  await page.viewport(390, 844)
  expect(window.innerWidth).toBe(390)
  await expectDialogFits()
  await page.screenshot({ path: '__screenshots__/actvero-me-profile-narrow.png' })
  await page.getByRole('tab', { name: '价格配置' }).click()
  await expect.element(page.getByText('已保存参考报价（0）')).toBeVisible()
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes[0]).toMatchObject({
    name: '团队草稿',
    slug: 'team-draft',
    display_order: 25,
    access: { enabled: false },
    operations: [],
  })
})

it('configures an image source with explicit per-image price and keeps client access closed', async () => {
  await page.viewport(390, 844)
  const { saved } = await show(true)
  await select('image-model')
  await page.getByRole('button', { name: '下一步' }).click()
  await expect
    .element(page.getByLabelText('提示词上限（字符）'))
    .toHaveValue('2000')
  await page.getByRole('combobox', { name: '尺寸', exact: true }).click()
  await page.getByRole('option', { name: '1024x1024', exact: true }).click()
  await page.getByRole('combobox', { name: '质量', exact: true }).click()
  await page.getByRole('option', { name: 'low', exact: true }).click()
  await expectDialogFits()
  await page.screenshot({ path: '__screenshots__/image-config-narrow.png' })
  await page.getByRole('tab', { name: '价格配置' }).click()
  await page.getByRole('switch', { name: '配置价格' }).click()
  await page.getByRole('combobox', { name: '币种', exact: true }).click()
  await page.getByRole('option', { name: 'USD', exact: true }).click()
  await page.getByLabelText('每张单价').fill('0.035')
  await expect
    .element(page.getByRole('combobox', { name: '录入单位' }))
    .toHaveTextContent('每张')
  await expectDialogFits()
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes[0]).toMatchObject({
    access: { enabled: false },
    operations: [
      {
        kind: 'image_generation',
        enabled: false,
        image: {
          size: '1024x1024',
          quality: 'low',
          max_prompt_characters: 2000,
        },
        budget_price: {
          currency: 'USD',
          metric: 'images',
          unit: 1,
          input: '0.035',
        },
        bindings: [{ enabled: false, price: null }],
      },
    ],
  })
})

it('starts from a registered model and saves one closed interface with its binding and no prices', async () => {
  await page.viewport(390, 844)
  const { saved } = await show()
  await select('text-embedding-3-small')
  await expect
    .element(page.getByRole('combobox', { name: '接口类型' }))
    .toHaveTextContent('向量')
  expect(writes).toHaveLength(0)
  await expectDialogFits()
  await page.screenshot({ path: '__screenshots__/model-source-narrow.png' })
  await page.getByRole('button', { name: '下一步' }).click()
  await expect
    .element(page.getByLabelText('技术名称'))
    .toHaveValue('text-embedding-3-small')
  await expect.element(page.getByLabelText('默认维度')).toBeVisible()
  await expect
    .element(page.getByRole('combobox', { name: '配置接口' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('combobox', { name: '添加接口' }))
    .toBeInTheDocument()
  await expect
    .element(page.getByRole('switch', { name: '启用向量接口' }))
    .not.toBeChecked()
  await expectDialogFits()
  await page.screenshot({ path: '__screenshots__/model-config-narrow.png' })
  await page.getByRole('tab', { name: '调用设置' }).click()
  await expect
    .element(page.getByRole('switch', { name: '启用模型' }))
    .not.toBeChecked()
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes[0]).toMatchObject({
    slug: 'text-embedding-3-small',
    budget_price: null,
    access: { enabled: false, audience: 'administrators' },
    operations: [
      {
        kind: 'embedding',
        enabled: false,
        budget_price: null,
        bindings: [
          {
            channel_id: channel.id,
            upstream_id: 'text-embedding-3-small',
            enabled: false,
            price: null,
          },
        ],
      },
    ],
  })
  expect((writes[0].operations as unknown[]).length).toBe(1)
})

it('requires an explicit interface for unknown models and clears it on source changes', async () => {
  const { close } = await show()
  await select('custom-model')
  await expect
    .element(
      page.getByText(
        '未识别接口类型，请按上游模型资料选择；不会自动开放调用或配置价格。'
      )
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeDisabled()
  await page.getByRole('combobox', { name: '接口类型' }).click()
  await page.getByRole('option', { name: '重排', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeEnabled()
  await select('image-model')
  await expect.element(page.getByText('此模型的接口暂不可用。')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeDisabled()
  await select('custom-model')
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect.element(page.getByText('放弃模型草稿？')).toBeVisible()
  await page.getByRole('button', { name: '继续配置' }).click()
  expect(close).not.toHaveBeenCalled()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '放弃草稿' }).click()
  expect(close).toHaveBeenCalledOnce()
  expect(writes).toHaveLength(0)
})

it('preserves the chosen source on metadata failure and allows a read-only retry', async () => {
  await show()
  const original = globalThis.fetch
  let failed = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/model-hint') && !failed) {
        failed = true
        return Response.json(
          { error: { message: '模型资料暂时不可用' } },
          { status: 503 }
        )
      }
      return original(url, init)
    })
  )
  await select('text-embedding-3-small')
  await expect.element(page.getByText('模型资料暂时不可用')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeEnabled()
  await expect
    .element(page.getByRole('combobox', { name: '上游模型', exact: true }))
    .toHaveTextContent('text-embedding-3-small')
  expect(writes).toHaveLength(0)
})

it('drops the previous source and SDK type when changing channels, and explains empty inventory', async () => {
  await show()
  await select('text-embedding-3-small')
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeEnabled()
  await page.getByRole('combobox', { name: '渠道', exact: true }).click()
  await page.getByRole('option', { name: alternate.name }).click()
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeDisabled()
  await select('custom-model')
  await expect
    .element(page.getByRole('combobox', { name: '接口类型' }))
    .toHaveTextContent('选择模型支持的接口')
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeDisabled()
  await page.getByRole('combobox', { name: '渠道', exact: true }).click()
  await page.getByRole('option', { name: empty.name }).click()
  await expect
    .element(page.getByText('此渠道还没有登记模型，请先在渠道库存中添加。'))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '下一步' }))
    .toBeDisabled()
  expect(writes).toHaveLength(0)
})
