import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page, userEvent } from 'vitest/browser'
import { ChannelDetail } from './channel-detail'
import { ChannelEditor } from './channel-editor'
import type { ProviderModule } from './provider-modules'
import { ProviderPicker } from './provider-picker'
import type { Detail } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'presets-org' },
    csrf: 'csrf-test',
    user: { id: 'admin' },
  }),
}))

const presets = [
  ['aihubmix', 'AIHubMix', 'https://aihubmix.com', '/v1', 'aggregator', true],
  [
    'volcengine',
    '火山方舟',
    'https://ark.cn-beijing.volces.com',
    '/api/v3',
    'vendor',
    false,
  ],
  [
    'zhipu',
    '智谱 GLM',
    'https://open.bigmodel.cn',
    '/api/paas/v4',
    'vendor',
    false,
  ],
  ['moonshot', 'Kimi', 'https://api.moonshot.cn', '/v1', 'vendor', false],
  [
    'qwen',
    '千问按量 API',
    'https://maas.qianwenaiapi.com',
    '/compatible-mode/v1',
    'vendor',
    false,
  ],
  [
    'qwen-token-plan',
    '千问 Token Plan（团队版）',
    'https://token-plan.maas.qianwenaiapi.com',
    '/compatible-mode/v1',
    'vendor',
    false,
  ],
] as const

const providers: ProviderModule[] = presets.map(
  ([id, name, root, prefix, category, modelDiscovery]) => ({
    id,
    name,
    official_service_root: root,
    default_api_prefix: prefix,
    setup_help:
      id === 'qwen-token-plan'
        ? '使用对应席位的 sk-sp- 套餐密钥；当前仅接入对话。'
        : '普通 API Key；套餐密钥不适用于此渠道。',
    default_base_url: root + prefix,
    version: 1,
    category,
    icon_key: id,
    aliases:
      id === 'moonshot'
        ? ['Moonshot', '月之暗面']
        : id === 'qwen-token-plan'
          ? ['阿里云', '通义千问', 'Token Plan']
          : [],
    reference_catalog:
      id === 'qwen-token-plan'
        ? {
            models: ['qwen3-max', 'qwen3-coder-plus'],
            source_url: 'https://help.aliyun.com/zh/model-studio/',
            checked_at: '2026-10-04T00:00:00Z',
          }
        : null,
    base_url_help: '服务根地址',
    allow_no_auth: false,
    default_apis: ['chat_completions'],
    model_discovery: modelDiscovery,
    balance_query: false,
    member_inference: true,
    member_operations: ['chat'],
    test_operations: ['chat'],
  })
)

const detail: Detail = {
  id: 'preset-channel',
  version: 1,
  provider: 'volcengine',
  name: '火山普通 API',
  description: '',
  icon: '',
  base_url: 'https://ark.cn-beijing.volces.com/api/v3',
  connection: { address_mode: 'provider_default', resolver_version: 1 },
  manual_enabled: true,
  automatic_protection: { enabled: true },
  auth_mode: 'api_key',
  credential_configured: true,
  timeout_seconds: 20,
  declared_apis: ['chat_completions'],
  archived: false,
  model_count: 0,
  created_at: '2026-10-04T00:00:00Z',
  last_check: null,
  checks: [],
  models: [],
}

const clients: QueryClient[] = []
async function show(component: ReactNode, channel?: Detail) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  client.setQueryData(
    ['organization', 'presets-org', 'llm-providers'],
    providers
  )
  if (channel)
    client.setQueryData(
      ['organization', 'presets-org', 'model-channels', channel.id],
      channel
    )
  clients.push(client)
  const view = await render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
  await waitForAnimations()
  return view
}
beforeEach(async () => page.viewport(1280, 900))
afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 800)
})

it('searches API-driven preset cards and filters aggregators without package cards', async () => {
  const select = vi.fn()
  await show(
    <ProviderPicker providers={providers} select={select} close={vi.fn()} />
  )
  await page.getByRole('combobox', { name: '供应商分类' }).click()
  await page.getByRole('option', { name: '聚合服务' }).click()
  await expect
    .element(page.getByRole('button', { name: 'AIHubMix' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '火山方舟' }))
    .not.toBeInTheDocument()
  await page.getByRole('combobox', { name: '供应商分类' }).click()
  await page.getByRole('option', { name: '全部供应商分类' }).click()
  await page.getByRole('textbox', { name: '搜索供应商' }).fill('月之暗面')
  await expect.element(page.getByRole('button', { name: 'Kimi' })).toBeVisible()
  await page.getByRole('button', { name: 'Kimi' }).click()
  expect(select).toHaveBeenCalledWith(
    expect.objectContaining({ id: 'moonshot' })
  )
})

