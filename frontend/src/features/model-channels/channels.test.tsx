import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ChannelEditor } from './channel-editor'
import { ChannelTest } from './channel-test'
import { ModelInventory } from './model-inventory'
import { ModelChannelsPage } from './page'
import { providerAvatarPicker } from './provider-avatars'
import type { ProviderModule } from './provider-modules'
import type { Detail } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
    user: { id: 'test-admin' },
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    action,
    children,
  }: {
    title: string
    action: ReactNode
    children: ReactNode
  }) => (
    <main className='flex min-w-0 flex-col gap-6 p-6'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h1>{title}</h1>
        {action}
      </div>
      {children}
    </main>
  ),
}))

const channel: Detail = {
  id: 'test-channel',
  version: 1,
  provider: 'openai-compatible',
  name: '验收渠道',
  description: '',
  icon: '',
  base_url: 'https://example.test/v1',
  connection: {
    address_mode: 'legacy_api_base',
    legacy_base_url: 'https://example.test/v1',
    resolver_version: 1,
  },
  manual_enabled: true,
  auth_mode: 'api_key',
  credential_configured: true,
  timeout_seconds: 20,
  declared_apis: ['chat_completions'],
  archived: false,
  model_count: 1,
  last_check: null,
  created_at: '2026-09-24T00:00:00Z',
  checks: [],
  models: [
    {
      id: 'existing-model',
      source: 'manual',
      registered_at: '2026-09-24T00:00:00Z',
    },
  ],
}
const providers: ProviderModule[] = [
  ['openai', 'OpenAI', 'https://api.openai.com', '/v1'],
  ['anthropic', 'Anthropic', 'https://api.anthropic.com', '/v1'],
  ['gemini', 'Gemini', 'https://generativelanguage.googleapis.com', '/v1beta'],
  ['openai-compatible', '自定义 OpenAI 兼容', '', '/v1'],
].map(([id, name, official_service_root, default_api_prefix]) => ({
  id: id as ProviderModule['id'],
  name,
  default_base_url:
    official_service_root + (id === 'openai' ? default_api_prefix : ''),
  official_service_root,
  default_api_prefix,
  setup_help: '',
  version: 1,
  category: id === 'openai-compatible' ? 'compatible' : 'vendor',
  icon_key: id,
  aliases: id === 'anthropic' ? ['Claude'] : [],
  base_url_help: '接口根地址',
  allow_no_auth: id === 'openai-compatible',
  default_apis: ['chat_completions'],
  model_discovery: true,
  balance_query: false,
  member_inference: true,
  member_operations:
    id === 'openai' || id === 'openai-compatible'
      ? ['chat', 'embedding', 'rerank']
      : ['chat'],
  test_operations: ['chat'],
}))
async function selectCompatible() {
  const dialog = page.getByRole('dialog', { name: '添加渠道' })
  await expect.element(dialog).toBeVisible()
  await waitForAnimations()
  await page
    .getByRole('button', { name: '自定义 OpenAI 兼容', exact: true })
    .click()
  await expect.element(page.getByLabelText('渠道名称')).toBeVisible()
}
const clients: QueryClient[] = []
beforeEach(async () => {
  await page.viewport(1280, 900)
})
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 800)
})
async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  client.setQueryData(['organization', 'test-org', 'llm-providers'], providers)
  clients.push(client)
  const screen = await render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
  return { screen, client }
}

it('creates a channel and archives and restores it through the list controls', async () => {
  let stored: Detail | null = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      const method = options?.method ?? 'GET'
      if (method === 'POST') {
        const body = JSON.parse(String(options?.body))
        expect(body.auth_mode).toBe('none')
        expect(body.api_key).toBeUndefined()
        stored = {
          ...channel,
          name: body.name,
          auth_mode: 'none',
          credential_configured: false,
          model_count: 0,
          models: [],
        }
        return Response.json(stored)
      }
      if (method === 'PUT' && stored) {
        const body = JSON.parse(String(options?.body))
        stored = {
          ...stored,
          archived: body.archived,
          version: stored.version + 1,
        }
        return Response.json(stored)
      }
      const state = new URL(url, 'http://example.test').searchParams.get(
        'state'
      )
      const items =
        stored &&
        (state === 'all' || stored.archived === (state === 'archived'))
          ? [stored]
          : []
      return Response.json({ items, total: items.length })
    })
  )
  const { screen } = await show(<ModelChannelsPage />)
  await screen.getByRole('button', { name: '添加渠道', exact: true }).click()
  await selectCompatible()
  await page.getByLabelText('渠道名称').fill('新渠道')
  await page.getByLabelText('BaseURL').fill('https://example.test')
  await page.getByRole('combobox', { name: '身份认证' }).click()
  await page.getByRole('option', { name: '无认证', exact: true }).click()
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect
    .element(screen.getByRole('button', { name: '新渠道', exact: true }))
    .toBeVisible()
  await screen.getByRole('button', { name: '新渠道的更多操作' }).click()
  await page.getByRole('menuitem', { name: '归档渠道' }).click()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect
    .element(screen.getByText('还没有渠道。选择供应商，开始接入模型。'))
    .toBeVisible()
  await screen.getByRole('combobox', { name: '归档' }).click()
  await page.getByRole('option', { name: '已归档', exact: true }).click()
  await expect
    .element(screen.getByRole('button', { name: '新渠道', exact: true }))
    .toBeVisible()
  await screen.getByRole('button', { name: '新渠道的更多操作' }).click()
  await page.getByRole('menuitem', { name: '恢复渠道' }).click()
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await expect
    .element(screen.getByText('没有匹配的渠道', { exact: true }))
    .toBeVisible()
})

