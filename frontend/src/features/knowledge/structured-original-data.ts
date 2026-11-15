import { officePackage } from './office-package'

export const docxType =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
export const xlsxType =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

const word = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const excel = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const drawing = 'http://schemas.openxmlformats.org/drawingml/2006/main'
const rel =
  'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const packageRel =
  'http://schemas.openxmlformats.org/package/2006/relationships'
type Package = ReturnType<typeof officePackage>

type WordPicture = { path: string; offset: number }
type WordParagraph = {
  kind: 'paragraph'
  line: number
  style: string
  text: string
  images: WordPicture[]
}
export type WordBlock = WordParagraph | { kind: 'table'; rows: WordBlock[][][] }
export type GridRow = { number: number; cells: Map<number, string> }
export type GridSheet = { name: string; rows: GridRow[]; columns: number[] }

export type Structured =
  | { kind: 'word'; blocks: WordBlock[]; images: Map<string, Blob> }
  | { kind: 'grid'; sheets: GridSheet[]; csv: boolean }

const malformed = () => new Error('无法读取文档结构')
const tooLarge = () => new Error('内容超出预览上限，请下载原件查看')
const decoder = new TextDecoder('utf-8', { fatal: true })

function all(root: Document | Element, ns: string, name: string) {
  return Array.from(root.getElementsByTagNameNS(ns, name))
}

function children(root: Element, ns: string, name: string) {
  return Array.from(root.children).filter(
    (el) => el.namespaceURI === ns && el.localName === name
  )
}

function xml(pkg: Package, path: string) {
  const data = pkg.read(path)
  if (!data) return undefined
  const text =
    data[0] === 0xff && data[1] === 0xfe
      ? new TextDecoder('utf-16le', { fatal: true }).decode(data)
      : data[0] === 0xfe && data[1] === 0xff
        ? new TextDecoder('utf-16be', { fatal: true }).decode(data)
        : decoder.decode(data)
  if (/<!DOCTYPE|<!ENTITY/i.test(text)) throw malformed()
  const result = new DOMParser().parseFromString(text, 'application/xml')
  if (result.getElementsByTagName('parsererror').length) throw malformed()
  return result
}

function relations(pkg: Package, path: string, suffix: string, prefix: string) {
  const content = xml(pkg, path)
  const targets = new Map<string, string>()
  if (!content) return targets
  for (const entry of all(content, packageRel, 'Relationship')) {
    const id = entry.getAttribute('Id')
    const target = entry.getAttribute('Target')
    if (
      id &&
      target &&
      !entry.getAttribute('TargetMode') &&
      entry.getAttribute('Type')?.endsWith('/' + suffix)
    ) {
      const full = target.startsWith('/') ? target.slice(1) : prefix + target
      if (full.startsWith(prefix) && !full.split('/').includes('..'))
        targets.set(id, full)
    }
  }
  return targets
}

function wordOriginal(pkg: Package): Structured {
  const content = xml(pkg, 'word/document.xml')
  const body = content && all(content, word, 'body')[0]
  if (!content || !body) throw malformed()
  const order = new Map(
    all(content, word, 'p').map((p, index) => [p, index + 1])
  )
  if (order.size > 20000) throw tooLarge()
  const targets = relations(
    pkg,
    'word/_rels/document.xml.rels',
    'image',
    'word/'
  )
  const images = new Map<string, Blob>()
  const loadedImages = new Set<string>()

  function paragraph(node: Element, line: number): WordParagraph {
    let text = ''
    let offset = 0
    const marks: WordPicture[] = []
    const style =
      all(node, word, 'pStyle')[0]
        ?.getAttributeNS(word, 'val')
        ?.toLowerCase() ?? ''
    // The same text nodes and traversal order as the backend parser keeps offsets stable.
    const walker = content!.createTreeWalker(node, NodeFilter.SHOW_ELEMENT)
    for (
      let el = walker.nextNode() as Element | null;
      el;
      el = walker.nextNode() as Element | null
    ) {
      if (el.namespaceURI === word && el.localName === 't') {
        const value = el.textContent ?? ''
        text += value
        offset += Array.from(value).length
      }
      if (el.namespaceURI !== drawing || el.localName !== 'blip') continue
      const path = targets.get(el.getAttributeNS(rel, 'embed') ?? '')
      if (!path) continue
      if (!loadedImages.has(path)) {
        loadedImages.add(path)
        const data = pkg.read(path)
        const png =
          data?.length &&
          data.length >= 8 &&
          [137, 80, 78, 71, 13, 10, 26, 10].every((byte, i) => data[i] === byte)
        const jpeg = data?.[0] === 0xff && data[1] === 0xd8
        if (data && (png || jpeg))
          images.set(
            path,
            new Blob([data.slice()], { type: png ? 'image/png' : 'image/jpeg' })
          )
      }
      if (images.has(path)) marks.push({ path, offset })
    }
    return { kind: 'paragraph', line, style, text, images: marks }
  }

  function blocks(node: Element, depth = 0): WordBlock[] {
    if (depth > 32) throw malformed()
    return Array.from(node.children).flatMap((el): WordBlock[] => {
      if (el.namespaceURI !== word) return []
      const line = order.get(el)
      if (line) return [paragraph(el, line)]
      if (el.localName === 'tbl')
        return [
          {
            kind: 'table',
            rows: children(el, word, 'tr').map((row) =>
              children(row, word, 'tc').map((cell) => blocks(cell, depth + 1))
            ),
          },
        ]
      return el.localName === 'sdt' ||
        el.localName === 'sdtContent' ||
        el.localName === 'customXml'
        ? blocks(el, depth + 1)
        : []
    })
  }
  return { kind: 'word', blocks: blocks(body), images }
}

