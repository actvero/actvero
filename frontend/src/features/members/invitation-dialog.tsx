import { useRef, useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'

const schema = z.object({
  email: z.email('请输入有效邮箱'),
  name: z.string().trim().max(200),
})
export function InviteDialog({
  open,
  onOpenChange,
  path,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  path: string
}) {
  const { csrf } = useOrganization()
  const client = useQueryClient()
  const request = useRef<{ key: string; id: string } | null>(null)
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: { email: '', name: '' },
  })
  const invite = useMutation({
    mutationFn: (value: z.infer<typeof schema>) => {
      const key = JSON.stringify(value)
      if (request.current?.key !== key)
        request.current = { key, id: crypto.randomUUID() }
      return api<Schema['InvitationView']>(
        path + '/invitations',
        'POST',
        { ...value, request_id: request.current.id },
        csrf
      )
    },
    onSuccess: async (result) => {
      if (result.mail_status === 'submitted')
        toast.success('邀请邮件已提交，请在邀请记录中查看加入状态')
      else toast.error('邀请已创建，邮件提交失败。请在邀请记录中重试')
      form.reset()
      request.current = null
      onOpenChange(false)
      await client.invalidateQueries({ queryKey: ['organization'] })
    },
  })
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!invite.isPending) onOpenChange(value)
      }}
    >
      <DialogContent
        className='sm:max-w-md'
        onPointerDownOutside={(event) => {
          if (form.formState.isDirty || invite.isPending) event.preventDefault()
        }}
      >
        <DialogHeader>
          <DialogTitle>邀请成员</DialogTitle>
          <DialogDescription>
            邀请对方加入当前组织。加入后可由管理员调整角色。
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            id='invite-member'
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit((value) => invite.mutate(value))}
          >
            <FormField
              control={form.control}
              name='email'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>邮箱</FormLabel>
                  <FormControl>
                    <Input
                      type='email'
                      placeholder='name@example.com'
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>姓名（选填）</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <p className='text-sm text-muted-foreground'>加入角色：普通成员</p>
            {invite.isError && <RequestError error={invite.error} />}
          </form>
        </Form>
        <DialogFooter>
          <Button
            variant='outline'
            disabled={invite.isPending}
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button
            type='submit'
            form='invite-member'
            disabled={invite.isPending}
          >
            {invite.isPending ? '正在发送…' : '发送邀请'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
export function InvitationAction({
  invitation,
  path,
}: {
  invitation: Schema['InvitationView']
  path: string
}) {
  const { csrf } = useOrganization()
  const client = useQueryClient()
  const [operation, setOperation] = useState<
    'retry' | 'resend' | 'revoke' | null
  >(null)
  const id = useRef('')
  const mutation = useMutation({
    mutationFn: () =>
      api<Schema['InvitationView']>(
        path +
          '/invitations/' +
          invitation.id +
          (operation === 'revoke' ? '/revoke' : '/delivery'),
        'POST',
        operation === 'revoke'
          ? undefined
          : { request_id: id.current, replace: operation === 'resend' },
        csrf
      ),
    onSuccess: async (result) => {
      setOperation(null)
      await client.invalidateQueries({ queryKey: ['organization'] })
      if (result.mail_status === 'failed' && result.status !== 'revoked')
        toast.error('邮件提交失败，请稍后重试')
    },
  })
  const choose = (value: typeof operation) => {
    mutation.reset()
    id.current = crypto.randomUUID()
    setOperation(value)
  }
  if (!['pending', 'expired'].includes(invitation.status)) return null
  const names = { retry: '重试发送', resend: '重发邀请', revoke: '撤销邀请' }
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size='icon'
            variant='ghost'
            aria-label={'管理邀请 ' + invitation.email}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end'>
          <DropdownMenuGroup>
            <DropdownMenuItem
              onSelect={() =>
                choose(
                  invitation.mail_status === 'failed' &&
                    invitation.status !== 'expired'
                    ? 'retry'
                    : 'resend'
                )
              }
            >
              {invitation.mail_status === 'failed' &&
              invitation.status !== 'expired'
                ? '重试发送'
                : '重发邀请'}
            </DropdownMenuItem>
            <DropdownMenuItem
              variant='destructive'
              onSelect={() => choose('revoke')}
            >
              撤销邀请
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <AlertDialog
        open={operation !== null}
        onOpenChange={(open) => {
          if (!open && !mutation.isPending) setOperation(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {operation ? names[operation] : '邀请操作'}？
            </AlertDialogTitle>
            <AlertDialogDescription>
              {invitation.email}。
              {operation === 'revoke'
                ? '撤销后原邀请链接将失效。'
                : operation === 'resend'
                  ? '生成新的邀请链接，原链接将失效。'
                  : '重新提交尚未成功发送的邀请邮件。'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {mutation.isError && <RequestError error={mutation.error} />}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={mutation.isPending}>
              取消
            </AlertDialogCancel>
            <Button
              variant={operation === 'revoke' ? 'destructive' : 'default'}
              disabled={mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? '正在处理…' : '确认'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
