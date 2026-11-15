import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import {
  ArrowLeft,
  ChevronDown,
  ChevronUp,
  PanelRightClose,
  PanelRightOpen,
  ScanLine,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

const originalMin = 320
const asideMin = 290
const handleWidth = 8

export type Toolbar = {
  filename: string
  back?: { label: string; action: () => void }
  trailing?: ReactNode
}

export function ReaderToolbar({
  toolbar,
  children,
}: {
  toolbar: Toolbar
  children?: ReactNode
}) {
  const chars = Array.from(toolbar.filename)
  const title =
    chars.length > 24 ? chars.slice(0, 23).join('') + '…' : toolbar.filename
  return (
    <header className='grid h-12 shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-1 border-b px-1.5 sm:px-2'>
      <div className='flex min-w-0 items-center'>
        {toolbar.back && (
          <Button
            variant='ghost'
            size='icon-sm'
            aria-label={toolbar.back.label}
            onClick={toolbar.back.action}
          >
            <ArrowLeft />
          </Button>
        )}
        <span className='truncate text-sm font-medium' title={toolbar.filename}>
          {title}
        </span>
      </div>
      <div className='flex min-w-0 items-center gap-0.5'>{children}</div>
      <div className='flex items-center justify-end gap-0.5'>
        {toolbar.trailing}
      </div>
    </header>
  )
}

export function ReaderLayout({
  original,
  sidebar,
  label,
  initialOpen = true,
  toggleLabel = '切片',
  tools,
}: {
  original: (trailing: ReactNode) => ReactNode
  sidebar?: ReactNode
  label: string
  initialOpen?: boolean
  toggleLabel?: string
  tools?: ReactNode
}) {
  const id = useId()
  const root = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [open, setOpen] = useState(initialOpen)
  const [portion, setPortion] = useState(0.65)
  const [dragging, setDragging] = useState(false)
  const start = useRef<{ x: number; original: number } | null>(null)
  const wide = width >= 720
  const split = Boolean(sidebar) && open
  const maximum = Math.max(originalMin, width - asideMin - handleWidth)
  const originalWidth = Math.round(
    Math.min(maximum, Math.max(originalMin, width * portion))
  )
  const move = (px: number) =>
    setPortion(Math.max(originalMin, Math.min(maximum, px)) / width)

  useEffect(() => {
    const node = root.current
    if (!node) return
    const resize = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width)
    )
    resize.observe(node)
    return () => resize.disconnect()
  }, [])

  return (
    <div
      ref={root}
      className='grid min-h-0 min-w-0 flex-1 overflow-hidden'
      style={{
        gridTemplateColumns:
          wide && split
            ? `${originalWidth}px ${handleWidth}px minmax(0,1fr)`
            : 'minmax(0,1fr)',
        gridTemplateRows:
          !wide && split ? 'minmax(0,1fr) minmax(0,1fr)' : 'minmax(0,1fr)',
      }}
    >
      <div className='@container min-h-0 min-w-0'>
        {original(
          <>
            {sidebar && (
              <Button
                size='icon-sm'
                variant='ghost'
                aria-label={`${open ? '收起' : '展开'}${toggleLabel}`}
                title={`${open ? '收起' : '展开'}${toggleLabel}`}
                aria-controls={id}
                aria-expanded={open}
                onClick={() => setOpen((value) => !value)}
              >
                {open ? <PanelRightClose /> : <PanelRightOpen />}
              </Button>
            )}
            {tools}
          </>
        )}
      </div>
      {wide && split && (
        <div
          role='separator'
          tabIndex={0}
          aria-label='调整原文和切片宽度'
          aria-orientation='vertical'
          aria-controls={id}
          aria-valuemin={originalMin}
          aria-valuemax={maximum}
          aria-valuenow={originalWidth}
          aria-valuetext={`原文宽度 ${originalWidth} 像素`}
          className={cn(
            'cursor-col-resize touch-none border-s bg-muted/30 hover:bg-ring/35 focus-visible:bg-ring/35 focus-visible:outline-none',
            dragging && 'bg-ring/55'
          )}
          onPointerDown={(event) => {
            if (event.button !== 0) return
            event.currentTarget.focus()
            event.currentTarget.setPointerCapture(event.pointerId)
            start.current = { x: event.clientX, original: originalWidth }
            setDragging(true)
          }}
          onPointerMove={(event) => {
            if (start.current)
              move(start.current.original + event.clientX - start.current.x)
          }}
          onLostPointerCapture={() => {
            start.current = null
            setDragging(false)
          }}
          onKeyDown={(event) => {
            const value =
              event.key === 'ArrowLeft'
                ? originalWidth - 16
                : event.key === 'ArrowRight'
                  ? originalWidth + 16
                  : event.key === 'Home'
                    ? originalMin
                    : event.key === 'End'
                      ? maximum
                      : null
            if (value === null) return
            event.preventDefault()
            move(value)
          }}
        />
      )}
      {sidebar && (
        <aside
          id={id}
          hidden={!open}
          aria-label={label}
          className={cn(
            'min-h-0 min-w-0 flex-col overflow-hidden',
            open && 'flex',
            !wide && 'border-t'
          )}
        >
          {sidebar}
        </aside>
      )}
    </div>
  )
}

export function ChunkTranscript({
  content,
  sliceKey,
  location,
  onBack,
  onLocate,
  previous,
  next,
}: {
  content: string
  sliceKey?: string
  location?: string
  onBack?: () => void
  onLocate?: () => void
  previous?: { disabled: boolean; action: () => void }
  next?: { disabled: boolean; action: () => void }
}) {
  return (
    <>
      <header className='flex h-12 shrink-0 items-center justify-between gap-1 border-b px-2'>
        {onBack ? (
          <Button variant='ghost' size='sm' onClick={onBack}>
            <ArrowLeft data-icon='inline-start' />
            切片列表
          </Button>
        ) : (
          <h2 className='px-2 text-sm font-semibold'>切片正文</h2>
        )}
        {previous && next && (
          <div className='flex items-center gap-1'>
            <Button
              size='icon-sm'
              variant='ghost'
              aria-label='上一切片'
              disabled={previous.disabled}
              onClick={previous.action}
            >
              <ChevronUp />
            </Button>
            <Button
              size='icon-sm'
              variant='ghost'
              aria-label='下一切片'
              disabled={next.disabled}
              onClick={next.action}
            >
              <ChevronDown />
            </Button>
          </div>
        )}
        {onLocate && (
          <Button
            size='icon-sm'
            variant='ghost'
            aria-label='定位引用'
            title='定位引用'
            onClick={onLocate}
          >
            <ScanLine />
          </Button>
        )}
      </header>
      <div
        key={sliceKey}
        className='min-h-0 flex-1 overflow-auto p-4'
        tabIndex={0}
        aria-label='切片全文'
      >
        {location && (
          <p className='mb-3 text-xs text-muted-foreground'>{location}</p>
        )}
        <div className='text-sm leading-7 wrap-anywhere whitespace-pre-wrap'>
          {content}
        </div>
      </div>
    </>
  )
}
