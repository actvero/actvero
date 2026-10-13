import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { toast } from 'sonner'
import { api, dateTime, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ServerTable } from '@/components/data-table/server-table'
import { LoadingState, RequestError } from '@/components/request-state'

type Device = Schema['DeviceView']
const statuses = { active: '有效', expired: '已过期', revoked: '已退出' }

export function DeviceSettings({
  userId,
  csrf,
}: {
  userId: string
  csrf: string
}) {
  const [selected, setSelected] = useState<Device | null>(null)
  const [page, setPage] = useState(1)
  const trigger = useRef<HTMLButtonElement | null>(null)
  const refreshButton = useRef<HTMLButtonElement>(null)
  const client = useQueryClient()
  const key = ['account', userId, 'devices']
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      api<Schema['DeviceList']>(
        '/account/devices',
        'GET',
        undefined,
        undefined,
        signal
      ),
    refetchInterval: 30_000,
  })
  function close() {
    setSelected(null)
  }
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api<Schema['Message']>(
        '/account/devices/' + id,
        'DELETE',
        undefined,
        csrf
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: key })
      close()
      toast.success('该设备已退出')
    },
  })
  const resetRevoke = revoke.reset
  const columns = useMemo<ColumnDef<Device>[]>(
    () => [
      {
        accessorKey: 'name',
        header: '设备',
        cell: ({ row }) => (
          <span className='block max-w-40 truncate' title={row.original.name}>
            {row.original.name}
          </span>
        ),
      },
      { accessorKey: 'os', header: '系统' },
      {
        accessorKey: 'last_active_at',
        header: '最近活动',
        cell: ({ row }) => dateTime(row.original.last_active_at),
      },
      {
        accessorKey: 'status',
        header: '状态',
        cell: ({ row }) => (
          <Badge
            variant={row.original.status === 'active' ? 'secondary' : 'outline'}
          >
            {statuses[row.original.status]}
          </Badge>
        ),
      },
      {
        id: 'actions',
        header: '操作',
        cell: ({ row }) => (
          <Button
            variant='ghost'
            size='sm'
            disabled={row.original.status !== 'active'}
            aria-label={'退出设备 ' + row.original.name}
            onClick={(event) => {
              trigger.current = event.currentTarget
              resetRevoke()
              setSelected(row.original)
            }}
          >
            退出
          </Button>
        ),
      },
    ],
    [resetRevoke]
  )
  return (
    <>
      <div className='flex min-w-0 flex-col gap-4'>
        <div className='flex justify-end'>
          <Button
            ref={refreshButton}
            variant='outline'
            size='sm'
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            刷新
          </Button>
        </div>
        {query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <RequestError
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : (
          <ServerTable
            items={query.data.items.slice((page - 1) * 20, page * 20)}
            columns={columns}
            total={query.data.items.length}
            page={page}
            onPage={setPage}
            empty='尚无桌面登录设备'
          />
        )}
      </div>
      <ConfirmDialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open && !revoke.isPending) close()
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          const target = trigger.current
          if (target?.isConnected && !target.disabled) target.focus()
          else refreshButton.current?.focus()
        }}
        title='退出这台设备？'
        desc={
          selected
            ? `“${selected.name}”将停止访问组织服务，需要重新登录才能继续使用。其他设备和网页不受影响。`
            : ''
        }
        cancelBtnText='取消'
        confirmText={revoke.isPending ? '正在退出…' : '退出设备'}
        isLoading={revoke.isPending}
        handleConfirm={() => {
          if (selected) revoke.mutate(selected.id)
        }}
      >
        {revoke.isError && <RequestError error={revoke.error} />}
      </ConfirmDialog>
    </>
  )
}
