import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from '@tanstack/react-router'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { MyModelsPage } from './page'
import { readMyModelSearch } from './search'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'member-org' },
    user: { id: 'member-self' },
  }),
}))
vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    description,
    action,
    children,
  }: {
    title: string
    description: string
    action: ReactNode
    children: ReactNode
  }) => (
    <main className='flex min-w-0 flex-col gap-5 p-4 sm:p-8'>
      <header>
        <h1>{title}</h1>
        <p>{description}</p>
        {action}
      </header>
      {children}
    </main>
  ),
}))

const capabilities: Schema['ModelCapabilities'] = {
  reasoning: 'unknown',
  streaming: 'supported',
  structured_output: 'unknown',
  tools: 'unknown',
  vision: 'unknown',
}
function operation(
  kind: Schema['MemberOperationView']['kind'],
  slug: string,
  status: Schema['MemberOperationView']['point_price_status'] = 'ready'
): Schema['MemberOperationView'] {
  const path = {
    chat: '/api/llm/v1/chat/completions',
    embedding: '/api/llm/v1/embeddings',
    rerank: '/api/llm/v1/rerank',
    image_generation: '/api/llm/v1/images/generations',
    speech: '/api/llm/v1/audio/speech',
    transcription: '/api/llm/v1/audio/transcriptions',
  }[kind]
  return {
    kind,
    pricing_status: status === 'ready' ? 'ready' : 'no_price',
    input_modalities: ['text'],
    output_modalities: kind === 'image_generation' ? ['image'] : ['text'],
    image: null,
    limits: {
      embedding_space: '',
      max_batch_size: 32,
      max_input_characters: 20000,
    },
    capabilities,
    context_window: null,
    max_output: null,
    reasoning_options: [],
    point_rates:
      status === 'ready'
        ? {
            input: kind === 'image_generation' ? '50' : '100',
            output: kind === 'chat' ? '200' : null,
          }
        : {},
    point_price_status: status,
    metric: kind === 'image_generation' ? 'images' : 'tokens',
    unit: kind === 'image_generation' ? 1 : 1000000,
    endpoint: {
      method: 'POST',
      path,
      inbound_protocol: 'openai_compatible',
      stream: kind === 'chat',
      tools: kind === 'chat',
      example:
        kind === 'chat'
          ? { model: slug, messages: [{ role: 'user', content: '你好' }] }
          : { model: slug, prompt: '示例图片' },
    },
  }
}
function model(
  name: string,
  slug: string,
  kinds: Schema['MemberOperationView']['kind'][] = ['chat']
): Schema['MemberModelView'] {
  const suffix = [...slug]
    .reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 1)
    .toString(16)
    .padStart(12, '0')
  return {
    id: `00000000-0000-4000-8000-${suffix}`,
    name,
    slug,
    display_order: 0,
    resource: 'llm:fixture',
    operations: kinds.map((kind) => operation(kind, slug)),
  }
}
const models = [
  model('团队对话', 'team-chat', ['chat', 'embedding']),
  model('绘图模型', 'draw-image', ['image_generation']),
]
const quota: Schema['QuotaView'] = {
  status: 'active',
  policy: { name: '默认策略' },
  windows: [],
}
const clients: QueryClient[] = []

