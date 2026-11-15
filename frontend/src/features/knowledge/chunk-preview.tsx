import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import { LoadingState, RequestError } from '@/components/request-state'
import { ChunkFields } from './chunk-fields'
import { ChunkCard } from './document-reader'
import { ChunkTranscript, ReaderLayout } from './reader-layout'
import {
  chunkingError,
  useKnowledge,
  type Chunking,
  type Document,
} from './shared'
import { DocumentOriginal } from './source'

type Preview = Schema['ChunkPreviewView']

export function ChunkPreviewReader({
  baseId,
  doc,
  config,
  generation,
  onBack,
  onApplied,
}: {
  baseId: string
  doc: Document
  config: Chunking
  generation: string
  onBack: () => void
  onApplied: () => void
}) {
  const [draft, setDraft] = useState(config)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(1)
  const [transcript, setTranscript] = useState(false)
  const { key, csrf, refresh } = useKnowledge()
  const path = `/knowledge/${baseId}/documents/${doc.id}`
  const issue = chunkingError(draft)
  const body = {
    generation_id: generation,
    chunking: draft,
    page,
    query: search,
  }
  // Session identity scopes this cache; the CSRF credential must not enter cache keys.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    queryKey: [...key, path, 'chunk-preview', body],
    enabled: !issue,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      // Cancel both debounce and request when the user changes parameters again.
      await new Promise<void>((resolve, reject) => {
        const abort = () => {
          clearTimeout(timer)
          reject(new DOMException('Aborted', 'AbortError'))
        }
        const timer = setTimeout(() => {
          signal.removeEventListener('abort', abort)
          resolve()
        }, 300)
        if (signal.aborted) abort()
        else signal.addEventListener('abort', abort, { once: true })
      })
      return api<Preview>(`${path}/chunk-preview`, 'POST', body, csrf, signal)
    },
  })
  const result = !issue && !query.isError ? query.data : undefined
  const chunk =
    result?.chunks.find((item) => item.sequence === selected) ??
    result?.chunks[0]
  const lastPage = Math.max(1, Math.ceil((result?.filtered_total ?? 0) / 50))
  const apply = useMutation({
    mutationFn: async () => {
      if (!result || query.isFetching || issue)
        throw new Error('请等待当前参数的预览完成')
      return api(
        `${path}/rebuild`,
        'POST',
        {
          generation_id: generation,
          chunking: result.chunking,
          preview_token: result.preview_token,
        },
        csrf
      )
    },
    onSuccess: async () => {
      await refresh()
      toast.success('已开始重新切片，可在处理队列查看进度')
      onApplied()
    },
  })
  const update = (value: Chunking) => {
    setDraft(value)
    setPage(1)
    setSelected(1)
    setTranscript(false)
    apply.reset()
  }
  return (
    <ReaderLayout
      label='切片预览'
      original={(trailing) => (
        <DocumentOriginal
          baseId={baseId}
          documentId={doc.id}
          generationId={generation}
          highlights={{
            sources: chunk?.sources ?? [],
            text_ranges: chunk?.text_ranges ?? [],
          }}
          jump={query.dataUpdatedAt + (chunk?.sequence ?? 0)}
          toolbar={{
            filename: doc.filename,
            back: { label: '退出切片预览', action: onBack },
            trailing,
          }}
        />
      )}
      sidebar={
        <>
          <header className='flex h-12 shrink-0 items-center justify-between gap-2 border-b px-3'>
            <Button
              variant='ghost'
              size='sm'
              onClick={onBack}
              disabled={apply.isPending}
            >
              <ArrowLeft data-icon='inline-start' />
              返回切片
            </Button>
            <span className='text-xs text-muted-foreground'>
              预览 · 尚未应用
            </span>
          </header>
          {transcript && chunk ? (
            <ChunkTranscript
              sliceKey={String(chunk.sequence)}
              content={
                chunk.parent_content
                  ? `${chunk.content}\n\n—— 父片 ${chunk.parent_sequence} 上下文 ——\n\n${chunk.parent_content}`
                  : chunk.content
              }
              location={`#${chunk.sequence} · ${Array.from(chunk.content).length} 字`}
              onBack={() => setTranscript(false)}
            />
          ) : (
            <>
              <div className='min-h-0 flex-1 overflow-y-auto'>
                <fieldset
                  disabled={apply.isPending}
                  className='min-w-0 border-b p-4'
                >
                  <ChunkFields value={draft} onChange={update} />
                  <Button
                    type='button'
                    variant='ghost'
                    size='sm'
                    className='mt-2'
                    onClick={() => update(config)}
                  >
                    恢复文档参数
                  </Button>
                </fieldset>
                <div
                  className='flex flex-col gap-3 p-4'
                  aria-busy={query.isFetching}
                >
                  <div
                    role='status'
                    className='text-xs leading-6 text-muted-foreground'
                  >
                    {issue ? (
                      '请修正参数后预览'
                    ) : !result && query.isFetching ? (
                      '正在计算切片…'
                    ) : result ? (
                      <>
                        <span className='font-medium text-foreground'>
                          {result.total_chunks} 个
                          {result.parent_count ? '子片' : '切片'}
                        </span>
                        {result.parent_count > 0 && (
                          <span> · {result.parent_count} 个父片</span>
                        )}
                        <div>
                          平均 {result.average_chars} 字 · 最短{' '}
                          {result.shortest_chars} 字 · 最长{' '}
                          {result.longest_chars} 字
                        </div>
                      </>
                    ) : null}
                  </div>
                  <InputGroup>
                    <InputGroupAddon>
                      <Search />
                    </InputGroupAddon>
                    <InputGroupInput
                      aria-label='查找预览切片'
                      placeholder='搜索切片内容…'
                      value={search}
                      maxLength={200}
                      onChange={(event) => {
                        setSearch(event.target.value)
                        setPage(1)
                        setSelected(1)
                      }}
                    />
                  </InputGroup>
                  {issue ? (
                    <p className='text-sm text-destructive'>{issue.message}</p>
                  ) : query.isError ? (
                    <RequestError error={query.error} />
                  ) : !result ? (
                    <LoadingState />
                  ) : (
                    <>
                      {result.chunks.map((item) => (
                        <ChunkCard
                          key={item.sequence}
                          chunk={{ ...item, id: String(item.sequence) }}
                          parentSequence={item.parent_sequence}
                          selected={chunk?.sequence === item.sequence}
                          disabled={false}
                          onSelect={(_, open) => {
                            setSelected(item.sequence)
                            setTranscript(open)
                          }}
                        />
                      ))}
                      {!result.chunks.length && (
                        <Empty>
                          <EmptyHeader>
                            <EmptyTitle>没有匹配的切片</EmptyTitle>
                          </EmptyHeader>
                        </Empty>
                      )}
                      {lastPage > 1 && (
                        <div className='flex items-center justify-between'>
                          <Button
                            variant='ghost'
                            size='icon-sm'
                            aria-label='上一页预览切片'
                            disabled={page === 1}
                            onClick={() => setPage(page - 1)}
                          >
                            <ChevronLeft />
                          </Button>
                          <span className='text-xs text-muted-foreground'>
                            {page} / {lastPage}
                          </span>
                          <Button
                            variant='ghost'
                            size='icon-sm'
                            aria-label='下一页预览切片'
                            disabled={page >= lastPage}
                            onClick={() => setPage(page + 1)}
                          >
                            <ChevronRight />
                          </Button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </>
          )}
          <footer className='flex shrink-0 flex-col gap-2 border-t p-3'>
            {apply.isError && <RequestError error={apply.error} />}
            <Button
              disabled={
                !result?.total_chunks ||
                query.isFetching ||
                !!issue ||
                apply.isPending
              }
              onClick={() => apply.mutate()}
            >
              {apply.isPending ? '正在应用…' : '应用并重新建立索引'}
            </Button>
          </footer>
        </>
      }
    />
  )
}
