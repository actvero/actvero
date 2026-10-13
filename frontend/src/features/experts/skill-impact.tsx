import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api, ApiError, type Schema } from '@/lib/api'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { LoadingState, RequestError } from '@/components/request-state'
import { useExperts } from './shared'

export function SkillExpertImpact({
  skillId,
  targetVersionId,
  sourceVersionId,
  selected = [],
  onChange,
  disabled = false,
  onForbidden,
}: {
  skillId: string
  targetVersionId?: string
  sourceVersionId?: string
  selected?: Schema['ExpertDraftSelection'][]
  onChange?: (selected: Schema['ExpertDraftSelection'][]) => void
  disabled?: boolean
  onForbidden?: () => void
}) {
  const { key } = useExperts()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [
      ...key,
      'skill-impact',
      skillId,
      targetVersionId,
      sourceVersionId,
      q,
      page,
    ],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        skill_id: skillId,
        q,
        page: String(page),
      })
      if (targetVersionId) params.set('target_version_id', targetVersionId)
      if (sourceVersionId) params.set('source_version_id', sourceVersionId)
      return api<Schema['ExpertSkillImpactView']>(
        '/experts/skill-impact?' + params,
        'GET',
        undefined,
        undefined,
        signal
      )
    },
  })
  const forbidden =
    query.error instanceof ApiError && [401, 403].includes(query.error.status)
  useEffect(() => {
    if (forbidden) onForbidden?.()
  }, [forbidden, onForbidden])
  return (
    <div className='flex min-h-0 flex-col gap-3'>
      <Alert>
        <AlertTitle>受影响专家</AlertTitle>
        <AlertDescription>
          {targetVersionId
            ? '旧发布引用保留。只更新勾选的专家草稿，仍需单独检查并发布专家。'
            : '停止此版本后，精确引用它的草稿和已发布专家可能不可用。'}
        </AlertDescription>
      </Alert>
      <Input
        aria-label='搜索受影响专家'
        placeholder='搜索专家名称'
        value={q}
        maxLength={100}
        disabled={disabled || forbidden}
        onChange={(e) => {
          setQ(e.target.value)
          setPage(1)
        }}
      />
      {onChange && (
        <div className='flex flex-wrap items-center justify-between gap-2 text-sm'>
          <span>已选择 {selected.length} 位专家（最多 50 位）</span>
          <Button
            type='button'
            variant='ghost'
            size='sm'
            disabled={disabled || forbidden || !selected.length}
            onClick={() => onChange([])}
          >
            清空选择
          </Button>
        </div>
      )}
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <>
          <p className='text-sm text-muted-foreground'>
            {query.data.total ?? 0} 位专家 · 草稿与当前发布
          </p>
          {(query.data.items ?? []).map((e) => {
            const checked = selected.some((s) => s.expert_id === e.id)
            return (
              <div
                key={e.id}
                className='flex items-start gap-3 rounded-md border p-3'
              >
                {onChange && (
                  <Checkbox
                    aria-label={`更新 ${e.name} 的草稿`}
                    checked={checked}
                    disabled={
                      disabled ||
                      !e.draft_changes?.length ||
                      (!checked && selected.length >= 50)
                    }
                    onCheckedChange={(value) =>
                      onChange(
                        value === true
                          ? [
                              ...selected,
                              {
                                expert_id: e.id,
                                revision: e.revision,
                                changes: e.draft_changes ?? [],
                              },
                            ]
                          : selected.filter((s) => s.expert_id !== e.id)
                      )
                    }
                  />
                )}
                <div className='flex min-w-0 flex-col gap-1 text-sm'>
                  <Link
                    to='/experts/$expertId'
                    params={{ expertId: e.id }}
                    className='break-words underline underline-offset-4'
                  >
                    {e.name}
                  </Link>
                  <span className='text-muted-foreground'>
                    草稿引用：{e.draft_versions?.join('、') || '无'} ·
                    已发布引用：{e.published_versions?.join('、') || '无'}
                  </span>
                  {onChange && (
                    <span>
                      {e.draft_changes?.length
                        ? `${e.draft_changes.length} 项引用将更新`
                        : '草稿无需更新'}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
          {!query.data.total && (
            <p className='text-sm text-muted-foreground'>
              没有匹配的专家引用。
            </p>
          )}
          <div className='flex items-center justify-between gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={disabled || page <= 1}
              onClick={() => setPage(page - 1)}
            >
              上一页
            </Button>
            <span className='text-sm'>
              {page} / {Math.max(1, Math.ceil((query.data.total ?? 0) / 20))}
            </span>
            <Button
              type='button'
              variant='outline'
              size='sm'
              disabled={disabled || page * 20 >= (query.data.total ?? 0)}
              onClick={() => setPage(page + 1)}
            >
              下一页
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