it.each(presets)(
  'shows the official ordinary API root and prefix for %s',
  async (_id, name, root, prefix, _category, modelDiscovery) => {
    await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
    await page.getByRole('button', { name, exact: true }).click()
    await expect.element(page.getByText(root, { exact: true })).toBeVisible()
    await expect.element(page.getByText(prefix, { exact: true })).toBeVisible()
    await expect
      .element(
        page.getByText(
          _id === 'qwen-token-plan'
            ? '使用对应席位的 sk-sp- 套餐密钥；当前仅接入对话。'
            : '普通 API Key；套餐密钥不适用于此渠道。'
        )
      )
      .toBeVisible()
    if (modelDiscovery) {
      await expect
        .element(page.getByRole('button', { name: '检查目录连接' }))
        .toBeVisible()
      await expect
        .element(page.getByRole('button', { name: '从上游获取' }))
        .toBeVisible()
    } else {
      await expect
        .element(page.getByRole('button', { name: '检查目录连接' }))
        .not.toBeInTheDocument()
      await expect
        .element(page.getByRole('button', { name: '从上游获取' }))
        .not.toBeInTheDocument()
      await expect
        .element(
          page.getByText(
            _id === 'qwen-token-plan'
              ? '上游模型库存'
              : '此预设暂未接入模型目录'
          )
        )
        .toBeVisible()
    }
  }
)

it('keeps the new provider card and long official root within a 390px editor', async () => {
  await page.viewport(390, 844)
  await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
  await page.getByRole('textbox', { name: '搜索供应商' }).fill('千问')
  await expect
    .element(page.getByRole('button', { name: '千问按量 API' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '千问 Token Plan（团队版）' }))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.getByRole('button', { name: '千问按量 API' }).click()
  const root = page.getByText('https://maas.qianwenaiapi.com', {
    exact: true,
  })
  await expect.element(root).toBeVisible()
  root.element().scrollIntoView({ block: 'center' })
  await expect
    .element(page.getByText('/compatible-mode/v1', { exact: true }))
    .toBeVisible()
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '__screenshots__/actvero-r11-qwen-390.png' })
})

it('loads Token Plan reference candidates without selecting or discovering them, then saves only chosen and manual models', async () => {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body)) as Record<string, unknown>
      calls.push({ url, body })
      if (url.endsWith('/channel-addresses/resolve'))
        return Response.json({
          address_mode: 'provider_default',
          resolver_version: 1,
          directory_method: 'GET',
          directory_url: null,
          operation_targets: [
            {
              operation: 'chat',
              method: 'POST',
              url: 'https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1/chat/completions',
            },
          ],
          warnings: [],
        })
      if (url.endsWith('/llm/channels') && options?.method === 'POST')
        return Response.json({
          ...detail,
          provider: 'qwen-token-plan',
          models: [
            {
              id: 'qwen3-max',
              source: 'configuration',
              registered_at: detail.created_at,
            },
            {
              id: 'my-seat-model',
              source: 'configuration',
              registered_at: detail.created_at,
            },
          ],
        })
      throw new Error('Unexpected request: ' + url)
    })
  )
  const saved = vi.fn()
  await page.viewport(390, 844)
  await show(<ChannelEditor close={vi.fn()} saved={saved} />)
  await page.getByRole('textbox', { name: '搜索供应商' }).fill('阿里云')
  await expect
    .element(page.getByRole('button', { name: '千问 Token Plan（团队版）' }))
    .toBeVisible()
  await page.getByRole('button', { name: '千问 Token Plan（团队版）' }).click()
  await expect
    .element(
      page.getByText('https://token-plan.maas.qianwenaiapi.com', {
        exact: true,
      })
    )
    .toBeVisible()
  await expect
    .element(page.getByText('使用对应席位的 sk-sp- 套餐密钥；当前仅接入对话。'))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '检查目录连接' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('button', { name: '从上游获取' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByText('官方套餐参考清单'))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByText('参考候选仅供查找，未验证当前密钥权限。'))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '载入套餐参考模型' }))
    .not.toBeInTheDocument()
  const search = page.getByRole('textbox', { name: '搜索或输入模型 ID' })
  await search.fill('qwen3-max')
  await expect
    .element(page.getByRole('button', { name: /qwen3-max.*参考/ }))
    .toBeVisible()
  expect(calls).toHaveLength(0)
  await page.getByRole('button', { name: /qwen3-max.*参考/ }).click()
  await search.fill('my-seat-model')
  await page
    .getByRole('button', { name: '添加自定义模型 ID：my-seat-model' })
    .click()
  await page.getByRole('button', { name: '预览最终地址' }).click()
  await expect
    .element(
      page.getByText(
        '模型目录：此套餐不提供目录，可搜索参考模型或输入实际模型 ID'
      )
    )
    .toBeVisible()
  await expect
    .element(
      page.getByText(
        'chat：POST https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1/chat/completions'
      )
    )
    .toBeVisible()
  await page
    .getByRole('textbox', { name: 'API Key', exact: true })
    .fill('sk-sp-test')
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(calls.map(({ url }) => url)).toEqual([
    expect.stringContaining('/channel-addresses/resolve'),
    expect.stringContaining('/llm/channels'),
  ])
  expect(calls[1].body).toEqual(
    expect.objectContaining({
      provider: 'qwen-token-plan',
      connection: expect.objectContaining({ address_mode: 'provider_default' }),
      models: [{ id: 'qwen3-max' }, { id: 'my-seat-model' }],
    })
  )
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
})

