import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileWarning,
  Minus,
  Plus,
} from 'lucide-react'
import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
} from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
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
import { ReaderToolbar, type Toolbar } from './reader-layout'
import { locationLabel } from './shared'
import { StructuredOriginal, readerScrollClass } from './structured-original'
import { docxType, xlsxType } from './structured-original-data'

GlobalWorkerOptions.workerSrc = workerUrl
type Preview = Schema['DocumentPreview']

export function OriginalViewer({
  preview,
  credentials,
  onEvent,
  onReadError,
  toolbar = { filename: preview.filename },
  jump = 0,
}: {
  preview: Preview
  credentials?: ReaderCredentials
  onEvent?: (event: ReaderEvent) => void
  onReadError?: (cause: unknown) => void
  toolbar?: Toolbar
  jump?: number
}) {
  const token = credentials?.token
  const parentOrigin = credentials?.parentOrigin
  // Location changes never download the immutable original again.
  const source = `${preview.document_id}:${preview.source_url}`
  return (
    <OriginalFile
      key={source}
      preview={preview}
      token={token}
      parentOrigin={parentOrigin}
      onEvent={onEvent}
      onReadError={onReadError}
      toolbar={toolbar}
      jump={jump}
    />
  )
}

function OriginalFile({
  preview,
  token,
  parentOrigin,
  onEvent,
  onReadError,
  toolbar,
  jump,
}: {
  preview: Preview
  token?: string
  parentOrigin?: string
  onEvent?: (event: ReaderEvent) => void
  onReadError?: (cause: unknown) => void
  toolbar: Toolbar
  jump: number
}) {
  const [loaded, setLoaded] = useState<{ bytes: ArrayBuffer; url: string }>()
  const [error, setError] = useState<unknown>()
  const [zoom, setZoom] = useState(1)
  const { document_id: docId, source_url: url, media_type: mediaType } = preview
  const locate = `${preview.generation_id}:${preview.citation_id}:${jump}`
  const loadedEvent = useRef(onEvent)
  const readError = useRef(onReadError)
  useEffect(() => {
    loadedEvent.current = onEvent
    readError.current = onReadError
  }, [onEvent, onReadError])
  useEffect(() => {
    const abort = new AbortController()
    let objectUrl: string | undefined
    const credentials =
      token && parentOrigin ? { token, parentOrigin } : undefined
    void readerFetch(url, credentials, abort.signal)
      .then(async (response) => {
        const bytes = await response.arrayBuffer()
        if (abort.signal.aborted) return
        objectUrl = URL.createObjectURL(new Blob([bytes], { type: mediaType }))
        setLoaded({ bytes, url: objectUrl })
        loadedEvent.current?.({ type: 'loaded', documentId: docId })
      })
      .catch((cause: unknown) => {
        if (!abort.signal.aborted) {
          setError(cause)
          readError.current?.(cause)
        }
      })
    return () => {
      abort.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [docId, url, mediaType, token, parentOrigin])

  const zoomControls = (
    <div className='flex items-center gap-0.5' aria-label='缩放'>
      <Button
        size='icon-xs'
        variant='ghost'
        aria-label='缩小原文'
        disabled={zoom <= 0.5}
        onClick={() => setZoom((v) => Math.max(0.5, v - 0.25))}
      >
        <Minus />
      </Button>
      <Button
        size='xs'
        variant='ghost'
        className='px-0.5'
        aria-label='适应宽度'
        title='重置缩放'
        onClick={() => setZoom(1)}
      >
        {Math.round(zoom * 100)}%
      </Button>
      <Button
        size='icon-xs'
        variant='ghost'
        aria-label='放大原文'
        disabled={zoom >= 2}
        onClick={() => setZoom((v) => Math.min(2, v + 0.25))}
      >
        <Plus />
      </Button>
    </div>
  )
  const pdf = mediaType === 'application/pdf'
  const image = mediaType === 'image/png' || mediaType === 'image/jpeg'
  const text = mediaType === 'text/plain' || mediaType === 'text/markdown'
  const structured =
    mediaType === 'text/csv' || mediaType === docxType || mediaType === xlsxType
  return (
    <section
      className='@container flex h-full min-h-0 flex-col'
      aria-label='原文预览'
    >
      {loaded && pdf && !error ? (
        <PdfOriginal
          bytes={loaded.bytes}
          preview={preview}
          toolbar={toolbar}
          onEvent={onEvent}
          locate={locate}
          zoom={zoom}
          zoomControls={zoomControls}
        />
      ) : (
        <>
          <ReaderToolbar toolbar={toolbar}>
            {loaded && (image || text || structured) ? zoomControls : null}
          </ReaderToolbar>
          {error != null ? (
            <div className='p-6'>
              <RequestError error={error} />
            </div>
          ) : !loaded ? (
            <LoadingState />
          ) : image ? (
            <ImageOriginal
              url={loaded.url}
              preview={preview}
              zoom={zoom}
              locate={locate}
            />
          ) : structured ? (
            <StructuredOriginal
              bytes={loaded.bytes}
              mediaType={mediaType}
              filename={preview.filename}
              downloadUrl={loaded.url}
              sources={preview.sources ?? []}
              zoom={zoom}
              locate={locate}
            />
          ) : text ? (
            <TextOriginal
              bytes={loaded.bytes}
              preview={preview}
              zoom={zoom}
              locate={locate}
            />
          ) : (
            <Empty className='flex-1'>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  <FileWarning />
                </EmptyMedia>
                <EmptyTitle>使用原应用打开此文档</EmptyTitle>
                <EmptyDescription>此格式暂不支持在线预览。</EmptyDescription>
              </EmptyHeader>
              <Button asChild>
                <a href={loaded.url} download={preview.filename}>
                  <Download data-icon='inline-start' />
                  下载原件
                </a>
              </Button>
            </Empty>
          )}
        </>
      )}
    </section>
  )
}

function PdfOriginal({
  bytes,
  preview,
  toolbar,
  locate,
  zoom,
  zoomControls,
  onEvent,
}: {
  bytes: ArrayBuffer
  preview: Preview
  toolbar: Toolbar
  locate: string
  zoom: number
  zoomControls: React.ReactNode
  onEvent?: (event: ReaderEvent) => void
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const citationPage =
    preview.sources?.find(
      (source) =>
        Number.isInteger(source.page) &&
        source.page! > 0 &&
        (!pdf || source.page! <= pdf.numPages)
    )?.page ?? 1
  const [navigation, setNavigation] = useState<{
    citation: string
    page: number
  }>()
  const requestedPage =
    navigation?.citation === locate ? navigation.page : citationPage
  const page = Math.max(
    1,
    Math.min(requestedPage, pdf?.numPages ?? requestedPage)
  )
  const setPage = (value: number) =>
    setNavigation({ citation: locate, page: value })
  const [width, setWidth] = useState(640)
  const [size, setSize] = useState({ width: 640, height: 900 })
  const scroll = useRef({ width: 640, height: 900, left: 0, top: 0 })
  const renderKey = `${page}:${zoom}:${width}`
  const [renderedKey, setRenderedKey] = useState('')
  const rendered = renderedKey === renderKey
  const [error, setError] = useState<unknown>(null)
  const container = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const marker = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const before = scroll.current
    const node = container.current
    if (!node) return
    node.scrollTo({
      left: (before.left * size.width) / before.width,
      top: (before.top * size.height) / before.height,
    })
    scroll.current = { ...size, top: node.scrollTop, left: node.scrollLeft }
  }, [size])
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
      setWidth(Math.max(200, entry.contentRect.width))
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (pdf) onEventRef.current?.({ type: 'page', page })
  }, [pdf, page])
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
  const lastPosition = useRef('')
  useEffect(() => {
    const position = `${locate}:${page}`
    if (!rendered || lastPosition.current === position) return
    lastPosition.current = position
    if (marker.current)
      marker.current.scrollIntoView({ block: 'center', inline: 'nearest' })
    else container.current?.scrollTo({ top: 0, left: 0 })
  }, [rendered, locate, page])
  const sources = (preview.sources ?? []).filter(
    (s) => s.page === page && sourceBox(s)
  )
  return (
    <>
      <ReaderToolbar toolbar={toolbar}>
        <Button
          className='hidden @sm:inline-flex'
          size='icon-xs'
          variant='ghost'
          aria-label='上一页原文'
          disabled={!pdf || page <= 1}
          onClick={() => setPage(page - 1)}
        >
          <ChevronLeft />
        </Button>
        <form
          className='flex items-center gap-0.5 @sm:gap-1'
          onSubmit={(e) => {
            e.preventDefault()
            setPage(
              Math.min(
                pdf?.numPages ?? 1,
                Math.max(
                  1,
                  Math.trunc(
                    Number(new FormData(e.currentTarget).get('page'))
                  ) || 1
                )
              )
            )
          }}
        >
          <Input
            aria-label='原文页码'
            className='h-7 w-10 px-1 text-center @sm:w-14'
            key={page}
            name='page'
            inputMode='numeric'
            defaultValue={page}
          />
          <span className='text-xs whitespace-nowrap text-muted-foreground'>
            / {pdf?.numPages ?? '—'}
          </span>
        </form>
        <Button
          className='hidden @sm:inline-flex'
          size='icon-xs'
          variant='ghost'
          aria-label='下一页原文'
          disabled={!pdf || page >= pdf.numPages}
          onClick={() => setPage(page + 1)}
        >
          <ChevronRight />
        </Button>
        {zoomControls}
      </ReaderToolbar>
      <div
        ref={container}
        className={cn(readerScrollClass, 'bg-muted/50')}
        aria-label='原文阅读区'
        tabIndex={0}
        onScroll={(event) => {
          scroll.current.top = event.currentTarget.scrollTop
          scroll.current.left = event.currentTarget.scrollLeft
        }}
      >
        {error != null && <RequestError error={error} />}
        <div className='relative mx-auto bg-white shadow-sm' style={size}>
          <canvas
            ref={canvas}
            style={size}
            aria-label={`${preview.filename} 第 ${page} 页`}
          />
          {error == null && !rendered && (
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
  zoom,
  locate,
}: {
  url: string
  preview: Preview
  zoom: number
  locate: string
}) {
  const marker = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (ready)
      marker.current?.scrollIntoView({ block: 'center', inline: 'nearest' })
  }, [ready, locate])
  return (
    <div
      className={cn(readerScrollClass, 'bg-muted/50')}
      tabIndex={0}
      aria-label='原图阅读区'
    >
      {failed ? (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>无法打开这张图片</EmptyTitle>
          </EmptyHeader>
        </Empty>
      ) : (
        <div
          className='relative mx-auto'
          style={{ width: zoom * 100 + '%', maxWidth: zoom * 1024 }}
        >
          <img
            src={url}
            alt={preview.filename}
            className='block h-auto w-full'
            onLoad={() => setReady(true)}
            onError={() => setFailed(true)}
          />
          {ready &&
            (preview.sources ?? [])
              .filter((s) => (!s.page || s.page === 1) && sourceBox(s))
              .map((source, index) => (
                <div
                  key={`${source.block_id}-${index}`}
                  ref={index === 0 ? marker : undefined}
                  className='pointer-events-none absolute rounded-sm border border-info/60 bg-info/15'
                  style={sourceBox(source)!}
                  aria-label='原文高亮'
                />
              ))}
        </div>
      )}
    </div>
  )
}

function TextOriginal({
  bytes,
  preview,
  zoom,
  locate,
}: {
  bytes: ArrayBuffer
  preview: Preview
  zoom: number
  locate: string
}) {
  const root = useRef<HTMLDivElement>(null)
  const text = useMemo(() => new TextDecoder().decode(bytes), [bytes])
  const ranges = preview.text_ranges
  const segments = useMemo(
    () => textSegments(text, ranges ?? []),
    [text, ranges]
  )
  useEffect(() => {
    root.current
      ?.querySelector('mark')
      ?.scrollIntoView({ block: 'center', inline: 'nearest' })
  }, [locate])
  return (
    <div
      className={readerScrollClass}
      ref={root}
      tabIndex={0}
      aria-label='原文阅读区'
    >
      <pre
        className='mx-auto max-w-5xl p-4 font-mono leading-relaxed wrap-anywhere whitespace-pre-wrap sm:p-6'
        style={{ fontSize: zoom * 0.875 + 'rem' }}
      >
        {segments.map((segment) =>
          segment.highlighted ? (
            <mark
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
  )
}
