import { useContext, useEffect, useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button as NativeButton } from '@/vendor/newapi/components/ui/button'
import { ChannelRowActionsLayoutContext } from '@/vendor/newapi/features/channels/components/channel-row-actions-context'
import { NumericSpinnerInput } from '@/vendor/newapi/features/channels/components/numeric-spinner-input'
import { createChannelFieldUpdateScheduler } from '@/vendor/newapi/features/channels/lib/channel-field-update'
import {
  Gauge,
  PlugZap,
  Pencil,
  Power,
  PowerOff,
  Ellipsis,
  Loader2,
  Trash2,
  Server,
} from 'lucide-react'
import { toast } from 'sonner'
import { messageOf } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useOrganization } from '@/features/auth/session'
import { gateway, useGatewayRefresh, type Channel } from './api'
import { useChannelTable } from './channel-table-context'

function RowAction({
  label,
  children,
  ...props
}: { label: string; children: React.ReactNode } & React.ComponentProps<
  typeof NativeButton
>) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <NativeButton
          variant='ghost'
          size='icon-sm'
          aria-label={label}
          {...props}
        >
          {children}
        </NativeButton>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

export function RowActions({ channel }: { channel: Channel }) {
  const { actions } = useChannelTable()
  const card = useContext(ChannelRowActionsLayoutContext) === 'card'
  const enabled = channel.status === 1
  return (
    <div className='-ms-1.5 flex shrink-0 items-center gap-1'>
      {!card && (
        <RowAction label='编辑' onClick={() => actions.onEdit(channel)}>
          <Pencil />
        </RowAction>
      )}
      <RowAction
        label='测试连接'
        disabled={actions.testingId === channel.id}
        onClick={() => actions.onQuickTest(channel)}
      >
        {actions.testingId === channel.id ? (
          <Loader2 className='animate-spin' />
        ) : (
          <Gauge />
        )}
      </RowAction>
      {card && (
        <RowAction label='测试渠道连接' onClick={() => actions.onTest(channel)}>
          <PlugZap />
        </RowAction>
      )}
      <RowAction
        label={`${enabled ? '禁用' : '启用'} ${channel.name}`}
        disabled={actions.pendingId === channel.id}
        className={
          enabled
            ? 'text-destructive hover:text-destructive'
            : 'text-success hover:text-success'
        }
        onClick={() => actions.onStatus(channel)}
      >
        {actions.pendingId === channel.id ? (
          <Loader2 className='animate-spin' />
        ) : enabled ? (
          <PowerOff />
        ) : (
          <Power />
        )}
      </RowAction>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <NativeButton
            variant='ghost'
            size='icon-sm'
            aria-label={`${channel.name} 打开菜单`}
          >
            <Ellipsis />
          </NativeButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end'>
          <DropdownMenuGroup>
            {card && (
              <DropdownMenuItem onSelect={() => actions.onEdit(channel)}>
                <Pencil />
                编辑
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onSelect={() => actions.onTest(channel)}>
              <PlugZap />
              测试渠道连接
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => actions.onModels(channel)}>
              <Server />
              查看支持的模型
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem
              variant='destructive'
              onSelect={() => actions.onDelete(channel)}
            >
              <Trash2 />
              删除渠道
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export function ChannelFieldCell({
  channel,
  field,
}: {
  channel: Channel
  field: 'priority' | 'weight'
}) {
  const { csrf } = useOrganization()
  const refresh = useGatewayRefresh()
  const [epoch, setEpoch] = useState(0)
  const save = useMutation({
    mutationFn: (value: number) =>
      gateway(
        `/channels/${channel.id}/fields`,
        'PATCH',
        { [field]: value },
        csrf
      ),
    onSuccess: async () => {
      await refresh()
      setEpoch((value) => value + 1)
    },
    onError: async (error) => {
      toast.error(messageOf(error))
      await refresh()
      setEpoch((value) => value + 1)
    },
  })
  const { mutate } = save
  const scheduler = useMemo(
    () => createChannelFieldUpdateScheduler((value) => mutate(value)),
    [mutate]
  )
  useEffect(() => () => scheduler.cancel(), [scheduler])
  return (
    <span
      role='group'
      aria-label={`${channel.name} ${field === 'priority' ? '优先级' : '权重'}`}
    >
      <NumericSpinnerInput
        key={epoch}
        value={channel[field] ?? 0}
        onChange={scheduler.schedule}
        onCommit={scheduler.flush}
        min={field === 'priority' ? -999 : 0}
        max={2147483647}
        disabled={save.isPending}
      />
    </span>
  )
}

export function BalanceCell({ channel }: { channel: Channel }) {
  const { quotaPerUnit } = useChannelTable()
  const card = useContext(ChannelRowActionsLayoutContext) === 'card'
  const format = (value: number | null | undefined) =>
    typeof value === 'number' && Number.isFinite(value)
      ? `${card ? '' : '$'}${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)}`
      : '—'
  const used =
    channel.used_quota == null || !quotaPerUnit
      ? null
      : channel.used_quota / quotaPerUnit
  return (
    <div className='flex items-center gap-3 text-sm text-muted-foreground tabular-nums'>
      <span title={`已使用：${format(used)}`}>{format(used)}</span>
      <span title={`剩余：${format(channel.balance)}`}>
        {format(channel.balance)}
      </span>
    </div>
  )
}

export function ChannelNameCell({ channel }: { channel: Channel }) {
  const { actions } = useChannelTable()
  return (
    <Button
      variant='link'
      className='h-auto max-w-full justify-start truncate p-0'
      onClick={() => actions.onEdit(channel)}
    >
      {channel.name}
    </Button>
  )
}
export function ChannelModelsCell({ channel }: { channel: Channel }) {
  const { actions } = useChannelTable()
  return (
    <Button variant='ghost' size='sm' onClick={() => actions.onModels(channel)}>
      {channel.models.split(',').filter(Boolean).length} 个
    </Button>
  )
}
