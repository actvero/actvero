import { useEffect, useRef, useState } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileWarning,
  Maximize,
  Minus,
  Plus,
  ScanLine,
} from 'lucide-react'
import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
} from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
} from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { LoadingState, RequestError } from '@/components/request-state'
import { sourceBox, textSegments } from './reader-geometry'
import {
  readerFetch,
  type ReaderCredentials,
  type ReaderEvent,
} from './reader-http'
import { locationLabel } from './shared'

GlobalWorkerOptions.workerSrc = workerUrl
type Preview = Schema['DocumentPreview']
export function OriginalViewer({
  preview,
  credentials,
  onEvent,
}: {
  preview: Preview
  credentials?: ReaderCredentials
  onEvent?: (event: ReaderEvent) => void
}) {
  const [loaded, setLoaded] = useState<{
    key: string
    bytes: ArrayBuffer
    url: string
  } | null>(null)
  const [error, setError] = useState<{ key: string; cause: unknown } | null>(
    null
  )
  const key = `${preview.source_url}:${credentials?.token ?? ''}`
  const loadedEvent = useRef(onEvent)
  useEffect(() => {
    loadedEvent.current = onEvent
  }, [onEvent])
  useEffect(() => {
    const abort = new AbortController()
    let objectUrl: string | undefined
    void readerFetch(preview.source_url, credentials, abort.signal)
      .then(async (response) => {
        const bytes = await response.arrayBuffer()
        if (abort.signal.aborted) return
        objectUrl = URL.createObjectURL(
          new Blob([bytes], { type: preview.media_type })
        )
        setLoaded({ key, bytes, url: objectUrl })
        loadedEvent.current?.({
          type: 'loaded',
          documentId: preview.document_id,
        })
      })
      .catch((e: unknown) => {
        if (!abort.signal.aborted) setError({ key, cause: e })
      })
    return () => {
      abort.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
    // Credentials are represented by key; selecting another citation doesn't refetch the original.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  const current = loaded?.key === key ? loaded : null
  if (error?.key === key)
    return (
      <div className='p-6'>
        <RequestError error={error.cause} />
      </div>
    )
  if (!current) return <LoadingState />
  const download = (
    <Button size='icon' variant='ghost' asChild>
      <a href={current.url} download={preview.filename} aria-label='下载原件'>
        <Download />
      </a>
    </Button>
  )
  return (
    <section className='flex h-full min-h-0 flex-col' aria-label='原文预览'>
      {preview.media_type === 'application/pdf' ? (
        <PdfOriginal
          bytes={current.bytes}
          preview={preview}
          download={download}
          onEvent={onEvent}
        />
      ) : preview.media_type.startsWith('image/') ? (
        <ImageOriginal
          url={current.url}
          preview={preview}
          download={download}
        />
      ) : preview.media_type.startsWith('text/') ? (
        <TextOriginal
          bytes={current.bytes}
          preview={preview}
          download={download}
        />
      ) : (
        <>
          <div className='flex justify-end border-b p-2'>{download}</div>
          <Empty className='flex-1'>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <FileWarning />
              </EmptyMedia>
              <EmptyTitle>使用原应用打开此文档</EmptyTitle>
              <EmptyDescription>此格式暂不支持在线原版预览。</EmptyDescription>
            </EmptyHeader>
            <Button asChild>
              <a href={current.url} download={preview.filename}>
                <Download data-icon='inline-start' />
                下载原件
              </a>
            </Button>
          </Empty>
        </>
      )}
    </section>
  )
}

function PdfOriginal({
  bytes,
  preview,
  download,
  onEvent,
}: {
  bytes: ArrayBuffer
  preview: Preview
  download: React.ReactNode
  onEvent?: (event: ReaderEvent) => void
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const citationPage = (preview.sources ?? [])[0]?.page ?? 1
  const [navigation, setNavigation] = useState({
    citation: preview.citation_id,
    page: citationPage,
  })
  const requestedPage =
    navigation.citation === preview.citation_id ? navigation.page : citationPage
  const page = Math.max(
    1,
    Math.min(requestedPage, pdf?.numPages ?? requestedPage)
  )
  const setPage = (value: number) =>
    setNavigation({ citation: preview.citation_id, page: value })
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(640)
  const [size, setSize] = useState({ width: 640, height: 900 })
  const renderKey = `${page}:${zoom}:${width}`
  const [renderedKey, setRenderedKey] = useState('')
  const rendered = renderedKey === renderKey
  const [error, setError] = useState<unknown>(null)
  const container = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const marker = useRef<HTMLDivElement>(null)
  const onEventRef = useRef(onEvent)
  useEffect(() => {
    onEventRef.current = onEvent
  }, [onEvent])
  useEffect(() => {
    let alive = true
    const task = getDocument({
      data: bytes.slice(0),
      useWasm: false,
      cMapUrl: '/pdf-assets/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/pdf-assets/standard_fonts/',
    })
    void task.promise
      .then((doc) => {
        if (alive) {
          setPdf(doc)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (alive) setError(e)
      })
    return () => {
      alive = false
      void task.destroy()
    }
  }, [bytes, preview.document_id])
  useEffect(() => {
    const element = container.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(200, entry.contentRect.width - 48))
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    onEventRef.current?.({ type: 'page', page })
  }, [page])
  useEffect(() => {
    if (!pdf || !canvas.current) return
    let alive = true
    let cancel: (() => void) | undefined
    const selectedPage = Math.min(Math.max(page, 1), pdf.numPages)
    void pdf
      .getPage(selectedPage)
      .then(async (source) => {
        if (!alive || !canvas.current) return
        const viewport = source.getViewport({ scale: 1 })
        const scaled = source.getViewport({
          scale: (Math.min(width, 1000) / viewport.width) * zoom,
        })
        const ratio = Math.min(
          window.devicePixelRatio || 1,
          2,
          Math.sqrt(16_000_000 / (scaled.width * scaled.height))
        )
        const node = canvas.current
        node.width = Math.floor(scaled.width * ratio)
        node.height = Math.floor(scaled.height * ratio)
        setSize({ width: scaled.width, height: scaled.height })
        const task = source.render({
          canvas: node,
          viewport: scaled,
          transform: [ratio, 0, 0, ratio, 0, 0],
        })
        cancel = () => task.cancel()
        await task.promise
        if (alive) {
          setRenderedKey(renderKey)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (alive) setError(e)
      })
    return () => {
      alive = false
      cancel?.()
    }
  }, [pdf, page, zoom, width, renderKey])
  useEffect(() => {
    if (rendered)
      marker.current?.scrollIntoView({ block: 'center', inline: 'nearest' })
  }, [rendered, preview.citation_id])
  const sources = (preview.sources ?? []).filter(
    (s) => s.page === page && sourceBox(s)
  )
  const sourcePages = [
    ...new Set(
      (preview.sources ?? []).map((s) => s.page).filter((v): v is number => !!v)
    ),
  ]
  return (
    <>
      <div className='flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2'>
        <div className='flex items-center gap-1'>
          <Button
            size='icon'
            variant='ghost'
            aria-label='上一页原文'
            disabled={!pdf || page <= 1}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft />
          </Button>
          <form
            className='flex items-center gap-2'
            onSubmit={(e) => {
              e.preventDefault()
              setPage(
                Math.min(
                  pdf?.numPages ?? 1,
                  Math.max(
                    1,
                    Number(new FormData(e.currentTarget).get('page')) || 1
                  )
                )
              )
            }}
          >
            <Input
              aria-label='原文页码'
              className='h-8 w-14 text-center'
              key={page}
              name='page'
              inputMode='numeric'
              defaultValue={page}
            />
            <span className='text-sm text-muted-foreground'>
              / {pdf?.numPages ?? '—'}
            </span>
          </form>
          <Button
            size='icon'
            variant='ghost'
            aria-label='下一页原文'
            disabled={!pdf || page >= pdf.numPages}
            onClick={() => setPage(page + 1)}
          >
            <ChevronRight />
          </Button>
        </div>
        <div className='flex items-center gap-1'>
          <Button
            size='icon'
            variant='ghost'
            aria-label='缩小原文'
            disabled={zoom <= 0.5}
            onClick={() => setZoom((v) => Math.max(0.5, v - 0.25))}
          >
            <Minus />
          </Button>
          <span className='w-12 text-center text-xs'>
            {Math.round(zoom * 100)}%
          </span>
          <Button
            size='icon'
            variant='ghost'
            aria-label='放大原文'
            disabled={zoom >= 2}
            onClick={() => setZoom((v) => Math.min(2, v + 0.25))}
          >
            <Plus />
          </Button>
          <Button
            size='icon'
            variant='ghost'
            aria-label='适应宽度'
            onClick={() => setZoom(1)}
          >
            <Maximize />
          </Button>
          {download}
        </div>
      </div>
      {sourcePages.length > 1 && (
        <div className='flex flex-wrap items-center gap-2 border-b px-3 py-1'>
          <span className='text-xs text-muted-foreground'>引用位置</span>
          {sourcePages.map((p) => (
            <Button
              key={p}
              size='sm'
              variant={page === p ? 'secondary' : 'ghost'}
              onClick={() => setPage(p)}
            >
              第 {p} 页
            </Button>
          ))}
        </div>
      )}
      <div
        ref={container}
        className='min-h-0 flex-1 overflow-auto bg-muted/50 p-6'
      >
        {error != null && <RequestError error={error} />}
        <div className='relative mx-auto bg-white shadow-sm' style={size}>
          <canvas
            ref={canvas}
            style={size}
            aria-label={`${preview.filename} 第 ${page} 页`}
          />
          {!rendered && (
            <div className='absolute inset-0 bg-background/80'>
              <LoadingState />
            </div>
          )}
          {rendered &&
            sources.map((source, i) => (
              <div
                key={`${source.block_id}-${i}`}
                ref={i === 0 ? marker : undefined}
                className='pointer-events-none absolute rounded-sm border border-info/60 bg-info/15'
                style={sourceBox(source)!}
                aria-label={`原文高亮 ${locationLabel(source)}`}
              />
            ))}
        </div>
      </div>
    </>
  )
}

function ImageOriginal({
  url,
  preview,
  download,
}: {
  url: string
  preview: Preview
  download: React.ReactNode
}) {
  const marker = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)
  useEffect(() => {
    if (ready) marker.current?.scrollIntoView({ block: 'center' })
  }, [ready, preview.citation_id])
  return (
    <>
      <div className='flex items-center justify-between border-b px-3 py-2'>
        <span className='text-sm'>原件</span>
        {download}
      </div>
      <div className='min-h-0 flex-1 overflow-auto bg-muted/50 p-6'>
        <div className='relative mx-auto max-w-5xl'>
          <img
            src={url}
            alt={preview.filename}
            className='block h-auto w-full'
            onLoad={() => setReady(true)}
          />
          {ready &&
            (preview.sources ?? [])
              .filter((s) => sourceBox(s))
              .map((s, i) => (
                <div
                  key={`${s.block_id}-${i}`}
                  ref={i === 0 ? marker : undefined}
                  className='pointer-events-none absolute rounded-sm border border-info/60 bg-info/15'
                  style={sourceBox(s)!}
                  aria-label='原文高亮'
                />
              ))}
        </div>
      </div>
    </>
  )
}

function TextOriginal({
  bytes,
  preview,
  download,
}: {
  bytes: ArrayBuffer
  preview: Preview
  download: React.ReactNode
}) {
  const marker = useRef<HTMLElement>(null)
  const segments = textSegments(
    new TextDecoder().decode(bytes),
    preview.text_ranges ?? []
  )
  useEffect(() => {
    marker.current?.scrollIntoView({ block: 'center' })
  }, [preview.citation_id])
  return (
    <>
      <div className='flex items-center justify-between border-b px-3 py-2'>
        <span className='truncate text-sm text-muted-foreground'>
          {(preview.sources ?? [])[0]
            ? locationLabel((preview.sources ?? [])[0])
            : '原件'}
        </span>
        <div className='flex items-center gap-1'>
          <Button
            size='icon'
            variant='ghost'
            aria-label='定位引用'
            disabled={!(preview.text_ranges ?? []).length}
            onClick={() => marker.current?.scrollIntoView({ block: 'center' })}
          >
            <ScanLine />
          </Button>
          {download}
        </div>
      </div>
      <div className='min-h-0 flex-1 overflow-auto bg-muted/50 p-4 sm:p-6'>
        <pre className='mx-auto max-w-4xl rounded-sm border bg-background p-6 font-mono text-sm leading-7 break-words whitespace-pre-wrap sm:p-10'>
          {segments.map((segment, i) =>
            segment.highlighted ? (
              <mark
                ref={
                  i === segments.findIndex((s) => s.highlighted)
                    ? marker
                    : undefined
                }
                key={segment.start}
                className='rounded-sm bg-info/15 text-inherit outline outline-info/40'
              >
                {segment.text}
              </mark>
            ) : (
              <span key={segment.start}>{segment.text}</span>
            )
          )}
        </pre>
      </div>
    </>
  )
}
