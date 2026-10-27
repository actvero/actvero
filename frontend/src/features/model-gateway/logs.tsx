import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { ServerTable } from '@/components/data-table/server-table'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { gateway, useGateway, useGatewayRefresh, type Page } from './api'
import { EditorDialog } from './shared'

type NativeLog = {
  id: number
  created_at: number
  model_name: string
  channel_name: string
  request_id: string
  type: number
  prompt_tokens: number
  completion_tokens: number
  use_time: number
}
type Review = {
  id: string
  version: number
  model: string
  created_at: string
  reason: string
  request_id: string | null
}
export function GatewayLogsButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant='outline' onClick={() => setOpen(true)}>
        网关记录
      </Button>
      {open && (
        <EditorDialog title='网关记录' onClose={() => setOpen(false)} wide>
          <Tabs defaultValue='logs'>
            <TabsList>
              <TabsTrigger value='logs'>调用记录</TabsTrigger>
              <TabsTrigger value='review'>待核对账单</TabsTrigger>
            </TabsList>
            <TabsContent value='logs'>
              <NativeLogs />
            </TabsContent>
            <TabsContent value='review'>
              <Reviews />
            </TabsContent>
          </Tabs>
        </EditorDialog>
      )}
    </>
  )
}
function NativeLogs() {
  const [page, setPage] = useState(1)
  const query = useGateway<Page<NativeLog>>('/logs?page=' + page)
  if (query.isPending) return <LoadingState />
  if (query.error)
    return (
      <RequestError error={query.error} retry={() => void query.refetch()} />
    )
  return (
    <ServerTable
      items={query.data.items}
      total={query.data.total}
      page={page}
      onPage={setPage}
      empty='暂无网关调用记录。'
      columns={[
        {
          header: '时间',
          accessorKey: 'created_at',
          cell: ({ row }) =>
            new Date(row.original.created_at * 1000).toLocaleString('zh-CN'),
        },
        { header: '模型', accessorKey: 'model_name' },
        { header: '渠道', accessorKey: 'channel_name' },
        {
          header: '类型',
          id: 'type',
          cell: ({ row }) =>
            row.original.type === 2
              ? '消费'
              : row.original.type === 5
                ? '错误'
                : '记录',
        },
        {
          header: '输入 / 输出 Token',
          id: 'usage',
          cell: ({ row }) =>
            `${row.original.prompt_tokens ?? '—'} / ${row.original.completion_tokens ?? '—'}`,
        },
        {
          header: '请求标识',
          accessorKey: 'request_id',
          cell: ({ row }) => (
            <span className='font-mono text-xs break-all'>
              {row.original.request_id || '—'}
            </span>
          ),
        },
      ]}
    />
  )
}
function Reviews() {
  const { csrf } = useOrganization()
  const refresh = useGatewayRefresh()
  const [page, setPage] = useState(1)
  const query = useGateway<Page<Review>>('/settlements?page=' + page)
  const recheck = useMutation({
    mutationFn: (row: Review) =>
      gateway(
        `/settlements/${row.id}/recheck?version=${row.version}`,
        'POST',
        {},
        csrf
      ),
    onSuccess: () => refresh(),
  })
  return (
    <div className='flex flex-col gap-4 pt-4'>
      {recheck.error && <RequestError error={recheck.error} />}
      {query.isPending ? (
        <LoadingState />
      ) : query.error ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        <ServerTable
          items={query.data.items}
          total={query.data.total}
          page={page}
          onPage={setPage}
          empty='没有待核对的网关账单。'
          columns={[
            { header: '模型', accessorKey: 'model' },
            {
              header: '时间',
              accessorKey: 'created_at',
              cell: ({ row }) =>
                new Date(row.original.created_at).toLocaleString('zh-CN'),
            },
            { header: '状态说明', accessorKey: 'reason' },
            {
              header: '操作',
              id: 'action',
              cell: ({ row }) => (
                <Button
                  size='sm'
                  variant='outline'
                  disabled={recheck.isPending}
                  onClick={() => recheck.mutate(row.original)}
                >
                  重新核对账单
                </Button>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}
