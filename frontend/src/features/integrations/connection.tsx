import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, messageOf, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { TableCell, TableRow } from '@/components/ui/table'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ListPagination } from '@/components/list-pagination'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { results, settlements } from '@/features/llm-calls/filters'
import {
  applicationSettings,
  applications,
  timestamp,
  type Application,
} from './data'
import { CopyButton, IntegrationTable, NoItems } from './shared'

export function ConnectionSettings({
  app,
  save,
}: {
  app: Application
  save: (input: Schema['ApplicationUpdate']) => Promise<void>
}) {
  const field = useId()
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const checkUrl = app.integration_base_url + '/me'
  const command =
    'curl --fail-with-body -H "Authorization: Bearer $ACTVERO_KEY" ' +
    "'" +
    checkUrl.replaceAll("'", "'\\''") +
    "'"

  async function changeStatus() {
    setBusy(true)
    try {
      await save({
        ...applicationSettings(app),
        enabled: !app.enabled,
      })
      toast.success(app.enabled ? '应用已停用' : '应用已启用')
      setConfirm(false)
    } catch (error) {
      toast.error(messageOf(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className='flex max-w-3xl flex-col gap-5'>
      <Card>
        <CardHeader>
          <div className='flex items-center justify-between gap-3'>
            <CardTitle>连接信息</CardTitle>
            <Button asChild variant='outline' size='sm'>
              <a href='/api/docs' target='_blank' rel='noreferrer'>
                API 文档
              </a>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor={field + '-api'}>集成 API 地址</FieldLabel>
              <div className='flex flex-wrap items-center gap-2'>
                <Input
                  id={field + '-api'}
                  className='min-w-0 flex-1 font-mono'
                  value={app.integration_base_url}
                  readOnly
                />
                <CopyButton
                  value={app.integration_base_url}
                  label='复制集成 API 地址'
                />
              </div>
            </Field>
            <Field>
              <FieldLabel htmlFor={field}>模型服务地址</FieldLabel>
              <div className='flex flex-wrap items-center gap-2'>
                <Input
                  id={field}
                  className='min-w-0 flex-1 font-mono'
                  value={app.model_base_url}
                  readOnly
                />
                <CopyButton
                  value={app.model_base_url}
                  label='复制模型服务地址'
                />
              </div>
            </Field>
            <Field>
              <FieldLabel htmlFor={field + '-command'}>测试连接</FieldLabel>
              <div className='flex flex-wrap items-center gap-2'>
                <Input
                  id={field + '-command'}
                  className='min-w-0 flex-1 font-mono'
                  value={command}
                  readOnly
                />
                <CopyButton value={command} label='复制测试命令' />
              </div>
              <p className='text-sm text-muted-foreground'>
                在接入系统后端设置 ACTVERO_KEY 后运行此命令。
              </p>
            </Field>
          </FieldGroup>
        </CardContent>
      </Card>
      <div className='flex items-center justify-between gap-4'>
        <div className='flex flex-col gap-1'>
          <span className='text-sm font-medium'>应用状态</span>
          <span className='text-sm text-muted-foreground'>
            停用后，应用的所有密钥将暂停使用。
          </span>
        </div>
        <Button
          variant='outline'
          disabled={busy}
          onClick={() => (app.enabled ? setConfirm(true) : void changeStatus())}
        >
          {app.enabled ? '停用应用' : '启用应用'}
        </Button>
      </div>
      <ConfirmDialog
        open={confirm}
        onOpenChange={(open) => {
          if (!busy) setConfirm(open)
        }}
        title='停用应用'
        desc={`停用「${app.name}」后，通过其密钥发起的调用将被拒绝。`}
        destructive
        cancelBtnText='取消'
        confirmText={busy ? '停用中…' : '停用应用'}
        isLoading={busy}
        handleConfirm={() => void changeStatus()}
      />
    </div>
  )
}

export function ApplicationCalls({ app }: { app: Application }) {
  const { organization } = useOrganization()
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'integration-calls',
      app.id,
      page,
    ],
    queryFn: ({ signal }) =>
      api<Schema['CallPage']>(
        `${applications}/${app.id}/calls?page=${page}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  if (query.isPending) return <LoadingState />
  if (query.isError)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  if (!query.data.total) return <NoItems title='暂无调用记录' />
  return (
    <div className='flex flex-col gap-4'>
      <IntegrationTable headers={['模型', '调用时间', '结果', '结算', '金额']}>
        {query.data.items.map((call) => (
          <TableRow key={call.id}>
            <TableCell className='font-medium'>
              {call.model_name ?? '—'}
            </TableCell>
            <TableCell>{timestamp(call.created_at)}</TableCell>
            <TableCell>
              <Badge
                variant={
                  call.result_status === 'success' ? 'success' : 'secondary'
                }
              >
                {results[call.result_status]}
              </Badge>
            </TableCell>
            <TableCell>{settlements[call.settlement_status]}</TableCell>
            <TableCell className='tabular-nums'>
              {call.amount == null
                ? '—'
                : `${call.amount} ${call.currency ?? ''}`}
            </TableCell>
          </TableRow>
        ))}
      </IntegrationTable>
      <ListPagination
        total={query.data.total}
        page={page}
        pageCount={Math.ceil(query.data.total / query.data.page_size)}
        onPage={setPage}
      />
    </div>
  )
}
