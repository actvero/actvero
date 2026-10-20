import { type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { ModelEditor } from './model-editor'
import { type Model, values } from './model-form'
import type { ReferenceModel } from './reference-models'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'test-org' },
    csrf: 'csrf-test',
    user: { id: 'admin' },
  }),
}))

const model = {
  id: 'model-1',
  kind: 'chat',
  name: '团队模型',
  slug: 'team-chat',
  version: 1,
  archived: false,
  binding_states: [],
  bindings: [],
} as unknown as Model
const clients: QueryClient[] = []
function readResponse(url: string) {
  if (url.includes('/channels?')) return Response.json({ items: [], total: 0 })
  if (url.endsWith('/routes')) return Response.json([])
  if (url.endsWith('/endpoints'))
    return Response.json({ endpoints: [], version: 1 })
  return Response.json({ items: [], total: 0 })
}
async function show(component: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  const view = await render(
    <QueryClientProvider client={client}>{component}</QueryClientProvider>
  )
  await expect
    .poll(() => page.getByRole('dialog').element().getBoundingClientRect().right)
    .toBeLessThanOrEqual(innerWidth + 1)
  return view
}
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

it('keeps a dirty draft across operation switches and asks before closing', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => readResponse(String(url)))
  )
  const close = vi.fn()
  const draft = values()
  draft.name = '团队模型'
  draft.slug = 'team-chat'
  await show(
    <ModelEditor initialValues={draft} close={close} saved={vi.fn()} />
  )
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await page.getByRole('combobox', { name: '添加接口' }).click()
  await page.getByRole('option', { name: '向量' }).click()
  await page.getByRole('button', { name: '配置', exact: true }).first().click()
  await page.getByRole('button', { name: '取消' }).click()
  await expect.element(page.getByText('放弃未保存的模型修改？')).toBeVisible()
  expect(close).not.toHaveBeenCalled()
})

it('treats a source-first initial draft as unsaved even before another edit', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => readResponse(String(url)))
  )
  const draft = values()
  draft.name = '来源预填模型'
  draft.slug = 'source-model'
  const close = vi.fn()
  await show(
    <ModelEditor initialValues={draft} close={close} saved={vi.fn()} />
  )
  await page.getByRole('button', { name: '取消' }).click()
  await expect.element(page.getByText('放弃未保存的模型修改？')).toBeVisible()
  expect(close).not.toHaveBeenCalled()
})

it('allows a new model slug conflict to be corrected without entering version comparison', async () => {
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        writes += 1
        return writes === 1
          ? Response.json(
              { error: { message: '技术名称已存在' } },
              { status: 409 }
            )
          : Response.json(model)
      }
      return readResponse(String(url))
    })
  )
  const draft = values()
  draft.name = '新模型'
  draft.slug = 'taken'
  const saved = vi.fn()
  await show(
    <ModelEditor initialValues={draft} close={vi.fn()} saved={saved} />
  )
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.element(page.getByText('技术名称已存在')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '加载最新并比较' }))
    .not.toBeInTheDocument()
  await page.getByLabelText('技术名称').fill('available')
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => saved.mock.calls.length).toBe(1)
  expect(writes).toBe(2)
})

it('keeps 409 draft, compares latest version, and never retries the stale PUT', async () => {
  const writes: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        writes.push(JSON.parse(String(init.body)))
        return Response.json(
          { error: { message: '版本冲突' } },
          { status: 409 }
        )
      }
      if (String(url).endsWith('/models/model-1'))
        return Response.json({
          ...model,
          name: '服务器名称',
          version: 2,
          routing: { mode: 'auto' },
          budget_price: {
            metric: 'tokens',
            currency: 'USD',
            unit: 1000000,
            input: '9',
            output: '18',
            note: '',
          },
        })
      return readResponse(String(url))
    })
  )
  await show(<ModelEditor model={model} close={vi.fn()} saved={vi.fn()} />)
  await page.getByLabelText('展示名称').fill('本地草稿')
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect
    .element(page.getByText('服务器配置已变化，草稿仍保留'))
    .toBeVisible()
  await expect.element(page.getByLabelText('展示名称')).toHaveValue('本地草稿')
  await page.getByRole('button', { name: '加载最新并比较' }).click()
  await expect.element(page.getByText(/服务器版本 2：服务器名称/)).toBeVisible()
  await expect.element(page.getByText('对话路由')).toBeVisible()
  await expect.element(page.getByText('对话价格')).toBeVisible()
  expect(writes).toHaveLength(1)
  await page.getByRole('button', { name: '放弃草稿，采用服务器配置' }).click()
  await expect
    .element(page.getByLabelText('展示名称'))
    .toHaveValue('服务器名称')
})

