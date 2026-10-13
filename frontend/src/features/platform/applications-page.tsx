import { useState } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
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
  Form,
  FormField,
  FormItem,
  FormControl,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'

export function ApplicationsPage() {
  const { data: session } = useSession()
  const client = useQueryClient()
  const [decision, setDecision] = useState<{
    row: Schema['OpeningApplication']
    approve: boolean
  } | null>(null)
  const query = useQuery({
    queryKey: ['platform', 'applications'],
    queryFn: () =>
      api<Schema['OpeningApplicationPage']>('/platform/applications'),
  })
  const process = useMutation({
    mutationFn: (reason: string) =>
      api(
        `/platform/applications/${decision?.row.id}/decision`,
        'POST',
        { approve: decision?.approve, reason },
        session?.csrf
      ),
    onSuccess: async () => {
      setDecision(null)
      await client.invalidateQueries({ queryKey: ['platform'] })
      await client.invalidateQueries({ queryKey: ['session'] })
      toast.success('申请已处理')
    },
  })
  return (
    <PageShell title='开通申请'>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <div className='overflow-hidden rounded-md border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>组织名称</TableHead>
                <TableHead>申请人</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>申请时间</TableHead>
                <TableHead className='text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.items.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.organization_name}</TableCell>
                  <TableCell>
                    <div>{row.applicant_name}</div>
                    <div className='text-sm text-muted-foreground'>
                      {row.applicant_email}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        row.status === 'approved' ? 'success' : 'secondary'
                      }
                    >
                      {row.status === 'pending'
                        ? '待审核'
                        : row.status === 'approved'
                          ? '已通过'
                          : '已拒绝'}
                    </Badge>
                    {row.reason && (
                      <p className='max-w-64 text-sm text-muted-foreground'>
                        {row.reason}
                      </p>
                    )}
                  </TableCell>
                  <TableCell>{dateTime(row.created_at)}</TableCell>
                  <TableCell>
                    {row.status === 'pending' && (
                      <div className='flex justify-end gap-2'>
                        <Button
                          variant='outline'
                          size='sm'
                          onClick={() => {
                            process.reset()
                            setDecision({ row, approve: false })
                          }}
                        >
                          拒绝
                        </Button>
                        <Button
                          size='sm'
                          onClick={() => {
                            process.reset()
                            setDecision({ row, approve: true })
                          }}
                        >
                          通过
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {!query.data.total && (
                <TableRow>
                  <TableCell colSpan={5} className='h-24 text-center'>
                    暂无开通申请
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}
      {decision && (
        <DecisionForm
          approve={decision.approve}
          name={decision.row.organization_name}
          onClose={() => setDecision(null)}
          onSubmit={(reason) => process.mutate(reason)}
          pending={process.isPending}
          error={process.error}
        />
      )}
    </PageShell>
  )
}
function DecisionForm({
  approve,
  name,
  onClose,
  onSubmit,
  pending,
  error,
}: {
  approve: boolean
  name: string
  onClose: () => void
  onSubmit: (reason: string) => void
  pending: boolean
  error: unknown
}) {
  const schema = z.object({
    reason: approve
      ? z.string()
      : z.string().trim().min(1, '请填写拒绝原因').max(500),
  })
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: { reason: '' },
  })
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{approve ? '通过开通申请' : '拒绝开通申请'}</DialogTitle>
          <DialogDescription>
            {approve ? `将创建“${name}”，申请人成为组织管理员。` : name}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form
            className='flex flex-col gap-4'
            onSubmit={form.handleSubmit((values) => onSubmit(values.reason))}
          >
            {!approve && (
              <FormField
                control={form.control}
                name='reason'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>拒绝原因</FormLabel>
                    <FormControl>
                      <Textarea {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            {!!error && <RequestError error={error} />}
            <DialogFooter>
              <Button
                type='button'
                variant='outline'
                disabled={pending}
                onClick={onClose}
              >
                取消
              </Button>
              <Button disabled={pending}>
                {pending ? '处理中…' : approve ? '确认通过' : '确认拒绝'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
