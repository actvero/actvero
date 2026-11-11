import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import type { Model } from '@/vendor/newapi/features/models/types'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useOrganization } from '@/features/auth/session'
import { supportsMemberAccess } from './model-name'

export function useAccessColumns(onManage: (model: Model) => void) {
  const { organization, csrf } = useOrganization()
  const [names, setNames] = useState<string[]>([])
  const onModelsVisible = useCallback((models: Model[]) => {
    const next = models
      .filter((m) => m.name_rule === 0 && supportsMemberAccess(m.model_name))
      .map((m) => m.model_name)
      .sort()
    setNames((previous) =>
      previous.join('\0') === next.join('\0') ? previous : next
    )
  }, [])
  // CSRF authenticates this read-only POST; it is not part of cache identity.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    queryKey: [
      'model-gateway',
      organization.tenant_id,
      'publication-status',
      names,
    ],
    queryFn: () =>
      api<Schema['PublicationStatuses']>(
        '/model-gateway/publication/status',
        'POST',
        { models: names },
        csrf
      ),
    enabled: names.length > 0,
    retry: false,
    staleTime: 10000,
    refetchOnWindowFocus: true,
  })
  const { data } = query
  const accessColumns = useMemo<ColumnDef<Model>[]>(() => {
    const statuses = new Map(data?.items.map((item) => [item.model_name, item]))
    return [
      {
        id: 'member_access',
        header: '开放范围',
        size: 105,
        enableSorting: false,
        cell: ({ row }) => {
          const state = statuses.get(row.original.model_name)
          if (row.original.name_rule !== 0)
            return (
              <span className='text-xs text-muted-foreground'>
                按具体模型开放
              </span>
            )
          if (!supportsMemberAccess(row.original.model_name))
            return (
              <span className='text-xs text-muted-foreground'>
                名称格式不支持
              </span>
            )
          return (
            <Button
              variant='link'
              className='h-auto justify-start p-0'
              aria-label={
                state ? undefined : `查看 ${row.original.model_name} 的使用设置`
              }
              onClick={() => onManage(row.original)}
            >
              {state
                ? !state.enabled
                  ? '未开放'
                  : state.audience === 'organization'
                    ? '全体成员'
                    : state.audience === 'selected'
                      ? `指定 ${state.member_count} 人`
                      : '仅管理员'
                : '—'}
            </Button>
          )
        },
      },
      {
        id: 'access_readiness',
        header: '状态',
        size: 100,
        enableSorting: false,
        meta: { mobileBadge: true },
        cell: ({ row }) => {
          const state = statuses.get(row.original.model_name)
          if (!state || row.original.name_rule !== 0)
            return <span className='text-muted-foreground'>—</span>
          const status = !state.enabled
            ? '未发布'
            : state.checks.some((check) => check.status === 'blocked')
              ? '待维护'
              : '已发布'
          return (
            <Button
              type='button'
              variant='ghost'
              size='sm'
              className='-mx-2 px-2'
              aria-label={`${row.original.model_name} · ${status}，查看使用设置`}
              onClick={() => onManage(row.original)}
            >
              <Badge
                variant={status === '已发布' ? 'secondary' : 'outline'}
                dot={status === '待维护'}
              >
                {status}
              </Badge>
            </Button>
          )
        },
      },
    ]
  }, [data, onManage])
  return { accessColumns, onModelsVisible }
}
