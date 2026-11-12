import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { DocumentDialog } from './documents'
import { sourceBox, textSegments } from './reader-geometry'
import { initial, type Base, type Document } from './shared'

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

it('全屏查看原件，点击切片切换高亮；不请求解析文本或重复下载原件', async () => {
  const base: Base = {
    ...initial,
    id: 'base',
    name: '说明资料',
    version: 1,
    embedding_profile: {},
    document_count: 1,
    status: 'ready',
    updated_at: '2026-11-12T00:00:00Z',
    can_manage: true,
  }
  const doc: Document = {
    id: 'document',
    filename: '指南.md',
    media_type: 'text/markdown',
    size: 80,
    created_at: '2026-11-12T00:00:00Z',
    generation_id: 'generation',
    active_generation_id: 'generation',
    status: 'unconfigured',
    error: '',
    chunk_count: 2,
    indexed_count: 0,
  }
  const source = {
    block_id: '0',
    heading: '',
    line: 1,
    start: 0,
    end: 4,
    coordinate_space: 'unknown',
  }
  const original = '# 原件标题\n\n第一段😀原文\n\n第二段原文'
  const sourceUrl = '/api/v1/knowledge/base/documents/document/source'
  const fetcher = vi.fn(async (url: string) => {
    if (url === sourceUrl) return new Response(original)
    if (url.includes('/preview?')) {
      const second = url.includes('chunk_id=second')
      return Response.json({
        document_id: doc.id,
        generation_id: doc.generation_id,
        filename: doc.filename,
        media_type: doc.media_type,
        source_url: sourceUrl,
        sources: [source],
        citation_id: second ? 'second' : 'first',
        text_ranges: second
          ? [{ start: 16, end: 21 }]
          : [{ start: 8, end: 15 }],
      })
    }
    return Response.json({
      ...doc,
      chunks: [
        {
          id: 'first',
          sequence: 1,
          content: '第一段😀原文',
          sources: [source],
        },
        { id: 'second', sequence: 2, content: '第二段原文', sources: [source] },
      ],
      total_chunks: 2,
      can_manage: true,
      source_url: sourceUrl,
    })
  })
  vi.stubGlobal('fetch', fetcher)
  await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <DocumentDialog base={base} doc={doc} onClose={() => {}} />
    </QueryClientProvider>
  )
  await expect
    .element(page.getByRole('region', { name: '原文预览' }))
    .toBeVisible()
  await expect
    .poll(() => document.querySelector('mark')?.textContent)
    .toBe('第一段😀原文\n')
  await page.getByRole('button', { name: '切片 2', exact: true }).click()
  await expect
    .poll(() => document.querySelector('mark')?.textContent)
    .toBe('第二段原文')
  expect(fetcher.mock.calls.filter(([url]) => url === sourceUrl)).toHaveLength(
    1
  )
  expect(
    fetcher.mock.calls.some(([url]) => url.includes('parsed-source'))
  ).toBe(false)
  await page.getByRole('textbox', { name: '查找切片' }).fill('原文')
  await expect
    .element(page.getByRole('textbox', { name: '查找切片' }))
    .toHaveFocus()
  await expect
    .element(page.getByRole('region', { name: '原文预览' }))
    .toBeVisible()
  await page.getByRole('button', { name: '收起切片' }).click()
  await expect
    .element(page.getByRole('complementary', { name: '文档切片' }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '展开切片' }).click()
  await expect
    .element(page.getByRole('complementary', { name: '文档切片' }))
    .toBeVisible()
})

it('高亮坐标按原图比例转换，拒绝未知坐标，Unicode 偏移保持一致', () => {
  expect(
    sourceBox({
      block_id: '0',
      heading: '',
      start: 0,
      end: 1,
      coordinate_space: 'normalized',
      bbox: [0.1, 0.2, 0.5, 0.4],
    })
  ).toEqual({ left: '10%', top: '20%', width: '40%', height: '20%' })
  expect(
    sourceBox({
      block_id: '0',
      heading: '',
      start: 0,
      end: 1,
      coordinate_space: 'unknown',
      bbox: [10, 20, 50, 40],
    })
  ).toBeNull()
  expect(
    sourceBox({
      block_id: '0',
      heading: '',
      start: 0,
      end: 1,
      coordinate_space: 'normalized',
      bbox: [-0.1, 0.2, 0.5, 0.4],
    })
  ).toBeNull()
  expect(
    textSegments('甲😀乙丙', [
      { start: 1, end: 2 },
      { start: 2, end: 3 },
    ])
  ).toEqual([
    { text: '甲', highlighted: false, start: 0 },
    { text: '😀乙', highlighted: true, start: 1 },
    { text: '丙', highlighted: false, start: 3 },
  ])
})
