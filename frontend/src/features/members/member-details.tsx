import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, dateTime, type Schema } from '@/lib/api'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { RequestError, LoadingState } from '@/components/request-state'
import { UserAvatar } from '@/components/user-avatar'
import { useOrganization } from '@/features/auth/session'
import { roleName, states } from './labels'

type Change = Schema['MemberChange']
export function MemberDetails({
  id,
  path,
  onClose,
}: {
  id: string
  path: string
  onClose: () => void
}) {
  const { csrf, organization, user } = useOrganization()
  const client = useQueryClient()
  const returnFocus = useRef<HTMLElement | null>(null)
  const [action, setAction] = useState<Change['action'] | null>(null)
  const [role, setRole] = useState<'administrator' | 'member' | null>(null)
  const [reason, setReason] = useState('')
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      user.id,
      'member',
      id,
      path,
    ],
    queryFn: ({ signal }) =>
      api<Schema['MemberView']>(
        path + '/members/' + id,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  const change = useMutation({
    mutationFn: () =>
      api<Schema['MemberView']>(
        path + '/members/' + id,
        'PATCH',
        { action, role, reason, version: query.data!.version },
        csrf
      ),
    onSuccess: async () => {
      setAction(null)
      onClose()
      await client.invalidateQueries({ queryKey: ['session'] })
      await client.invalidateQueries({ queryKey: ['organization'] })
    },
    onError: () => {
      void query.refetch()
    },
  })
  const member = query.data
  const actionLabels = {
    role: '调整角色',
    pause: '暂停访问',
    restore: '恢复访问',
    remove: '移出组织',
  }
  const selectAction = (next: Change['action']) => {
    change.reset()
    setReason('')
    setAction(next)
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !change.isPending) onClose()
      }}
    >
      <DialogContent
        className='max-h-[calc(100dvh-2rem)] overflow-y-auto'
        onOpenAutoFocus={() => {
          returnFocus.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          returnFocus.current?.focus()
        }}
        onPointerDownOutside={(event) => {
          if (role && role !== member?.role) event.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>编辑成员</DialogTitle>
          <DialogDescription>
            查看成员信息和管理当前组织的访问权限。
          </DialogDescription>
        </DialogHeader>
        <div className='flex flex-col gap-5'>
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : (
            member && (
              <>
                <dl className='grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-6 gap-y-4 text-sm'>
                  <dt className='text-muted-foreground'>姓名</dt>
                  <dd className='flex items-center gap-3'>
                    <UserAvatar user={member} />
                    <span className='break-words'>
                      {member.name}
                      {member.is_self ? '（你）' : ''}
                    </span>
                  </dd>
                  <dt className='text-muted-foreground'>邮箱</dt>
                  <dd className='break-all'>{member.email ?? '未设置'}</dd>
                  <dt>
                    <Label
                      htmlFor={
                        member.status === 'active' ? 'member-role' : undefined
                      }
                    >
                      角色
                    </Label>
                  </dt>
                  <dd>
                    {member.status === 'active' ? (
                      <Select
                        value={role ?? member.role}
                        onValueChange={(value) =>
                          setRole(value as 'administrator' | 'member')
                        }
                      >
                        <SelectTrigger id='member-role' className='w-full'>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectGroup>
                            <SelectItem value='administrator'>
                              管理员
                            </SelectItem>
                            <SelectItem value='member'>普通成员</SelectItem>
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    ) : (
                      roleName(member.role)
                    )}
                  </dd>
                  <dt className='text-muted-foreground'>状态</dt>
                  <dd>
                    <Badge
                      variant={
                        member.status === 'active' ? 'secondary' : 'outline'
                      }
                    >
                      {states[member.status]}
                    </Badge>
                  </dd>
                  <dt className='text-muted-foreground'>加入方式</dt>
                  <dd>
                    {{
                      setup: '首次初始化',
                      invitation: '邀请加入',
                      direct: '管理员添加',
                    }[member.source] ?? member.source}
                  </dd>
                  <dt className='text-muted-foreground'>加入时间</dt>
                  <dd>{dateTime(member.joined_at)}</dd>
                </dl>
                <p className='text-sm text-muted-foreground'>
                  所有管理员权限相同。最后一名有效管理员不能被降级、暂停或移出。
                </p>
                {member.status !== 'removed' && (
                  <div className='flex flex-wrap gap-2'>
                    <Button
                      variant='outline'
                      size='sm'
                      onClick={() =>
                        selectAction(
                          member.status === 'active' ? 'pause' : 'restore'
                        )
                      }
                    >
                      {member.status === 'active' ? '暂停访问' : '恢复访问'}
                    </Button>
                    <Button
                      variant='destructive'
                      size='sm'
                      onClick={() => selectAction('remove')}
                    >
                      移出组织
                    </Button>
                  </div>
                )}
              </>
            )
          )}
        </div>
        <DialogFooter>
          <Button
            variant='outline'
            disabled={change.isPending}
            onClick={onClose}
          >
            取消
          </Button>
          {member?.status === 'active' && (
            <Button
              disabled={
                !role ||
                role === member.role ||
                change.isPending ||
                query.isFetching
              }
              onClick={() => selectAction('role')}
            >
              保存修改
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
      <AlertDialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open && !change.isPending) setAction(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {action ? actionLabels[action] : '确认操作'}？
            </AlertDialogTitle>
            <AlertDialogDescription>
              {member?.name}：
              {action === 'remove'
                ? '移出后立即失去本组织访问权限，再次加入需要新的邀请。'
                : action === 'pause'
                  ? '暂停后立即失去本组织访问权限。'
                  : action === 'restore'
                    ? '恢复后需要重新登录，旧会话不会自动恢复访问。'
                    : '将调整为' + roleName(role ?? 'member') + '。'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Label htmlFor='change-reason'>原因（选填）</Label>
          <Textarea
            id='change-reason'
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
          {change.isError && <RequestError error={change.error} />}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={change.isPending}>
              取消
            </AlertDialogCancel>
            <Button
              variant={
                action === 'remove' || action === 'pause'
                  ? 'destructive'
                  : 'default'
              }
              disabled={change.isPending || query.isFetching}
              onClick={() => change.mutate()}
            >
              {change.isPending ? '正在提交…' : '确认'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  )
}
