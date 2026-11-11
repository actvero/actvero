import { useId, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Ellipsis, FileArchive, Info } from 'lucide-react'
import { toast } from 'sonner'
import { api, dateTime } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Field, FieldLabel } from '@/components/ui/field'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { RequestError } from '@/components/request-state'
import {
  audiences,
  packageSize,
  useWorkbenches,
  type Workbench,
  type WorkbenchVersion,
} from './shared'
import { WorkbenchStatusBadge } from './status-badge'

type Action = 'publish' | 'withdraw' | 'delete' | 'inspect'

export function WorkbenchVersions({ item }: { item: Workbench }) {
  const id = useId()
  const [dialog, setDialog] = useState<{
    action: Action
    version: WorkbenchVersion
    revision: number
  }>()
  const [notes, setNotes] = useState('')
  const trigger = useRef<HTMLButtonElement>(null)
  const { csrf, update, refresh } = useWorkbenches()
  const change = useMutation({
    mutationFn: async (selection: NonNullable<typeof dialog>) => {
      const { action, version, revision } = selection
      const path = `/workbenches/${item.id}/versions/${version.id}`
      if (action === 'delete') {
        await api(`${path}?revision=${revision}`, 'DELETE', undefined, csrf)
        await refresh()
      } else {
        const updated = await api<Workbench>(
          `${path}/${action}`,
          'POST',
          {
            revision,
            ...(action === 'publish' ? { release_notes: notes } : {}),
          },
          csrf
        )
        update(updated)
      }
    },
    onSuccess: (_, selection) => {
      setDialog(undefined)
      toast.success(
        selection.action === 'publish'
          ? '版本已发布'
          : selection.action === 'withdraw'
            ? '版本已下架'
            : '草稿已删除'
      )
    },
  })
  function open(action: Action, version: WorkbenchVersion) {
    change.reset()
    setNotes('')
    setDialog({ action, version, revision: item.revision })
  }
  function close(value: boolean) {
    if (!value && !change.isPending) setDialog(undefined)
  }
  function restoreFocus(event: Event) {
    if (trigger.current?.isConnected) {
      event.preventDefault()
      trigger.current.focus()
    }
  }
  const version = dialog?.version
  return (
    <>
      {item.versions.length ? (
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>版本</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className='hidden sm:table-cell'>DSH 要求</TableHead>
                <TableHead className='hidden md:table-cell'>包大小</TableHead>
                <TableHead className='hidden lg:table-cell'>上传时间</TableHead>
                <TableHead className='w-12'>
                  <span className='sr-only'>操作</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {item.versions.map((row) => (
                <TableRow key={row.id}>
                  <TableCell
                    className='max-w-28 truncate font-medium'
                    title={row.version}
                  >
                    {row.version}
                  </TableCell>
                  <TableCell>
                    <WorkbenchStatusBadge status={row.status} />
                  </TableCell>
                  <TableCell
                    className='hidden max-w-52 truncate sm:table-cell'
                    title={row.dsh_requirement}
                  >
                    {row.dsh_requirement}
                  </TableCell>
                  <TableCell className='hidden md:table-cell'>
                    {packageSize(row.size)}
                  </TableCell>
                  <TableCell className='hidden lg:table-cell'>
                    {dateTime(row.created_at)}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant='ghost'
                          size='icon'
                          aria-label={`${row.version} 版本操作`}
                          onFocus={(event) => {
                            trigger.current = event.currentTarget
                          }}
                        >
                          <Ellipsis />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align='end'>
                        <DropdownMenuGroup>
                          <DropdownMenuItem
                            onSelect={() => open('inspect', row)}
                          >
                            查看包信息
                          </DropdownMenuItem>
                          {row.status === 'draft' && (
                            <DropdownMenuItem
                              onSelect={() => open('publish', row)}
                            >
                              发布版本
                            </DropdownMenuItem>
                          )}
                          {row.status === 'published' && (
                            <DropdownMenuItem
                              variant='destructive'
                              onSelect={() => open('withdraw', row)}
                            >
                              下架版本
                            </DropdownMenuItem>
                          )}
                          {row.status === 'draft' && (
                            <DropdownMenuItem
                              variant='destructive'
                              onSelect={() => open('delete', row)}
                            >
                              删除草稿
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <Empty className='border'>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <FileArchive />
            </EmptyMedia>
            <EmptyTitle>暂无版本</EmptyTitle>
            <EmptyDescription>上传安装包以创建版本草稿。</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {version && dialog.action === 'inspect' && (
        <Dialog open onOpenChange={close}>
          <DialogContent onCloseAutoFocus={restoreFocus}>
            <DialogHeader>
              <DialogTitle>版本 {version.version}</DialogTitle>
              <DialogDescription>{item.package_name}</DialogDescription>
            </DialogHeader>
            <dl className='grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-5 gap-y-3 text-sm'>
              <dt className='text-muted-foreground'>状态</dt>
              <dd>
                <WorkbenchStatusBadge status={version.status} />
              </dd>
              <dt className='text-muted-foreground'>DSH 要求</dt>
              <dd className='break-all'>{version.dsh_requirement}</dd>
              <dt className='text-muted-foreground'>包大小</dt>
              <dd>{packageSize(version.size)}</dd>
              <dt className='text-muted-foreground'>SHA-256</dt>
              <dd className='font-mono break-all'>{version.sha256}</dd>
              <dt className='text-muted-foreground'>上传者</dt>
              <dd>{version.uploader_name}</dd>
              <dt className='text-muted-foreground'>上传时间</dt>
              <dd>{dateTime(version.created_at)}</dd>
              {version.published_at && (
                <>
                  <dt className='text-muted-foreground'>发布时间</dt>
                  <dd>{dateTime(version.published_at)}</dd>
                </>
              )}
              {version.release_notes && (
                <>
                  <dt className='text-muted-foreground'>更新说明</dt>
                  <dd className='max-h-48 overflow-y-auto break-words whitespace-pre-wrap'>
                    {version.release_notes}
                  </dd>
                </>
              )}
            </dl>
          </DialogContent>
        </Dialog>
      )}
      {version && dialog.action === 'publish' && (
        <Dialog open onOpenChange={close}>
          <DialogContent onCloseAutoFocus={restoreFocus}>
            <DialogHeader>
              <DialogTitle>发布 {version.version}</DialogTitle>
              <DialogDescription>
                {item.display_name} · {audiences[item.audience]}
                {item.audience === 'selected'
                  ? `（${item.member_ids.length} 人）`
                  : ''}
              </DialogDescription>
            </DialogHeader>
            <form
              className='flex flex-col gap-4'
              onSubmit={(event) => {
                event.preventDefault()
                if (!change.isPending) change.mutate(dialog)
              }}
            >
              <div className='flex items-start gap-2 rounded-md border p-3 text-sm text-muted-foreground'>
                <Info className='mt-0.5 size-4 shrink-0' />
                <div className='flex min-w-0 flex-col gap-1'>
                  <p className='break-all'>
                    DSH 要求 {version.dsh_requirement}
                  </p>
                  {item.current_version && (
                    <p>当前版本 {item.current_version} 将进入历史版本。</p>
                  )}
                </div>
              </div>
              <Field>
                <FieldLabel htmlFor={`${id}-notes`}>
                  更新说明（可选）
                </FieldLabel>
                <Textarea
                  id={`${id}-notes`}
                  rows={4}
                  maxLength={4000}
                  value={notes}
                  disabled={change.isPending}
                  onChange={(event) => setNotes(event.target.value)}
                />
              </Field>
              {change.isError && <RequestError error={change.error} />}
              <DialogFooter>
                <Button
                  type='button'
                  variant='outline'
                  disabled={change.isPending}
                  onClick={() => close(false)}
                >
                  取消
                </Button>
                <Button type='submit' disabled={change.isPending}>
                  {change.isPending ? '正在发布…' : '确认发布'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
      {version &&
        (dialog.action === 'withdraw' || dialog.action === 'delete') && (
          <ConfirmDialog
            open
            onOpenChange={close}
            onCloseAutoFocus={restoreFocus}
            title={
              dialog.action === 'withdraw'
                ? `下架 ${version.version}`
                : `删除 ${version.version} 草稿`
            }
            desc={
              dialog.action === 'withdraw'
                ? '下架后该工作台将没有当前发布版本，历史版本仍可在后台查看。'
                : '将删除此草稿及其安装包。删除后可重新上传该版本。'
            }
            cancelBtnText='取消'
            confirmText={dialog.action === 'withdraw' ? '确认下架' : '删除草稿'}
            destructive
            isLoading={change.isPending}
            handleConfirm={() => change.mutate(dialog)}
          >
            {change.isError && <RequestError error={change.error} />}
          </ConfirmDialog>
        )}
    </>
  )
}