it.each([1280, 390])(
  'searches, selects, removes and adds custom model IDs without network calls at %ipx',
  async (width) => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await page.viewport(width, 844)
    await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
    await page
      .getByRole('button', { name: '千问 Token Plan（团队版）' })
      .click()
    const search = page.getByRole('textbox', { name: '搜索或输入模型 ID' })
    await search.fill('qwen3')
    await expect
      .element(page.getByRole('button', { name: /qwen3-max.*参考/ }))
      .toBeVisible()
    await search.fill('qwen3-max')
    await expect
      .element(
        page.getByRole('button', { name: '添加自定义模型 ID：qwen3-max' })
      )
      .not.toBeInTheDocument()
    await page.getByRole('button', { name: /qwen3-max.*参考/ }).click()
    await expect
      .element(
        page.getByRole('group', { name: '已选模型' }).getByText('qwen3-max')
      )
      .toBeVisible()
    await search.fill('qwen3-max')
    await expect.element(page.getByText('已在清单中')).toBeVisible()
    await search.fill('qwen3-cod')
    await expect
      .element(page.getByRole('button', { name: /qwen3-coder-plus.*参考/ }))
      .toBeVisible()
    await page
      .getByRole('button', { name: '添加自定义模型 ID：qwen3-cod' })
      .click()
    await expect.element(page.getByText('已选择（2）')).toBeVisible()
    await page.getByRole('button', { name: '移除 qwen3-max' }).click()
    await expect.element(page.getByText('已选择（1）')).toBeVisible()
    await search.fill('invalid model ID')
    await page
      .getByRole('button', { name: '添加自定义模型 ID：invalid model ID' })
      .click()
    await expect
      .element(
        page.getByRole('alert').filter({ hasText: '模型 ID 最多 200 个字符' })
      )
      .toBeVisible()
    await expect.element(page.getByText('已选择（1）')).toBeVisible()
    expect(fetch).not.toHaveBeenCalled()
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width)
  }
)

it('keeps upstream model ID case on Enter and rejects only identical duplicates', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await show(<ChannelEditor close={vi.fn()} saved={vi.fn()} />)
  await page.getByRole('button', { name: '千问 Token Plan（团队版）' }).click()
  const search = page.getByRole('textbox', { name: '搜索或输入模型 ID' })
  await search.fill('Model-A')
  await userEvent.keyboard('{Enter}')
  await expect
    .element(page.getByRole('group', { name: '已选模型' }).getByText('Model-A'))
    .toBeVisible()
  await search.fill('model-a')
  await expect
    .element(page.getByRole('button', { name: '添加自定义模型 ID：model-a' }))
    .toBeVisible()
  await userEvent.keyboard('{Enter}')
  await expect
    .element(
      page
        .getByRole('group', { name: '已选模型' })
        .getByText('model-a', { exact: true })
    )
    .toBeVisible()
  await expect.element(page.getByText('已选择（2）')).toBeVisible()
  await search.fill('model-a')
  await userEvent.keyboard('{Enter}')
  await expect.element(page.getByText('已选择（2）')).toBeVisible()
  await search.fill('qwen3-max')
  await userEvent.keyboard('{Enter}')
  await expect
    .element(
      page.getByRole('group', { name: '已选模型' }).getByText('qwen3-max')
    )
    .toBeVisible()
  await search.fill('QWEN3-CODER-PLUS')
  await expect
    .element(page.getByRole('button', { name: /qwen3-coder-plus.*参考/ }))
    .toBeVisible()
  await expect
    .element(
      page.getByRole('button', {
        name: '添加自定义模型 ID：QWEN3-CODER-PLUS',
      })
    )
    .toBeVisible()
  await userEvent.keyboard('{Enter}')
  await expect
    .element(
      page
        .getByRole('group', { name: '已选模型' })
        .getByText('QWEN3-CODER-PLUS')
    )
    .toBeVisible()
  await expect.element(page.getByText('已选择（4）')).toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
})

