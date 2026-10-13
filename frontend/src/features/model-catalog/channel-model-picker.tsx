import { useDeferredValue, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'

export type ChannelModelSource = {
  channel: Schema['ChannelDetail']
  upstream: string
}

export function ChannelPicker({
  disabled = false,
  onClear,
  children,
}: {
  disabled?: boolean
  onClear?: () => void
  children: (channel: Schema['ChannelDetail']) => ReactNode
}) {
  const { organization } = useOrganization()
  const [search, setSearch] = useState('')
  const q = useDeferredValue(search)
  const [page, setPage] = useState(1)
  const [channel, setChannel] = useState('')
  const prefix = ['organization', organization.tenant_id, 'model-channels']
  const params = new URLSearchParams({
    q,
    state: 'current',
    page: String(page),
  }).toString()
  const channels = useQuery({
    queryKey: [...prefix, 'list', params],
    queryFn: ({ signal }) =>
      api<Schema['ChannelPage']>(
        '/llm/channels?' + params,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const detail = useQuery({
    queryKey: [...prefix, channel],
    enabled: !!channel,
    queryFn: ({ signal }) =>
      api<Schema['ChannelDetail']>(
        '/llm/channels/' + channel,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return (
    <div className='flex flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='channel-search'>搜索渠道</Label>
        <Input
          disabled={disabled}
          id='channel-search'
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
            setChannel('')
            onClear?.()
          }}
          placeholder='渠道名称或地址'
        />
      </div>
      {channels.isPending ? (
        <LoadingState />
      ) : channels.isError ? (
        <RequestError
          error={channels.error}
          retry={() => void channels.refetch()}
        />
      ) : (
        <>
          <div className='flex flex-col gap-2'>
            <Label htmlFor='mapping-channel'>渠道</Label>
            <Select
              value={channel}
              disabled={disabled}
              onValueChange={(id) => {
                setChannel(id)
                onClear?.()
              }}
            >
              <SelectTrigger id='mapping-channel' className='w-full'>
                <SelectValue placeholder='选择渠道' />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {channels.data.items.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          {channels.data.total === 0 && (
            <p className='text-sm text-muted-foreground'>
              {q ? '没有匹配渠道。' : '请先添加渠道并登记模型。'}
            </p>
          )}
          {channels.data.total > 20 && (
            <div className='flex items-center justify-between gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={disabled || page === 1}
                onClick={() => {
                  setPage(page - 1)
                  setChannel('')
                  onClear?.()
                }}
              >
                上一页渠道
              </Button>
              <span className='text-sm'>第 {page} 页</span>
              <Button
                type='button'
                variant='outline'
                size='sm'
                disabled={disabled || page * 20 >= channels.data.total}
                onClick={() => {
                  setPage(page + 1)
                  setChannel('')
                  onClear?.()
                }}
              >
                下一页渠道
              </Button>
            </div>
          )}
        </>
      )}
      {channel &&
        (detail.isPending || detail.isFetching ? (
          <LoadingState />
        ) : detail.isError ? (
          <RequestError
            error={detail.error}
            retry={() => void detail.refetch()}
          />
        ) : (
          children(detail.data)
        ))}
    </div>
  )
}

export function ChannelModelPicker({
  disabled = false,
  onChange,
}: {
  disabled?: boolean
  onChange: (source: ChannelModelSource | null) => void
}) {
  return (
    <ChannelPicker disabled={disabled} onClear={() => onChange(null)}>
      {(channel) => (
        <RegisteredModelPicker
          key={channel.id + ':' + channel.version}
          channel={channel}
          disabled={disabled}
          onChange={onChange}
        />
      )}
    </ChannelPicker>
  )
}
function RegisteredModelPicker({
  channel,
  disabled,
  onChange,
}: {
  channel: Schema['ChannelDetail']
  disabled: boolean
  onChange: (source: ChannelModelSource | null) => void
}) {
  const [upstream, setUpstream] = useState('')
  const [modelSearch, setModelSearch] = useState('')
  return (
    <>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='upstream-search'>搜索上游模型</Label>
        <Input
          disabled={disabled}
          id='upstream-search'
          value={modelSearch}
          onChange={(e) => setModelSearch(e.target.value)}
          placeholder='模型 ID'
        />
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='mapping-model'>上游模型</Label>
        <Select
          value={upstream}
          disabled={disabled}
          onValueChange={(id) => {
            setUpstream(id)
            onChange({ channel: channel, upstream: id })
          }}
        >
          <SelectTrigger id='mapping-model' className='w-full'>
            <SelectValue placeholder='选择已登记模型' />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {channel.models
                .filter(
                  (m) =>
                    m.id.toLowerCase().includes(modelSearch.toLowerCase()) ||
                    m.id === upstream
                )
                .map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.id}
                  </SelectItem>
                ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      {!channel.models.length && (
        <p role='status' className='text-sm text-muted-foreground'>
          此渠道还没有登记模型，请先在渠道库存中添加。
        </p>
      )}
      {!!channel.models.length &&
        !channel.models.some((model) =>
          model.id.toLowerCase().includes(modelSearch.toLowerCase())
        ) && (
          <p role='status' className='text-sm text-muted-foreground'>
            没有匹配的上游模型。
          </p>
        )}
    </>
  )
}
