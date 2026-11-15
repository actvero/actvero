import '@/styles/index.css'
import { strToU8, zipSync } from 'fflate'
import { afterEach, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { page } from 'vitest/browser'
import type { Schema } from '@/lib/api'
import { officePackage } from './office-package'
import { OriginalViewer } from './original-viewer'
import { docxType, xlsxType } from './structured-original-data'

const word = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const excel = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const drawing = 'http://schemas.openxmlformats.org/drawingml/2006/main'
const relation =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const packageRelation =
  'http://schemas.openxmlformats.org/package/2006/relationships'
const png =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf2gAAAAASUVORK5CYII='
const sourceUrl = '/api/v1/knowledge/synthetic/source'
const at = (
  location: Partial<Schema['SourceLocation']>
): Schema['SourceLocation'] => ({
  block_id: 'synthetic',
  heading: '',
  coordinate_space: 'unknown',
  start: 0,
  end: 0,
  ...location,
})
const archive = (files: Record<string, string | Uint8Array>) =>
  zipSync(
    Object.fromEntries(
      Object.entries(files).map(([name, value]) => [
        name,
        typeof value === 'string' ? strToU8(value) : value,
      ])
    )
  )

async function open(
  body: BodyInit,
  mediaType: string,
  filename: string,
  sources: Schema['SourceLocation'][]
) {
  const native = window.fetch.bind(window)
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === sourceUrl
        ? Promise.resolve(new Response(body))
        : native(input, init)
    )
  )
  await render(
    <div style={{ height: 680, width: 800 }}>
      <OriginalViewer
        preview={{
          document_id: 'doc',
          generation_id: 'gen',
          citation_id: 'chunk',
          filename,
          media_type: mediaType,
          source_url: sourceUrl,
          sources,
        }}
      />
    </div>
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('Word 原件按正文顺序显示段落、表格和安全图片，空段落也计入定位', async () => {
  const zip = archive({
    'word/document.xml': `<w:document xmlns:w="${word}" xmlns:a="${drawing}" xmlns:r="${relation}">
      <w:body>
        <w:p/>
        <w:p><w:r><w:t>表格前</w:t><w:drawing><a:blip r:embed="image"/></w:drawing></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>甲😀乙</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        <w:p><w:r><w:t>表格后</w:t></w:r></w:p>
      </w:body>
    </w:document>`,
    'word/_rels/document.xml.rels': `<Relationships xmlns="${packageRelation}"><Relationship Id="image" Type="${relation}/image" Target="media/logo.png"/></Relationships>`,
    'word/media/logo.png': Uint8Array.from(atob(png), (c) => c.charCodeAt(0)),
  })
  await open(zip as Uint8Array<ArrayBuffer>, docxType, '测试.docx', [
    at({ line: 3, start: 1, end: 2 }),
  ])
  await expect.element(page.getByRole('cell', { name: '甲😀乙' })).toBeVisible()
  await expect
    .poll(() => document.querySelector('mark')?.textContent)
    .toBe('😀')
  await expect
    .element(page.getByRole('img', { name: '文档内嵌图片' }))
    .toBeVisible()
  await expect.element(page.getByText('表格后')).toBeVisible()
  expect(document.querySelector('article img')?.getAttribute('src')).toMatch(
    /^blob:/
  )
})

it('Excel 跳到引用工作表，保留原单元格地址并展示公式缓存值', async () => {
  const zip = archive({
    'xl/workbook.xml': `<workbook xmlns="${excel}" xmlns:r="${relation}"><sheets><sheet name="概览" r:id="one"/><sheet name="Sheet1" r:id="two"/></sheets></workbook>`,
    'xl/_rels/workbook.xml.rels': `<Relationships xmlns="${packageRelation}">
      <Relationship Id="one" Type="${relation}/worksheet" Target="worksheets/sheet1.xml"/>
      <Relationship Id="two" Type="${relation}/worksheet" Target="/xl/worksheets/sheet2.xml"/>
    </Relationships>`,
    'xl/worksheets/sheet1.xml': `<worksheet xmlns="${excel}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>总表</t></is></c></row></sheetData></worksheet>`,
    'xl/worksheets/sheet2.xml': `<worksheet xmlns="${excel}"><sheetData><row r="108"><c r="C108" t="s"><v>0</v></c><c r="E108"><f>1+2</f><v>3</v></c></row></sheetData></worksheet>`,
    'xl/sharedStrings.xml': `<sst xmlns="${excel}"><si><r><t>原始</t></r><r><t>文字</t></r></si></sst>`,
  })
  await open(zip as Uint8Array<ArrayBuffer>, xlsxType, '测试.xlsx', [
    at({ sheet: 'Sheet1', cell_range: 'C108:E108' }),
  ])
  await expect
    .element(page.getByRole('rowheader', { name: '108' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('columnheader', { name: 'E' }))
    .toBeVisible()
  await expect
    .element(page.getByRole('cell', { name: '3' }))
    .toHaveAttribute('data-original-highlight', '')
  await expect
    .element(page.getByRole('cell', { name: '原始文字' }))
    .toBeVisible()
  await page.getByRole('combobox', { name: '工作表' }).click()
  await page.getByRole('option', { name: '概览' }).click()
  await expect.element(page.getByRole('cell', { name: '总表' })).toBeVisible()
})

it('CSV 多行带引号字段按一条记录渲染，定位优先使用记录地址', async () => {
  await open(
    '名称,备注\r\n甲,"一行\r\n另一行"\r\n乙,"带""引号"""\r\n',
    'text/csv',
    '测试.csv',
    [at({ cell_range: 'row:2' })]
  )
  await expect
    .element(page.getByRole('row', { name: /2 甲/ }))
    .toHaveAttribute('data-original-highlight', '')
  await expect
    .element(page.getByRole('cell', { name: '带"引号"' }))
    .toBeVisible()
  expect(document.querySelectorAll('tbody tr')).toHaveLength(3)
})

it('Office 文件拒绝非法内部路径与伪报的解包尺寸', () => {
  const unsafe = archive({ '../sample.xml': '<sample/>' })
  expect(() => officePackage(unsafe.buffer as ArrayBuffer)).toThrow()
  const zip = archive({ 'sample.xml': 'a'.repeat(64 * 1024) })
  const view = new DataView(zip.buffer as ArrayBuffer)
  const central = view.getUint32(zip.length - 6, true)
  view.setUint32(central + 24, 128, true)
  expect(() =>
    officePackage(zip.buffer as ArrayBuffer).read('sample.xml')
  ).toThrow()
})