it('shows a real empty state; opening or cancelling configuration makes no upstream call', async () => {
  const fetcher = vi.fn(async (_url: string) =>
    Response.json({ items: [], total: 0 })
  )
  vi.stubGlobal('fetch', fetcher)
  const { screen } = await show(<ModelChannelsPage />)
  await expect
    .element(screen.getByText('还没有渠道。选择供应商，开始接入模型。'))
    .toBeVisible()
  await screen.getByRole('button', { name: '添加渠道', exact: true }).click()
  await selectCompatible()
  await expect
    .element(page.getByRole('dialog', { name: '添加渠道' }))
    .toBeVisible()
  await expect.element(page.getByLabelText('BaseURL')).toHaveValue('')
  await Promise.all(
    page
      .getByRole('dialog', { name: '添加渠道' })
      .element()
      .getAnimations()
      .map((animation) => animation.finished)
  )
  await page.screenshot({ path: '__screenshots__/channel-create-desktop.png' })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  expect(
    fetcher.mock.calls.every((call) =>
      String(call[0]).includes('/llm/channels?')
    )
  ).toBe(true)
  await expect
    .element(screen.getByRole('button', { name: '添加渠道', exact: true }))
    .toHaveFocus()
})

it('keeps secrets out of caches and preserves credentials and manual disable on edit', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(options?.method).toBe('PUT')
    expect(body.api_key).toBeUndefined()
    expect(body.version).toBe(1)
    expect(body.manual_enabled).toBe(false)
    return Response.json({ ...channel, version: 2 })
  })
  vi.stubGlobal('fetch', fetcher)
  const saved = vi.fn()
  const { client } = await show(
    <ChannelEditor
      channel={{ ...channel, manual_enabled: false }}
      close={vi.fn()}
      saved={saved}
    />
  )
  await expect
    .element(page.getByLabelText('API Key', { exact: true }))
    .toHaveValue('')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(client.getMutationCache().getAll()).toHaveLength(0)
  expect(
    client
      .getQueryCache()
      .getAll()
      .filter((query) => !query.queryKey.includes('llm-providers'))
      .every((query) => query.state.data === undefined)
  ).toBe(true)
})

it('requires a replacement credential before saving a changed destination', async () => {
  const fetcher = vi.fn(async () => Response.json({ ...channel, version: 2 }))
  vi.stubGlobal('fetch', fetcher)
  await show(
    <ChannelEditor channel={channel} close={vi.fn()} saved={vi.fn()} />
  )
  await page.getByLabelText('BaseURL').fill('https://different.test/v1')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect
    .element(page.getByText('请填写 API Key；修改地址时需要重新填写'))
    .toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
  await page.getByLabelText('API Key', { exact: true }).fill('fixture-secret')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => fetcher.mock.calls.length).toBe(1)
})

it('selects a bundled provider avatar, preserves connection fields, and restores the default', async () => {
  const chosen = providerAvatarPicker.options.find(
    (item) => item.id === 'deepseek'
  )!
  const nativeFetch = globalThis.fetch.bind(globalThis)
  const asset = await (await nativeFetch(chosen.image)).arrayBuffer()
  const expectedIcon =
    'data:image/webp;base64,' +
    btoa(
      Array.from(new Uint8Array(asset), (byte) =>
        String.fromCharCode(byte)
      ).join('')
    )
  let failAsset = true
  const saved = vi.fn()
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body).toEqual({
      provider: channel.provider,
      name: channel.name,
      description: channel.description,
      icon: expectedIcon,
      base_url: channel.base_url,
      connection: channel.connection,
      auth_mode: channel.auth_mode,
      timeout_seconds: channel.timeout_seconds,
      declared_apis: channel.declared_apis,
      manual_enabled: channel.manual_enabled,
      automatic_protection: { enabled: true },
      test_defaults: null,
      version: channel.version,
      models: channel.models.map(({ id }) => ({ id })),
    })
    return Response.json({ ...channel, icon: body.icon, version: 2 })
  })
  vi.stubGlobal('fetch', (input: string, options?: RequestInit) => {
    if (input.includes('/api/v1/')) return fetcher(input, options)
    if (failAsset) return Promise.resolve(new Response(null, { status: 503 }))
    return nativeFetch(input, options)
  })
  await show(<ChannelEditor channel={channel} close={vi.fn()} saved={saved} />)
  const trigger = page.getByRole('button', { name: '编辑渠道图标' })
  await trigger.click()
  await page.getByRole('menuitem', { name: '选择厂商图标' }).click()
  const picker = page.getByRole('dialog', { name: '选择厂商图标' })
  await expect
    .element(page.getByRole('textbox', { name: '搜索图标' }))
    .toHaveFocus()
  // Every bundled image must render, including the options below the fold.
  await expect
    .poll(() => picker.element().querySelectorAll('img').length)
    .toBe(18)
  await Promise.all(
    picker
      .element()
      .getAnimations()
      .map((animation) => animation.finished)
  )
  await page.screenshot({
    path: '__screenshots__/channel-avatar-picker-desktop.png',
  })
  await page.getByRole('textbox', { name: '搜索图标' }).fill('no-such-provider')
  await expect
    .element(picker.getByRole('status'))
    .toHaveTextContent('没有匹配的图标')
  await page.getByRole('textbox', { name: '搜索图标' }).fill('深度求索')
  await page.getByRole('button', { name: 'DeepSeek', exact: true }).click()
  await expect.element(picker.getByText('图标加载失败，请重试')).toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
  failAsset = false
  await page.getByRole('button', { name: 'DeepSeek', exact: true }).click()
  await expect.element(picker).not.toBeInTheDocument()
  await expect.element(trigger).toHaveFocus()
  await expect
    .poll(() => trigger.element().querySelector('img')?.src)
    .toBe(expectedIcon)
  expect(fetcher).not.toHaveBeenCalled()
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)

  await trigger.click()
  await page.getByRole('menuitem', { name: '选择厂商图标' }).click()
  await userEvent.keyboard('{Escape}')
  await expect.element(trigger).toHaveFocus()
  expect(trigger.element().querySelector('img')?.src).toBe(expectedIcon)
  await trigger.click()
  await page.getByRole('menuitem', { name: '恢复默认' }).click()
  await expect.poll(() => trigger.element().querySelector('img')).toBeNull()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('keeps the avatar chooser within a narrow dark viewport and supports keyboard selection', async () => {
  await page.viewport(390, 844)
  document.documentElement.classList.add('dark')
  try {
    await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
    await selectCompatible()
    const trigger = page.getByRole('button', { name: '编辑渠道图标' })
    await trigger.click()
    await page.getByRole('menuitem', { name: '选择厂商图标' }).click()
    const picker = page.getByRole('dialog', { name: '选择厂商图标' })
    await expect
      .poll(() => picker.element().querySelectorAll('img').length)
      .toBe(18)
    const box = picker.element().getBoundingClientRect()
    expect(box.left).toBeGreaterThanOrEqual(0)
    expect(box.right).toBeLessThanOrEqual(390)
    expect(picker.element().scrollWidth).toBeLessThanOrEqual(
      picker.element().clientWidth + 1
    )
    await Promise.all(
      picker
        .element()
        .getAnimations()
        .map((animation) => animation.finished)
    )
    await page.screenshot({
      path: '__screenshots__/channel-avatar-picker-narrow.png',
    })
    await page.getByRole('textbox', { name: '搜索图标' }).fill('claude')
    await expect
      .element(picker.getByRole('button', { name: 'Anthropic' }))
      .toBeVisible()
    await userEvent.keyboard('{Tab}{Enter}')
    await expect.element(picker).not.toBeInTheDocument()
    await expect.element(trigger).toHaveFocus()
    await expect
      .poll(() => trigger.element().querySelector('img'))
      .not.toBeNull()
  } finally {
    document.documentElement.classList.remove('dark')
  }
})