it('confirms public slug rename and never writes an archived model', async () => {
  const writes: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') writes.push(JSON.parse(String(init.body)))
      if (init?.method === 'PUT')
        return Response.json({ ...model, slug: 'renamed' })
      return readResponse(String(url))
    })
  )
  await show(<ModelEditor model={model} close={vi.fn()} saved={vi.fn()} />)
  await page.getByLabelText('技术名称').fill('renamed')
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.element(page.getByText('确认更改技术名称？')).toBeVisible()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '确认更改并保存' }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({ slug: 'renamed', version: 1 })
})

it('renders archived model as read-only at narrow width', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => readResponse(String(url)))
  )
  await page.viewport(390, 844)
  await show(
    <ModelEditor
      model={{ ...model, archived: true }}
      close={vi.fn()}
      saved={vi.fn()}
    />
  )
  await expect.element(page.getByText('模型已归档')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '保存配置' }))
    .not.toBeInTheDocument()
  await expect.element(page.getByLabelText('技术名称')).toBeDisabled()
  await new Promise((resolve) => setTimeout(resolve, 450))
  await page.screenshot({
    path: '__screenshots__/actvero-g2-02-editor-narrow.png',
  })
})

it('stops further writes after a permission loss', async () => {
  let writes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        writes += 1
        return Response.json(
          { error: { message: '权限已失效' } },
          { status: 403 }
        )
      }
      return readResponse(String(url))
    })
  )
  await show(<ModelEditor model={model} close={vi.fn()} saved={vi.fn()} />)
  await page.getByLabelText('展示名称').fill('新名称')
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.element(page.getByText('没有编辑权限')).toBeVisible()
  await expect.element(page.getByLabelText('展示名称')).toBeDisabled()
  await expect
    .element(page.getByRole('button', { name: '保存配置' }))
    .not.toBeInTheDocument()
  expect(writes).toBe(1)
})

it('shows single-hop mapping and preserves binding identity in the save payload', async () => {
  const bindingId = 'bbf35b36-d5f6-4a19-a9e7-3ea4607a97d6'
  const bound = {
    ...model,
    bindings: [
      {
        binding_id: bindingId,
        channel_id: 'channel-a',
        upstream_id: 'vendor-model',
        enabled: false,
        priority: 0,
        weight: 100,
        compatibility_key: '',
        price: null,
      },
    ],
    binding_states: [
      {
        binding_id: bindingId,
        operation: 'chat',
        channel_id: 'channel-a',
        channel_name: '渠道 A',
        upstream_id: 'vendor-model',
        state: 'registered',
      },
    ],
  } as Model
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        writes.push(JSON.parse(String(init.body)))
        return Response.json(bound)
      }
      return readResponse(String(url))
    })
  )
  await show(<ModelEditor model={bound} close={vi.fn()} saved={vi.fn()} />)
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await expect
    .element(page.getByText('技术名称 team-chat → 上游模型名称 vendor-model'))
    .toBeVisible()
  await new Promise((resolve) => setTimeout(resolve, 450))
  await page.screenshot({
    path: '__screenshots__/actvero-g2-02-editor-desktop.png',
  })
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({
    bindings: [{ binding_id: bindingId, upstream_id: 'vendor-model' }],
  })
})

