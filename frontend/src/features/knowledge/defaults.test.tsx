import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { KnowledgeDefaults } from './defaults'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org', role: 'administrator' },
    user: { id: 'admin' },
    csrf: 'synthetic',
  }),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('一次提交多个 Key，失败保留输入，成功清空且不回显密钥', async () => {
  let fail = true
  const submissions: unknown[] = []
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/credentials/batch')) {
      submissions.push(JSON.parse(String(options?.body)))
      return fail
        ? Response.json({ error: { message: '暂时无法保存' } }, { status: 503 })
        : Response.json([], { status: 201 })
    }
    return Response.json({
      version: 0,
      embedding_model_id: null,
      rerank_model_id: null,
      rerank_enabled: false,
      models: [],
      credentials: [],
      executor_name: null,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <KnowledgeDefaults />
    </QueryClientProvider>
  )
  const field = page.getByLabelText('API Key', { exact: true })
  await field.fill('synthetic-key-one, synthetic-key-two，synthetic-key-three')
  await expect.element(field).toHaveAttribute('type', 'password')
  await page.getByRole('button', { name: '添加 Key' }).click()
  await expect.poll(() => submissions.length).toBe(1)
  await expect
    .element(field)
    .toHaveValue('synthetic-key-one, synthetic-key-two，synthetic-key-three')
  fail = false
  await page.getByRole('button', { name: '添加 Key' }).click()
  await expect.element(field).toHaveValue('')
  expect(submissions).toEqual(
    Array(2).fill({
      keys: ['synthetic-key-one', 'synthetic-key-two', 'synthetic-key-three'],
    })
  )
})