function Inventory() {
  const [value, changed] = useState(channel)
  const [busy, setBusy] = useState(false)
  return (
    <ModelInventory
      channel={value}
      modelDiscovery
      changed={changed}
      busy={busy}
      setBusy={setBusy}
    />
  )
}

it('keeps fetched choices, the search and selection after a failed refresh', async () => {
  let calls = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      calls += 1
      return Response.json({
        channel: {
          ...channel,
          version: channel.version + calls,
          model_directory: {
            snapshot_id: 'first-snapshot',
            fetched_at: '2026-10-26T00:00:00Z',
            candidates: [{ id: 'upstream-a' }, { id: 'upstream-b' }],
            partial: false,
          },
        },
        ok: calls === 1,
        message: calls === 1 ? '读取成功' : '上游拒绝认证',
        candidates:
          calls === 1 ? [{ id: 'upstream-a' }, { id: 'upstream-b' }] : [],
        snapshot_id: calls === 1 ? 'first-snapshot' : null,
        partial: false,
      })
    })
  )
  await show(<Inventory />)
  await page.getByRole('button', { name: '从上游获取' }).click()
  await page
    .getByRole('textbox', { name: '搜索上游返回的模型' })
    .fill('upstream-a')
  await page.getByRole('checkbox', { name: 'upstream-a' }).click()
  await page.getByRole('button', { name: '重新获取' }).click()
  await expect
    .element(page.getByText('上游拒绝认证', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '搜索上游返回的模型' }))
    .toHaveValue('upstream-a')
  await expect
    .element(page.getByRole('checkbox', { name: 'upstream-a' }))
    .toBeChecked()
  await expect
    .element(page.getByRole('button', { name: '登记并配置（1）' }))
    .toBeEnabled()
  expect(calls).toBe(2)
})

it('requires selection to register discovered models and retains inventory when refresh fails', async () => {
  let version = 1
  let fail = false
  let value = channel
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body.version).toBe(version)
    version += 1
    value = { ...value, version }
    if (url.endsWith('/discover')) {
      if (!fail)
        value = {
          ...value,
          model_directory: {
            snapshot_id: 'snapshot',
            fetched_at: '2026-10-26T00:00:00Z',
            candidates: [{ id: 'new-model' }, { id: 'existing-model' }],
            partial: false,
          },
        }
      return Response.json({
        channel: value,
        ok: !fail,
        message: fail ? '目录读取失败' : '成功',
        candidates: fail ? [] : [{ id: 'new-model' }, { id: 'existing-model' }],
        snapshot_id: 'snapshot',
        partial: false,
      })
    }
    expect(body.snapshot_id).toBe('snapshot')
    expect(body.models).toEqual([{ id: 'new-model' }])
    value = {
      ...value,
      model_count: 2,
      models: [
        ...value.models,
        {
          id: 'new-model',
          source: 'discovery',
          registered_at: '2026-09-24T00:00:00Z',
        },
      ],
    }
    return Response.json(value)
  })
  vi.stubGlobal('fetch', fetcher)
  await show(<Inventory />)
  await page.getByRole('button', { name: '从上游获取' }).click()
  await expect
    .element(page.getByRole('button', { name: '仅登记（0）' }))
    .toBeDisabled()
  expect(fetcher).toHaveBeenCalledTimes(1)
  await page.getByRole('checkbox', { name: 'new-model' }).click()
  await page.getByRole('button', { name: '仅登记（1）' }).click()
  await expect
    .element(page.getByRole('button', { name: '移除 new-model' }))
    .toBeVisible()
  fail = true
  await page.getByRole('button', { name: '重新获取' }).click()
  await expect
    .element(page.getByText('目录读取失败', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '移除 existing-model' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '移除 new-model' }))
    .toBeVisible()
})

