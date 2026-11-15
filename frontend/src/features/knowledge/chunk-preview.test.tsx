import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { DocumentDialog } from './document-reader'
import { initial, type Base, type Document } from './shared'

vi.mock('@/features/auth/session', () => ({
  useOrganization: () => ({
    organization: { tenant_id: 'org', role: 'administrator' },
    user: { id: 'admin' },
    csrf: 'synthetic',
  }),
}))
afterEach(() => vi.unstubAllGlobals())

it('自动试算隔离过期结果，原文高亮与新参数一致，明确应用才重建', async () => {
  await page.viewport(1280, 900)
  const doc: Document = {
    id: 'doc',
    filename: '指南.txt',
    media_type: 'text/plain',
    size: 30,
    created_at: '2026-11-15T00:00:00Z',
    generation_id: 'generation',
    active_generation_id: 'generation',
    status: 'ready',
    error: '',
    chunk_count: 1,
    indexed_count: 1,
  }
  const base: Base = {
    ...initial,
    id: 'base',
    name: '指南',
    version: 1,
    embedding_profile: {},
    retrieval: { mode: 'keyword', vector_weight: 50 },
    document_count: 1,
    status: 'ready',
    updated_at: doc.created_at,
    can_manage: true,
  }
  const sourceUrl = '/api/v1/knowledge/base/documents/doc/source'
  const previewCalls = vi.fn()
  const rebuild = vi.fn()
  let finishOld: (() => void) | undefined
  let rejectApply = true
  const onClose = vi.fn()
  vi.stubGlobal('fetch', async (url: RequestInfo, options?: RequestInit) => {
    const path = String(url)
    if (path === sourceUrl) return new Response('第一段原文。第二段原文。')
    if (path.endsWith('/rebuild')) {
      rebuild(JSON.parse(String(options?.body)))
      if (rejectApply)
        return Response.json(
          { error: { message: '文档处理版本已变化，请刷新' } },
          { status: 409 }
        )
      return Response.json({ ...doc, generation_id: 'new-generation' })
    }
    if (path.endsWith('/chunk-preview')) {
      const body = JSON.parse(String(options?.body))
      previewCalls(body)
      if (body.chunking.target_chars === 600)
        await new Promise<void>((resolve) => {
          finishOld = resolve
        })
      const target = body.chunking.target_chars
      return Response.json({
        generation_id: 'generation',
        chunking: body.chunking,
        preview_token: String(target).padStart(64, '0'),
        total_chunks: 2,
        filtered_total: 2,
        parent_count: 0,
        average_chars: target,
        shortest_chars: 6,
        longest_chars: target,
        model_limit: 10000,
        chunks: [
          {
            sequence: 1,
            content: `预览 ${target}`,
            sources: [],
            text_ranges: [{ start: 0, end: 6 }],
          },
          {
            sequence: 2,
            content: '第二段原文。',
            sources: [],
            text_ranges: [{ start: 6, end: 12 }],
          },
        ],
      })
    }
    if (path.includes('/preview?'))
      return Response.json({
        document_id: doc.id,
        generation_id: 'generation',
        filename: doc.filename,
        media_type: doc.media_type,
        source_url: sourceUrl,
        citation_id: new URL(path, location.href).searchParams.get('chunk_id'),
        sources: [],
        text_ranges: [],
      })
    return Response.json({
      ...doc,
      chunking: initial.chunking,
      total_chunks: 1,
      chunks: [
        { id: 'original', sequence: 1, content: '已存切片', sources: [] },
      ],
      can_manage: true,
      source_url: sourceUrl,
    })
  })
  await render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <DocumentDialog base={base} doc={doc} onClose={onClose} />
    </QueryClientProvider>
  )
  await page.getByRole('button', { name: '调整切片' }).click()
  await expect
    .element(page.getByText('预览 1200', { exact: true }))
    .toBeVisible()
  expect(rebuild).not.toHaveBeenCalled()
  const target = page.getByLabelText('每片约多少字')
  const apply = page.getByRole('button', { name: '应用并重新建立索引' })
  await target.fill('600')
  await expect.poll(() => finishOld).toBeDefined()
  await target.fill('900')
  await expect
    .element(page.getByText('预览 900', { exact: true }))
    .toBeVisible()
  finishOld!()
  await expect
    .element(page.getByText('预览 600', { exact: true }))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '切片 2', exact: true }).click()
  await expect
    .poll(() => document.querySelector('mark')?.textContent)
    .toBe('第二段原文。')
  await target.fill('')
  await expect.element(apply).toBeDisabled()
  await expect
    .element(page.getByText('预览 900', { exact: true }))
    .not.toBeInTheDocument()
  await target.fill('1200')
  await expect.element(apply).toBeEnabled()
  await apply.click()
  await expect
    .element(page.getByText('文档处理版本已变化，请刷新'))
    .toBeVisible()
  expect(onClose).not.toHaveBeenCalled()
  rejectApply = false
  await apply.click()
  await expect.poll(() => onClose.mock.calls.length).toBe(1)
  expect(rebuild).toHaveBeenLastCalledWith({
    generation_id: 'generation',
    chunking: initial.chunking,
    preview_token: '1200'.padStart(64, '0'),
  })
})