export function cellAddress(value: string) {
  const match = /^([A-Z]{1,3})([1-9]\d{0,6})$/i.exec(value)
  if (!match) return null
  const row = Number(match[2])
  let column = 0
  for (const c of match[1].toUpperCase())
    column = column * 26 + c.charCodeAt(0) - 64
  return column <= 16384 && row <= 1048576 ? { column, row } : null
}

export function columnName(number: number) {
  let label = ''
  for (let n = number; n > 0; n = Math.floor((n - 1) / 26))
    label = String.fromCharCode(65 + ((n - 1) % 26)) + label
  return label
}

function excelOriginal(pkg: Package): Structured {
  const workbook = xml(pkg, 'xl/workbook.xml')
  if (!workbook) throw malformed()
  const targets = relations(
    pkg,
    'xl/_rels/workbook.xml.rels',
    'worksheet',
    'xl/'
  )
  const shared = xml(pkg, 'xl/sharedStrings.xml')
  const values = shared
    ? all(shared, excel, 'si').map((item) =>
        all(item, excel, 't')
          .map((t) => t.textContent)
          .join('')
      )
    : []
  let rowCount = 0
  let cellCount = 0
  const sheets = all(workbook, excel, 'sheet').map((sheet): GridSheet => {
    const name = sheet.getAttribute('name') ?? ''
    const path = targets.get(sheet.getAttributeNS(rel, 'id') ?? '')
    const sheetData = path ? xml(pkg, path) : undefined
    if (!sheetData) throw malformed()
    const rows: GridRow[] = []
    const columns = new Set<number>()
    for (const row of all(sheetData, excel, 'row')) {
      const cells = new Map<number, string>()
      let number = 0
      for (const cell of children(row, excel, 'c')) {
        const address = cellAddress(cell.getAttribute('r') ?? '')
        if (!address || (number && address.row !== number)) throw malformed()
        number = address.row
        columns.add(address.column)
        const type = cell.getAttribute('t')
        let value = children(cell, excel, 'v')[0]?.textContent ?? ''
        if (type === 's') {
          if (!/^\d+$/.test(value) || values[Number(value)] === undefined)
            throw malformed()
          value = values[Number(value)]
        } else if (type === 'inlineStr') {
          value = all(cell, excel, 't')
            .map((t) => t.textContent)
            .join('')
        }
        cells.set(address.column, value)
        if (++cellCount > 200000) throw tooLarge()
      }
      if (number) rows.push({ number, cells })
      if (++rowCount > 20000) throw tooLarge()
    }
    return {
      name,
      rows: rows.sort((a, b) => a.number - b.number),
      columns: [...columns].sort((a, b) => a - b),
    }
  })
  if (!sheets.length) throw malformed()
  return { kind: 'grid', sheets, csv: false }
}

function csvOriginal(text: string): Structured {
  const rows: GridRow[] = []
  let cells = new Map<number, string>()
  let field = ''
  let quoted = false
  let started = false
  let recordStarted = false
  let width = 0
  let cellCount = 0
  const addField = () => {
    cells.set(cells.size + 1, field)
    field = ''
    started = false
    if (++cellCount > 200000 || cells.size > 16384) throw tooLarge()
  }
  const addRecord = () => {
    if (recordStarted) addField()
    width = Math.max(width, cells.size)
    rows.push({ number: rows.length + 1, cells })
    if (rows.length > 20000) throw tooLarge()
    cells = new Map()
    recordStarted = false
  }
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c !== '"') field += c
      else if (text[i + 1] === '"') {
        field += '"'
        i++
      } else quoted = false
    } else if (c === '\n' || c === '\r') {
      addRecord()
      if (c === '\r' && text[i + 1] === '\n') i++
    } else {
      recordStarted = true
      if (c === ',') addField()
      else {
        if (c === '"' && !started) quoted = true
        else field += c
        started = true
      }
    }
  }
  if (recordStarted) addRecord()
  return {
    kind: 'grid',
    csv: true,
    sheets: [
      {
        name: '',
        rows,
        columns: Array.from({ length: width }, (_, index) => index + 1),
      },
    ],
  }
}

export function readStructured(bytes: ArrayBuffer, mediaType: string) {
  if (mediaType === 'text/csv') return csvOriginal(decoder.decode(bytes))
  const pkg = officePackage(bytes)
  return mediaType === docxType ? wordOriginal(pkg) : excelOriginal(pkg)
}