it('keeps the form within a narrow viewport with a scrollable body and visible actions', async () => {
  await page.viewport(390, 844)
  await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
  await selectCompatible()
  await page.getByRole('tab', { name: '高级设置' }).click()
  await expect.element(page.getByLabelText('请求超时（秒）')).toBeVisible()
  const dialog = document.querySelector('[role="dialog"]') as HTMLElement
  expect(dialog.getBoundingClientRect().width).toBeLessThanOrEqual(390)
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await page.screenshot({ path: '__screenshots__/channel-create-narrow.png' })
  await page.getByRole('tab', { name: '连接与模型' }).click()
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  const body = dialog.querySelector('.overflow-y-auto') as HTMLElement
  expect(body.scrollHeight).toBeGreaterThan(body.clientHeight)
  await page.screenshot({
    path: '__screenshots__/channel-connection-narrow.png',
  })
  await page.getByRole('button', { name: '取消', exact: true }).click()
})

it('opens the selected model tab and preserves the page layout on narrow screens', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json(
        url.endsWith('/channel-addresses/resolve')
          ? {
              address_mode: 'legacy_api_base',
              resolver_version: 1,
              directory_method: 'GET',
              directory_url: 'https://example.test/v1/models',
              operation_targets: [],
              warnings: [],
            }
          : url.includes('/llm/channels?')
            ? { items: [channel], total: 1 }
            : channel
      )
    )
  )
  const { screen } = await show(<ModelChannelsPage />)
  await expect
    .element(screen.getByRole('button', { name: '验收渠道', exact: true }))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/channel-list-desktop.png' })
  await screen.getByRole('button', { name: '1 个登记模型' }).click()
  await expect
    .element(page.getByRole('tab', { name: '上游模型（1）' }))
    .toHaveAttribute('data-state', 'active')
  await expect
    .element(page.getByRole('button', { name: '移除 existing-model' }))
    .toBeVisible()
  await page.getByRole('tab', { name: '健康', exact: true }).click()
  await expect.element(page.getByText('此渠道没有关联绑定。')).toBeVisible()
  await page.getByRole('tab', { name: '连接信息' }).click()
  await page.viewport(390, 844)
  const dialog = document.querySelector('[role="dialog"]') as HTMLElement
  expect(dialog.getBoundingClientRect().width).toBeLessThanOrEqual(390)
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await page.screenshot({ path: '__screenshots__/channel-detail-narrow.png' })
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
})

