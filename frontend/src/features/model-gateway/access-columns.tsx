import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import type { Model } from '@/vendor/newapi/features/models/types'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useOrganization } from '@/features/auth/session'

export function useAccessColumns(onManage: (model: Model) => void) {
  const { organization, csrf } = useOrganization()
  const [names, setNames] = useState<string[]>([])
  const onModelsVisible = useCallback((models: Model[]) => {
    const next = models
      .filter(
        (m) =>
          m.name_rule === 0 &&
          /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$/.test(m.model_name)
      )
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
  const { data, isError, refetch } = query
  const accessColumns = useMemo<ColumnDef<Model>[]>(() => {
    const statuses = new Map(data?.items.map((item) => [item.model_name, item]))
    return [
      {
        id: 'member_access',
        header: '开放范围',
        size: 105,
        enableSorting: false,
        meta: { mobileBadge: true },
        cell: ({ row }) => {
          const state = statuses.get(row.original.model_name)
          if (row.original.name_rule !== 0)
            return (
              <span className='text-xs text-muted-foreground'>
                按具体模型开放
              </span>
            )
          return (
            <Button
              variant='link'
              className='h-auto justify-start p-0'
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
                : isError
                  ? '读取失败'
                  : '读取中…'}
            </Button>
          )
        },
      },
      {
        id: 'access_readiness',
        header: '接入检查',
        size: 170,
        enableSorting: false,
        cell: ({ row }) => {
          const state = statuses.get(row.original.model_name)
          if (row.original.name_rule !== 0)
            return (
              <span className='text-xs text-muted-foreground'>
                资料匹配规则
              </span>
            )
          if (isError)
            return (
              <Button variant='link' size='sm' onClick={() => void refetch()}>
                检查失败 · 重试
              </Button>
            )
          if (!state)
            return (
              <span className='text-xs text-muted-foreground'>检查中…</span>
            )
          const problems = state.checks.filter(
            (check) => check.status !== 'ready'
          )
          return (
            <button
              type='button'
              className='flex min-w-0 flex-col items-start gap-1 text-left'
              onClick={() => onManage(row.original)}
            >
              <Badge variant={state.ready ? 'secondary' : 'outline'}>
                {state.ready
                  ? '配置就绪'
                  : problems.some((c) => c.status === 'unknown')
                    ? '状态待确认'
                    : '待完善'}
              </Badge>
              <span
                className='max-w-48 truncate text-xs text-muted-foreground'
                title={problems.map((c) => c.message).join('；')}
              >
                {state.ready
                  ? `${state.active_channels} 个可用渠道`
                  : problems[0]?.message}
              </span>
            </button>
          )
        },
      },
    ]
  }, [data, isError, refetch, onManage])
  return { accessColumns, onModelsVisible }
}