async function show({
  initial = '/my-models',
  catalog = models,
  quotaValue = quota,
}: {
  initial?: string
  catalog?: Schema['MemberModelView'][]
  quotaValue?: Schema['QuotaView']
} = {}) {
  const requests: { url: string; method: string }[] = []
  let revoked = false
  let unavailable = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      requests.push({ url, method: init?.method ?? 'GET' })
      if (url.startsWith('/api/v1/account/llm/models?')) {
        if (revoked)
          return Response.json(
            { error: { message: '模型权限已撤销' } },
            { status: 403 }
          )
        if (unavailable)
          return Response.json(
            { error: { message: '目录暂不可用' } },
            { status: 503 }
          )
        const params = new URL(url, location.origin).searchParams
        const q = (params.get('q') ?? '').toLowerCase()
        const kind = params.get('operation')
        const filtered = catalog.filter(
          (item) =>
            (item.name.toLowerCase().includes(q) ||
              item.slug.toLowerCase().includes(q)) &&
            (!kind ||
              item.operations.some((operation) => operation.kind === kind))
        )
        const selectedPage = Number(params.get('page') ?? '1')
        return Response.json({
          items: filtered.slice((selectedPage - 1) * 20, selectedPage * 20),
          total: filtered.length,
          page: selectedPage,
          page_size: 20,
          has_more: selectedPage * 20 < filtered.length,
        })
      }
      if (url === '/api/v1/account/llm/quota') return Response.json(quotaValue)
      throw new Error(`Unexpected request: ${url}`)
    })
  )
  const root = createRootRoute({ component: Outlet })
  const list = createRoute({
    getParentRoute: () => root,
    path: '/my-models',
    validateSearch: readMyModelSearch,
    component: () => <MyModelsPage search={list.useSearch()} />,
  })
  const keys = createRoute({
    getParentRoute: () => root,
    path: '/my-access-keys',
    component: () => <h1>访问密钥页</h1>,
  })
  const usage = createRoute({
    getParentRoute: () => root,
    path: '/my-usage',
    component: () => <h1>我的额度页</h1>,
  })
  const router = createRouter({
    routeTree: root.addChildren([list, keys, usage]),
    history: createMemoryHistory({ initialEntries: [initial] }),
  })
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
  return {
    requests,
    router,
    client,
    revoke: () => {
      revoked = true
    },
    fail: () => {
      unavailable = true
    },
    recover: () => {
      unavailable = false
    },
  }
}

afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 900)
})

it('lists authorized operations and server endpoints with points only, then shows a key-free example', async () => {
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  })
  await page.viewport(1440, 900)
  const { requests } = await show()
  await expect
    .element(page.getByText('团队对话', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('积分价：输入 100', { exact: false }).first())
    .toBeVisible()
  await page.screenshot({
    path: '__screenshots__/actvero-g6-04-models-desktop.png',
  })
  const trigger = page.getByRole('button', { name: '查看接入示例' }).first()
  await trigger.click()
  await expect
    .element(page.getByRole('dialog', { name: /接入示例/ }))
    .toBeVisible()
  const template = page
    .getByLabelText('对话接入命令')
    .element() as HTMLTextAreaElement
  expect(template.value).toContain('/api/llm/v1/chat/completions')
  expect(template.value).toContain('${ACTVERO_API_KEY}')
  expect(template.value).toContain('"Authorization: Bearer ${ACTVERO_API_KEY}"')
  expect(template.value).not.toContain(
    "'Authorization: Bearer ${ACTVERO_API_KEY}'"
  )
  expect(template.value).toContain('team-chat')
  expect(template.value).not.toContain('sk-live')
  expect(requests.every((request) => request.method === 'GET')).toBe(true)
  await page.getByRole('button', { name: '复制示例' }).click()
  expect(writeText).toHaveBeenCalledWith(template.value)
  await page.getByRole('button', { name: '关闭' }).click()
  await expect
    .element(page.getByRole('dialog', { name: /接入示例/ }))
    .not.toBeInTheDocument()
  await expect.element(trigger).toHaveFocus()
})

