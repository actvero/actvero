import { useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { useReturnFocus } from '@/hooks/use-return-focus'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSkills, type Skill, type Version } from './shared'

export function CompareDialog({
  skill,
  target,
  close,
}: {
  skill: Skill
  target: Version
  close: () => void
}) {
  const { key } = useSkills()
  const restoreFocus = useReturnFocus()
  const [beforeId, setBeforeId] = useState(
    skill.versions.find((v) => v.id !== target.id)?.id ?? target.id
  )
  const [afterId, setAfterId] = useState(target.id)
  const [selected, setSelected] = useState('')
  const before = skill.versions.find((v) => v.id === beforeId)!
  const after = skill.versions.find((v) => v.id === afterId)!
  const paths = [
    ...new Set([...before.files, ...after.files].map((f) => f.path)),
  ].sort()
  const changed = paths.flatMap((path) => {
    const a = before.files.find((f) => f.path === path),
      b = after.files.find((f) => f.path === path)
    if (beforeId === afterId || (a?.sha256 && a.sha256 === b?.sha256)) return []
    return [
      { path, kind: !a ? '新增' : !b ? '删除' : '修改', before: a, after: b },
    ]
  })
  const entry = changed.find((f) => f.path === selected) ?? changed[0]
  const queries = useQueries({
    queries: [before, after].map((version, index) => ({
      queryKey: [...key, skill.id, version.id, 'file', entry?.path],
      enabled:
        !!entry &&
        (index === 0 ? entry.before?.previewable : entry.after?.previewable) ===
          true,
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api<Schema['SkillFileContent']>(
          `/skills/${skill.id}/versions/${version.id}/file?${new URLSearchParams({ path: entry?.path ?? '' })}`,
          'GET',
          undefined,
          undefined,
          signal
        ),
    })),
  })
  return (
    <Dialog open onOpenChange={(v) => !v && close()}>
      <DialogContent
        onCloseAutoFocus={restoreFocus}
        className='max-h-[90dvh] overflow-y-auto sm:max-w-5xl'
      >
        <DialogHeader>
          <DialogTitle>版本对比</DialogTitle>
          <DialogDescription>
            按文件摘要比较新增、删除与修改；文本文件可并排查看原文。
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-4 sm:grid-cols-2'>
          {[
            {
              id: 'compare-before',
              label: '基准版本',
              value: beforeId,
              change: setBeforeId,
            },
            {
              id: 'compare-after',
              label: '对比版本',
              value: afterId,
              change: setAfterId,
            },
          ].map((item) => (
            <div key={item.id} className='space-y-2'>
              <Label htmlFor={item.id}>{item.label}</Label>
              <Select
                value={item.value}
                onValueChange={(v) => {
                  item.change(v)
                  setSelected('')
                }}
              >
                <SelectTrigger id={item.id} className='w-full'>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {skill.versions.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      v{v.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}
        </div>
        {!changed.length ? (
          <p className='py-12 text-center text-muted-foreground'>
            这两个版本没有文件变化。
          </p>
        ) : (
          <>
            <ScrollArea viewportClassName='max-h-40' aria-label='变更文件'>
              <div className='space-y-1'>
                {changed.map((file) => (
                  <Button
                    key={file.path}
                    variant={entry?.path === file.path ? 'secondary' : 'ghost'}
                    className='w-full justify-start'
                    onClick={() => setSelected(file.path)}
                  >
                    <Badge variant='outline'>{file.kind}</Badge>
                    <span className='truncate'>{file.path}</span>
                  </Button>
                ))}
              </div>
            </ScrollArea>
            <div className='grid min-w-0 gap-4 md:grid-cols-2'>
              {queries.map((query, index) => {
                const file = index === 0 ? entry?.before : entry?.after
                return (
                  <section key={index} className='min-w-0 space-y-2'>
                    <h3 className='text-sm font-medium break-all'>
                      v{index === 0 ? before.version : after.version} ·{' '}
                      {entry?.path}
                    </h3>
                    {!file ? (
                      <p className='py-8 text-sm text-muted-foreground'>
                        此版本中不存在此文件
                      </p>
                    ) : !file.previewable ? (
                      <p className='py-8 text-sm text-muted-foreground'>
                        请下载技能包查看此文件
                      </p>
                    ) : query.isPending ? (
                      <LoadingState />
                    ) : query.isError ? (
                      <RequestError
                        error={query.error}
                        retry={() => void query.refetch()}
                      />
                    ) : (
                      <pre className='max-h-96 overflow-auto rounded-md bg-muted p-4 text-xs leading-6'>
                        {query.data.content}
                      </pre>
                    )}
                  </section>
                )
              })}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