it('fetches a directory once before creation, then saves only selected and manually entered models', async () => {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    calls.push({ url, body })
    if (url.endsWith('/channel-drafts/inspect')) {
      expect(body.discover).toBe(true)
      expect(body.api_key).toBe('draft-fixture-secret')
      expect(body.name).toBeUndefined()
      expect(body.models).toBeUndefined()
      return Response.json({
        ok: true,
        message: '模型目录读取成功',
        checked_at: channel.created_at,
        candidates: body.discover ? [{ id: 'model-a' }, { id: 'model-b' }] : [],
        partial: !!body.discover,
      })
    }
    expect(url).toBe('/api/v1/llm/channels')
    expect(body.models).toEqual([{ id: 'model-a' }, { id: 'manual-c' }])
    return Response.json({
      ...channel,
      models: (body.models as { id: string }[]).map((model) => ({
        ...model,
        source: 'configuration',
        registered_at: channel.created_at,
      })),
      model_count: 2,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const saved = vi.fn()
  const { client } = await show(<ChannelEditor close={vi.fn()} saved={saved} />)
  await selectCompatible()
  await page.getByLabelText('BaseURL').fill('https://example.test')
  await page
    .getByLabelText('API Key', { exact: true })
    .fill('draft-fixture-secret')
  await expect
    .element(page.getByRole('button', { name: '检查目录连接' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByLabelText('渠道名称'))
    .toHaveValue('自定义 OpenAI 兼容')
  await page.getByRole('button', { name: '从上游获取' }).click()
  await page.getByRole('textbox', { name: '搜索或输入模型 ID' }).fill('model-a')
  await expect
    .element(page.getByRole('button', { name: 'model-a' }))
    .toBeVisible()
  await expect.element(page.getByText('上游只返回了部分目录')).toBeVisible()
  await page.getByRole('button', { name: 'model-a' }).click()
  await page
    .getByRole('textbox', { name: '搜索或输入模型 ID' })
    .fill('manual-c')
  await page
    .getByRole('button', { name: '添加自定义模型 ID：manual-c' })
    .click()
  await page.getByLabelText('渠道名称').fill('新渠道')
  expect(saved).not.toHaveBeenCalled()
  expect(calls).toHaveLength(1)
  const dialog = page.getByRole('dialog', { name: '添加渠道' })
  await Promise.all(
    dialog
      .element()
      .getAnimations()
      .map((animation) => animation.finished)
  )
  const body = dialog.element().querySelector('.overflow-y-auto') as HTMLElement
  body.scrollTop = 0
  await page.screenshot({
    path: '__screenshots__/channel-create-with-models.png',
  })
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(calls).toHaveLength(2)
  expect(client.getMutationCache().getAll()).toHaveLength(0)
  expect(
    JSON.stringify(
      client
        .getQueryCache()
        .getAll()
        .map((query) => query.state.data)
    )
  ).not.toContain('draft-fixture-secret')
})

it('preserves selected models on discovery failure and invalidates old discovery when connection changes', async () => {
  let fail = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({
        ok: !fail,
        message: fail ? '上游拒绝认证' : '目录读取成功',
        checked_at: channel.created_at,
        candidates: fail
          ? []
          : [{ id: 'selected-model' }, { id: 'unselected-model' }],
        partial: false,
      })
    )
  )
  await show(
    <ChannelEditor channel={channel} close={vi.fn()} saved={vi.fn()} />
  )
  await page.getByRole('button', { name: '从上游获取' }).click()
  await page
    .getByRole('textbox', { name: '搜索或输入模型 ID' })
    .fill('selected-model')
  await page
    .getByRole('button', { name: 'selected-model', exact: true })
    .click()
  fail = true
  await page.getByRole('button', { name: '重新获取' }).click()
  await expect.element(page.getByText('上游拒绝认证')).toBeVisible()
  await expect
    .element(
      page.getByRole('group', { name: '已选模型' }).getByText('selected-model')
    )
    .toBeVisible()
  await page.getByLabelText('BaseURL').fill('https://different.test/v1')
  await expect.element(page.getByText('上游拒绝认证')).not.toBeInTheDocument()
  await page
    .getByRole('textbox', { name: '搜索或输入模型 ID' })
    .fill('unselected-model')
  await expect
    .element(
      page.getByRole('button', { name: 'unselected-model', exact: true })
    )
    .not.toBeInTheDocument()
  await expect
    .element(
      page.getByRole('group', { name: '已选模型' }).getByText('selected-model')
    )
    .toBeVisible()
  await page.getByRole('button', { name: '从上游获取', exact: true }).click()
  await expect
    .element(page.getByText('请填写 API Key；修改地址时需要重新填写'))
    .toBeVisible()
})

it('loads complete inventory before editing a list row and preserves it on save', async () => {
  let fail = true
  const { models: _models, checks: _checks, ...listRow } = channel
  const saved = vi.fn()
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, options?: RequestInit) => {
      requests.push(options?.method ?? 'GET')
      if (options?.method === 'GET')
        return fail
          ? Response.json({ error: { message: '加载失败' } }, { status: 503 })
          : Response.json(channel)
      const body = JSON.parse(String(options?.body))
      expect(body.models).toEqual([{ id: 'existing-model' }])
      expect(body.version).toBe(channel.version)
      expect(body.api_key).toBeUndefined()
      return Response.json({ ...channel, name: body.name, version: 2 })
    })
  )
  await show(<ChannelEditor channel={listRow} close={vi.fn()} saved={saved} />)
  await expect.element(page.getByText('加载失败')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '保存渠道' }))
    .not.toBeInTheDocument()
  fail = false
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect
    .element(
      page.getByRole('group', { name: '已选模型' }).getByText('existing-model')
    )
    .toBeVisible()
  await page.getByLabelText('渠道名称').fill('改名保留模型')
  await page.getByRole('button', { name: '保存渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(requests).toEqual(['GET', 'GET', 'PUT'])
})

it('allows cancelling an in-flight directory fetch and aborts the browser request', async () => {
  let signal: AbortSignal | undefined
  vi.stubGlobal(
    'fetch',
    vi.fn((_url: string, options?: RequestInit) => {
      signal = options?.signal ?? undefined
      return new Promise<Response>((_resolve, reject) =>
        signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError'))
        )
      )
    })
  )
  function Cancellable() {
    const [open, setOpen] = useState(true)
    return open ? (
      <ChannelEditor
        channel={channel}
        close={() => setOpen(false)}
        saved={vi.fn()}
      />
    ) : (
      <p>已关闭配置</p>
    )
  }
  await show(<Cancellable />)
  await page.getByRole('button', { name: '从上游获取', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: '从上游获取' }))
    .toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '保存渠道' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect.element(page.getByText('已关闭配置')).toBeVisible()
  expect(signal?.aborted).toBe(true)
})

