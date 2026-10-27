import { useMemo } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { GroupBadge } from '@/vendor/newapi/components/group-badge'
import { ProviderBadge } from '@/vendor/newapi/components/provider-badge'
import { StatusBadge } from '@/vendor/newapi/components/status-badge'
import {
  formatResponseTime,
  formatRelativeTime,
  getResponseTimeConfig,
  getChannelTypeIcon,
  getChannelTypeLabel,
} from '@/vendor/newapi/features/channels/lib/channel-utils'
import { useTranslation } from 'react-i18next'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip'
import { splitNames, type Channel } from './api'
import {
  RowActions,
  ChannelFieldCell,
  BalanceCell,
  ChannelNameCell,
  ChannelModelsCell,
} from './channel-cells'

export function useChannelColumns(): ColumnDef<Channel>[] {
  const { t } = useTranslation()
  return useMemo(
    () => [
      {
        accessorKey: 'id',
        header: 'ID',
        size: 55,
        cell: ({ row }) => (
          <span className='text-xs text-muted-foreground'>
            {row.original.id}
          </span>
        ),
      },
      {
        accessorKey: 'name',
        header: '名称',
        size: 180,
        cell: ({ row }) => <ChannelNameCell channel={row.original} />,
      },
      {
        accessorKey: 'type',
        header: '类型',
        size: 165,
        enableSorting: false,
        cell: ({ row }) => (
          <ProviderBadge
            iconKey={`${getChannelTypeIcon(row.original.type)}.Color`}
            iconSize={18}
            label={t(getChannelTypeLabel(row.original.type))}
            colorText={false}
            showDot={false}
            copyable={false}
          />
        ),
      },
      {
        accessorKey: 'status',
        header: '状态',
        size: 95,
        enableSorting: false,
        cell: ({ row }) => (
          <StatusBadge
            label={
              row.original.status === 1
                ? '已启用'
                : row.original.status === 3
                  ? '自动禁用'
                  : '已禁用'
            }
            variant={
              row.original.status === 1
                ? 'success'
                : row.original.status === 3
                  ? 'danger'
                  : 'neutral'
            }
            copyable={false}
          />
        ),
      },
      {
        accessorKey: 'group',
        header: '分组',
        size: 110,
        enableSorting: false,
        cell: ({ row }) => (
          <div className='flex flex-wrap gap-1'>
            {splitNames(row.original.group).map((group) => (
              <GroupBadge
                key={group}
                group={group}
                copyable={false}
                size='sm'
              />
            ))}
          </div>
        ),
      },
      {
        accessorKey: 'priority',
        header: '优先级',
        size: 105,
        cell: ({ row }) => (
          <ChannelFieldCell channel={row.original} field='priority' />
        ),
      },
      {
        accessorKey: 'weight',
        header: '权重',
        size: 105,
        enableSorting: false,
        cell: ({ row }) => (
          <ChannelFieldCell channel={row.original} field='weight' />
        ),
      },
      {
        accessorKey: 'balance',
        header: '已使用 / 剩余',
        size: 165,
        cell: ({ row }) => <BalanceCell channel={row.original} />,
      },
      {
        accessorKey: 'response_time',
        header: '响应',
        size: 110,
        cell: ({ row }) => (
          <StatusBadge
            label={formatResponseTime(row.original.response_time, t)}
            variant={getResponseTimeConfig(row.original.response_time).variant}
            copyable={false}
            size='sm'
          />
        ),
      },
      {
        accessorKey: 'test_time',
        header: '上次测试',
        enableSorting: false,
        size: 120,
        cell: ({ row }) =>
          row.original.test_time ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <StatusBadge
                    label={formatRelativeTime(row.original.test_time, 'zh-CN')}
                    variant='neutral'
                    copyable={false}
                  />
                </span>
              </TooltipTrigger>
              <TooltipContent>
                {new Date(row.original.test_time * 1000).toLocaleString(
                  'zh-CN'
                )}
              </TooltipContent>
            </Tooltip>
          ) : (
            <span className='text-muted-foreground'>—</span>
          ),
      },
      {
        accessorKey: 'models',
        header: '模型',
        size: 90,
        enableSorting: false,
        cell: ({ row }) => <ChannelModelsCell channel={row.original} />,
      },
      {
        id: 'actions',
        header: '操作',
        enableSorting: false,
        enableHiding: false,
        size: 145,
        cell: ({ row }) => <RowActions channel={row.original} />,
      },
    ],
    [t]
  )
}
