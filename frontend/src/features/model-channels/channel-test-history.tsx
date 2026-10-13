import { useId, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ApiError, dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CollapsibleSection } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { FilterSelect } from '@/components/filter-select'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { channelPath } from './api'
import { DiagnosticEvidence } from './diagnostic-evidence'
import {
  meterLabel,
  operationLabels,
  type TestOperation,
} from './test-operations'

type Record = Schema['ChannelTestRecord']

function RecordSummary({ record }: { record: Record }) {
  return (
    <div className='flex min-w-0 flex-col gap-2 text-sm'>
      <p className='break-all'>
        {record.model} ·{' '}
        {operationLabels[record.operation as TestOperation] ?? record.operation}
      </p>
      <div className='flex flex-wrap items-center gap-2'>
        <Badge
          variant={
            record.status === 'success'
              ? 'success'
              : record.status === 'failure'
                ? 'destructive'
                : 'outline'
          }
        >
          {record.status === 'success'
            ? '成功'
            : record.status === 'failure'
              ? '失败'
              : '处理中／结果未确认'}
        </Badge>
        <span>
          {dateTime(record.tested_at)} · {record.duration_ms ?? '—'} ms
        </span>
        <Badge variant='outline'>
          配置 {record.channel_version ? `v${record.channel_version}` : '未知'}
        </Badge>
        {record.stale && <Badge variant='outline'>旧配置</Badge>}
        {record.stream != null && (
          <Badge variant='outline'>
            {record.stream ? '流式测试' : '非流式测试'}
          </Badge>
        )}
        {record.record_version === 'legacy_audit' && (
          <Badge variant='secondary'>历史审计记录</Badge>
        )}
      </div>
      <p className='text-muted-foreground'>
        {meterLabel(record.operation, record)}
      </p>
      {record.uncertain && <p>执行结果未确认，可能产生费用</p>}
      {record.error_code && <p className='break-all'>{record.error_code}</p>}
    </div>
  )
}

async function read<T>(
  path: string,
  signal: AbortSignal,
  forbidden: () => void
) {
  try {
    return await api<T>(path, 'GET', undefined, undefined, signal)
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 403) forbidden()
    throw cause
  }
}

