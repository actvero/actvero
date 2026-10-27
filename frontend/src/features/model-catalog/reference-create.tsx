import { useDeferredValue, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  PencilLine,
} from 'lucide-react'
import { api, dateTime, type Schema } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ReferenceDetail } from './reference-detail'
import { emptyReferenceFilters } from './reference-filter-values'
import { ReferenceFilterBar } from './reference-filters'
import type { ReferenceModel } from './reference-models'

export function ReferenceCreate({
  close,
  restoreFocus,
  manual,
  select,
}: {
  close: () => void
  restoreFocus?: () => void
  manual: () => void
  select: (model: ReferenceModel) => void
}) {
  const { organization } = useOrganization()
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({ ...emptyReferenceFilters })
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<ReferenceModel | null>(null)
  const [detail, setDetail] = useState(false)
  const params = new URLSearchParams({ q: search, page: String(page) })
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  const serialized = params.toString()
  const deferred = useDeferredValue(serialized)
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'reference-models',
      deferred,
    ],
    queryFn: ({ signal }) =>
      api<Schema['ReferencePage']>(
        '/llm/reference-models?' + deferred,
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  })
  const updating = query.isFetching || serialized !== deferred
  const pages = Math.max(
    1,
    Math.ceil((query.data?.total ?? 0) / (query.data?.page_size ?? 20))
  )
  function resetSelection() {
    setSelected(null)
    setDetail(false)
  }
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <SheetContent
        className='w-full gap-0 sm:max-w-6xl'
        aria-describedby={undefined}
        onCloseAutoFocus={
          restoreFocus
            ? (event) => {
                event.preventDefault()
                restoreFocus()
              }
            : undefined
        }
      >
        <SheetHeader className='shrink-0 px-4 pr-12 sm:px-6'>
          <SheetTitle>添加模型</SheetTitle>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <div>
              <h3 className='font-medium'>从公共库创建</h3>
              <p className='text-sm text-muted-foreground'>
                搜索模型并带入参数，渠道可稍后关联。
              </p>
            </div>
            <Button variant='outline' onClick={manual}>
              <PencilLine data-icon='inline-start' />
              手动创建
            </Button>
          </div>
        </SheetHeader>
        <Separator />
        <div className='flex min-h-0 flex-1 flex-col gap-4 p-4 sm:p-6'>
          <div
            className={cn(
              'max-h-[36dvh] shrink-0 overflow-y-auto',
              detail && 'hidden lg:block'
            )}
          >
            <ReferenceFilterBar
              search={search}
              setSearch={(value) => {
                setSearch(value)
                setPage(1)
                resetSelection()
              }}
              filters={filters}
              change={(value) => {
                setFilters(value)
                setPage(1)
                resetSelection()
              }}
              facets={query.data?.facets}
              preferred=''
              prioritize={false}
              setPrioritize={() => {}}
            />
          </div>
          <div className='flex shrink-0 flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground'>
            <span>models.dev · {query.data?.total ?? '—'} 条模型资料</span>
            {query.data && (
              <span>获取于 {dateTime(query.data.fetched_at)}</span>
            )}
          </div>
          {query.data?.stale && (
            <Alert>
              <AlertDescription>
                公共库暂时无法更新，当前显示缓存资料。
              </AlertDescription>
            </Alert>
          )}
          <div className='grid min-h-0 flex-1 gap-4 lg:grid-cols-2'>
            <div
              className={cn(
                'min-h-0 min-w-0 flex-col gap-3',
                detail ? 'hidden lg:flex' : 'flex'
              )}
            >
              <div
                className='min-h-0 flex-1 overflow-y-auto rounded-lg border p-2'
                aria-busy={updating}
                aria-label='公共库搜索结果'
              >
                {query.isPending ||
                query.isPlaceholderData ||
                serialized !== deferred ? (
                  <LoadingState />
                ) : query.isError ? (
                  <RequestError
                    error={query.error}
                    retry={() => void query.refetch()}
                  />
                ) : query.data.items.length === 0 ? (
                  <div
                    role='status'
                    className='flex flex-col items-start gap-3 p-4 text-sm'
                  >
                    <p>没有找到匹配的模型，可调整搜索条件或手动创建。</p>
                    <Button variant='outline' onClick={manual}>
                      改为手动创建
                    </Button>
                  </div>
                ) : (
                  <div className='flex flex-col gap-1'>
                    {query.data.items.map((model) => {
                      const active =
                        selected?.provider === model.provider &&
                        selected.model_id === model.model_id
                      return (
                        <Button
                          key={`${model.provider}/${model.model_id}`}
                          variant={active ? 'secondary' : 'ghost'}
                          aria-pressed={active}
                          className='h-auto w-full justify-start px-3 py-3 text-left whitespace-normal'
                          onClick={() => {
                            setSelected(model)
                            setDetail(true)
                          }}
                        >
                          <span className='flex w-full min-w-0 flex-col gap-2'>
                            <span className='flex items-center justify-between gap-2'>
                              <span className='truncate'>{model.name}</span>
                              {active && <Check data-icon='inline-end' />}
                            </span>
                            <span className='text-xs break-all text-muted-foreground'>
                              {model.model_id}
                            </span>
                            <span className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                              <span>{model.provider_name}</span>
                              <span>
                                上下文{' '}
                                {model.context_window?.toLocaleString() ??
                                  '未知'}
                              </span>
                              <span>
                                输出{' '}
                                {model.max_output?.toLocaleString() ?? '未知'}
                              </span>
                              {model.status === 'deprecated' && (
                                <Badge variant='outline'>已弃用</Badge>
                              )}
                            </span>
                          </span>
                        </Button>
                      )
                    })}
                  </div>
                )}
              </div>
              <div className='flex shrink-0 items-center justify-between gap-2'>
                <Button
                  variant='outline'
                  size='sm'
                  disabled={page === 1 || updating}
                  onClick={() => {
                    setPage(page - 1)
                    resetSelection()
                  }}
                >
                  <ChevronLeft data-icon='inline-start' />
                  上一页
                </Button>
                <span className='text-sm tabular-nums'>
                  {page} / {pages}
                </span>
                <Button
                  variant='outline'
                  size='sm'
                  disabled={page >= pages || updating || query.isError}
                  onClick={() => {
                    setPage(page + 1)
                    resetSelection()
                  }}
                >
                  下一页
                  <ChevronRight data-icon='inline-end' />
                </Button>
              </div>
            </div>
            <div
              className={cn(
                'min-h-0 min-w-0 overflow-y-auto rounded-lg border p-4',
                detail ? 'block' : 'hidden lg:block'
              )}
            >
              {selected ? (
                <>
                  <Button
                    variant='ghost'
                    size='sm'
                    className='mb-3 lg:hidden'
                    onClick={() => setDetail(false)}
                  >
                    <ArrowLeft data-icon='inline-start' />
                    返回搜索结果
                  </Button>
                  <ReferenceDetail
                    key={`${selected.provider}/${selected.model_id}`}
                    model={selected}
                    mode='metadata'
                  />
                </>
              ) : (
                <p className='text-sm text-muted-foreground'>
                  选择模型，查看参数与参考报价。
                </p>
              )}
            </div>
          </div>
        </div>
        <Separator />
        <SheetFooter className='shrink-0 flex-row flex-wrap items-center justify-end px-4 sm:px-6'>
          <p className='mr-auto text-xs text-muted-foreground'>
            参数可在下一步修改，收费价格单独配置。
          </p>
          <Button variant='outline' onClick={close}>
            取消
          </Button>
          <Button
            disabled={!selected || updating || query.isError}
            onClick={() => {
              if (selected && !updating && !query.isError) select(selected)
            }}
          >
            使用此模型
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