it('selects provider defaults, filters aliases and clears credentials when switching', async () => {
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
  const cards = ['OpenAI', 'Anthropic', 'Gemini'].map((name) =>
    page
      .getByRole('button', { name, exact: true })
      .element()
      .getBoundingClientRect()
  )
  expect(cards[0].width).toBeCloseTo(cards[1].width, 0)
  expect(cards[1].width).toBeCloseTo(cards[2].width, 0)
  expect(cards[0].top).toBe(cards[2].top)
  await page.getByLabelText('搜索供应商').fill('Claude')
  await expect
    .element(page.getByRole('button', { name: 'OpenAI', exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: 'Anthropic', exact: true }).click()
  await expect
    .element(page.getByLabelText('BaseURL'))
    .toHaveValue('https://api.anthropic.com/v1')
  await expect
    .element(page.getByText('可配置与测试', { exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('tab', { name: '高级设置' }).click()
  await page.getByRole('button', { name: '允许调用的接口' }).click()
  await expect
    .element(page.getByRole('checkbox', { name: '对话补全', exact: true }))
    .toBeChecked()
  for (const name of ['文本向量', '重排', 'Responses']) {
    await expect
      .element(page.getByRole('checkbox', { name, exact: true }))
      .not.toBeInTheDocument()
  }
  await page.getByRole('tab', { name: '连接与模型' }).click()
  await page.getByLabelText('渠道名称').fill('自用渠道')
  await page
    .getByLabelText('API Key', { exact: true })
    .fill('never-transfer-secret')
  await page.getByRole('combobox', { name: '身份认证' }).click()
  await expect
    .element(page.getByRole('option', { name: '无认证' }))
    .not.toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  await page.getByRole('button', { name: '更换供应商', exact: true }).click()
  await page.getByRole('button', { name: '更换', exact: true }).click()
  await page.getByRole('button', { name: 'OpenAI', exact: true }).click()
  await expect.element(page.getByLabelText('渠道名称')).toHaveValue('自用渠道')
  await expect
    .element(page.getByLabelText('BaseURL'))
    .toHaveValue('https://api.openai.com/v1')
  await expect
    .element(page.getByLabelText('API Key', { exact: true }))
    .toHaveValue('')
  expect(fetcher).not.toHaveBeenCalled()
})

it('sends one channel test and displays unknown usage without estimating it', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    expect(JSON.parse(String(options?.body))).toMatchObject({
      upstream_id: 'existing-model',
      operation: 'chat',
      endpoint: 'chat_completions',
      stream: false,
      certify_health: false,
      input: { prompt: '测试内容', max_output_tokens: 32 },
      version: 1,
    })
    return Response.json({
      ok: true,
      message: '对话测试成功',
      output: '连接成功',
      duration_ms: 150,
      usage_source: 'unknown',
    })
  })
  vi.stubGlobal('fetch', fetcher)
  function Test() {
    const [busy, setBusy] = useState(false)
    return <ChannelTest channel={channel} busy={busy} setBusy={setBusy} />
  }
  const { client } = await show(<Test />)
  await page.getByLabelText('测试内容', { exact: true }).fill('测试内容')
  await page.getByLabelText('最大输出 Token').fill('32')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByText('上游未返回完整用量')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(client.getMutationCache().getAll()).toHaveLength(0)
})

it('keeps the provider picker usable in a narrow viewport', async () => {
  await page.viewport(390, 844)
  await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
  const dialog = page.getByRole('dialog', { name: '添加渠道' }).element()
  expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth + 1)
  await page.getByLabelText('搜索供应商').fill('不存在')
  await expect.element(page.getByText('没有匹配的供应商')).toBeVisible()
  await page.getByRole('button', { name: '清除筛选' }).click()
  await expect
    .element(page.getByRole('button', { name: 'Anthropic', exact: true }))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/provider-picker-narrow.png' })
})

function MultiTest({ archived = false }: { archived?: boolean }) {
  const [busy, setBusy] = useState(false)
  return (
    <ChannelTest
      channel={{ ...channel, archived }}
      operations={['chat', 'embedding', 'rerank']}
      initialModelId='existing-model'
      busy={busy}
      setBusy={setBusy}
    />
  )
}

it('requires an explicit endpoint and sends bounded embedding parameters with a vector preview', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    expect(JSON.parse(String(options?.body))).toMatchObject({
      upstream_id: 'existing-model',
      version: 1,
      operation: 'embedding',
      endpoint: 'embeddings',
      stream: false,
      certify_health: false,
      input: { input: ['第一条', '第二条'], dimensions: 3 },
    })
    return Response.json({
      ok: true,
      operation: 'embedding',
      message: '向量测试成功',
      duration_ms: 20,
      usage_source: 'upstream',
      input_tokens: 4,
      vectors: [
        { index: 0, dimensions: 3, values: [0.1, 0.2, 0.3] },
        { index: 1, dimensions: 3, values: [0.2, 0.3, 0.4] },
      ],
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await page.viewport(390, 844)
  await show(<MultiTest />)
  await expect
    .element(page.getByRole('button', { name: '开始测试' }))
    .toBeDisabled()
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '文本向量', exact: true }).click()
  await page.getByLabelText('输入文本（每行一条）').fill('第一条\n第二条')
  await page.getByLabelText('维度（选填）').fill('3')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByText('返回 2 条向量 · 3 维')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
    window.innerWidth + 1
  )
  await page.screenshot({
    path: '__screenshots__/channel-embedding-test-narrow.png',
  })
})

it('rejects excess rerank count and renders rankings while preserving unknown token usage', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body.operation).toBe('rerank')
    expect(body.input.documents).toHaveLength(2)
    expect(body.input.top_n).toBe(1)
    expect(body.input.prompt).toBeUndefined()
    return Response.json({
      ok: true,
      message: '重排测试成功',
      operation: 'rerank',
      duration_ms: 10,
      usage_source: 'upstream',
      search_units: 1,
      ranks: [{ index: 1, relevance_score: 0.9 }],
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await show(<MultiTest />)
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '重排', exact: true }).click()
  await page.getByLabelText('返回数量（选填）').fill('3')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect.element(page.getByText('请输入 1 至 2 的整数')).toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
  await page.getByLabelText('返回数量（选填）').fill('1')
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect
    .element(page.getByRole('cell', { name: '#2', exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('上游返回用量：输入 未知 Token · 搜索单位 1'))
    .toBeVisible()
})