export function ChannelTestHistory({
  id,
  revision,
  busy,
  initialOpen = false,
}: {
  id: string
  revision: number
  busy: boolean
  initialOpen?: boolean
}) {
  const { organization } = useOrganization()
  const versionId = useId()
  const [open, setOpen] = useState(initialOpen)
  const [page, setPage] = useState(1)
  const [operation, setOperation] = useState('')
  const [status, setStatus] = useState('')
  const [versionInput, setVersionInput] = useState('')
  const [version, setVersion] = useState('')
  const [versionError, setVersionError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [permissionLost, setPermissionLost] = useState(false)
  const params = new URLSearchParams({ page: String(page) })
  if (operation) params.set('operation', operation)
  if (status) params.set('status', status)
  if (version) params.set('channel_version', version)
  const queryString = params.toString()
  // The stable setter only latches a permission loss; it cannot change fetched data.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'channel-tests',
      id,
      revision,
      queryString,
    ],
    queryFn: ({ signal }) =>
      read<Record[]>(channelPath(id) + `/tests?${queryString}`, signal, () =>
        setPermissionLost(true)
      ),
    enabled: open && !busy && !permissionLost,
  })
  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- stable permission latch setter
  const detail = useQuery({
    queryKey: [
      'organization',
      organization.tenant_id,
      'channel-diagnostic',
      selected,
      revision,
    ],
    queryFn: ({ signal }) =>
      read<Schema['DiagnosticDetail']>(
        '/llm/diagnostics/' + selected,
        signal,
        () => setPermissionLost(true)
      ),
    enabled: !!selected && !busy && !permissionLost,
  })
  return (
    <CollapsibleSection title='测试记录' open={open} onOpenChange={setOpen}>
      <div className='flex min-w-0 flex-col gap-4'>
        <fieldset
          disabled={busy || permissionLost}
          className='flex flex-wrap items-end gap-2'
        >
          <FilterSelect
            label='操作'
            value={operation}
            onChange={(value) => {
              setOperation(value)
              setPage(1)
            }}
            options={Object.entries(operationLabels).map(([value, label]) => ({
              value,
              label,
            }))}
          />
          <FilterSelect
            label='结果'
            value={status}
            onChange={(value) => {
              setStatus(value)
              setPage(1)
            }}
            options={[
              { value: 'success', label: '成功' },
              { value: 'failure', label: '失败' },
              { value: 'unconfirmed', label: '结果未确认' },
            ]}
          />
          <form
            className='flex flex-wrap items-end gap-2'
            onSubmit={(event) => {
              event.preventDefault()
              const value = versionInput.trim()
              if (
                value &&
                (!/^[1-9]\d*$/.test(value) ||
                  !Number.isSafeInteger(Number(value)))
              ) {
                setVersionError('请输入正整数版本号，留空查看全部。')
                return
              }
              setVersionError('')
              setVersion(value)
              setPage(1)
            }}
          >
            <div className='grid gap-1'>
              <Label htmlFor={versionId}>配置版本</Label>
              <Input
                id={versionId}
                className='w-32'
                inputMode='numeric'
                value={versionInput}
                placeholder='全部版本'
                onChange={(event) => setVersionInput(event.target.value)}
                aria-invalid={!!versionError}
                aria-describedby={
                  versionError ? versionId + '-error' : undefined
                }
              />
            </div>
            <Button type='submit' variant='outline' size='sm'>
              筛选版本
            </Button>
          </form>
        </fieldset>
        {versionError && (
          <p id={versionId + '-error'} className='text-sm text-destructive'>
            {versionError}
          </p>
        )}
        <Button
          type='button'
          variant='outline'
          size='sm'
          disabled={busy || query.isFetching || permissionLost}
          onClick={() => void query.refetch()}
        >
          刷新记录
        </Button>
        {permissionLost ? (
          <RequestError
            error={
              query.error ??
              detail.error ??
              new Error('管理权限已变化，请返回渠道列表。')
            }
          />
        ) : query.isPending ? (
          <LoadingState />
        ) : query.error ? (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : !query.data?.length ? (
          <p className='text-sm text-muted-foreground'>暂无测试记录</p>
        ) : (
          query.data.map((row) => (
            <div
              key={row.request_id}
              className='flex min-w-0 flex-col gap-2 rounded-md border p-3'
            >
              <RecordSummary record={row} />
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <span className='font-mono text-xs break-all text-muted-foreground'>
                  {row.request_id}
                </span>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  disabled={busy}
                  onClick={() => setSelected(row.request_id)}
                >
                  查看结果
                </Button>
              </div>
            </div>
          ))
        )}
        <div className='flex items-center justify-between gap-2'>
          <Button
            type='button'
            variant='outline'
            size='sm'
            disabled={busy || query.isFetching || permissionLost || page === 1}
            onClick={() => setPage((value) => value - 1)}
          >
            上一页
          </Button>
          <span className='text-sm'>第 {page} 页</span>
          <Button
            type='button'
            variant='outline'
            size='sm'
            disabled={
              busy ||
              query.isFetching ||
              permissionLost ||
              !!query.error ||
              (query.data?.length ?? 0) < 20
            }
            onClick={() => setPage((value) => value + 1)}
          >
            下一页
          </Button>
        </div>
      </div>
      <Dialog
        open={!!selected}
        onOpenChange={(value) => {
          if (!value) setSelected(null)
        }}
      >
        <DialogContent className='max-h-[85dvh] overflow-y-auto sm:max-w-2xl'>
          <DialogHeader>
            <DialogTitle>测试结果详情</DialogTitle>
            <DialogDescription className='break-all'>
              请求 ID：{selected}
            </DialogDescription>
          </DialogHeader>
          {permissionLost ? (
            <RequestError
              error={
                detail.error ?? query.error ?? new Error('管理权限已变化。')
              }
            />
          ) : detail.isPending ? (
            <LoadingState />
          ) : detail.error ? (
            <RequestError
              error={detail.error}
              retry={() => void detail.refetch()}
            />
          ) : (
            detail.data && (
              <div className='flex min-w-0 flex-col gap-4'>
                <RecordSummary record={detail.data.record} />
                {detail.data.record.record_version === 'legacy_audit' && (
                  <p className='text-sm text-muted-foreground'>
                    此记录只有历史审计信息，没有完整的执行阶段证据。
                  </p>
                )}
                <DiagnosticEvidence
                  attempt={detail.data.record.attempt}
                  healthCertification={detail.data.record.health_certification}
                />
                {['image_generation', 'speech'].includes(
                  detail.data.record.operation
                ) && (
                  <p className='text-sm text-muted-foreground'>
                    历史媒体已过期。这里只保存测试元数据，无法重新预览或下载。
                  </p>
                )}
                <p className='text-sm text-muted-foreground'>
                  查看记录不会重新发送上游请求。
                </p>
              </div>
            )
          )}
        </DialogContent>
      </Dialog>
    </CollapsibleSection>
  )
}
