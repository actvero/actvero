import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { pendingRecoveries, recoveryKey } from './reconcile-recovery'
import { Settlements } from './settlements'

const callId = '69fc6575-7066-4bd1-a4f7-0a8705ee6d71'
const requestId = 'ad81c775-7eef-4db1-a692-06a228a2e5cf'
const tenantId = 'tenant-fixture'
const userId = 'user-fixture'
const key = recoveryKey(tenantId, userId, callId)
const entry: Schema['SettlementView'] = {
  id: callId,
  member_id: '434e8eb9-dc0c-4981-ae77-6aaab6ca3afd',
  member_name: '测试成员',
  model_name: '团队模型',
  kind: 'chat',
  metric: 'tokens',
  status: 'review',
  result_status: 'unknown',
  settlement_status: 'review',
  terminal_reason: null,
  version: 2,
  points: null,
  reserved_points: '0.28',
  usage: {},
  created_at: '2026-10-04T00:00:00Z',
  settled_at: null,
  reason: '',
}
const context: Schema['ReconciliationContext'] = {
  settlement: entry,
  price: {
    currency: 'USD',
    metric: 'tokens',
    unit: 1000000,
    input: '2',
    output: '8',
    cache_read: '0.2',
    cache_write_5m: null,
    cache_write_1h: null,
    note: '',
  },
  currency: 'USD',
  ratio: '100',
  required_fields: ['input_tokens', 'output_tokens', 'cache_read_tokens'],
  eligible: true,
  available_after: null,
}

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: tenantId },
    user: { id: userId },
    csrf: 'csrf-test',
  }),
}))

const clients: QueryClient[] = []
async function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>
      <Settlements />
    </QueryClientProvider>
  )
}

afterEach(async () => {
  await cleanup()
  await Promise.all(clients.map((client) => client.cancelQueries()))
  clients.forEach((client) => client.clear())
  clients.length = 0
  sessionStorage.removeItem(key)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await page.viewport(1280, 900)
})

function mockFetch(
  handler: (url: string, init?: RequestInit) => Promise<Response> | Response,
  items: Schema['SettlementView'][] = [entry]
) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('/llm/settlements?'))
        return Response.json({ items, total: items.length })
      return handler(url, init)
    })
  )
}

