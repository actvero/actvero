import '@/styles/index.css'
import { expect, it, vi, afterEach } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import { OriginalViewer } from './original-viewer'

// Small real two-page PDF; exercises PDF.js worker, canvas and page geometry.
function samplePdf() {
  const stream = '0.2 0.4 0.8 rg 40 80 100 35 re f'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << >> /Contents 5 0 R >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << >> /Contents 5 0 R >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ]
  let text = '%PDF-1.7\n'
  const offsets = [0]
  objects.forEach((body, i) => {
    offsets.push(text.length)
    text += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = text.length
  text += `xref\n0 6\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`)
    .join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
  return text
}
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
it('真实 PDF 原件渲染、跳页与缩放后高亮仍跟随原文', async () => {
  const originalFetch = window.fetch.bind(window)
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/v1/knowledge/test/source'
        ? Promise.resolve(
            new Response(samplePdf(), {
              headers: { 'content-type': 'application/pdf' },
            })
          )
        : originalFetch(input, init)
    )
  )
  await render(
    <div style={{ height: 720, width: 900 }}>
      <OriginalViewer
        preview={{
          document_id: 'doc',
          generation_id: 'gen',
          citation_id: 'citation',
          filename: '原文.pdf',
          media_type: 'application/pdf',
          source_url: '/api/v1/knowledge/test/source',
          sources: [
            {
              block_id: '1',
              heading: '',
              start: 0,
              end: 1,
              page: 2,
              coordinate_space: 'normalized',
              bbox: [0.1, 0.2, 0.6, 0.4],
            },
          ],
          text_ranges: [],
        }}
      />
    </div>
  )
  await expect.element(page.getByLabelText('原文高亮 第 2 页')).toBeVisible()
  await expect
    .element(page.getByRole('textbox', { name: '原文页码' }))
    .toHaveValue('2')
  const highlighted = () =>
    document.querySelector('[aria-label="原文高亮 第 2 页"]') as HTMLElement
  expect(highlighted().style.left).toBe('10%')
  const before = highlighted().getBoundingClientRect().width
  await page.getByRole('button', { name: '放大原文' }).click()
  await expect
    .poll(() => highlighted()?.getBoundingClientRect().width)
    .toBeGreaterThan(before)
  await page.getByRole('button', { name: '上一页原文' }).click()
  await expect
    .element(page.getByLabelText('原文高亮 第 2 页'))
    .not.toBeInTheDocument()
  await page.getByRole('button', { name: '下一页原文' }).click()
  await expect.element(page.getByLabelText('原文高亮 第 2 页')).toBeVisible()
})