it('uses server-side search, operation filtering and pagination without leaking other operations', async () => {
  const catalog = Array.from({ length: 21 }, (_, index) =>
    model(`对话${index + 1}`, `chat-${index + 1}`)
  )
  catalog.push(model('图片专用', 'picture', ['image_generation']))
  const { requests, router } = await show({ catalog })
  await expect.element(page.getByText('对话1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect.poll(() => router.state.location.search.page).toBe(2)
  await expect.element(page.getByText('对话21', { exact: true })).toBeVisible()
  expect(requests.some(({ url }) => url.includes('page=2'))).toBe(true)
  await page.getByLabelText('搜索模型名称或公开 ID').fill('图片')
  await page.getByRole('combobox', { name: '操作' }).click()
  await page.getByRole('option', { name: '图片生成' }).click()
  await page.getByRole('button', { name: '应用筛选' }).click()
  await expect
    .element(page.getByText('图片专用', { exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByText('对话21', { exact: true }))
    .not.toBeInTheDocument()
  expect(
    requests.some(
      ({ url }) =>
        url.includes('q=%E5%9B%BE%E7%89%87') &&
        url.includes('operation=image_generation')
    )
  ).toBe(true)
})

it('clears an open example and prior model details when the member loses access', async () => {
  const { client, revoke } = await show()
  await expect
    .element(page.getByText('团队对话', { exact: true }))
    .toBeVisible()
  await page.getByRole('button', { name: '查看接入示例' }).first().click()
  await expect.element(page.getByLabelText('对话接入命令')).toBeVisible()
  revoke()
  await client.invalidateQueries({
    queryKey: ['organization', 'member-org', 'member-self', 'my-models'],
  })
  await expect.element(page.getByText('模型权限已撤销')).toBeVisible()
  await expect
    .element(page.getByLabelText('对话接入命令'))
    .not.toBeInTheDocument()
  await expect
    .element(page.getByText('团队对话', { exact: true }))
    .not.toBeInTheDocument()
})

it('distinguishes an empty authorization from a failed directory', async () => {
  await show({ catalog: [] })
  await expect.element(page.getByText('暂无可用模型')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '查看接入示例' }))
    .not.toBeInTheDocument()
})

it('hides stale model details on a transient directory error and recovers on explicit retry', async () => {
  const { client, fail, recover } = await show()
  await expect
    .element(page.getByText('团队对话', { exact: true }))
    .toBeVisible()
  fail()
  await client.invalidateQueries({
    queryKey: ['organization', 'member-org', 'member-self', 'my-models'],
  })
  await expect.element(page.getByText('目录暂不可用')).toBeVisible()
  await expect
    .element(page.getByText('团队对话', { exact: true }))
    .not.toBeInTheDocument()
  recover()
  await page.getByRole('button', { name: '重试' }).click()
  await expect
    .element(page.getByText('团队对话', { exact: true }))
    .toBeVisible()
})

it('shows no authorization and unconfigured price honestly, and keeps the 390px example within the viewport', async () => {
  await page.viewport(390, 844)
  const unpriced = model('未计价模型', 'unpriced')
  unpriced.operations[0] = operation('chat', 'unpriced', 'no_price')
  await show({
    catalog: [unpriced],
    quotaValue: { status: 'unconfigured', policy: null, windows: [] },
  })
  await expect.element(page.getByText('未配置预算价，暂不可发送')).toBeVisible()
  await expect
    .element(page.getByText('尚未配置成员额度策略', { exact: false }))
    .toBeVisible()
  await page.screenshot({ path: '__screenshots__/actvero-g6-04-models-390.png' })
  await page.getByRole('button', { name: '查看接入示例' }).click()
  const dialog = page.getByRole('dialog', { name: /接入示例/ })
  await expect.element(dialog).toBeVisible()
  await expect
    .poll(() => Number(getComputedStyle(dialog.element()).opacity))
    .toBe(1)
  await page.screenshot({ path: '__screenshots__/actvero-g6-04-example-390.png' })
  expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(390)
})

it.each(['speech', 'transcription'] as const)(
  'shows executable %s upload or download templates without sending a call',
  async (kind) => {
    const item = model('语音模型', 'team-audio', [kind])
    item.operations[0].metric = kind === 'speech' ? 'characters' : 'seconds'
    item.operations[0].unit = kind === 'speech' ? 1000 : 1
    item.operations[0].endpoint.example =
      kind === 'speech'
        ? {
            model: item.slug,
            input: '你好',
            voice: 'alloy',
            response_format: 'wav',
          }
        : { model: item.slug }
    const { requests } = await show({ catalog: [item] })
    await page.getByRole('button', { name: '查看接入示例' }).click()
    await expect
      .element(page.getByRole('dialog', { name: /接入示例/ }))
      .toBeVisible()
    const template = page
      .getByLabelText(
        kind === 'speech' ? '语音合成接入命令' : '语音转文字接入命令'
      )
      .element() as HTMLTextAreaElement
    expect(template.value).toContain(item.operations[0].endpoint.path)
    expect(template.value).toContain('${ACTVERO_API_KEY}')
    if (kind === 'speech') {
      expect(template.value).toContain('--output speech.wav')
      expect(template.value).toContain('"response_format": "wav"')
    } else {
      expect(template.value).toContain(
        "--form 'file=@sample.wav;type=audio/wav'"
      )
      expect(template.value).toContain("--form 'model=team-audio'")
      expect(template.value).not.toContain('Content-Type: application/json')
    }
    expect(requests.every((request) => request.method === 'GET')).toBe(true)
  }
)