async function open() {
  await show()
  await page.getByRole('button', { name: '核对', exact: true }).click()
  await expect
    .element(page.getByText('计量单位：Token', { exact: false }))
    .toBeVisible()
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

it('uses the historical token fields, invalidates preview on edit, and sends only explicit numbers', async () => {
  await page.viewport(390, 844)
  const previews: Record<string, unknown>[] = []
  const writes: Record<string, unknown>[] = []
  mockFetch((url, init) => {
    if (url.endsWith('/reconciliation')) return Response.json(context)
    if (url.endsWith('/reconcile/preview')) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      previews.push(body)
      return Response.json({
        call_id: callId,
        version: 2,
        action: 'settle',
        metric: 'tokens',
        usage: Object.fromEntries(
          Object.entries(body.usage as Record<string, unknown>).filter(
            ([name]) => name !== 'metric'
          )
        ),
        amount: '0.000244',
        points: '0.0244',
        currency: 'USD',
      })
    }
    if (url.endsWith('/reconcile')) {
      writes.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      return Response.json({ items: [], total: 0 })
    }
    throw new Error('Unexpected API: ' + url)
  })
  await open()
  await page.getByLabelText(/核对依据/).fill('人工核对上游账单')
  await page.getByLabelText(/输入 Token/).fill('80')
  await page.getByLabelText(/输出 Token/).fill('10')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await expect
    .element(page.getByText('请填写确认的数量', { exact: false }))
    .toBeVisible()
  expect(previews).toHaveLength(0)
  await page.getByLabelText(/缓存读取 Token/).fill('20')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await expect.element(page.getByText('按历史快照预览')).toBeVisible()
  expect(previews[0].usage).toEqual({
    metric: 'tokens',
    input_tokens: 80,
    output_tokens: 10,
    cache_read_tokens: 20,
  })
  await page.getByLabelText(/输出 Token/).fill('11')
  await expect.element(page.getByText('输入已修改，原预览失效')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认结算' }))
    .toBeDisabled()
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await expect
    .element(page.getByRole('button', { name: '确认结算' }))
    .toBeEnabled()
  await page.screenshot({ path: '/private/tmp/actvero-g6-reconcile-390.png' })
  const dialog = page.getByRole('dialog', { name: /核对用量/ }).element()
  const scrollingBody = dialog.querySelector(
    'form > .overflow-y-auto'
  ) as HTMLElement
  scrollingBody.scrollTop = scrollingBody.scrollHeight
  expect(scrollingBody.scrollTop).toBeGreaterThan(0)
  await expect.element(page.getByText('按历史快照预览')).toBeVisible()
  const footerTop = dialog
    .querySelector('[data-slot="dialog-footer"]')
    ?.getBoundingClientRect().top
  expect(footerTop).toBeDefined()
  expect(
    page.getByText('按历史快照预览').element().getBoundingClientRect().bottom
  ).toBeLessThanOrEqual(footerTop!)
  await page.screenshot({
    path: '/private/tmp/actvero-g6-reconcile-preview-390.png',
  })
  await page.viewport(1280, 900)
  await page.screenshot({
    path: '/private/tmp/actvero-g6-reconcile-desktop.png',
  })
  await page.getByRole('button', { name: '确认结算' }).click()
  await expect
    .element(page.getByRole('dialog', { name: /核对用量/ }))
    .not.toBeInTheDocument()
  expect(writes).toHaveLength(1)
  expect(writes[0]).toMatchObject({
    version: 2,
    action: 'settle',
    reason: '人工核对上游账单',
    usage: {
      metric: 'tokens',
      input_tokens: 80,
      output_tokens: 11,
      cache_read_tokens: 20,
    },
  })
  expect(String(writes[0].request_id)).toMatch(/^[a-f0-9-]{36}$/)
  expect(sessionStorage.getItem(key)).toBeNull()
})

it('release requires explicit confirmation and ignores a hidden invalid image quantity', async () => {
  const imageContext: Schema['ReconciliationContext'] = {
    ...context,
    settlement: { ...entry, metric: 'images', kind: 'image_generation' },
    price: {
      ...context.price,
      metric: 'images',
      input: '0.035',
      output: null,
      unit: 1,
    },
    required_fields: ['image_count'],
  }
  const previews: Record<string, unknown>[] = []
  mockFetch((url, init) => {
    if (url.endsWith('/reconciliation')) return Response.json(imageContext)
    if (url.endsWith('/reconcile/preview')) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      previews.push(body)
      return Response.json({
        call_id: callId,
        version: 2,
        action: 'release',
        metric: 'images',
        usage: {},
        amount: '0',
        points: '0',
        currency: 'USD',
      })
    }
    if (url.endsWith('/reconcile')) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      expect(body).not.toHaveProperty('usage')
      return Response.json({ items: [], total: 0 })
    }
    throw new Error('Unexpected API: ' + url)
  })
  await show()
  await page.getByRole('button', { name: '核对', exact: true }).click()
  await expect.element(page.getByLabelText(/确认交付张数/)).toBeVisible()
  await page.getByLabelText(/确认交付张数/).fill('not-a-number')
  await page.getByRole('combobox', { name: '处理方式' }).click()
  await page.getByRole('option', { name: '确认无使用，释放预占' }).click()
  await page.getByLabelText(/核对依据/).fill('已核实供应商没有计费')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await expect.element(page.getByText('请确认已核实没有使用量')).toBeVisible()
  await page
    .getByRole('checkbox', { name: '已依据外部记录确认没有使用量' })
    .click()
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await expect.element(page.getByText('按历史快照预览')).toBeVisible()
  expect(previews[0]).toEqual({
    version: 2,
    action: 'release',
    reason: '已核实供应商没有计费',
  })
  await page.getByRole('button', { name: '确认释放' }).click()
  await expect
    .element(page.getByRole('dialog', { name: /核对用量/ }))
    .not.toBeInTheDocument()
})

