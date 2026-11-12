import type { ReactNode } from 'react'
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from '@tanstack/react-query'
import '@/styles/index.css'
import { waitForAnimations } from '@/test-utils/animations'
import { ARK_AGENT_PLAN_CONFIG } from '@/vendor/newapi/features/channels/lib/connection-templates'
import { ModelPricingPanel } from '@/vendor/newapi/features/model-pricing/model-pricing-panel'
import { PriceSyncDialog } from '@/vendor/newapi/features/models/components/dialogs/price-sync-dialog'
import { SyncWizardDialog } from '@/vendor/newapi/features/models/components/dialogs/sync-wizard-dialog'
import { ModelMutateDrawer } from '@/vendor/newapi/features/models/components/drawers/model-mutate-drawer'
import { api as nativeApi } from '@/vendor/newapi/lib/api'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { GatewayChannels } from './channels'
import { ModelParameters, type ParameterDraftState } from './model-parameters'
import { NativeLanguage } from './native-language'
import { NativeModelManagement } from './native-models'
import { bindNativeAdministrator } from './native-session'
import { GatewayPage } from './page'
import { makePricing, tokenRates } from './pricing'
import { ModelPublication } from './publication'
import { GatewayStatistics } from './statistics'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => {
    const session = useQueryClient().getQueryData<{
      organization: { tenant_id: string }
      csrf: string
    }>(['test-organization-session'])
    if (!session)
      throw new Error('Organization session is outside this query client')
    return session
  },
}))
vi.mock('@tanstack/react-router', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-router')>(
    '@tanstack/react-router'
  )
  const search = { section: 'metadata' }
  const navigate = () => Promise.resolve()
  return {
    ...actual,
    getRouteApi: (id: string) =>
      id === '/_authenticated/models'
        ? { useSearch: () => search, useNavigate: () => navigate }
        : actual.getRouteApi(id as '/_authenticated/models'),
  }
})
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
    <main>
      <h1>{title}</h1>
      {action}
      {children}
    </main>
  ),
}))
vi.mock('@/features/model-catalog/page', () => ({
  ModelCatalogPage: () => <p>legacy-model-page</p>,
}))
vi.mock('@/features/model-channels/page', () => ({
  ModelChannelsPage: () => <p>legacy-channel-page</p>,
}))
const nativeAdapter = nativeApi.defaults.adapter
let nativeDetailVersion = 'a'.repeat(64)
let nativeUpdateVersion = ''
let client: QueryClient
const writes: { url: string; body: Record<string, unknown> }[] = []
const reads: string[] = []
const c = {
  id: 1,
  name: '测试渠道',
  type: 1,
  status: 1,
  base_url: 'https://api.example.com',
  models: 'chosen',
  group: 'default',
  weight: 1,
  revision: 'revision',
  priority: 0,
  model_mapping: '{}',
}
async function show(
  node: ReactNode,
  handler: (
    url: string,
    method?: string,
    body?: Record<string, unknown>
  ) => unknown = () => undefined
) {
  nativeDetailVersion = 'a'.repeat(64)
  nativeUpdateVersion = ''
  nativeApi.defaults.adapter = async (config) => {
    let data: unknown
    if (config.method === 'get') reads.push(config.url ?? '')
    const custom =
      config.method === 'get' ? handler(config.url ?? '') : undefined
    if (
      config.method === 'put' ||
      config.method === 'post' ||
      config.method === 'patch'
    ) {
      nativeUpdateVersion = String(config.headers.get('If-Match'))
      const body = JSON.parse(config.data)
      writes.push({ url: config.url ?? '', body })
      data = handler(config.url ?? '', config.method.toUpperCase(), body)
    } else if (custom !== undefined) {
      data = custom
    } else if (config.url === '/api/vendors/') {
      data = { items: [], total: 0 }
    } else if (config.url === '/api/status') {
      data = { quota_per_unit: 500000 }
    } else if (config.url === '/api/option/model_pricing') {
      data = {
        entries: [],
        options: { quota_per_unit: 500000 },
        empty_version: 'empty',
      }
    } else if (config.url === '/api/channel/1') {
      data = {
        ...c,
        key: '',
        revision: nativeDetailVersion,
        channel_info: { is_multi_key: false, multi_key_mode: 'random' },
        setting: '{"proxy":"http://proxy.example:8080"}',
        settings: '{"disable_task_polling_sleep":true,"custom_native":true}',
        header_override: '{"x-native":"kept"}',
      }
    } else if (config.url === '/api/channel/default_base_urls') {
      data = { 1: 'https://api.openai.com' }
    } else if (
      config.url === '/api/group/' ||
      config.url === '/api/prefill_group/'
    ) {
      data = ['default']
    } else if (config.url === '/api/task_plugin_options') {
      data = []
    } else if (config.url === '/api/channel/models') {
      data = ['chosen', 'unselected']
    } else if (config.url === '/api/channel/ops') {
      data = { retry_times: 0 }
    } else {
      throw new Error('Unexpected native request ' + config.url)
    }
    return {
      data: { success: true, data },
      config,
      headers: {},
      status: 200,
      statusText: 'OK',
    }
  }
  writes.length = 0
  reads.length = 0
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['test-organization-session'], {
    organization: { tenant_id: 'gateway-test' },
    csrf: 'csrf',
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (
        url.endsWith('/publication/status') ||
        url.endsWith('/publication/preview')
      ) {
        reads.push(url)
        const custom = handler(url)
        if (custom !== undefined) return Response.json(custom)
        const body = JSON.parse(String(init?.body ?? '{}'))
        const status = (model: string) => ({
          model_name: model,
          enabled: body.draft?.enabled ?? false,
          audience: body.draft?.audience ?? 'administrators',
          member_count: 0,
          ready: true,
          active_channels: 1,
          checks: [],
          automatic: {},
        })
        return Response.json(
          url.endsWith('/publication/status')
            ? { items: body.models.map(status) }
            : {
                configuration: status(body.draft.model_name),
                member_name: body.member_id ? 'Preview member' : null,
                discoverable: !!body.draft.enabled,
                access_message: body.draft.enabled
                  ? '该成员可在桌面模型目录中发现此模型'
                  : '此模型尚未开放',
                quota_status: 'active',
                remaining_points: '100',
                resets_at: null,
              }
        )
      }
      if (init?.method && init.method !== 'GET') {
        const body = JSON.parse(String(init.body ?? '{}'))
        writes.push({ url, body })
        return Response.json(handler(url, init.method, body) ?? { data: {} })
      }
      reads.push(url)
      const custom = handler(url)
      if (custom !== undefined) return Response.json(custom)
      if (url.includes('/parameters?'))
        return Response.json({
          data: {
            version: 0,
            automatic: { status: 'unresolved' },
            sources: [],
          },
        })
      if (url.includes('/models?') || url.endsWith('/vendors'))
        return Response.json({ data: { items: [], total: 0 } })
      if (url.includes('/channels?'))
        return Response.json({ data: { items: [c], total: 1 } })
      if (url.endsWith('/channel-options'))
        return Response.json({
          data: {
            base_urls: { '1': 'https://api.openai.com' },
            groups: ['default'],
          },
        })
      if (url.endsWith('/channels/1/directory'))
        return Response.json({
          models: ['chosen', 'unselected'],
          fetched_at: '2026-01-01T00:00:00Z',
        })
      throw new Error('Unexpected request ' + url)
    })
  )
  await render(
    <QueryClientProvider client={client}>{node}</QueryClientProvider>
  )
  await waitForAnimations()
}
afterEach(async () => {
  await cleanup()
  await client?.cancelQueries()
  client?.clear()
  nativeApi.defaults.adapter = nativeAdapter
  vi.unstubAllGlobals()
})
it('prefills Agent Plan native routes and labels its supplier public directory', async () => {
  await page.viewport(1440, 1000)
  await show(<GatewayChannels />, (url) =>
    url === '/api/channel/fetch_models' ? ['upstream-agent-model'] : undefined
  )
  await page.getByRole('button', { name: '添加渠道', exact: true }).click()
  await page
    .getByRole('option', { name: '火山 Agent Plan 内置', exact: true })
    .click()
  await expect
    .element(page.getByRole('textbox', { name: 'API 地址', exact: true }))
    .toHaveValue('https://ark.cn-beijing.volces.com')
  await page.getByRole('textbox', { name: /API 密钥/ }).fill('test-plan-key')
  await page.getByRole('button', { name: '获取公开模型', exact: true }).click()
  await expect
    .poll(() =>
      writes.some((write) => write.url === '/api/channel/fetch_models')
    )
    .toBe(true)
  const discovery = writes.find(
    (write) => write.url === '/api/channel/fetch_models'
  )!
  expect(discovery.body).toMatchObject({
    type: 58,
    base_url: 'https://ark.cn-beijing.volces.com',
    advanced_custom: JSON.stringify(ARK_AGENT_PLAN_CONFIG),
  })
  expect(discovery.body).not.toHaveProperty('models')
  await expect.element(page.getByText(/来自火山公开文本模型目录/)).toBeVisible()
  await expect
    .element(page.getByText('upstream-agent-model', { exact: true }).first())
    .toBeVisible()
})
it('keeps missing prices distinct from free pricing and refreshes clean imported prices', async () => {
  bindNativeAdministrator('csrf', '')
  const config = {
    entries: [
      {
        model_name: 'public-model',
        version: 'empty',
        configured: {},
        effective: {},
      },
    ],
    options: {},
    empty_version: 'empty',
  }
  await show(
    <NativeLanguage>
      <ModelPricingPanel modelName='public-model' />
    </NativeLanguage>,
    (url) =>
      url === '/api/option/model_pricing'
        ? config
        : url === '/api/pricing'
          ? []
          : undefined
  )
  await expect
    .element(page.getByText('未配置计费价格', { exact: true }))
    .toBeVisible()
  const preview = page.getByRole('complementary', { name: '预览' })
  await expect.element(preview).toHaveTextContent('尚未配置价格')
  await expect.element(preview).not.toHaveTextContent('tier("base"')
  await page.getByRole('button', { name: '保存模型价格', exact: true }).click()
  expect(writes).toHaveLength(0)
  client.setQueryData(['model-pricing-config', 'public-model'], {
    ...config,
    entries: [
      {
        model_name: 'public-model',
        version: 'imported',
        configured: {},
        effective: {
          'billing_setting.billing_mode': 'tiered_expr',
          'billing_setting.billing_expr':
            'tier("reference", p * 1 + cr * 0.1 + c * 3)',
        },
        pricing_reference: {
          label: 'TRAE 官方参考价',
          url: 'https://docs.volcengine.com/docs/trae-cn/billing-items?lang=zh',
          verified_at: '2026-10-28',
          basis: 'official_reference',
        },
      },
    ],
  })
  await expect
    .element(page.getByRole('link', { name: 'TRAE 官方参考价', exact: true }))
    .toBeVisible()
  await expect.element(preview).not.toHaveTextContent('尚未配置价格')
})