it('previews exact channel candidates, requires confirmation, and keeps duplicate mappings out of the draft', async () => {
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        writes.push(JSON.parse(String(init.body)))
        return Response.json(model)
      }
      if (String(url).includes('/model-candidates?'))
        return Response.json({
          page: 1,
          page_size: 50,
          total: 3,
          items: [
            {
              channel_id: 'a',
              channel_name: '渠道 A',
              channel_version: 1,
              upstream_id: 'team-chat',
              manual_enabled: true,
              operations: ['chat'],
            },
            {
              channel_id: 'b',
              channel_name: '已停用渠道',
              channel_version: 2,
              upstream_id: 'team-chat',
              manual_enabled: false,
              operations: ['chat'],
            },
            {
              channel_id: 'c',
              channel_name: '不适配渠道',
              channel_version: 1,
              upstream_id: 'team-chat',
              manual_enabled: true,
              operations: ['embedding'],
            },
          ],
        })
      return readResponse(String(url))
    })
  )
  await show(<ModelEditor model={model} close={vi.fn()} saved={vi.fn()} />)
  await page.getByRole('tab', { name: '渠道与路由' }).click()
  await page.getByRole('combobox', { name: '调度方式' }).click()
  await page.getByRole('option', { name: '自动调度' }).click()
  await page.getByRole('button', { name: '查找候选' }).click()
  await expect
    .element(page.getByText('找到 3 条候选。', { exact: false }))
    .toBeVisible()
  await expect
    .element(
      page.getByRole('checkbox', { name: '选择候选 不适配渠道 / team-chat' })
    )
    .toBeDisabled()
  await page
    .getByRole('checkbox', { name: '选择候选 渠道 A / team-chat' })
    .click()
  await page
    .getByRole('checkbox', { name: '选择候选 已停用渠道 / team-chat' })
    .click()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '确认关联 2 条到草稿' }).click()
  await expect.element(page.getByText('渠道与模型映射 · 2')).toBeVisible()
  await page.screenshot({ path: '__screenshots__/actvero-me-mapping-desktop.png' })
  await page.getByRole('button', { name: '查找候选' }).click()
  await expect
    .element(
      page.getByRole('checkbox', { name: '选择候选 渠道 A / team-chat' })
    )
    .toBeDisabled()
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].bindings as { enabled: boolean }[]).toHaveLength(2)
  expect(
    (writes[0].bindings as { enabled: boolean }[]).every(
      (binding) => !binding.enabled
    )
  ).toBe(true)
})

it('previews reference changes, confirms overwrite, and preserves an existing public slug', async () => {
  const reference: ReferenceModel = {
    provider: 'openai',
    provider_name: 'OpenAI',
    model_id: 'upstream-reference',
    name: '参考名称',
    context_window: 128000,
    max_output: 16000,
    capabilities: {
      streaming: 'unknown',
      tools: 'unknown',
      vision: 'unknown',
      structured_output: 'unknown',
      reasoning: 'unknown',
    },
    reasoning_options: [],
    price: null,
    price_notes: [],
    price_importable: false,
    temperature: 'unknown',
  }
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/reference-models'))
        return Response.json({
          items: [reference],
          total: 1,
          fetched_at: '2026-10-03T00:00:00Z',
          stale: false,
          skipped: 0,
        })
      if (init?.method === 'PUT') {
        writes.push(JSON.parse(String(init.body)))
        return Response.json(model)
      }
      return readResponse(String(url))
    })
  )
  await show(<ModelEditor model={model} close={vi.fn()} saved={vi.fn()} />)
  await page.getByRole('button', { name: '选择公开模型' }).click()
  await page
    .getByRole('button', { name: /参考名称 upstream-reference/ })
    .click()
  await page.getByRole('checkbox', { name: '覆盖已有资料' }).click()
  await page.getByRole('button', { name: /预览修改/ }).click()
  await expect.element(page.getByText('当前：团队模型')).toBeVisible()
  await expect.element(page.getByText('修改为：参考名称')).toBeVisible()
  await expect
    .element(page.getByText(/渠道绑定、调用权限和其他接口配置保持原值/))
    .toBeVisible()
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '确认应用到草稿' }).click()
  await expect.element(page.getByLabelText('展示名称')).toHaveValue('参考名称')
  await expect.element(page.getByLabelText('技术名称')).toHaveValue('team-chat')
  await page.getByRole('button', { name: '保存配置' }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toMatchObject({
    name: '参考名称',
    slug: 'team-chat',
    bindings: [],
  })
  expect(writes[0].budget_price).toBeNull()
})
