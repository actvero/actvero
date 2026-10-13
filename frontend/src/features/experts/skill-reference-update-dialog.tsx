import { useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { LoadingState, RequestError } from '@/components/request-state'
import { type Expert, useExperts } from './shared'

export function SkillReferenceUpdateDialog({
  expert,
  close,
  submit,
  disabled,
  feedback,
}: {
  expert: Expert
  close: () => void
  submit: (changes: Schema['ExactSkillChange'][]) => Promise<void>
  disabled: boolean
  feedback?: ReactNode
}) {
  const { key } = useExperts()
  const [chosen, setChosen] = useState<string[]>([])
  const query = useQuery({
    queryKey: [
      ...key,
      expert.id,
      expert.revision,
      expert.content.skills,
      'skill-update-preview',
    ],
    queryFn: async ({ signal }) =>
      Promise.all(
        (expert.content.skills ?? []).map(async (ref) => {
          const target = await api<Schema['ExpertDependencyOption']>(
            `/experts/dependencies/skills/${ref.skill_id}`,
            'GET',
            undefined,
            undefined,
            signal
          )
          const change: Schema['ExactSkillChange'] | undefined =
            target.status === 'available' &&
            target.version_id &&
            target.sha256 &&
            (target.version_id !== ref.version_id ||
              target.sha256 !== ref.sha256)
              ? {
                  key: ref.key,
                  from_version_id: ref.version_id,
                  from_sha256: ref.sha256,
                  to_version_id: target.version_id,
                  to_sha256: target.sha256,
                }
              : undefined
          return { ref, target, change }
        })
      ),
  })
  const changes =
    query.data
      ?.filter((e) => chosen.includes(e.ref.key) && e.change)
      .map((e) => e.change!) ?? []
  return (
    <Dialog open onOpenChange={(open) => !open && !disabled && close()}>
      <DialogContent className='flex max-h-[85dvh] flex-col sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>选择技能引用更新</DialogTitle>
          <DialogDescription>
            只修改所选引用，其余草稿内容和已发布版本保持不变。更新后需另行检查并发布专家。
          </DialogDescription>
        </DialogHeader>
        <div className='flex min-h-0 flex-col gap-3 overflow-y-auto'>
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : (
            query.data.map(({ ref, target, change }) => (
              <div
                key={ref.key}
                className='flex items-start gap-3 rounded-md border p-3'
              >
                <Checkbox
                  aria-label={`更新 ${ref.label}`}
                  checked={chosen.includes(ref.key)}
                  disabled={disabled || !change}
                  onCheckedChange={(value) =>
                    setChosen(
                      value === true
                        ? [...chosen, ref.key]
                        : chosen.filter((key) => key !== ref.key)
                    )
                  }
                />
                <div className='flex min-w-0 flex-col gap-1 text-sm'>
                  <span className='font-medium break-words'>{ref.label}</span>
                  <span className='text-muted-foreground'>
                    锁定版本：
                    {expert.check.dependencies.find(
                      (d) => d.kind === 'skills' && d.key === ref.key
                    )?.locked_version || ref.version_id}
                  </span>
                  <span>
                    {change
                      ? `更新为 v${target.version}`
                      : target.status === 'available'
                        ? '已是当前推荐版本'
                        : '当前无可更新版本'}
                  </span>
                </div>
              </div>
            ))
          )}
          <Alert>
            <AlertTitle>更新范围</AlertTitle>
            <AlertDescription>
              已选择 {changes.length}{' '}
              项。服务端会重新核对草稿版本与目标摘要，发生变化时整笔拒绝。
            </AlertDescription>
          </Alert>
        </div>
        {feedback}
        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            disabled={disabled}
            onClick={close}
          >
            取消
          </Button>
          <Button
            type='button'
            disabled={
              disabled || query.isPending || query.isError || !changes.length
            }
            onClick={() => void submit(changes)}
          >
            更新所选引用到草稿
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
