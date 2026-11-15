import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, FileText, Search } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import { LoadingState, RequestError } from '@/components/request-state'
import { ChunkPreviewReader } from './chunk-preview'
import { ChunkTranscript, ReaderLayout } from './reader-layout'
import {
  locationLabel,
  useKnowledge,
  useKnowledgeData,
  type Base,
  type Chunking,
  type Document,
} from './shared'
import { DocumentOriginal, readerDialogClass } from './source'

type Chunk = Schema['ChunkView']
const pageSize = 50

export function DocumentDialog({
  base,
  doc,
  onClose,
}: {
  base: Base
  doc: Document | null
  onClose: () => void
}) {
  return (
    <Dialog
      open={!!doc}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className={readerDialogClass}
        motion='fade'
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <DialogTitle className='sr-only'>{doc?.filename ?? '文档'}</DialogTitle>
        {doc && (
          <Reader key={doc.id} baseId={base.id} doc={doc} onClose={onClose} />
        )}
      </DialogContent>
    </Dialog>
  )
}

type Selection = {
  chunk: Chunk
  page: number
  index: number
  generation: string
}
function Reader({
  baseId,
  doc,
  onClose,
}: {
  baseId: string
  doc: Document
  onClose: () => void
}) {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [selection, setSelection] = useState<Selection>()
  const [transcript, setTranscript] = useState(false)
  const [moving, setMoving] = useState(false)
  const [error, setError] = useState<unknown>()
  const [jump, setJump] = useState(0)
  const [adjusting, setAdjusting] = useState<{
    config: Chunking
    generation: string
  }>()
  const list = useRef<HTMLDivElement>(null)
  const restore = useRef<{ id: string; scroll: boolean }>(undefined)
  const operation = useRef(0)
  const { key } = useKnowledge()
  const client = useQueryClient()
  const documentPath = `/knowledge/${baseId}/documents/${doc.id}`
  const path = (pageNumber: number, generation?: string) => {
    const p = new URLSearchParams({ page: String(pageNumber), q: search })
    if (generation) p.set('generation_id', generation)
    return `${documentPath}?${p}`
  }
  const query = useKnowledgeData<Schema['DocumentDetail']>(
    path(page),
    true,
    true
  )
  const detail = query.data
  const active =
    selection?.generation === detail?.generation_id ? selection : undefined
  const first = detail?.chunks[0]
  const selected = active?.chunk ?? first
  const lastPage = Math.max(
    1,
    Math.ceil((detail?.total_chunks ?? 0) / pageSize)
  )
  useEffect(() => {
    const target = restore.current
    if (!target || query.isPlaceholderData || transcript) return
    const button = list.current?.querySelector<HTMLElement>(
      '[aria-pressed="true"]'
    )
    if (button?.dataset.chunkId === target.id) {
      if (target.scroll) button.scrollIntoView({ block: 'nearest' })
      button.focus({ preventScroll: true })
    }
    restore.current = undefined
  }, [query.isPlaceholderData, transcript, selected?.id])

  function select(chunk: Chunk, open: boolean) {
    if (!detail?.generation_id) return
    setSelection({
      chunk,
      page,
      index: detail.chunks.findIndex((item) => item.id === chunk.id),
      generation: detail.generation_id,
    })
    setJump((value) => value + 1)
    setTranscript(open)
    setError(undefined)
  }

  function goToPage(next: number) {
    setPage(next)
    setSelection(undefined)
    list.current?.scrollTo({ top: 0 })
  }

  async function move(direction: -1 | 1) {
    if (!active || moving) return
    const id = ++operation.current
    const fetchPage = (target: number) => {
      if (
        target === page &&
        detail?.generation_id === active.generation &&
        !query.isPlaceholderData
      )
        return Promise.resolve(detail)
      const entry = path(target, active.generation)
      return client.fetchQuery({
        queryKey: [...key, entry],
        queryFn: ({ signal }) =>
          api<Schema['DocumentDetail']>(
            entry,
            'GET',
            undefined,
            undefined,
            signal
          ),
        staleTime: 15_000,
      })
    }
    setMoving(true)
    setError(undefined)
    try {
      const current = await fetchPage(active.page)
      let target = active.page
      const index = current.chunks.findIndex(
        (chunk) => chunk.id === active.chunk.id
      )
      if (index < 0) throw new Error('当前切片已变化，请返回列表重新打开')
      let position = index + direction
      let next: Chunk | undefined = current.chunks[position]
      if (!next) {
        target += direction
        if (target >= 1 && target <= lastPage) {
          const adjacent = await fetchPage(target)
          position = direction > 0 ? 0 : adjacent.chunks.length - 1
          next = adjacent.chunks[position]
        }
      }
      if (next && operation.current === id) {
        setSelection({
          chunk: next,
          page: target,
          index: position,
          generation: active.generation,
        })
        setJump((value) => value + 1)
      }
    } catch (cause) {
      if (operation.current === id) setError(cause)
    } finally {
      if (operation.current === id) setMoving(false)
    }
  }

  const isTranscript = transcript && !!active
  const offset = active ? (active.page - 1) * pageSize + active.index : 0
  const sidebar = (
    <>
      <div
        hidden={isTranscript}
        className={cn('min-h-0 flex-1 flex-col', !isTranscript && 'flex')}
      >
        <div className='flex shrink-0 flex-col gap-2 border-b px-3 py-2'>
          <div className='flex items-center gap-2'>
            <h2 className='text-sm font-semibold'>切片列表</h2>
            {detail && <Badge variant='secondary'>{detail.total_chunks}</Badge>}
            {detail?.can_manage && detail.chunking && detail.generation_id && (
              <Button
                variant='ghost'
                size='sm'
                className='ms-auto'
                onClick={() =>
                  setAdjusting({
                    config: detail.chunking!,
                    generation: detail.generation_id!,
                  })
                }
              >
                调整切片
              </Button>
            )}
          </div>
          <InputGroup>
            <InputGroupAddon>
              <Search />
            </InputGroupAddon>
            <InputGroupInput
              aria-label='查找切片'
              placeholder='搜索切片内容…'
              value={search}
              maxLength={200}
              onChange={(event) => {
                setSearch(event.target.value)
                goToPage(1)
              }}
            />
          </InputGroup>
        </div>
        <div
          ref={list}
          className='flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3'
          aria-busy={query.isFetching && query.isPlaceholderData}
        >
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError error={query.error} />
          ) : (
            <>
              {detail?.chunks.map((chunk) => (
                <ChunkCard
                  key={chunk.id}
                  chunk={chunk}
                  selected={selected?.id === chunk.id}
                  disabled={query.isPlaceholderData}
                  onSelect={select}
                />
              ))}
              {!detail?.chunks.length && (
                <Empty>
                  <EmptyHeader>
                    <EmptyMedia variant='icon'>
                      <FileText />
                    </EmptyMedia>
                    <EmptyTitle>
                      {search ? '没有匹配的切片' : '切片生成后显示在这里'}
                    </EmptyTitle>
                  </EmptyHeader>
                </Empty>
              )}
            </>
          )}
        </div>
        <footer className='flex shrink-0 items-center justify-between border-t px-3 py-1'>
          <Button
            variant='ghost'
            size='icon-sm'
            aria-label='上一页切片'
            disabled={page === 1 || query.isPlaceholderData}
            onClick={() => goToPage(page - 1)}
          >
            <ChevronLeft />
          </Button>
          <span className='text-xs text-muted-foreground'>
            {page} / {lastPage}
          </span>
          <Button
            variant='ghost'
            size='icon-sm'
            aria-label='下一页切片'
            disabled={page >= lastPage || query.isPlaceholderData}
            onClick={() => goToPage(page + 1)}
          >
            <ChevronRight />
          </Button>
        </footer>
      </div>
      {isTranscript && active && (
        <>
          {error != null && (
            <div className='px-2 py-1'>
              <RequestError error={error} />
            </div>
          )}
          <ChunkTranscript
            sliceKey={active.chunk.id}
            content={active.chunk.content}
            location={chunkLocation(active.chunk)}
            onBack={() => {
              operation.current++
              setMoving(false)
              restore.current = {
                id: active.chunk.id,
                scroll: page !== active.page,
              }
              setPage(active.page)
              setTranscript(false)
            }}
            previous={{
              disabled: moving || offset <= 0,
              action: () => void move(-1),
            }}
            next={{
              disabled: moving || offset + 1 >= (detail?.total_chunks ?? 0),
              action: () => void move(1),
            }}
          />
        </>
      )}
    </>
  )
  if (adjusting)
    return (
      <ChunkPreviewReader
        baseId={baseId}
        doc={doc}
        config={adjusting.config}
        generation={adjusting.generation}
        onBack={() => setAdjusting(undefined)}
        onApplied={onClose}
      />
    )
  return (
    <ReaderLayout
      original={(trailing) => (
        <DocumentOriginal
          baseId={baseId}
          documentId={doc.id}
          generationId={detail?.generation_id ?? doc.generation_id}
          chunkId={selected?.id}
          toolbar={{
            filename: doc.filename,
            back: { label: '返回文档列表', action: onClose },
            trailing,
          }}
          jump={jump}
        />
      )}
      sidebar={sidebar}
      label='文档切片'
    />
  )
}