it('previews a null directory and saves manual stock without checking or testing upstream', async () => {
  const calls: { url: string; body: Record<string, unknown> }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      const body = JSON.parse(String(options?.body)) as Record<string, unknown>
      calls.push({ url, body })
      if (url.endsWith('/channel-addresses/resolve'))
        return Response.json({
          address_mode: 'provider_default',
          resolver_version: 1,
          directory_method: 'GET',
          directory_url: null,
          operation_targets: [
            {
              operation: 'chat',
              method: 'POST',
              url: 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
            },
          ],
          warnings: [],
        })
      if (url.endsWith('/llm/channels') && options?.method === 'POST')
        return Response.json({
          ...detail,
          models: [
            {
              id: 'doubao-pro-32k',
              source: 'configuration',
              registered_at: '2026-10-04T00:00:00Z',
            },
          ],
          model_count: 1,
        })
      throw new Error('Unexpected request: ' + url)
    })
  )
  const saved = vi.fn()
  await page.viewport(390, 844)
  await show(<ChannelEditor close={vi.fn()} saved={saved} />)
  await page.getByRole('button', { name: '火山方舟', exact: true }).click()
  await page.getByRole('button', { name: '预览最终地址' }).click()
  await expect
    .element(page.getByText('模型目录：当前预设暂未接入，请手动登记模型 ID'))
    .toBeVisible()
  await page
    .getByRole('textbox', { name: '搜索或输入模型 ID' })
    .fill('doubao-pro-32k')
  await page
    .getByRole('button', { name: '添加自定义模型 ID：doubao-pro-32k' })
    .click()
  await page
    .getByRole('textbox', { name: 'API Key', exact: true })
    .fill('fake-preset-key')
  await page.getByRole('button', { name: '保存为新渠道' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(calls.map(({ url }) => url)).toEqual([
    expect.stringContaining('/channel-addresses/resolve'),
    expect.stringContaining('/llm/channels'),
  ])
  expect(calls[1].body).toEqual(
    expect.objectContaining({
      provider: 'volcengine',
      connection: expect.objectContaining({ address_mode: 'provider_default' }),
      models: [{ id: 'doubao-pro-32k' }],
    })
  )
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
  await page.screenshot({ path: '__screenshots__/actvero-r11-manual-390.png' })
})

it('keeps saved no-directory channels readable and allows manual registration', async () => {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      calls.push(url)
      if (url.endsWith('/channel-addresses/resolve'))
        return Response.json({
          address_mode: 'provider_default',
          resolver_version: 1,
          directory_method: 'GET',
          directory_url: null,
          operation_targets: [
            {
              operation: 'chat',
              method: 'POST',
              url: 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
            },
          ],
          warnings: [],
        })
      if (url.endsWith('/channels/preset-channel/models'))
        return Response.json({
          ...detail,
          version: 2,
          models: [
            {
              id: 'doubao-pro-32k',
              source: 'manual',
              registered_at: '2026-10-04T00:00:00Z',
            },
          ],
          model_count: 1,
        })
      if (url.endsWith('/channels/preset-channel')) return Response.json(detail)
      throw new Error('Unexpected request: ' + url + ' ' + options?.method)
    })
  )
  await show(
    <ChannelDetail
      id={detail.id}
      initialTab='connection'
      close={vi.fn()}
      changed={vi.fn()}
      edit={vi.fn()}
      restoreFocus={vi.fn()}
    />,
    detail
  )
  await expect
    .element(
      page.getByText(
        '当前预设暂未接入模型目录，请手动登记模型 ID；可单独进行调用诊断。'
      )
    )
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '检查目录' }))
    .not.toBeInTheDocument()
  await page.getByRole('tab', { name: '上游模型（0）' }).click()
  await expect
    .element(page.getByRole('button', { name: '发现模型' }))
    .not.toBeInTheDocument()
  await expect.element(page.getByText('此预设暂未接入模型目录')).toBeVisible()
  await page.getByRole('textbox', { name: '模型 ID' }).fill('doubao-pro-32k')
  await page.getByRole('button', { name: '登记模型', exact: true }).click()
  await expect
    .poll(
      () =>
        calls.filter((url) => url.endsWith('/channels/preset-channel/models'))
          .length
    )
    .toBe(1)
  expect(
    calls.some(
      (url) =>
        url.endsWith('/discover') ||
        url.endsWith('/check') ||
        url.includes('/diagnostics')
    )
  ).toBe(false)
})