it('shows unconfirmed and stale diagnostic records without sending another inference', async () => {
  const fetcher = vi.fn(async (url: string) => {
    expect(url).toContain('/tests?page=1')
    return Response.json([
      {
        request_id: 'r1',
        model: 'existing-model',
        operation: 'embedding',
        tested_at: '2026-09-28T00:00:00Z',
        status: 'unconfirmed',
        uncertain: true,
        stale: true,
      },
    ])
  })
  vi.stubGlobal('fetch', fetcher)
  await show(<MultiTest />)
  expect(fetcher).not.toHaveBeenCalled()
  await page.getByRole('button', { name: '测试记录', exact: true }).click()
  await expect.element(page.getByText('处理中／结果未确认')).toBeVisible()
  await expect.element(page.getByText('旧配置', { exact: true })).toBeVisible()
  await expect
    .element(page.getByText('执行结果未确认，可能产生费用'))
    .toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

it('keeps fields locked during one request and does not retry an uncertain failure', async () => {
  let release: (value: Response) => void = () => {}
  const fetcher = vi.fn(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve
      })
  )
  vi.stubGlobal('fetch', fetcher)
  await show(<MultiTest />)
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '对话', exact: true }).click()
  await page.getByRole('button', { name: '开始测试' }).click()
  await expect
    .element(page.getByRole('button', { name: '测试中…' }))
    .toBeDisabled()
  await expect
    .element(page.getByLabelText('测试接口', { exact: true }))
    .toBeDisabled()
  release(
    Response.json({
      ok: false,
      message: '测试超时',
      duration_ms: 30,
      uncertain: true,
      error_code: 'upstream_timeout',
    })
  )
  await expect
    .element(page.getByText('执行结果未确认，可能产生费用'))
    .toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

function ImageTest() {
  const [busy, setBusy] = useState(false)
  return (
    <ChannelTest
      channel={channel}
      operations={['chat', 'image_generation']}
      initialModelId='existing-model'
      busy={busy}
      setBusy={setBusy}
    />
  )
}

it('generates an image explicitly, previews a private blob, and releases it when switching tests', async () => {
  const encoded =
    'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP8z4AdMOEQH6QSAM1BAQ/oQeJvAAAAAElFTkSuQmCC'
  let release: (value: Response) => void = () => {}
  const fetcher = vi.fn((_url: string, options?: RequestInit) => {
    expect(JSON.parse(String(options?.body))).toMatchObject({
      upstream_id: 'existing-model',
      version: 1,
      operation: 'image_generation',
      endpoint: 'images',
      stream: false,
      certify_health: false,
      input: { prompt: '画一只橘猫', size: '1024x1024', quality: 'high' },
    })
    return new Promise<Response>((resolve) => {
      release = resolve
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const createBlob = vi.spyOn(URL, 'createObjectURL')
  const revokeBlob = vi.spyOn(URL, 'revokeObjectURL')
  const { client } = await show(<ImageTest />)
  expect(fetcher).not.toHaveBeenCalled()
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '图片生成', exact: true }).click()
  await expect
    .element(page.getByLabelText('最大输出 Token'))
    .not.toBeInTheDocument()
  await page.getByLabelText('图片描述').fill('画一只橘猫')
  await page.getByLabelText('图片尺寸').click()
  await page.getByRole('option', { name: '1024x1024', exact: true }).click()
  await page.getByLabelText('画质').click()
  await page.getByRole('option', { name: 'high', exact: true }).click()
  await page.getByRole('button', { name: '生成 1 张图片' }).click()
  await expect
    .element(page.getByRole('button', { name: '测试中…' }))
    .toBeDisabled()
  await expect.element(page.getByLabelText('图片尺寸')).toBeDisabled()
  release(
    Response.json({
      ok: true,
      message: '图片生成成功',
      operation: 'image_generation',
      duration_ms: 50,
      usage_source: 'unknown',
      image_count: 1,
      image: {
        b64_json: encoded,
        width: 8,
        height: 8,
        bytes: 75,
        media_type: 'image/png',
      },
    })
  )
  const preview = page.getByRole('img', { name: '生成的测试图片' })
  await expect.element(preview).toBeVisible()
  await expect
    .poll(() => (preview.element() as HTMLImageElement).naturalWidth)
    .toBe(8)
  const link = page.getByRole('link', { name: '下载图片' })
  await expect.element(link).toHaveAttribute('download', 'actvero-image.png')
  const blobUrl = link.element().getAttribute('href')!
  expect(blobUrl.startsWith('blob:')).toBe(true)
  await expect.element(page.getByText('上游未返回完整用量')).toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(createBlob).toHaveBeenCalledTimes(1)
  expect(
    JSON.stringify(
      client
        .getQueryCache()
        .getAll()
        .map((q) => q.state.data)
    )
  ).not.toContain(encoded)
  await page.viewport(390, 844)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(391)
  await page.screenshot({
    path: '__screenshots__/channel-image-test-narrow.png',
  })
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '对话', exact: true }).click()
  await expect.element(preview).not.toBeInTheDocument()
  expect(revokeBlob).toHaveBeenCalledWith(blobUrl)
})

it('omits default image parameters and keeps failed media delivery uncertain without retrying', async () => {
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body))
    expect(body.operation).toBe('image_generation')
    for (const field of [
      'size',
      'quality',
      'response_format',
      'n',
      'max_output_tokens',
    ])
      expect(body.input[field]).toBeUndefined()
    return Response.json({
      ok: false,
      message: '图片无法安全读取',
      operation: 'image_generation',
      duration_ms: 50,
      uncertain: true,
      image_count: 1,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await show(<ImageTest />)
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '图片生成', exact: true }).click()
  await page.getByRole('button', { name: '生成 1 张图片' }).click()
  await expect
    .element(page.getByText('执行结果未确认，可能产生费用'))
    .toBeVisible()
  await expect
    .element(page.getByRole('link', { name: '下载图片' }))
    .not.toBeInTheDocument()
  expect(fetcher).toHaveBeenCalledTimes(1)
})

function SpeechTest() {
  const [busy, setBusy] = useState(false)
  return (
    <ChannelTest
      channel={channel}
      operations={['chat', 'speech']}
      initialModelId='existing-model'
      busy={busy}
      setBusy={setBusy}
    />
  )
}