it.each([
  [1440, 900],
  [1024, 480],
  [390, 640],
])(
  'keeps native price source selection inside a %i × %i viewport',
  async (width, height) => {
    await page.viewport(width, height)
    await show(
      <NativeLanguage>
        <PriceSyncDialog open onOpenChange={() => {}} />
      </NativeLanguage>,
      (url) => (url === '/api/ratio_sync/channels' ? [] : undefined)
    )
    const pricing = page.getByRole('dialog', {
      name: '同步模型定价',
      exact: true,
    })
    await expect.element(pricing).toBeVisible()
    await page
      .getByRole('button', { name: '选择价格来源', exact: true })
      .click()
    const sources = page.getByRole('dialog', {
      name: '选择价格来源',
      exact: true,
    })
    await expect.element(sources).toBeVisible()
    await expect
      .poll(() => {
        const bounds = sources.element().getBoundingClientRect()
        return (
          bounds.top >= 15 &&
          bounds.bottom <= height - 15 &&
          bounds.left >= 15 &&
          bounds.right <= width - 15 &&
          bounds.height <= height * 0.9 + 1
        )
      })
      .toBe(true)
    const confirm = sources.getByRole('button', {
      name: '确认选择',
      exact: true,
    })
    await expect
      .poll(() => {
        const bounds = confirm.element().getBoundingClientRect()
        return bounds.top >= 0 && bounds.bottom <= height
      })
      .toBe(true)
    await sources.getByRole('button', { name: '取消', exact: true }).click()
    await expect.element(pricing).toBeVisible()
    await expect
      .element(page.getByRole('button', { name: '选择价格来源', exact: true }))
      .toHaveFocus()
    expect(writes).toHaveLength(0)
  }
)
it('creates independent metadata through the shared native model form without a channel', async () => {
  const close = vi.fn()
  await show(
    <NativeLanguage>
      <ModelMutateDrawer open onOpenChange={close} />
    </NativeLanguage>
  )
  await page.getByLabelText('调用 ID *', { exact: true }).fill('team-model')
  await page.getByLabelText('展示名称', { exact: true }).fill('团队通用模型')
  await page.getByRole('button', { name: '保存资料', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].url).toBe('/api/models/')
  expect(writes[0].body.model_name).toBe('team-model')
  expect(writes[0].body.display_name).toBe('团队通用模型')
  expect(writes[0].body).not.toHaveProperty('channel_id')
  expect(reads.some((url) => url.includes('/channels'))).toBe(false)
  await expect.poll(() => close.mock.calls).toContainEqual([false])
})
it('previews public metadata and applies only selected native source revisions', async () => {
  await show(
    <NativeLanguage>
      <SyncWizardDialog open onOpenChange={() => {}} />
    </NativeLanguage>,
    (url) => {
      if (url.startsWith('/api/models/sync_upstream/preview'))
        return {
          source: {
            version: 'source-v1',
            locale: 'zh',
            models_url: 'https://example.com/models',
            vendors_url: 'https://example.com/vendors',
          },
          candidates: [
            {
              model_name: 'public-chat',
              kind: 'create',
              scope: 'catalog',
              record_version: 'new-record',
              fields: [],
              vendor_to_create: 'Vendor',
              upstream: {
                vendor: 'Vendor',
                description: '公开资料',
                icon: '',
                tags: '',
                endpoints: '',
                name_rule: 0,
                status: 1,
              },
            },
          ],
        }
      if (url === '/api/models/sync_upstream')
        return {
          created_models: ['public-chat'],
          updated_models: [],
          created_vendors: ['Vendor'],
        }
      return undefined
    }
  )
  await page.getByRole('button', { name: '加载资料预览', exact: true }).click()
  expect(writes).toHaveLength(0)
  await page.getByRole('combobox', { name: '同步范围', exact: true }).click()
  await page.getByRole('option', { name: '上游模型列表', exact: true }).click()
  await page
    .getByRole('checkbox', { name: '选择 public-chat', exact: true })
    .click()
  await page.getByRole('button', { name: '预览所选变更', exact: true }).click()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '检查并确认', exact: true }).click()
  expect(writes).toHaveLength(0)
  await page
    .getByRole('button', { name: '应用 1 个模型的变更', exact: true })
    .click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({
    source_version: 'source-v1',
    locale: 'zh',
  })
  expect(writes[0].body.selections).toEqual([
    {
      model_name: 'public-chat',
      record_version: 'new-record',
      create: true,
      fields: [],
    },
  ])
  await expect
    .element(page.getByText('资料同步完成', { exact: true }))
    .toBeVisible()
})
it('saves an existing native model from the footer button with its loaded revision', async () => {
  const close = vi.fn()
  const model = {
    id: 21,
    model_name: 'editable-model',
    status: 1,
    sync_official: 1,
    name_rule: 0,
    created_time: 100,
    updated_time: 100,
    revision: 'a'.repeat(64),
  }
  await show(
    <NativeLanguage>
      <ModelMutateDrawer open currentRow={model} onOpenChange={close} />
    </NativeLanguage>,
    (url) =>
      url === '/api/models/21'
        ? { ...model, description: 'Original' }
        : undefined
  )
  await expect
    .element(page.getByLabelText('展示名称', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByLabelText('说明信息', { exact: true }))
    .not.toBeInTheDocument()
  await page.getByLabelText('展示名称', { exact: true }).fill('通过底部保存')
  await page.getByRole('button', { name: '保存资料', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({
    id: 21,
    description: 'Original',
    display_name: '通过底部保存',
    model_name: 'editable-model',
  })
  expect(nativeUpdateVersion).toBe('a'.repeat(64))
  await expect.poll(() => close.mock.calls).toContainEqual([false])
})
it('edits and clears the member-facing name without changing the invocation ID', async () => {
  const model = {
    id: 21,
    model_name: 'deepseek-flash',
    display_name: 'DeepSeek V4.1 Flash',
    status: 1,
    sync_official: 1,
    name_rule: 0,
    created_time: 100,
    updated_time: 100,
    revision: 'b'.repeat(64),
  }
  await show(
    <NativeLanguage>
      <ModelMutateDrawer open currentRow={model} onOpenChange={() => {}} />
    </NativeLanguage>,
    (url) => (url === '/api/models/21' ? model : undefined)
  )
  await expect
    .element(page.getByLabelText('展示名称', { exact: true }))
    .toHaveValue(model.display_name)
  await page.getByLabelText('展示名称', { exact: true }).fill('团队快速模型')
  await page.getByRole('button', { name: '保存资料', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({
    model_name: model.model_name,
    display_name: '团队快速模型',
  })
  expect(nativeUpdateVersion).toBe(model.revision)
  await page.getByLabelText('展示名称', { exact: true }).fill('')
  await page.getByRole('button', { name: '保存资料', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].body).toMatchObject({
    model_name: model.model_name,
    display_name: '',
  })
})
it('edits through the native form and preserves provider settings without resubmitting a key', async () => {
  localStorage.setItem('actvero:gateway-channels:view', 'table')
  await show(<GatewayChannels />)
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: /测试渠道.*返回渠道列表/ }))
    .toBeVisible()
  for (const name of ['路由与映射', '请求与响应', '其他设置']) {
    await expect
      .element(page.getByRole('tab', { name: new RegExp('^' + name) }))
      .toBeVisible()
  }
  await page
    .getByLabelText('名称 *', { exact: true })
    .fill('Renamed native channel')
  // A background detail read must not advance the dirty editor's snapshot.
  nativeDetailVersion = 'b'.repeat(64)
  await nativeApi.get('/api/channel/1')
  await page.getByRole('button', { name: '更新渠道', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].url).toBe('/api/channel/')
  expect(nativeUpdateVersion).toBe('a'.repeat(64))
  expect(writes[0].body).toMatchObject({
    name: 'Renamed native channel',
    header_override: '{"x-native":"kept"}',
  })
  expect(writes[0].body).not.toHaveProperty('key')
  expect(JSON.parse(String(writes[0].body.setting))).toMatchObject({
    proxy: 'http://proxy.example:8080',
  })
  expect(JSON.parse(String(writes[0].body.settings))).toMatchObject({
    disable_task_polling_sleep: true,
    custom_native: true,
  })
  await page.getByRole('button', { name: '添加渠道', exact: true }).click()
  await expect
    .element(page.getByRole('heading', { name: '创建渠道', exact: true }))
    .toBeVisible()
  await page.getByRole('option', { name: /^OpenAI 内置 #/ }).click()
  for (const name of ['路由与映射', '请求与响应', '其他设置']) {
    await expect
      .element(page.getByRole('tab', { name: new RegExp('^' + name) }))
      .toBeVisible()
  }
  await expect
    .element(page.getByRole('button', { name: '创建渠道', exact: true }))
    .toBeVisible()
  await page.getByRole('button', { name: /创建渠道.*返回渠道列表/ }).click()
  await expect
    .element(page.getByRole('heading', { name: '创建渠道', exact: true }))
    .not.toBeInTheDocument()
  expect(writes).toHaveLength(1)
})
it('keeps organization access in the host session outside the native query cache', async () => {
  await page.viewport(1280, 900)
  let parameters = { version: 2, context_window: 32000 }
  let pricingFailed = false
  await show(
    <NativeLanguage>
      <NativeModelManagement />
    </NativeLanguage>,
    (url, method, body) => {
      if (url === '/api/models/')
        return {
          items: [
            {
              id: 21,
              model_name: 'policy-model',
              status: 1,
              sync_official: 1,
              name_rule: 0,
              created_time: 100,
              updated_time: 100,
            },
          ],
          total: 1,
        }
      if (url === '/api/models/21')
        return {
          id: 21,
          model_name: 'policy-model',
          name_rule: 0,
          status: 1,
          sync_official: 1,
          created_time: 100,
          updated_time: 100,
          revision: 'a'.repeat(64),
        }
      if (url.includes('/publication?model=policy-model'))
        return {
          data: {
            ...parameters,
            model_name: 'policy-model',
            name: 'Policy model',
            enabled: false,
            audience: 'administrators',
            relay_ready: true,
          },
        }
      if (url.includes('/parameters?') && url.endsWith('model=policy-model')) {
        if (method === 'PUT')
          parameters = {
            ...parameters,
            ...body,
            version: parameters.version + 1,
          }
        return { data: parameters }
      }
      if (url.includes('/reference-models?')) {
        const base = {
          model_id: 'policy-model',
          name: '公共模型',
          context_window: 128000,
          capabilities: { tools: 'supported', structured_output: 'unknown' },
          reasoning_options: [],
        }
        return {
          items: [
            {
              ...base,
              provider: 'a',
              provider_name: '供应商 A',
              max_output: 96000,
            },
            {
              ...base,
              provider: 'b',
              provider_name: '供应商 B',
              max_output: 8000,
              price: {
                currency: 'USD',
                metric: 'tokens',
                unit: 1000000,
                input: '0.15',
                output: '0.47',
                cache_read: '0.016',
              },
              quote_snapshot: {
                raw_cost: {
                  input: '0.15',
                  output: '0.47',
                  cache_read: '0.016',
                  cache_write: '0.2',
                },
              },
            },
          ],
          fetched_at: '2026-01-01T00:00:00Z',
          stale: false,
          page_size: 20,
          total: 2,
        }
      }
      if (url === '/api/option/model_pricing') {
        if (method === 'PATCH' && !pricingFailed) {
          pricingFailed = true
          throw new Error('报价暂时无法写入')
        }
        return {
          entries: [
            {
              model_name: 'policy-model',
              version: 'existing-price-version',
              configured: { ModelRatio: 1, CompletionRatio: 2 },
              effective: { ModelRatio: 1, CompletionRatio: 2 },
              cache_write_mode: 'standard',
            },
          ],
          options: {},
          empty_version: 'empty',
        }
      }
      return undefined
    }
  )
  await expect
    .element(page.getByRole('button', { name: '使用设置', exact: true }))
    .not.toBeInTheDocument()
  await page
    .getByRole('row')
    .filter({ hasText: 'policy-model' })
    .getByRole('button', { name: 'policy-model', exact: true })
    .click()
  await page.getByRole('tab', { name: '使用设置', exact: true }).click()
  await expect
    .element(page.getByRole('switch', { name: '开放使用', exact: true }))
    .toBeVisible()
  for (const name of ['模型资料', '定价', '渠道与分组', '使用设置'])
    await expect
      .element(page.getByRole('tab', { name, exact: true }))
      .toBeVisible()
  await expect
    .element(page.getByRole('tab', { name: '成员预览', exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('radio', { name: '全体成员', exact: true }).click()
  await page.getByRole('tab', { name: '模型资料', exact: true }).click()
  await page
    .getByRole('textbox', { name: '上下文上限（Token）', exact: true })
    .fill('64000')
  await page.getByRole('button', { name: '从远程拉取' }).click()
  await expect
    .element(page.getByLabelText('搜索公开模型'))
    .toHaveValue('policy-model')
  await page.getByRole('button', { name: /公共模型.*供应商 A/ }).click()
  await expect.element(page.getByText('与已填参数冲突')).toBeVisible()
  await page.getByRole('button', { name: /公共模型.*供应商 B/ }).click()
  const preview = page.getByRole('table', { name: '模型参数预览' })
  await expect
    .element(preview.getByRole('row').filter({ hasText: '上下文上限' }))
    .toHaveTextContent(/64,000.*128,000.*保留.*更新/)
  await expect
    .element(preview.getByRole('row').filter({ hasText: '结构化输出' }))
    .toHaveTextContent(/未提供.*留空/)
  await page.getByRole('button', { name: '填入空白', exact: true }).click()
  await expect
    .element(page.getByText('已应用远程报价，请核对后保存定价。'))
    .not.toBeInTheDocument()
  await expect
    .element(
      page.getByRole('textbox', { name: '最大输出（Token）', exact: true })
    )
    .toHaveValue('8000')
  await page.getByRole('tab', { name: '模型资料', exact: true }).click()
  await expect
    .element(page.getByLabelText('调用 ID *', { exact: true }))
    .toBeVisible()
  await page.getByRole('tab', { name: '使用设置', exact: true }).click()
  await expect
    .element(page.getByRole('radio', { name: '全体成员', exact: true }))
    .toBeChecked()
  await page.getByRole('tab', { name: '模型资料', exact: true }).click()
  await expect
    .element(
      page.getByRole('textbox', { name: '上下文上限（Token）', exact: true })
    )
    .toHaveValue('64000')
  await page.getByRole('tab', { name: '使用设置', exact: true }).click()
  await page.getByRole('button', { name: /policy-model.*返回模型列表/ }).click()
  await expect.element(page.getByRole('alertdialog')).toBeVisible()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect
    .element(page.getByRole('radio', { name: '全体成员', exact: true }))
    .toBeChecked()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '从远程拉取' }).click()
  await page.getByRole('button', { name: /policy-model.*返回模型详情/ }).click()
  await expect
    .element(page.getByRole('radio', { name: '全体成员', exact: true }))
    .toBeChecked()
  await page.getByRole('button', { name: '从远程拉取' }).click()
  await page.getByRole('button', { name: /公共模型.*供应商 B/ }).click()
  await page.getByRole('button', { name: '覆盖已有值', exact: true }).click()
  await expect
    .element(page.getByText(/模型参数已保存，定价保存失败/))
    .toBeVisible()
  const parameterUrl = '/api/v1/model-gateway/parameters?model=policy-model'
  expect(writes.find(({ url }) => url === parameterUrl)?.body).toMatchObject({
    version: 2,
    context_window: 128000,
    max_output: 8000,
  })
  await page.getByRole('button', { name: '覆盖已有值', exact: true }).click()
  await expect
    .element(page.getByRole('heading', { name: 'Models.dev 模型资料' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('tab', { name: '使用设置', exact: true }))
    .toHaveAttribute('aria-selected', 'true')
  await expect
    .element(page.getByRole('radio', { name: '全体成员', exact: true }))
    .toBeChecked()
  await page.getByRole('button', { name: '保存为未开放', exact: true }).click()
  await expect
    .poll(() => writes.find(({ url }) => url.endsWith('/publication'))?.body)
    .toMatchObject({
      version: 3,
      audience: 'organization',
      context_window: 128000,
    })
  await page.getByRole('tab', { name: '模型资料', exact: true }).click()
  await expect
    .element(page.getByLabelText('上下文上限（Token）', { exact: true }))
    .toHaveValue('128000')
  expect(writes.filter(({ url }) => url === parameterUrl)).toHaveLength(1)
  const priceWrites = writes.filter(
    ({ url }) => url === '/api/option/model_pricing'
  )
  expect(priceWrites).toHaveLength(2)
  expect(priceWrites[1].body).toMatchObject({
    changes: [
      {
        model_name: 'policy-model',
        expected_version: 'existing-price-version',
        pricing: {
          'billing_setting.billing_mode': 'tiered_expr',
          'billing_setting.billing_expr':
            'tier("base", p * 0.15 + c * 0.47 + cr * 0.016 + cc * 0.2)',
        },
      },
    ],
  })
})

it('summarizes model publication and shows maintenance details in usage settings', async () => {
  const names = [
    'DeepSeek Flash',
    'orphan-model',
    'unknown-model',
    'pending-check',
    'bad,model',
  ]
  const models = names.map((model_name, index) => ({
    id: index + 21,
    model_name,
    status: 1,
    sync_official: 1,
    name_rule: 0,
    created_time: 100,
    updated_time: 100,
  }))
  const states = names.slice(0, 4).map((model_name, index) => ({
    model_name,
    enabled: index !== 1,
    audience: 'administrators',
    member_count: 0,
    ready: index === 0,
    active_channels: index === 1 ? 0 : 1,
    automatic: { status: index === 2 ? 'unresolved' : 'resolved' },
    checks:
      index === 0
        ? []
        : [
            {
              key: index === 1 ? 'channels' : 'parameters',
              status: index === 3 ? 'unknown' : 'blocked',
              message:
                index === 1
                  ? '未关联当前调用分组的启用渠道'
                  : '尚无可靠能力资料',
            },
          ],
  }))
  await show(
    <NativeLanguage>
      <NativeModelManagement />
    </NativeLanguage>,
    (url) => {
      if (url === '/api/models/') return { items: models, total: models.length }
      if (url === '/api/models/23') return models[2]
      if (url.endsWith('/publication/status')) return { items: states }
      if (url.includes('/publication?model=unknown-model'))
        return { data: { ...states[2], version: 1, relay_ready: true } }
      if (url.endsWith('/publication/preview'))
        return { configuration: states[2] }
      return undefined
    }
  )
  await expect
    .element(page.getByRole('row').filter({ hasText: 'DeepSeek Flash' }))
    .toHaveTextContent('已发布')
  await expect
    .element(page.getByRole('row').filter({ hasText: 'orphan-model' }))
    .toHaveTextContent('未发布')
  await expect
    .element(page.getByRole('row').filter({ hasText: 'unknown-model' }))
    .toHaveTextContent('待维护')
  await expect
    .element(page.getByRole('row').filter({ hasText: 'pending-check' }))
    .toHaveTextContent('已发布')
  await expect
    .element(page.getByRole('row').filter({ hasText: 'bad,model' }))
    .toHaveTextContent('名称格式不支持')
  await expect
    .element(page.getByText('尚无可靠能力资料'))
    .not.toBeInTheDocument()
  const statusCall = vi
    .mocked(fetch)
    .mock.calls.find(([url]) => String(url).endsWith('/publication/status'))
  expect(JSON.parse(String(statusCall?.[1]?.body)).models).toEqual(
    [...names.slice(0, 4)].sort()
  )
  await page
    .getByRole('button', { name: /unknown-model.*待维护.*查看使用设置/ })
    .click()
  await expect
    .element(page.getByText('尚无可靠能力资料', { exact: true }))
    .toBeVisible()
})
it('blocks opening an incomplete model while allowing its disabled draft to be saved', async () => {
  await show(<ModelPublication model='team' />, (url) => {
    if (url.includes('/publication?'))
      return {
        data: {
          model_name: 'team',
          name: 'Team',
          enabled: false,
          audience: 'organization',
          version: 0,
          relay_ready: true,
        },
      }
    if (url.endsWith('/publication/preview'))
      return {
        configuration: {
          model_name: 'team',
          enabled: false,
          audience: 'organization',
          member_count: 0,
          ready: false,
          active_channels: 1,
          checks: [
            {
              key: 'pricing',
              label: '模型价格',
              status: 'blocked',
              message: '尚未配置模型价格',
              action: 'pricing',
            },
          ],
          automatic: {},
        },
      }
  })
  await expect
    .element(page.getByText('尚未配置模型价格', { exact: true }))
    .toBeVisible()
  await page.getByRole('switch', { name: '开放使用', exact: true }).click()
  await expect
    .element(page.getByRole('button', { name: '保存并开放', exact: true }))
    .toBeDisabled()
  await page.getByRole('switch', { name: '开放使用', exact: true }).click()
  await page.getByRole('button', { name: '保存为未开放', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({
    enabled: false,
    audience: 'organization',
  })
})
it('keeps an existing non-chat operation while access edits expose no operation or parameter selectors', async () => {
  await show(<ModelPublication model='vectors' />, (url) =>
    url.includes('/publication?')
      ? {
          data: {
            model_name: 'vectors',
            name: 'Vectors',
            kind: 'embedding',
            enabled: false,
            audience: 'organization',
            version: 2,
            relay_ready: true,
            retrieval: {
              dimensions: 1536,
              embedding_space: 'stable-space',
              max_batch_size: 16,
              max_input_characters: 20000,
            },
          },
        }
      : undefined
  )
  await expect
    .element(page.getByRole('combobox', { name: '客户端用途' }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('tab', { name: '成员预览' }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '保存为未开放', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({
    kind: 'embedding',
    version: 2,
    retrieval: { dimensions: 1536, embedding_space: 'stable-space' },
  })
})
it('keeps a configured unavailable gateway explicit instead of showing another backend', async () => {
  await show(<GatewayPage view='models' />, (url) =>
    url.endsWith('/status')
      ? { configured: true, connected: false, error: '网关连接失败' }
      : undefined
  )
  await expect
    .element(page.getByText('网关连接失败', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('legacy-model-page'))
    .not.toBeInTheDocument()
})
it('converts native units and distinguishes inherited rates from explicit free rates', () => {
  const entry = {
    model_name: 'model',
    version: 'v1',
    configured: { ModelRatio: 1, CompletionRatio: 4, ImageRatio: 2 },
    effective: { ModelRatio: 1, CompletionRatio: 4 },
    billing_details: {},
  }
  expect(tokenRates(entry.effective, 250000)).toMatchObject({
    input: 4,
    output: 16,
  })
  const pricing = makePricing(
    entry,
    'tokens',
    { input: '2', output: '0', cache: '', write: '' },
    '',
    '',
    500000
  )
  expect(pricing).toMatchObject({
    ModelRatio: 1,
    CompletionRatio: 0,
    ImageRatio: 2,
    'billing_setting.billing_mode': 'ratio',
  })
  expect(pricing).not.toHaveProperty('CacheRatio')
  expect(() =>
    makePricing(
      entry,
      'tokens',
      { input: '0', output: '1', cache: '', write: '' },
      '',
      '',
      500000
    )
  ).toThrow()
})

it('opens a common model with automatic desktop controls and no fixed dollar reservation', async () => {
  await show(<ModelPublication model='team' />, (url) =>
    url.includes('/publication?')
      ? {
          data: {
            version: 0,
            relay_ready: true,
            capability_mode: 'auto',
            automatic: {
              status: 'resolved',
              source: { provider: 'deepseek', model: 'deepseek-flash' },
              context_window: 1000000,
              max_output: 256000,
              reasoning_options: [
                { type: 'effort', values: ['none', 'low', 'high', 'max'] },
              ],
              input_modalities: ['text', 'image'],
              output_modalities: ['text'],
              capabilities: {
                tools: 'supported',
                streaming: 'supported',
                structured_output: 'unknown',
              },
              chat_policy: {
                default_max_output: 8192,
                default_reasoning_effort: 'high',
              },
            },
          },
        }
      : undefined
  )
  await expect
    .element(page.getByText('自动识别', { exact: true }))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByRole('combobox', { name: '模型参数' }))
    .not.toBeInTheDocument()
  await expect.element(page.getByText(/1,000,000/)).toBeVisible()
  await expect.element(page.getByText(/关闭、低、高、最高/)).toBeVisible()
  await expect
    .element(page.getByText('输入：文本、图片 · 输出：文本', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText(/结构化输出：未识别/))
    .not.toBeInTheDocument()
  await expect.element(page.getByText(/流式输出/)).not.toBeInTheDocument()
  await expect.element(page.getByText(/默认输出 8,192 Token/)).toBeVisible()
  await expect
    .element(
      page.getByText('当前对话通道未接入音频、视频输入。', { exact: true })
    )
    .toBeVisible()
  await page.getByRole('button', { name: '保存为未开放' }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({
    model_name: 'team',
    capability_mode: 'auto',
  })
  expect(writes[0].body).not.toHaveProperty('reserve_usd')
})

it('collects unknown model facts in metadata without changing prices or publication', async () => {
  let state: ParameterDraftState | undefined
  await show(
    <ModelParameters
      model='unlisted'
      onChange={(value) => {
        state = value
      }}
    />,
    (url) =>
      url.includes('/parameters?')
        ? { data: { capabilities: { streaming: 'unsupported' } } }
        : undefined
  )
  await expect
    .element(page.getByRole('combobox', { name: '参数来源' }))
    .not.toBeInTheDocument()
  await expect.poll(() => state?.valid).toBe(true)
  expect(state?.draft).toMatchObject({ context_window: null, max_output: null })
  await page
    .getByRole('textbox', { name: '上下文上限（Token）', exact: true })
    .fill('4000')
  await page
    .getByRole('textbox', { name: '最大输出（Token）', exact: true })
    .fill('8000')
  await expect.poll(() => state?.valid).toBe(false)
  await page
    .getByRole('textbox', { name: '上下文上限（Token）', exact: true })
    .fill('64000')
  await expect.poll(() => state?.valid).toBe(true)
  await expect
    .element(page.getByRole('combobox', { name: '流式输出' }))
    .not.toBeInTheDocument()
  expect(state?.dirty).toBe(true)
  expect(state?.draft).toMatchObject({
    version: 0,
    capability_mode: 'manual',
    context_window: 64000,
    max_output: 8000,
    capabilities: { streaming: 'supported' },
  })
  expect(state?.draft).not.toHaveProperty('chat_policy')
  expect(state?.draft).not.toHaveProperty('enabled')
  expect(writes).toHaveLength(0)
})

it('uses native statistics tabs for current organization usage', async () => {
  await show(<GatewayStatistics />, (url) => {
    if (url === '/api/v1/model-gateway/status')
      return {
        configured: true,
        connected: true,
        backend: 'newapi',
        error: null,
      }
    if (url.startsWith('/api/data')) return []
    if (url === '/api/perf-metrics/summary') return { models: [] }
    return undefined
  })
  for (const name of ['模型调用分析', '分流', '用户统计'])
    await expect
      .element(page.getByRole('tab', { name, exact: true }))
      .toBeVisible()
  await expect.poll(() => reads.some((url) => url === '/api/data')).toBe(true)
})

it('shows an unavailable gateway and retries with the flat status contract', async () => {
  let connected = false
  await show(<GatewayStatistics />, (url) => {
    if (url === '/api/v1/model-gateway/status')
      return {
        configured: true,
        connected,
        backend: 'newapi',
        error: connected ? null : '网关连接失败',
      }
    if (url.startsWith('/api/data')) return []
    if (url === '/api/perf-metrics/summary') return { models: [] }
    return undefined
  })
  await expect
    .element(page.getByText('网关连接失败', { exact: true }))
    .toBeVisible()
  expect(reads).not.toContain('/api/data')
  connected = true
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await expect
    .element(page.getByRole('tab', { name: '模型调用分析', exact: true }))
    .toBeVisible()
  await expect.poll(() => reads.includes('/api/data')).toBe(true)
})

it('keeps unconfigured statistics explicit without starting native requests', async () => {
  await show(<GatewayStatistics />, (url) =>
    url === '/api/v1/model-gateway/status'
      ? { configured: false, connected: false, backend: 'direct', error: null }
      : undefined
  )
  await expect
    .element(page.getByText(/连接 New API 网关后可查看原生统计/))
    .toBeVisible()
  expect(reads).not.toContain('/api/data')
  expect(reads).not.toContain('/api/status')
})

it('preserves manual parameters when saving member access despite a different automatic profile', async () => {
  await show(<ModelPublication model='team' />, (url) =>
    url.includes('/publication?')
      ? {
          data: {
            version: 4,
            capability_mode: 'manual',
            context_window: 64000,
            max_output: 8000,
            chat_policy: { default_max_output: 2000 },
            automatic: {
              status: 'resolved',
              context_window: 1000000,
              max_output: 256000,
            },
          },
        }
      : undefined
  )
  await expect
    .element(page.getByText('管理员填写', { exact: true }))
    .not.toBeInTheDocument()
  await expect.element(page.getByText(/上下文 64,000/)).toBeVisible()
  await page.getByRole('button', { name: '保存为未开放', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({
    version: 4,
    capability_mode: 'manual',
    context_window: 64000,
    max_output: 8000,
    chat_policy: { default_max_output: 2000 },
  })
})