it('keeps the same command and request id after an unknown response and checks the receipt first', async () => {
  const writes: Record<string, unknown>[] = []
  let receiptReads = 0
  mockFetch((url, init) => {
    if (url.endsWith('/reconciliation')) return Response.json(context)
    if (url.endsWith('/reconcile/preview'))
      return Response.json({
        call_id: callId,
        version: 2,
        action: 'settle',
        metric: 'tokens',
        usage: { input_tokens: 80, output_tokens: 10, cache_read_tokens: 20 },
        amount: '0.000244',
        points: '0.0244',
        currency: 'USD',
      })
    if (url.includes('/mutation-receipts/')) {
      receiptReads += 1
      return Response.json({ error: { message: '尚无回执' } }, { status: 404 })
    }
    if (url.endsWith('/reconcile')) {
      writes.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      if (writes.length === 1) throw new TypeError('network lost after send')
      return Response.json({ items: [], total: 0 })
    }
    throw new Error('Unexpected API: ' + url)
  })
  await open()
  await page.getByLabelText(/核对依据/).fill('上游账单人工核对')
  await page.getByLabelText(/输入 Token/).fill('80')
  await page.getByLabelText(/输出 Token/).fill('10')
  await page.getByLabelText(/缓存读取 Token/).fill('20')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await page.getByRole('button', { name: '确认结算' }).click()
  await expect.element(page.getByText('结果尚未确认')).toBeVisible()
  const stored = JSON.parse(String(sessionStorage.getItem(key))) as Record<
    string,
    unknown
  >
  expect(Object.keys(stored).sort()).toEqual(['call_id', 'request_id'])
  expect(receiptReads).toBe(1)
  await page.getByRole('button', { name: '同编号重试原提交' }).click()
  await expect
    .element(page.getByRole('dialog', { name: /核对用量/ }))
    .not.toBeInTheDocument()
  expect(writes).toHaveLength(2)
  expect(writes[1]).toEqual(writes[0])
  expect(receiptReads).toBe(2)
  expect(sessionStorage.getItem(key)).toBeNull()
})

it('recovers an id-only receipt outside the current list filter without resending', async () => {
  sessionStorage.setItem(
    key,
    JSON.stringify({ call_id: callId, request_id: requestId })
  )
  const posts = vi.fn()
  mockFetch((url, init) => {
    if (init?.method === 'POST') posts()
    if (url.endsWith('/reconciliation')) return Response.json(context)
    if (url.includes('/mutation-receipts/'))
      return Response.json({
        request_id: requestId,
        resource_id: callId,
        scope: 'settlement.reconcile',
        state: 'completed',
      })
    throw new Error('Unexpected API: ' + url)
  }, [])
  expect(pendingRecoveries(tenantId, userId)).toHaveLength(1)
  await show()
  await expect.element(page.getByText('有待确认的核对请求')).toBeVisible()
  await page.getByRole('button', { name: '回查核对' }).click()
  await expect
    .element(page.getByText('有待确认的核对请求'))
    .not.toBeInTheDocument()
  expect(posts).not.toHaveBeenCalled()
  expect(sessionStorage.getItem(key)).toBeNull()
})

it('locks the draft on 409, refreshes the server version, and clears inaccessible context on 404', async () => {
  let contextReads = 0
  mockFetch((url) => {
    if (url.endsWith('/reconciliation')) {
      contextReads += 1
      if (contextReads > 1)
        return Response.json(
          { error: { message: '记录不存在' } },
          { status: 404 }
        )
      return Response.json(context)
    }
    if (url.endsWith('/reconcile/preview'))
      return Response.json(
        { error: { message: '记录已处理，请刷新' } },
        { status: 409 }
      )
    throw new Error('Unexpected API: ' + url)
  })
  await open()
  await page.getByLabelText(/核对依据/).fill('保留的核对依据')
  await page.getByLabelText(/输入 Token/).fill('80')
  await page.getByLabelText(/输出 Token/).fill('10')
  await page.getByLabelText(/缓存读取 Token/).fill('20')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await expect.element(page.getByText('服务端记录已变化')).toBeVisible()
  await expect
    .element(page.getByLabelText(/核对依据/))
    .toHaveValue('保留的核对依据')
  await page.getByRole('button', { name: '刷新服务端记录' }).click()
  await expect.element(page.getByText('记录不存在')).toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '确认结算' }))
    .not.toBeInTheDocument()
})

it.each([
  ['characters', 'input_characters', '计费字符数'],
  ['search_units', 'search_units', '上游搜索单位'],
  ['images', 'image_count', '确认交付张数'],
] as const)(
  '%s settlement sends only its explicit tagged quantity',
  async (metric, field, label) => {
    const selected: Schema['ReconciliationContext'] = {
      ...context,
      settlement: { ...entry, metric },
      price: { ...context.price, metric, output: null, cache_read: null },
      required_fields: [field],
    }
    const previews: Record<string, unknown>[] = []
    const writes: Record<string, unknown>[] = []
    mockFetch((url, init) => {
      if (url.endsWith('/reconciliation')) return Response.json(selected)
      if (url.endsWith('/reconcile/preview')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        previews.push(body)
        return Response.json({
          call_id: callId,
          version: 2,
          action: 'settle',
          metric,
          usage: { [field]: 0 },
          amount: '0',
          points: '0',
          currency: 'USD',
        })
      }
      if (url.endsWith('/reconcile')) {
        writes.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
        return Response.json({ items: [], total: 0 })
      }
      throw new Error('Unexpected API: ' + url)
    })
    await show()
    await page.getByRole('button', { name: '核对', exact: true }).click()
    await expect.element(page.getByLabelText(new RegExp(label))).toBeVisible()
    await page.getByLabelText(/核对依据/).fill('核对了供应商账单')
    await page.getByRole('button', { name: '查看结算预览' }).click()
    await expect
      .element(page.getByText('请填写确认的数量', { exact: false }))
      .toBeVisible()
    expect(previews).toHaveLength(0)
    await page.getByLabelText(new RegExp(label)).fill('0')
    await page.getByRole('button', { name: '查看结算预览' }).click()
    await expect.element(page.getByText('按历史快照预览')).toBeVisible()
    expect(previews[0].usage).toEqual({ metric, [field]: 0 })
    await page.getByRole('button', { name: '确认结算' }).click()
    await expect
      .element(page.getByRole('dialog', { name: /核对用量/ }))
      .not.toBeInTheDocument()
    expect(writes).toHaveLength(1)
    expect(writes[0].usage).toEqual({ metric, [field]: 0 })
  }
)