function chunkLocation(chunk: Chunk) {
  return `#${chunk.sequence} · ${Array.from(chunk.content).length} 字 · ${chunk.sources[0] ? locationLabel(chunk.sources[0]) : '原文'}`
}

export function ChunkCard({
  chunk,
  selected,
  disabled,
  onSelect,
  parentSequence,
}: {
  chunk: Chunk
  selected: boolean
  disabled: boolean
  onSelect: (chunk: Chunk, open: boolean) => void
  parentSequence?: number | null
}) {
  return (
    <div
      className={cn(
        'relative shrink-0 rounded-lg border',
        selected && 'border-info/60 bg-info/5'
      )}
    >
      <button
        type='button'
        aria-label={`切片 ${chunk.sequence}`}
        aria-pressed={selected}
        data-chunk-id={chunk.id}
        disabled={disabled}
        onClick={() => onSelect(chunk, false)}
        className='flex w-full flex-col gap-2 rounded-lg p-3 text-start hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
      >
        <span
          className='max-w-full truncate pe-8 text-xs text-muted-foreground'
          title={chunkLocation(chunk)}
        >
          {chunkLocation(chunk)}
          {parentSequence != null && ` · 父片 ${parentSequence}`}
        </span>
        <span className='line-clamp-3 text-sm leading-6 wrap-anywhere whitespace-pre-wrap'>
          {chunk.content}
        </span>
      </button>
      <Button
        size='icon-xs'
        variant='ghost'
        aria-label={`查看切片 ${chunk.sequence} 正文`}
        className='absolute inset-e-2 top-1.5'
        disabled={disabled}
        onClick={() => onSelect(chunk, true)}
      >
        <ChevronRight />
      </Button>
    </div>
  )
}
