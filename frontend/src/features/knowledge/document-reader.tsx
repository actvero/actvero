import { useState } from 'react'
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FileText,
  PanelRightClose,
  PanelRightOpen,
  Search,
  X,
} from 'lucide-react'
import type { Schema } from '@/lib/api'
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
import { State } from './controls'
import {
  locationLabel,
  useKnowledgeData,
  type Base,
  type Document,
} from './shared'
import { DocumentOriginal, readerDialogClass } from './source'

export function DocumentDialog({
  base,
  doc,
  onClose,
}: {
  base: Base
  doc: Document | null
  onClose: () => void
}) {
  const [showChunks, setShowChunks] = useState(true)
  return (
    <Dialog
      open={!!doc}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className={readerDialogClass}
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <header className='flex h-16 shrink-0 items-center gap-3 border-b px-4'>
          <Button
            size='icon'
            variant='ghost'
            aria-label='返回文档列表'
            onClick={onClose}
          >
            <ArrowLeft />
          </Button>
          <DialogTitle className='min-w-0 truncate'>
            {doc?.filename ?? '文档'}
          </DialogTitle>
          <span className='hidden truncate text-sm text-muted-foreground sm:block'>
            {base.name}
          </span>
          <div className='ms-auto flex items-center gap-2'>
            {doc && <State value={doc.status} />}
            <Button
              size='icon'
              variant='outline'
              aria-label={showChunks ? '收起切片' : '展开切片'}
              onClick={() => setShowChunks((v) => !v)}
            >
              {showChunks ? <PanelRightClose /> : <PanelRightOpen />}
            </Button>

            <Button
              size='icon'
              variant='ghost'
              aria-label='关闭文档'
              onClick={onClose}
            >
              <X />
            </Button>
          </div>
        </header>
        {doc && (
          <Reader key={doc.id} base={base} doc={doc} showChunks={showChunks} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function Reader({
  base,
  doc,
  showChunks,
}: {
  base: Base
  doc: Document
  showChunks: boolean
}) {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string>()
  const query = useKnowledgeData<Schema['DocumentDetail']>(
    `/knowledge/${base.id}/documents/${doc.id}?page=${page}&q=${encodeURIComponent(search)}`,
    true,
    true
  )
  if (query.isPending) return <LoadingState />
  if (query.isError) return <RequestError error={query.error} />
  const detail = query.data
  const selected =
    detail.chunks.find((c) => c.id === selectedId) ?? detail.chunks[0]
  return (
    <div className='relative flex min-h-0 flex-1 flex-col md:flex-row'>
      <div
        className={cn(
          'min-h-0 min-w-0 flex-1',
          showChunks && 'h-1/2 md:h-auto'
        )}
      >
        <DocumentOriginal
          baseId={base.id}
          documentId={doc.id}
          generationId={detail.generation_id}
          chunkId={selected?.id}
        />
      </div>
      {showChunks && (
        <aside
          className='flex h-1/2 min-h-0 flex-col border-t md:h-auto md:w-[38%] md:min-w-80 md:border-s md:border-t-0'
          aria-label='文档切片'
        >
          <div className='flex flex-col gap-3 border-b p-4'>
            <div className='flex items-center gap-2'>
              <h2 className='font-semibold'>切片</h2>
              <Badge variant='secondary'>{detail.total_chunks}</Badge>
            </div>
            <InputGroup>
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
              <InputGroupInput
                aria-label='查找切片'
                placeholder='搜索切片内容…'
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value)
                  setPage(1)
                  setSelectedId(undefined)
                }}
              />
            </InputGroup>
          </div>
          <div className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4'>
            {detail.chunks.map((chunk) => (
              <ChunkCard
                key={chunk.id}
                chunk={chunk}
                selected={selected?.id === chunk.id}
                onSelect={() => setSelectedId(chunk.id)}
              />
            ))}
            {!detail.chunks.length && (
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
          </div>
          <footer className='flex items-center justify-between border-t px-4 py-3'>
            <Button
              variant='ghost'
              size='icon'
              aria-label='上一页切片'
              disabled={page === 1}
              onClick={() => {
                setPage((v) => v - 1)
                setSelectedId(undefined)
              }}
            >
              <ChevronLeft />
            </Button>
            <span className='text-xs text-muted-foreground'>
              {page} / {Math.max(1, Math.ceil(detail.total_chunks / 50))}
            </span>
            <Button
              variant='ghost'
              size='icon'
              aria-label='下一页切片'
              disabled={page * 50 >= detail.total_chunks}
              onClick={() => {
                setPage((v) => v + 1)
                setSelectedId(undefined)
              }}
            >
              <ChevronRight />
            </Button>
          </footer>
        </aside>
      )}
    </div>
  )
}

function ChunkCard({
  chunk,
  selected,
  onSelect,
}: {
  chunk: Schema['ChunkView']
  selected: boolean
  onSelect: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const length = Array.from(chunk.content).length
  const long = length > 300 || chunk.content.split('\n').length > 6
  return (
    <div
      className={cn(
        'shrink-0 rounded-lg border transition-colors',
        selected && 'border-info/60 bg-info/5'
      )}
    >
      <button
        type='button'
        aria-label={`切片 ${chunk.sequence}`}
        aria-pressed={selected}
        onClick={onSelect}
        className='flex w-full flex-col gap-3 rounded-lg p-4 text-start hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'
      >
        <span className='text-xs text-muted-foreground'>
          #{chunk.sequence} ·{' '}
          {chunk.sources[0] ? locationLabel(chunk.sources[0]) : '原文'}
        </span>
        <span
          className={cn(
            'text-sm leading-7 break-words whitespace-pre-wrap',
            long && !expanded && 'line-clamp-6'
          )}
        >
          {chunk.content}
        </span>
        <span className='flex w-full items-center justify-between text-xs text-muted-foreground'>
          <span>{length} 字符</span>
          {selected && <span className='text-info'>当前切片</span>}
        </span>
      </button>
      {long && (
        <Button
          variant='ghost'
          size='sm'
          className='mx-2 mb-2'
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? '收起全文' : '展开全文'}
        </Button>
      )}
    </div>
  )
}
