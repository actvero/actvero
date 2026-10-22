import {
  createContext,
  useContext,
  type ComponentProps,
  type ReactNode,
} from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ServerTable } from '@/components/data-table/server-table'
import { ListDiagnostic } from './list-diagnostic'
import { ChannelAvatar, HealthBadge, ManualBadge, type Channel } from './shared'

type ChannelListControls = {
  selected: Set<string>
  selectable: Channel[]
  providers: { id: string; name: string }[]
  selectAll: (checked: boolean) => void
  toggleSelected: (id: string, checked: boolean) => void
  openDetail: (channel: Channel, tab?: string) => void
  quickActions: (channel: Channel) => ReactNode
  more: (channel: Channel) => ReactNode
}
const ChannelListContext = createContext<ChannelListControls | null>(null)
function useChannelListControls() {
  const controls = useContext(ChannelListContext)
  if (!controls) throw new Error('Channel list controls are unavailable')
  return controls
}

// TanStack renders cell callbacks as React components. Keep their identities
// stable so page updates do not unmount hovered buttons or open menus.
const columns: ColumnDef<Channel>[] = [
  {
    id: 'select',
    header: function SelectAllChannels() {
      const { selected, selectable, selectAll } = useChannelListControls()
      return (
        <Checkbox
          aria-label='选择当前页'
          checked={
            selectable.length > 0 &&
            selectable.every((channel) => selected.has(channel.id))
          }
          onCheckedChange={(checked) => selectAll(checked === true)}
        />
      )
    },
    cell: function SelectChannel({ row: { original: channel } }) {
      const { selected, toggleSelected } = useChannelListControls()
      return channel.archived ? null : (
        <Checkbox
          aria-label={`选择${channel.name}`}
          checked={selected.has(channel.id)}
          onCheckedChange={(checked) =>
            toggleSelected(channel.id, checked === true)
          }
        />
      )
    },
  },
  {
    id: 'name',
    header: '渠道 / 供应商',
    cell: function ChannelName({ row: { original: channel } }) {
      const { providers, openDetail } = useChannelListControls()
      return (
        <div className='flex min-w-60 items-center gap-3'>
          <ChannelAvatar channel={channel} />
          <div className='flex min-w-0 flex-col'>
            <Button
              variant='link'
              className='h-auto max-w-64 justify-start p-0'
              onClick={() => openDetail(channel)}
            >
              <span className='truncate'>{channel.name}</span>
            </Button>
            <span className='text-xs text-muted-foreground'>
              {providers.find((item) => item.id === channel.provider)?.name ??
                channel.provider}
            </span>
          </div>
        </div>
      )
    },
  },
  {
    id: 'manual',
    header: '渠道状态',
    cell: ({ row }) => <ManualBadge channel={row.original} />,
  },
  {
    id: 'health',
    header: '绑定健康',
    cell: ({ row }) => <HealthBadge channel={row.original} />,
  },
  {
    id: 'models',
    header: '启用绑定 / 库存',
    cell: function ChannelModels({ row: { original: channel } }) {
      const { openDetail } = useChannelListControls()
      return (
        <div className='flex flex-col items-start'>
          <span>
            {Object.values(channel.health_summary?.health_counts ?? {}).reduce(
              (sum, count) => sum + count,
              0
            )}{' '}
            个绑定
          </span>
          <Button
            variant='link'
            size='sm'
            className='h-auto justify-start p-0'
            onClick={() => openDetail(channel, 'models')}
          >
            {channel.model_count} 个登记模型
          </Button>
        </div>
      )
    },
  },
  {
    id: 'diagnostic',
    header: '最近测试',
    cell: ({ row }) => <ListDiagnostic channel={row.original} />,
  },
  {
    id: 'actions',
    header: () => <span className='sr-only'>操作</span>,
    cell: function ChannelActions({ row: { original: channel } }) {
      const { quickActions, more } = useChannelListControls()
      return (
        <div className='flex items-center gap-1'>
          {quickActions(channel)}
          {more(channel)}
        </div>
      )
    },
  },
]
export function ChannelTable({
  controls,
  ...props
}: Omit<ComponentProps<typeof ServerTable<Channel>>, 'columns' | 'getRowId'> & {
  controls: ChannelListControls
}) {
  return (
    <ChannelListContext value={controls}>
      <ServerTable
        {...props}
        columns={columns}
        getRowId={(channel) => channel.id}
      />
    </ChannelListContext>
  )
}
