import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download } from 'lucide-react'
import type { Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from '@/components/ui/empty'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { textSegments } from './reader-geometry'
import {
  cellAddress,
  columnName,
  readStructured,
  type GridSheet,
  type Structured,
  type WordBlock,
} from './structured-original-data'

type Source = Schema['SourceLocation']
type Pos = NonNullable<ReturnType<typeof cellAddress>>
const highlight = 'bg-info/15 text-inherit'
export const readerScrollClass =
  'min-h-0 flex-1 overflow-auto [scrollbar-width:none]'

function WordBody({
  blocks,
  ranges,
  urls,
}: {
  blocks: WordBlock[]
  ranges: Map<number, Schema['OriginalTextRange'][]>
  urls: Map<string, string>
}) {
  return blocks.map((block, i) => {
    if (block.kind === 'table')
      return (
        <table key={`table-${i}`} className='my-3 w-full border-collapse'>
          <tbody>
            {block.rows.map((row, index) => (
              <tr key={index}>
                {row.map((cell, j) => (
                  <td key={j} className='border p-2 align-top'>
                    <WordBody blocks={cell} ranges={ranges} urls={urls} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )
    const images = block.images
    const positions = [...new Set(images.map((image) => image.offset))]
    const segments = textSegments(
      block.text,
      ranges.get(block.line) ?? [],
      positions
    )
    function pictures(offset: number) {
      return images
        .filter((image) => image.offset === offset)
        .map((image, index) => {
          const url = urls.get(image.path)
          return url ? (
            <img
              key={index}
              src={url}
              alt='文档内嵌图片'
              className='my-2 max-w-full'
            />
          ) : null
        })
    }
    const heading = /^heading([1-6])$/.exec(block.style)
    return (
      <div
        key={block.line}
        role={heading ? 'heading' : undefined}
        aria-level={heading ? Number(heading[1]) : undefined}
        className={cn(
          'min-h-[1em] wrap-anywhere whitespace-pre-wrap',
          (heading || block.style === 'title') && 'text-[1.2em] font-semibold'
        )}
      >
        {segments.map((segment) => (
          <span key={segment.start}>
            {pictures(segment.start)}
            {segment.highlighted ? (
              <mark data-original-highlight className={highlight}>
                {segment.text}
              </mark>
            ) : (
              segment.text
            )}
          </span>
        ))}
        {pictures(Array.from(block.text).length)}
      </div>
    )
  })
}

function WordOriginal({
  original,
  sources,
  zoom,
  locate,
}: {
  original: Extract<Structured, { kind: 'word' }>
  sources: Source[]
  zoom: number
  locate: string
}) {
  const root = useRef<HTMLDivElement>(null)
  const [media, setMedia] = useState<{
    images: Map<string, Blob>
    urls: Map<string, string>
  }>()
  useEffect(() => {
    let live = true
    const urls = new Map(
      [...original.images].map(([path, blob]) => [
        path,
        URL.createObjectURL(blob),
      ])
    )
    queueMicrotask(() => {
      if (live) setMedia({ images: original.images, urls })
    })
    return () => {
      live = false
      urls.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [original.images])
  const urls = media?.images === original.images ? media.urls : null
  const byLine = useMemo(() => {
    const out = new Map<number, Schema['OriginalTextRange'][]>()
    for (const source of sources) {
      if (!source.line) continue
      const ranges = out.get(source.line) ?? []
      ranges.push({ start: source.start, end: source.end })
      out.set(source.line, ranges)
    }
    return out
  }, [sources])
  useEffect(() => {
    if (urls)
      root.current
        ?.querySelector('[data-original-highlight]')
        ?.scrollIntoView({ block: 'center', inline: 'nearest' })
  }, [locate, urls])
  return (
    <div
      className={readerScrollClass}
      ref={root}
      tabIndex={0}
      aria-label='原文阅读区'
    >
      {urls && (
        <article
          className='mx-auto flex max-w-5xl flex-col gap-2 bg-background p-6 leading-relaxed sm:p-8'
          style={{ fontSize: zoom + 'rem' }}
        >
          <WordBody blocks={original.blocks} ranges={byLine} urls={urls} />
        </article>
      )}
    </div>
  )
}

function excelRange(source: Source): [Pos, Pos] | null {
  const [start, end = start, ...other] = source.cell_range?.split(':') ?? []
  const from = start && cellAddress(start)
  const to = end && cellAddress(end)
  return from &&
    to &&
    !other.length &&
    from.column <= to.column &&
    from.row <= to.row
    ? [from, to]
    : null
}

function csvRow(source: Source) {
  const row = Number(
    /^row:(\d+)$/.exec(source.cell_range ?? '')?.[1] ?? source.line
  )
  return Number.isSafeInteger(row) && row > 0 ? row : null
}

const rowLimit = 100
const columnLimit = 32
function DocumentGrid({
  original,
  sources,
  zoom,
  locate,
}: {
  original: Extract<Structured, { kind: 'grid' }>
  sources: Source[]
  zoom: number
  locate: string
}) {
  const body = useRef<HTMLDivElement>(null)
  const citationSheet = sources.find((s) =>
    original.sheets.some((sht) => sht.name === s.sheet)
  )?.sheet
  const initialSheet = Math.max(
    0,
    original.sheets.findIndex((s) => s.name === citationSheet)
  )
  const [navigation, setNavigation] = useState<{
    locate: string
    sheet: number
    row?: number
    col?: number
  }>()
  const manual = navigation?.locate === locate ? navigation : undefined
  const sheetIndex = manual?.sheet ?? initialSheet
  const sheet: GridSheet = original.sheets[sheetIndex]
  const ranges = sources
    .filter((s) => s.sheet === sheet.name)
    .map(excelRange)
    .filter((value): value is [Pos, Pos] => value !== null)
  const csvRows = new Set(original.csv ? sources.map(csvRow) : [])
  const firstRow = sheet.rows.findIndex((r) =>
    original.csv
      ? csvRows.has(r.number)
      : ranges.some(([from, to]) => r.number >= from.row && r.number <= to.row)
  )
  const firstCol = sheet.columns.findIndex((c) =>
    ranges.some(([from, to]) => c >= from.column && c <= to.column)
  )
  const rowPage = manual?.row ?? Math.floor(Math.max(0, firstRow) / rowLimit)
  const colPage = manual?.col ?? Math.floor(Math.max(0, firstCol) / columnLimit)
  const rowPages = Math.ceil(sheet.rows.length / rowLimit)
  const colPages = Math.ceil(sheet.columns.length / columnLimit)
  const columns = sheet.columns.slice(
    colPage * columnLimit,
    (colPage + 1) * columnLimit
  )
  const rows = sheet.rows.slice(rowPage * rowLimit, (rowPage + 1) * rowLimit)
  useEffect(() => {
    if (!body.current) return
    const mark = body.current.querySelector('[data-original-highlight]')
    if (mark) mark.scrollIntoView({ block: 'center', inline: 'nearest' })
    else body.current.scrollTo({ top: 0, left: 0 })
  }, [locate, rowPage, colPage, sheetIndex])
  const move = (row: number, col: number) =>
    setNavigation({ locate, sheet: sheetIndex, row, col })
  return (
    <>
      {!original.csv && original.sheets.length > 0 && (
        <div className='flex shrink-0 items-center gap-2 border-b px-2 py-1'>
          <span className='text-xs text-muted-foreground'>工作表</span>
          <Select
            value={String(sheetIndex)}
            onValueChange={(value) =>
              setNavigation({ locate, sheet: Number(value) })
            }
          >
            <SelectTrigger
              aria-label='工作表'
              size='sm'
              className='max-w-[75%]'
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {original.sheets.map((s, index) => (
                  <SelectItem key={index} value={String(index)}>
                    {s.name || '未命名工作表'}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      )}
      <div
        ref={body}
        className={readerScrollClass}
        tabIndex={0}
        aria-label='原文表格'
      >
        <table
          className='w-max min-w-full border-separate border-spacing-0'
          style={{ fontSize: zoom * 0.875 + 'rem' }}
        >
          <thead className='sticky top-0 bg-muted'>
            <tr>
              <td className='border-e border-b' />
              {columns.map((column) => (
                <th
                  key={column}
                  scope='col'
                  className='border-e border-b px-3 py-1 font-medium'
                >
                  {columnName(column)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const rowSelected = csvRows.has(row.number)
              return (
                <tr
                  key={row.number}
                  data-original-highlight={rowSelected ? '' : undefined}
                  className={cn(rowSelected && highlight)}
                >
                  <th
                    scope='row'
                    className='border-e border-b px-2 py-1 text-end font-medium'
                  >
                    {row.number}
                  </th>
                  {columns.map((column) => {
                    const selected = ranges.some(
                      ([from, to]) =>
                        row.number >= from.row &&
                        row.number <= to.row &&
                        column >= from.column &&
                        column <= to.column
                    )
                    return (
                      <td
                        key={column}
                        data-original-highlight={selected ? '' : undefined}
                        className={cn(
                          'max-w-96 min-w-20 border-e border-b px-3 py-1 wrap-anywhere whitespace-pre-wrap',
                          selected && highlight
                        )}
                      >
                        {row.cells.get(column) ?? ''}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
        {!rows.length && (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>没有单元格内容</EmptyTitle>
            </EmptyHeader>
          </Empty>
        )}
      </div>
      {(rowPages > 1 || colPages > 1) && (
        <footer className='flex shrink-0 flex-wrap items-center justify-evenly gap-1 border-t px-1 py-0.5'>
          {rowPages > 1 && (
            <div className='flex items-center gap-0.5'>
              <Button
                size='icon-xs'
                variant='ghost'
                aria-label='上一组行'
                disabled={!rowPage}
                onClick={() => move(rowPage - 1, colPage)}
              >
                <ChevronLeft />
              </Button>
              <span className='text-xs text-muted-foreground'>
                行 {rows[0]?.number}–{rows.at(-1)?.number}
              </span>
              <Button
                size='icon-xs'
                variant='ghost'
                aria-label='下一组行'
                disabled={rowPage + 1 >= rowPages}
                onClick={() => move(rowPage + 1, colPage)}
              >
                <ChevronRight />
              </Button>
            </div>
          )}
          {colPages > 1 && (
            <div className='flex items-center gap-0.5'>
              <Button
                size='icon-xs'
                variant='ghost'
                aria-label='上一组列'
                disabled={!colPage}
                onClick={() => move(rowPage, colPage - 1)}
              >
                <ChevronLeft />
              </Button>
              <span className='text-xs text-muted-foreground'>
                列 {columnName(columns[0])}–{columnName(columns.at(-1)!)}
              </span>
              <Button
                size='icon-xs'
                variant='ghost'
                aria-label='下一组列'
                disabled={colPage + 1 >= colPages}
                onClick={() => move(rowPage, colPage + 1)}
              >
                <ChevronRight />
              </Button>
            </div>
          )}
        </footer>
      )}
    </>
  )
}

export function StructuredOriginal({
  bytes,
  mediaType,
  filename,
  downloadUrl,
  sources,
  zoom,
  locate,
}: {
  bytes: ArrayBuffer
  mediaType: string
  filename: string
  downloadUrl: string
  sources: Source[]
  zoom: number
  locate: string
}) {
  const result = useMemo(() => {
    try {
      return { original: readStructured(bytes, mediaType) }
    } catch (error) {
      return {
        error: error instanceof Error ? error.message : '无法读取文档结构',
      }
    }
  }, [bytes, mediaType])
  if (!result.original)
    return (
      <Empty className='flex-1'>
        <EmptyHeader>
          <EmptyTitle>无法在此处预览原件</EmptyTitle>
          <EmptyDescription>{result.error}</EmptyDescription>
        </EmptyHeader>
        <Button asChild>
          <a href={downloadUrl} download={filename}>
            <Download data-icon='inline-start' />
            下载原件
          </a>
        </Button>
      </Empty>
    )
  return result.original.kind === 'word' ? (
    <WordOriginal
      original={result.original}
      sources={sources}
      zoom={zoom}
      locate={locate}
    />
  ) : (
    <DocumentGrid
      original={result.original}
      sources={sources}
      zoom={zoom}
      locate={locate}
    />
  )
}
