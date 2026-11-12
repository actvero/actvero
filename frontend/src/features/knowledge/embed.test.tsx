import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@/styles/index.css'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { EmbeddedReader } from './embed'
import { readerProtocol, trustedParent } from './reader-http'

const clients: QueryClient[] = []
afterEach(() => {
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
it('只接受绑定父窗口的握手；阅读不带 Cookie，凭证不进入 URL 或缓存', async () => {
  const token = 'avr_synthetic_reader_credential'
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    expect(init?.credentials).toBe('omit')
    expect((init?.headers as Record<string, string>).Authorization).toBe(
      `Bearer ${token}`
    )
    expect(url).not.toContain(token)
    return url.endsWith('/manifest')
      ? Response.json({
          document_id: 'one',
          generation_id: 'gen',
          filename: '手册.txt',
          media_type: 'text/plain',
          sources: [],
          text_ranges: [],
          source_url: '/api/v1/knowledge-reader/source',
        })
      : new Response('真实原件内容')
  })
  vi.stubGlobal('fetch', fetcher)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  await render(
    <QueryClientProvider client={client}>
      <EmbeddedReader parentOrigin='https://host.example' />
    </QueryClientProvider>
  )
  const message = (origin: string, source: Window | null, type = 'init') =>
    window.dispatchEvent(
      new MessageEvent('message', {
        origin,
        source,
        data: { protocol: readerProtocol, type, token },
      })
    )
  message('https://evil.example', window.parent)
  message('https://host.example', null)
  expect(fetcher).not.toHaveBeenCalled()
  message('https://host.example', window.parent)
  await expect.element(page.getByText('真实原件内容')).toBeVisible()
  expect(
    JSON.stringify(
      client
        .getQueryCache()
        .getAll()
        .map((query) => ({ key: query.queryKey, data: query.state.data }))
    )
  ).not.toContain(token)
  message('https://host.example', window.parent, 'clear')
  await expect.element(page.getByText('等待打开原文')).toBeVisible()
  await expect.element(page.getByText('真实原件内容')).not.toBeInTheDocument()
})
it('拒绝任意路径、明文远程地址与非 Web 来源', () => {
  for (const value of [
    'http://host.example',
    'https://host.example/path',
    'javascript:alert(1)',
    'null',
  ])
    expect(trustedParent(value)).toBeNull()
  expect(trustedParent('https://host.example')).toBe('https://host.example')
  expect(trustedParent('http://127.0.0.1:8000')).toBe('http://127.0.0.1:8000')
})
