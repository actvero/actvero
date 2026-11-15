import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { useDocuments } from './document-data'
import { AddDocuments } from './document-upload'
import { Documents } from './documents'
import { KnowledgePage } from './page'
import { initial, type Base, type Document } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org', role: 'administrator' },
    user: { id: 'admin' },
    csrf: 'synthetic',
  }),
}))

vi.mock('@/components/layout/page-shell', () => ({
  PageShell: ({
    title,
    description,
    children,
  }: {
    title?: string
    description?: string
    children: ReactNode
  }) => (
    <main className='@container/content flex h-svh min-w-0 flex-col p-4'>
      {title && <h1>{title}</h1>}
      {description && <p>{description}</p>}
      {children}
    </main>
  ),
}))

const base: Base = {
  ...initial,
  id: 'base',
  name: '说明资料',
  description: '资料使用说明',
  version: 1,
  embedding_profile: {},
  retrieval: { mode: 'keyword', vector_weight: 50 },
  document_count: 11,
  status: 'ready',
  updated_at: '2026-11-12T00:00:00Z',
  can_manage: false,
}
const documents = Array.from(
  { length: 11 },
  (_, index): Document => ({
    id: `document-${index}`,
    filename: `指南${index + 1}.md`,
    media_type: 'text/markdown',
    size: 80,
    created_at: new Date(Date.UTC(2026, 10, index + 1)).toISOString(),
    generation_id: 'generation',
    active_generation_id: index === 1 ? 'older-generation' : 'generation',
    status: index === 1 ? 'indexing' : 'ready',
    error: '',
    chunk_count: 4,
    indexed_count: index === 1 ? 1 : 0,
    chunk_structure: index === 0 ? 'general' : 'parent_child',
    character_count: index === 0 ? null : index === 1 ? 0 : 80,
  })
)

function Fixture({ queue = false }: { queue?: boolean }) {
  const query = useDocuments(base.id, true)
  return (
    <main className='p-4'>
      <Documents base={base} query={query} queue={queue} />
    </main>
  )
}

function provider(children: React.ReactNode) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  )
}

afterEach(() => vi.unstubAllGlobals())

it('知识库卡片显示已保存头像，底部只显示文档数', async () => {
  const image =
    'data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20width=%2232%22%20height=%2232%22/%3E'
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({
        items: [
          { ...base, icon: { source: 'upload', image, key: '' } },
          {
            ...base,
            id: 'empty',
            name: '空库',
            document_count: 0,
            status: 'empty',
          },
        ],
        total: 2,
      })
    )
  )
  const onOpen = vi.fn()
  await render(provider(<KnowledgePage onOpen={onOpen} />))
  const card = page.getByRole('button', { name: /说明资料/ })
  await expect
    .element(card.getByText('11 份文档', { exact: true }))
    .toBeVisible()
  await expect
    .poll(() => card.element().querySelector('img')?.getAttribute('src'))
    .toBe(image)
  expect(card.element().querySelector('time')).toBeNull()
  await expect.element(card.getByText('仅管理员')).not.toBeInTheDocument()
  const empty = page.getByRole('button', { name: /空库/ })
  await expect
    .element(empty.getByText('0 份文档', { exact: true }))
    .toBeVisible()
  expect(empty.element().querySelector('svg')).not.toBeNull()
  await card.click()
  expect(onOpen).toHaveBeenCalledWith({ base: base.id })
})

it('宽屏显示左侧导航，横向页签与库名之间保留常规间距', async () => {
  await page.viewport(1440, 900)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/documents')) return Response.json(documents)
      if (url.endsWith('/icon-catalog')) return Response.json([])
      return Response.json({
        ...base,
        can_manage: true,
        icon: {
          source: 'upload',
          key: '',
          image:
            'data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22/%3E',
        },
      })
    })
  )
  function Detail() {
    const [tab, setTab] = useState<'queue' | 'search' | 'settings'>()
    return (
      <KnowledgePage
        baseId={base.id}
        initialTab={tab}
        onOpen={({ tab }) => setTab(tab)}
      />
    )
  }
  await render(provider(<Detail />))
  const nav = page.getByRole('tablist', { name: '知识库导航' })
  const table = page.getByRole('table', { name: '知识库文档' })
  const description = page.getByText(base.description, { exact: true })
  await expect.element(nav).toHaveAttribute('aria-orientation', 'vertical')
  await expect.element(table).toBeVisible()
  await expect.element(description).not.toBeInTheDocument()
  expect(nav.element().getBoundingClientRect().right).toBeLessThan(
    table.element().getBoundingClientRect().left
  )
  await nav.getByRole('tab', { name: '处理队列', exact: false }).click()
  await expect
    .element(page.getByRole('table', { name: '处理队列' }))
    .toBeVisible()

  const title = page.getByRole('heading', { name: base.name, exact: true })
  await page.viewport(860, 800)
  await expect.element(nav).toHaveAttribute('aria-orientation', 'horizontal')
  const gap =
    nav.element().getBoundingClientRect().top -
    title.element().getBoundingClientRect().bottom
  expect(gap).toBeGreaterThanOrEqual(16)
  expect(gap).toBeLessThanOrEqual(24)

  await page.viewport(390, 844)
  await expect
    .poll(() => nav.element().getBoundingClientRect().top)
    .toBeGreaterThanOrEqual(title.element().getBoundingClientRect().bottom)
  await expect.element(description).not.toBeInTheDocument()
  await expect
    .element(nav.getByRole('tab', { name: '处理队列', exact: false }))
    .toHaveAttribute('aria-selected', 'true')

  const avatar = page.getByRole('button', { name: '编辑知识库头像' })
  await expect.poll(() => avatar.element().querySelector('img')).not.toBeNull()
  expect(avatar.element().querySelector('svg')).toBeNull()
  await avatar.click()
  await expect
    .element(page.getByRole('dialog', { name: '选择知识库头像' }))
    .toBeVisible()
})

