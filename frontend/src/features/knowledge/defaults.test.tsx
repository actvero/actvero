import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { KnowledgeDefaults } from './defaults'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org', role: 'administrator' },
    user: { id: 'admin', name: '当前管理员' },
    csrf: 'synthetic',
  }),
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const defaults = {
  version: 0,
  embedding_model_id: null,
  rerank_model_id: null,
  rerank_enabled: false,
  models: [],
  credentials: [],
}

async function renderDefaults(fetcher: typeof fetch) {
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
}

it('一次提交多个 Key，失败保留输入，成功关闭并清空', async () => {
  let fail = true
  const submissions: unknown[] = []
  await renderDefaults(async (url, options) => {
    if (String(url).endsWith('/credentials/batch')) {
      submissions.push(JSON.parse(String(options?.body)))
      return fail
        ? Response.json({ error: { message: '暂时无法保存' } }, { status: 503 })
        : Response.json([], { status: 201 })
    }
    return Response.json(defaults)
  })
  await page.getByRole('button', { name: '添加 Key' }).click()
  const dialog = page.getByRole('dialog', { name: '添加 MinerU Key' })
  const field = dialog.getByLabelText('API Key', { exact: true })
  const name = dialog.getByLabelText('名称', { exact: true })
  await name.fill('解析账号')
  await field.fill('synthetic-key-one, synthetic-key-two，synthetic-key-three')
  await expect.element(field).toHaveAttribute('type', 'password')
  await dialog.getByRole('button', { name: '添加 Key' }).click()
  await expect.element(dialog.getByText('暂时无法保存')).toBeVisible()
  await expect
    .element(field)
    .toHaveValue('synthetic-key-one, synthetic-key-two，synthetic-key-three')
  fail = false
  await dialog.getByRole('button', { name: '添加 Key' }).click()
  await expect.element(dialog).not.toBeInTheDocument()
  await page.getByRole('button', { name: '添加 Key' }).click()
  await expect.element(field).toHaveValue('')
  await expect.element(name).toHaveValue('')
  expect(submissions).toEqual(
    Array(2).fill({
      keys: ['synthetic-key-one', 'synthetic-key-two', 'synthetic-key-three'],
      name: '解析账号',
    })
  )
})

it('切换模型立即保存，下一次修改使用最新版本，失败时恢复保存值', async () => {
  const submit = vi.fn()
  let configured = {
    ...defaults,
    version: 2,
    rerank_model_id: 'rerank-1',
    rerank_enabled: true,
    models: [
      { id: 'rerank-1', name: '重排模型', kind: 'rerank', dimensions: null },
      {
        id: 'embedding-1',
        name: '向量模型 A',
        kind: 'embedding',
        dimensions: 3,
      },
    ],
  }
  await renderDefaults(async (_url, options) => {
    if (options?.method === 'PUT') {
      const body = JSON.parse(String(options.body))
      submit(body)
      if (body.embedding_model_id)
        return Response.json(
          { error: { message: '暂时无法保存' } },
          { status: 503 }
        )
      configured = {
        ...configured,
        ...body,
        version: 3,
      }
      return Response.json(configured)
    }
    return Response.json(configured)
  })
  await page.getByRole('combobox', { name: '重排序' }).click()
  await page.getByRole('option', { name: '不启用' }).click()
  await expect
    .poll(() => submit.mock.calls[0]?.[0])
    .toEqual({
      version: 2,
      embedding_model_id: null,
      rerank_model_id: null,
      rerank_enabled: false,
    })
  const rerank = page.getByRole('combobox', { name: '重排序' })
  await expect.element(rerank).toHaveTextContent('不启用')
  await expect.element(rerank).toBeEnabled()
  const embedding = page.getByRole('combobox', { name: '向量模型' })
  await embedding.click()
  await page.getByRole('option', { name: '向量模型 A · 3 维' }).click()
  await expect.element(embedding).toBeEnabled()
  await expect.element(embedding).toHaveTextContent('暂不配置')
  expect(submit.mock.calls).toHaveLength(2)
  expect(submit.mock.calls[1][0]).toMatchObject({
    version: 3,
    embedding_model_id: 'embedding-1',
    rerank_model_id: null,
    rerank_enabled: false,
  })
})

it('从行尾菜单编辑 Key，并在确认后删除', async () => {
  let credentials = [{ id: 'credential-1', name: '测试 Key', enabled: true }]
  const deleted = vi.fn()
  await renderDefaults(async (url, options) => {
    if (String(url).endsWith('/credentials/credential-1')) {
      if (options?.method === 'PATCH') {
        credentials = [
          { ...credentials[0], ...JSON.parse(String(options.body)) },
        ]
        return Response.json(credentials[0])
      }
      if (options?.method === 'DELETE') {
        deleted()
        credentials = []
        return new Response(null, { status: 204 })
      }
    }
    return Response.json({ ...defaults, credentials })
  })

  await page.getByRole('button', { name: '测试 Key 操作' }).click()
  await page.getByRole('menuitem', { name: '编辑' }).click()
  const editor = page.getByRole('dialog', { name: '修改 Key 名称' })
  const name = editor.getByLabelText('名称', { exact: true })
  await expect.element(name).toHaveFocus()
  await name.fill('解析 Key')
  await editor.getByRole('button', { name: '保存名称' }).click()
  const actions = page.getByRole('button', { name: '解析 Key 操作' })
  await actions.click()
  await page.getByRole('menuitem', { name: '删除' }).click()
  const confirm = page.getByRole('alertdialog', { name: '删除 MinerU Key？' })
  await expect.element(confirm.getByText(/解析 Key/)).toBeVisible()
  expect(deleted).not.toHaveBeenCalled()
  await confirm.getByRole('button', { name: '取消' }).click()
  await expect.element(actions).toHaveFocus()
  await actions.click()
  await page.getByRole('menuitem', { name: '删除' }).click()
  await confirm.getByRole('button', { name: '删除' }).click()
  await expect.element(page.getByText('尚未添加 MinerU Key。')).toBeVisible()
  expect(deleted).toHaveBeenCalledOnce()
})