it('ignores a late completed receipt after the context denies access', async () => {
  sessionStorage.setItem(
    key,
    JSON.stringify({ call_id: callId, request_id: requestId })
  )
  const lateReceipt = deferred<Response>()
  mockFetch((url) => {
    if (url.endsWith('/reconciliation'))
      return Response.json(
        { error: { message: '权限已失效' } },
        { status: 403 }
      )
    if (url.includes('/mutation-receipts/')) return lateReceipt.promise
    throw new Error('Unexpected API: ' + url)
  }, [])
  await show()
  await page.getByRole('button', { name: '回查核对' }).click()
  await expect
    .element(page.getByText('记录不可访问或权限已变化', { exact: false }))
    .toBeVisible()
  lateReceipt.resolve(
    Response.json({
      request_id: requestId,
      resource_id: callId,
      scope: 'settlement.reconcile',
      state: 'completed',
    })
  )
  await expect
    .element(page.getByText('记录不可访问或权限已变化', { exact: false }))
    .toBeVisible()
  await expect
    .element(page.getByRole('dialog', { name: /核对用量/ }))
    .toBeVisible()
  await expect.element(page.getByText('核对结果已保存')).not.toBeInTheDocument()
  expect(sessionStorage.getItem(key)).toBeNull()
})

it('ignores a late context response after the receipt denies access', async () => {
  sessionStorage.setItem(
    key,
    JSON.stringify({ call_id: callId, request_id: requestId })
  )
  const lateContext = deferred<Response>()
  mockFetch((url) => {
    if (url.endsWith('/reconciliation')) return lateContext.promise
    if (url.includes('/mutation-receipts/'))
      return Response.json(
        { error: { message: '权限已失效' } },
        { status: 403 }
      )
    throw new Error('Unexpected API: ' + url)
  }, [])
  await show()
  await page.getByRole('button', { name: '回查核对' }).click()
  await expect
    .element(page.getByText('记录不可访问或权限已变化', { exact: false }))
    .toBeVisible()
  lateContext.resolve(Response.json(context))
  await expect
    .element(page.getByText('记录不可访问或权限已变化', { exact: false }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '查看结算预览' }))
    .not.toBeInTheDocument()
  expect(sessionStorage.getItem(key)).toBeNull()
})

it('does not send a reconciliation if its recovery id cannot be stored', async () => {
  const writes = vi.fn()
  mockFetch((url) => {
    if (url.endsWith('/reconciliation')) return Response.json(context)
    if (url.endsWith('/reconcile/preview'))
      return Response.json({
        call_id: callId,
        version: 2,
        action: 'settle',
        metric: 'tokens',
        usage: { input_tokens: 1, output_tokens: 0, cache_read_tokens: 0 },
        amount: '0.000002',
        points: '0.0002',
        currency: 'USD',
      })
    if (url.endsWith('/reconcile')) writes()
    throw new Error('Unexpected API: ' + url)
  })
  await open()
  await page.getByLabelText(/核对依据/).fill('核对供应商账单')
  await page.getByLabelText(/输入 Token/).fill('1')
  await page.getByLabelText(/输出 Token/).fill('0')
  await page.getByLabelText(/缓存读取 Token/).fill('0')
  await page.getByRole('button', { name: '查看结算预览' }).click()
  await expect.element(page.getByText('按历史快照预览')).toBeVisible()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  await page.getByRole('button', { name: '确认结算' }).click()
  await expect
    .element(page.getByText('本次核对尚未发送', { exact: false }))
    .toBeVisible()
  expect(writes).not.toHaveBeenCalled()
  expect(sessionStorage.getItem(key)).toBeNull()
})