it('文件名前显示对应格式图标，各宽度的文档列表均不显示分段模式', async () => {
  await page.viewport(1200, 800)
  const files = [
    { ...documents[0], filename: '手册.PDF', media_type: 'application/pdf' },
    { ...documents[1], filename: '介绍.docx' },
    { ...documents[2], filename: '数据.xlsx' },
    { ...documents[3], filename: '数据.csv', media_type: 'text/csv' },
    { ...documents[4], filename: '示例.png', media_type: 'image/png' },
    documents[5],
  ]
  vi.stubGlobal('fetch', vi.fn(async () => Response.json(files)))
  await render(provider(<Fixture />))
  const table = page.getByRole('table', { name: '知识库文档' })
  await expect.element(table.getByText('文件名', { exact: true })).toBeVisible()
  await expect.element(table.getByText('分段模式')).not.toBeInTheDocument()
  const icons = files.map(({ filename }) => {
    const button = table.getByRole('button', { name: filename, exact: true })
    return button.element().closest('td')!.querySelector('[aria-hidden="true"]')!
  })
  expect(new Set(icons.map((icon) => icon.innerHTML)).size).toBe(files.length)

  await page.viewport(390, 844)
  await expect.element(table.getByText('父子分段')).not.toBeInTheDocument()
  await expect.element(table.getByText('通用分段')).not.toBeInTheDocument()
  for (const icon of icons) expect(icon.getBoundingClientRect().width).toBe(16)
})

it('按文件名搜索和状态筛选，按全部符合条件的文档排序、翻页', async () => {
  await page.viewport(1200, 800)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json(documents))
  )
  await render(provider(<Fixture />))
  const firstName = () => document.querySelector('tbody tr button')?.textContent
  await expect.poll(firstName).toBe('指南11.md')

  await page.getByRole('combobox', { name: '文档排序' }).click()
  await page.getByRole('option', { name: '文件名 A–Z' }).click()
  await expect.poll(firstName).toBe('指南1.md')

  await page.getByRole('combobox', { name: '每页条数' }).click()
  await page.getByRole('option', { name: '10 条 / 页' }).click()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect.poll(firstName).toBe('指南11.md')

  await page.getByRole('searchbox', { name: '搜索文档' }).fill('指南2.MD')
  await expect.poll(firstName).toBe('指南2.md')
  await expect
    .element(page.getByRole('cell', { name: '0', exact: true }))
    .toBeVisible()
  await expect.element(page.getByText('旧版可检索')).toBeVisible()

  await page.getByRole('combobox', { name: '文档状态' }).click()
  await page.getByRole('option', { name: '可检索' }).click()
  await expect.element(page.getByText('没有符合条件的文档')).toBeVisible()
  await page.getByRole('button', { name: '清除筛选' }).click()
  await expect.poll(firstName).toBe('指南1.md')
  const firstRow = page.getByRole('row', { name: /指南1[.]md/ })
  await expect
    .element(firstRow.getByRole('cell', { name: '—', exact: true }))
    .toBeVisible()
  await expect
    .element(page.getByRole('button', { name: '上传文档' }))
    .not.toBeInTheDocument()
})

it('在窄屏处理队列显示实际进度，保留只读成员的处理详情入口', async () => {
  await page.viewport(390, 844)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json(documents))
  )
  await render(provider(<Fixture queue />))

  const progress = page.getByRole('progressbar', { name: '指南2.md 索引进度' })
  await expect.element(progress).toHaveAttribute('aria-valuenow', '25')
  await expect
    .element(page.getByRole('button', { name: '指南1.md', exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '展开 指南2.md 处理详情' }).click()
  await expect.element(page.getByText('上一版本仍可检索。')).toBeVisible()
  expect(document.documentElement.scrollWidth).toBe(window.innerWidth)

  await page.getByRole('combobox', { name: '任务状态' }).click()
  await page.getByRole('option', { name: '已完成' }).click()
  await expect
    .element(page.getByRole('button', { name: '指南1.md', exact: true }))
    .toBeVisible()
})

it('保留部分上传失败的文件，重试沿用原上传标识', async () => {
  await page.viewport(390, 844)
  const calls: URLSearchParams[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const params = new URL(url, window.location.href).searchParams
      calls.push(params)
      if (params.get('filename') === '第二份.md' && calls.length === 2) {
        return Response.json(
          { error: { message: '请稍后再试' } },
          { status: 503 }
        )
      }
      return Response.json({}, { status: 201 })
    })
  )
  await render(provider(<AddDocuments baseId={base.id} />))
  await page.getByRole('button', { name: '上传文档' }).click()
  const dialog = page.getByRole('dialog', { name: '上传文档' })
  await dialog
    .getByLabelText('上传知识库文档')
    .upload([new File(['一'], '第一份.md'), new File(['二'], '第二份.md')])
  await expect.element(dialog.getByText('第二份.md：请稍后再试')).toBeVisible()
  await page.getByRole('button', { name: '重试失败文件' }).click()
  await expect.element(dialog).not.toBeInTheDocument()
  expect(calls.map((params) => params.get('filename'))).toEqual([
    '第一份.md',
    '第二份.md',
    '第二份.md',
  ])
  expect(calls[2].get('upload_id')).toBe(calls[1].get('upload_id'))
})
