import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock3, Copy, Link2, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { api, dateTime, type Schema } from '@/lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CopyableField } from '@/components/copyable-field'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import { MailTestForm } from './mail-settings-form'

const organizationSchema = z.object({
  expires_in_hours: z.number(),
  recipient_email: z.union([z.email('请填写有效邮箱'), z.literal('')]),
})

type OrganizationForm = z.infer<typeof organizationSchema>

export function OrganizationInvitationsPage() {
  const { data: session } = useSession()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [delivery, setDelivery] = useState('link')
  const [createdInvite, setCreatedInvite] = useState<
    Schema['OrganizationCreated'] | null
  >(null)
  const [mailInvitation, setMailInvitation] = useState<string | null>(null)
  const mail = useQuery({
    queryKey: ['platform', 'mail'],
    queryFn: () => api<Schema['MailSettingsView']>('/platform/mail'),
  })
  const invitations = useQuery({
    queryKey: ['platform', 'organization-invitations'],
    queryFn: () =>
      api<Schema['OrganizationInvitationPage']>(
        '/platform/organization-invitations'
      ),
  })
  const form = useForm<OrganizationForm>({
    resolver: zodResolver(organizationSchema),
    defaultValues: {
      expires_in_hours: 72,
      recipient_email: '',
    },
  })
  const create = useMutation({
    mutationFn: (values: OrganizationForm) =>
      api<Schema['OrganizationCreated']>(
        '/platform/organization-invitations',
        'POST',
        {
          expires_in_hours: values.expires_in_hours,
          recipient_email: delivery === 'email' ? values.recipient_email : null,
        },
        session?.csrf
      ),
    onSuccess: async (result) => {
      setCreatedInvite(result)
      setOpen(false)
      form.reset()
      await client.invalidateQueries({
        queryKey: ['platform', 'organizations'],
      })
      await client.invalidateQueries({
        queryKey: ['platform', 'organization-invitations'],
      })
      if (result.mail_status === 'failed')
        toast.error('邀请已生成，但邮件发送失败，可在列表中重试')
      else
        toast.success(
          result.mail_status === 'sent' ? '邀请邮件已发送' : '邀请已生成'
        )
    },
  })
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api<Schema['OrganizationInvitation']>(
        `/platform/organization-invitations/${id}/revoke`,
        'POST',
        undefined,
        session?.csrf
      ),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: ['platform', 'organization-invitations'],
      })
      toast.success('邀请已撤销')
    },
  })
  const copyExisting = useMutation({
    mutationFn: (id: string) =>
      api<Schema['OrganizationInvitationLink']>(
        `/platform/organization-invitations/${id}/link`,
        'POST',
        undefined,
        session?.csrf
      ),
    onSuccess: async (result) => {
      await navigator.clipboard.writeText(result.invite_url)
      toast.success('邀请链接已复制')
    },
  })
  return (
    <PageShell
      title='开通邀请'
      action={
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button>
              <Link2 data-icon='inline-start' />
              生成邀请
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>生成邀请</DialogTitle>
              <DialogDescription>
                收到邀请的人填写组织名称并登录或注册账号。
              </DialogDescription>
            </DialogHeader>
            <Form {...form}>
              <form
                className='flex flex-col gap-4'
                onSubmit={form.handleSubmit((values) => create.mutate(values))}
              >
                <Tabs
                  value={delivery}
                  onValueChange={(value) => {
                    setDelivery(value)
                    form.setValue('recipient_email', '')
                  }}
                >
                  <TabsList>
                    <TabsTrigger value='link'>链接邀请</TabsTrigger>
                    <TabsTrigger value='email' disabled={!mail.data?.enabled}>
                      邮件邀请
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
                {delivery === 'email' && (
                  <FormField
                    control={form.control}
                    name='recipient_email'
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>收件邮箱</FormLabel>
                        <FormControl>
                          <Input type='email' required {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
                <FormField
                  control={form.control}
                  name='expires_in_hours'
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>链接有效期</FormLabel>
                      <Select
                        value={String(field.value)}
                        onValueChange={(value) => field.onChange(Number(value))}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectGroup>
                            <SelectItem value='24'>24 小时</SelectItem>
                            <SelectItem value='72'>3 天</SelectItem>
                            <SelectItem value='168'>7 天</SelectItem>
                            <SelectItem value='720'>30 天</SelectItem>
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {create.isError && <RequestError error={create.error} />}
                <DialogFooter>
                  <Button
                    type='button'
                    variant='outline'
                    onClick={() => setOpen(false)}
                  >
                    取消
                  </Button>
                  <Button type='submit' disabled={create.isPending}>
                    {create.isPending
                      ? '正在生成…'
                      : delivery === 'email'
                        ? '生成并发送'
                        : '生成邀请链接'}
                  </Button>
                </DialogFooter>
              </form>
            </Form>
          </DialogContent>
        </Dialog>
      }
    >
      <Dialog
        open={Boolean(mailInvitation)}
        onOpenChange={(value) => {
          if (!value) setMailInvitation(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>发送组织邀请</DialogTitle>
            <DialogDescription>
              邀请将绑定收件邮箱，有效期保持不变。
            </DialogDescription>
          </DialogHeader>
          {mailInvitation && (
            <MailTestForm
              key={mailInvitation}
              invitation
              path={`/platform/organization-invitations/${mailInvitation}/delivery`}
            />
          )}
        </DialogContent>
      </Dialog>
      {createdInvite &&
        invitations.data?.items.some(
          (item) =>
            item.id === createdInvite.invitation.id &&
            item.status === 'pending' &&
            item.can_copy
        ) && (
          <Alert>
            <ShieldCheck />
            <AlertTitle>组织邀请链接已生成</AlertTitle>
            <AlertDescription>
              <CopyableField
                label='组织邀请链接'
                hideLabel
                value={createdInvite.invite_url}
                copyLabel='复制链接'
              />
            </AlertDescription>
          </Alert>
        )}
      {(revoke.isError || copyExisting.isError) && (
        <RequestError error={revoke.error ?? copyExisting.error} />
      )}
      <div className='overflow-hidden rounded-md border'>
        {invitations.isPending ? (
          <LoadingState />
        ) : invitations.isError ? (
          <div className='p-6'>
            <RequestError
              error={invitations.error}
              retry={() => void invitations.refetch()}
            />
          </div>
        ) : invitations.data?.items.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className='px-6'>状态</TableHead>
                <TableHead>收件邮箱</TableHead>
                <TableHead>有效期至</TableHead>
                <TableHead>生成时间</TableHead>
                <TableHead className='px-6 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.data.items.map((invitation) => (
                <TableRow key={invitation.id}>
                  <TableCell className='px-6 py-4'>
                    <Badge
                      variant={
                        invitation.status === 'pending'
                          ? 'outline'
                          : invitation.status === 'accepted'
                            ? 'success'
                            : 'secondary'
                      }
                    >
                      {invitation.status === 'pending'
                        ? '待使用'
                        : invitation.status === 'accepted'
                          ? '已使用'
                          : invitation.status === 'revoked'
                            ? '已撤销'
                            : '已过期'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {invitation.recipient_email ?? '链接邀请'}
                  </TableCell>
                  <TableCell className='py-4 text-muted-foreground'>
                    <span className='inline-flex items-center gap-2'>
                      <Clock3 className='size-4' />
                      {dateTime(invitation.expires_at)}
                    </span>
                  </TableCell>
                  <TableCell className='py-4 text-muted-foreground'>
                    {dateTime(invitation.created_at)}
                  </TableCell>
                  <TableCell className='px-6 py-4 text-end'>
                    {invitation.status === 'pending' && (
                      <div className='flex justify-end gap-2'>
                        {invitation.can_copy && (
                          <Button
                            size='sm'
                            variant='ghost'
                            disabled={copyExisting.isPending}
                            onClick={() => copyExisting.mutate(invitation.id)}
                          >
                            <Copy data-icon='inline-start' />
                            复制
                          </Button>
                        )}
                        {invitation.can_copy && mail.data?.enabled && (
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            onClick={() => setMailInvitation(invitation.id)}
                          >
                            发送邮件
                          </Button>
                        )}
                        <Button
                          size='sm'
                          variant='outline'
                          disabled={revoke.isPending}
                          onClick={() => revoke.mutate(invitation.id)}
                        >
                          撤销
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className='p-10 text-center text-sm text-muted-foreground'>
            还没有生成邀请。
          </div>
        )}
      </div>
    </PageShell>
  )
}
