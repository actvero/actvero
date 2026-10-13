import { useDeferredValue, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronsUpDown } from 'lucide-react'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'

type Choice = { id: string; label: string }

/** Thin paginated single-select over the existing member and model directories. */
export function DictionaryPicker({
  kind,
  value,
  onChange,
}: {
  kind: 'member' | 'model' | 'channel'
  value: string
  onChange: (id: string) => void
}) {
  const { organization, user } = useOrganization()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const q = useDeferredValue(search.trim())
  const [page, setPage] = useState(1)
  const prefix =
    kind === 'member'
      ? `/enterprises/${organization.tenant_id}/members`
      : kind === 'channel'
        ? '/llm/channels'
        : '/llm/models'
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'call-filter-dictionary',
      kind,
      prefix,
      q,
      page,
    ],
    enabled: open,
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({
        q,
        page: String(page),
        ...(kind === 'model' ? { state: 'all' } : {}),
      })
      if (kind === 'member') {
        const result = await api<Schema['MemberPage']>(
          `${prefix}?${params}`,
          'GET',
          undefined,
          undefined,
          signal
        )
        return {
          items: result.items.map(
            (item): Choice => ({
              id: item.id,
              label: item.name || item.email || item.id,
            })
          ),
          total: result.total,
        }
      }
      if (kind === 'channel') {
        const result = await api<Schema['ChannelPage']>(
          `${prefix}?${params}`,
          'GET',
          undefined,
          undefined,
          signal
        )
        return {
          items: result.items.map((item) => ({
            id: item.id,
            label: item.name,
          })),
          total: result.total,
        }
      }
      const result = await api<Schema['CatalogPage']>(
        `${prefix}?${params}`,
        'GET',
        undefined,
        undefined,
        signal
      )
      return {
        items: result.items.map(
          (item): Choice => ({
            id: item.id,
            label:
              item.slug === item.name
                ? item.name
                : `${item.name} · ${item.slug}`,
          })
        ),
        total: result.total,
      }
    },
  })
  const selected = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'call-filter-selected',
      kind,
      prefix,
      value,
    ],
    enabled: !!value,
    queryFn: async ({ signal }) => {
      if (kind === 'member') {
        const item = await api<Schema['MemberView']>(
          `${prefix}/${value}`,
          'GET',
          undefined,
          undefined,
          signal
        )
        return item.name || item.email || '已选成员'
      }
      if (kind === 'channel')
        return (
          await api<Schema['ChannelDetail']>(
            `${prefix}/${value}`,
            'GET',
            undefined,
            undefined,
            signal
          )
        ).name
      const item = await api<Schema['CatalogView']>(
        `${prefix}/${value}`,
        'GET',
        undefined,
        undefined,
        signal
      )
      return item.slug === item.name ? item.name : `${item.name} · ${item.slug}`
    },
    retry: false,
  })
  const label =
    kind === 'member' ? '成员' : kind === 'channel' ? '渠道' : '模型'
  const pages = Math.max(1, Math.ceil((query.data?.total ?? 0) / 20))
  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <Button
          type='button'
          variant='outline'
          role='combobox'
          aria-label={`筛选${label}`}
          aria-expanded={open}
          className='min-w-0 justify-between'
        >
          <span className='truncate'>
            {value ? (selected.data ?? `已选${label}`) : `全部${label}`}
          </span>
          <ChevronsUpDown aria-hidden='true' />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align='start'
        className='w-(--radix-popover-trigger-width) max-w-[calc(100vw-2rem)] min-w-64 p-3'
      >
        <div className='flex min-w-0 flex-col gap-3'>
          <Input
            aria-label={`搜索${label}`}
            placeholder={`搜索${label}名称…`}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
          />
          <ScrollArea
            viewportClassName='max-h-60'
            className='overflow-hidden'
            role='region'
            aria-label={`${label}候选`}
          >
            <div className='flex min-w-0 flex-col gap-1'>
              <Button
                type='button'
                variant='ghost'
                className='justify-start'
                onClick={() => {
                  onChange('')
                  setOpen(false)
                }}
              >
                全部{label}
              </Button>
              {query.isPending ? (
                <LoadingState />
              ) : query.isError ? (
                <RequestError
                  error={query.error}
                  retry={() => void query.refetch()}
                />
              ) : query.data.items.length ? (
                query.data.items.map((item) => (
                  <Button
                    key={item.id}
                    type='button'
                    variant={value === item.id ? 'secondary' : 'ghost'}
                    className='min-w-0 justify-start'
                    onClick={() => {
                      onChange(item.id)
                      setOpen(false)
                    }}
                  >
                    <span className='truncate'>{item.label}</span>
                  </Button>
                ))
              ) : (
                <p className='px-2 py-4 text-sm text-muted-foreground'>
                  没有匹配的{label}
                </p>
              )}
            </div>
          </ScrollArea>
          <div className='flex items-center justify-between gap-2 text-sm text-muted-foreground'>
            <span>
              第 {page} / {pages} 页
            </span>
            <div className='flex gap-1'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={page <= 1 || query.isFetching}
                onClick={() => setPage(page - 1)}
              >
                上一页
              </Button>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={page >= pages || query.isFetching}
                onClick={() => setPage(page + 1)}
              >
                下一页
              </Button>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