function wavBase64() {
  const bytes = new Uint8Array(1644)
  const view = new DataView(bytes.buffer)
  const write = (at: number, value: string) =>
    [...value].forEach((c, i) => (bytes[at + i] = c.charCodeAt(0)))
  write(0, 'RIFF')
  view.setUint32(4, bytes.length - 8, true)
  write(8, 'WAVEfmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, 8000, true)
  view.setUint32(28, 16000, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  write(36, 'data')
  view.setUint32(40, 1600, true)
  return btoa(String.fromCharCode(...bytes))
}

it('validates speech input, delivers playable private WAV without autoplay, and releases it on edit', async () => {
  let release: (value: Response) => void = () => {}
  const fetcher = vi.fn((_url: string, options?: RequestInit) => {
    expect(JSON.parse(String(options?.body))).toMatchObject({
      version: 1,
      upstream_id: 'existing-model',
      operation: 'speech',
      endpoint: 'speech',
      stream: false,
      certify_health: false,
      input: {
        input: '你好，测试语音。',
        voice: 'alloy',
        response_format: 'wav',
      },
    })
    return new Promise<Response>((resolve) => {
      release = resolve
    })
  })
  vi.stubGlobal('fetch', fetcher)
  const createBlob = vi.spyOn(URL, 'createObjectURL')
  const revokeBlob = vi.spyOn(URL, 'revokeObjectURL')
  const { client } = await show(<SpeechTest />)
  expect(fetcher).not.toHaveBeenCalled()
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '语音合成', exact: true }).click()
  await expect
    .element(page.getByLabelText('最大输出 Token'))
    .not.toBeInTheDocument()
  await expect.element(page.getByText('输出格式：WAV')).toBeVisible()
  await page.getByRole('button', { name: '生成语音' }).click()
  await expect.element(page.getByText('请填写有效的上游音色 ID')).toBeVisible()
  expect(fetcher).not.toHaveBeenCalled()
  await page.getByLabelText('朗读文本').fill('你好，测试语音。')
  await page.getByLabelText('音色', { exact: true }).fill('alloy')
  await page.getByRole('button', { name: '生成语音' }).click()
  await expect
    .element(page.getByRole('button', { name: '测试中…' }))
    .toBeDisabled()
  await expect
    .element(page.getByLabelText('音色', { exact: true }))
    .toBeDisabled()
  const encoded = wavBase64()
  release(
    Response.json({
      request_id: 'speech-1',
      operation: 'speech',
      ok: true,
      message: '语音生成成功',
      duration_ms: 50,
      usage_source: 'unknown',
      audio_duration_ms: 100,
      audio: {
        b64_json: encoded,
        media_type: 'audio/wav',
        bytes: 1644,
        duration_ms: 100,
        channels: 1,
        sample_rate: 8000,
      },
    })
  )
  const player = page.getByLabelText('生成的语音')
  await expect.element(player).toBeVisible()
  const audio = player.element() as HTMLAudioElement
  await expect.poll(() => audio.duration).toBeCloseTo(0.1)
  expect(audio.autoplay).toBe(false)
  expect(audio.paused).toBe(true)
  const link = page.getByRole('link', { name: '下载音频' })
  await expect.element(link).toHaveAttribute('download', 'actvero-speech.wav')
  const url = link.element().getAttribute('href')!
  expect(url.startsWith('blob:')).toBe(true)
  await expect.element(page.getByText('上游未返回完整用量')).toBeVisible()
  expect(
    JSON.stringify(
      client
        .getQueryCache()
        .getAll()
        .map((q) => q.state.data)
    )
  ).not.toContain(encoded)
  expect(createBlob).toHaveBeenCalledTimes(1)
  expect(fetcher).toHaveBeenCalledTimes(1)
  await page.viewport(390, 844)
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(391)
  await page.screenshot({
    path: '__screenshots__/channel-speech-test-narrow.png',
  })
  await page.getByLabelText('朗读文本').fill('新的朗读内容')
  await expect.element(player).not.toBeInTheDocument()
  expect(revokeBlob).toHaveBeenCalledWith(url)
  expect(audio.getAttribute('src')).toBeNull()
})

it('keeps an uncertain speech failure out of playback and history has no raw audio', async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url.includes('/tests?'))
      return Response.json([
        {
          request_id: 'failed-speech',
          operation: 'speech',
          model: 'existing-model',
          tested_at: '2026-09-28T00:00:00Z',
          status: 'failure',
          uncertain: true,
          error_code: 'audio_delivery_failed',
          audio_duration_ms: null,
        },
      ])
    return Response.json({
      operation: 'speech',
      ok: false,
      message: '音频无法安全读取',
      uncertain: true,
      duration_ms: 100,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await show(<SpeechTest />)
  await page.getByLabelText('测试接口', { exact: true }).click()
  await page.getByRole('option', { name: '语音合成', exact: true }).click()
  await page.getByLabelText('音色', { exact: true }).fill('voice/custom')
  await page.getByRole('button', { name: '生成语音' }).click()
  await expect
    .element(page.getByText('执行结果未确认，可能产生费用'))
    .toBeVisible()
  await expect
    .element(page.getByLabelText('生成的语音'))
    .not.toBeInTheDocument()
  expect(fetcher).toHaveBeenCalledTimes(1)
  await page.getByRole('button', { name: '测试记录' }).click()
  await expect
    .element(page.getByText('输出音频 未知 ms（文件测量） · 上游用量未知'))
    .toBeVisible()
  expect(fetcher).toHaveBeenCalledTimes(2)
})
