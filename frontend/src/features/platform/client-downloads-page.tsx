import { useCallback, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Plus, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError, type Schema } from '@/lib/api'
import { useIsMobile } from '@/hooks/use-mobile'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ServerTable } from '@/components/data-table/server-table'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useSession } from '@/features/auth/session'
import {
  targetName,
  type Release,
  type Recommendation,
} from '@/features/client-downloads/data'
import { ClientReleaseEditor } from './client-release-editor'

const releaseStatusNames = {
  draft: '草稿',
  published: '已发布',
  withdrawn: '已下架',
} as const
const key = ['platform', 'client-downloads'] as const

export function ClientDownloadsSettingsPage() {
  const { data: session } = useSession()
  const client = useQueryClient()
  const mobile = useIsMobile()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [editing, setEditing] = useState<Release | 'new' | null>(null)
  const [denied, setDenied] = useState<unknown>(null)
  const [confirmation, setConfirmation] = useState<{
    row: Release
    action: 'withdraw' | 'delete'
  } | null>(null)
  const query = useQuery({
    queryKey: [...key, page, search, status],
    enabled: !denied,
    queryFn: ({ signal }) =>
      api<Schema['ReleasePage']>(
        '/platform/downloads?page=' +
          page +
          '&q=' +
          encodeURIComponent(search) +
          (status === 'all' ? '' : '&status=' + status),
        'GET',
        undefined,
        undefined,
        signal
      ),
    retry: false,
  })
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: key })
    await client.invalidateQueries({ queryKey: ['public', 'client-downloads'] })
  }
  const onDenied = useCallback(
    (error: unknown) => {
      setDenied(error)
      setEditing(null)
      setConfirmation(null)
      void client.cancelQueries({ queryKey: key }).then(() => {
        client.removeQueries({ queryKey: key })
        client.removeQueries({ queryKey: ['platform', 'release-events'] })
      })
    },
    [client]
  )
  useEffect(() => {
    if (
      query.error instanceof ApiError &&
      [401, 403].includes(query.error.status)
    )
      onDenied(query.error)
  }, [query.error, onDenied])
  const action = useMutation({
    mutationFn: async ({ row, action }: NonNullable<typeof confirmation>) =>
      api<unknown>(
        '/platform/downloads/' +
          row.id +
          (action === 'withdraw' ? '/withdraw' : ''),
        action === 'withdraw' ? 'POST' : 'DELETE',
        { expected_revision: row.revision },
        session?.csrf
      ),
    onSuccess: async () => {
      setConfirmation(null)
      toast.success('操作已完成')
      await refresh()
    },
    onError: (error) => {
      if (error instanceof ApiError && [401, 403].includes(error.status))
        onDenied(error)
      else void refresh()
    },
  })
  const forbiddenQuery =
    query.error instanceof ApiError && [401, 403].includes(query.error.status)
  const blocked = !!denied || forbiddenQuery
  const recommendations = query.data?.recommendations ?? []
  const columns: ColumnDef<Release>[] = [
    {
      header: '版本',
      cell: ({ row }) => (
        <Button variant='link' onClick={() => setEditing(row.original)}>
          v{row.original.version}
        </Button>
      ),
    },
    {
      header: '安装包',
      cell: ({ row }) => (
        <PackageLabels row={row.original} recommendations={recommendations} />
      ),
    },
    {
      header: '状态',
      cell: ({ row }) => (
        <Badge
          variant={
            row.original.status === 'published' ? 'success' : 'secondary'
          }
        >
          {releaseStatusNames[row.original.status]}
        </Badge>
      ),
    },
    { header: '发布日期', accessorKey: 'release_date' },
    { header: '操作', cell: ({ row }) => <Actions row={row.original} /> },
  ]
  function Actions({ row }: { row: Release }) {
    return (
      <div className='flex flex-wrap gap-1'>
        <Button size='sm' variant='ghost' onClick={() => setEditing(row)}>
          编辑
        </Button>
        {row.status === 'published' && (
          <Button
            size='sm'
            variant='ghost'
            onClick={() => {
              action.reset()
              setConfirmation({ row, action: 'withdraw' })
            }}
          >
            下架
          </Button>
        )}
        {row.status === 'draft' && (
          <Button
            size='sm'
            variant='ghost'
            onClick={() => {
              action.reset()
              setConfirmation({ row, action: 'delete' })
            }}
          >
            删除
          </Button>
        )}
      </div>
    )
  }
  return (
    <PageShell
      title='客户端下载'
      action={
        <>
          <Button asChild variant='outline'>
            <a href='/download' target='_blank' rel='noreferrer'>
              查看下载页
              <ExternalLink />
            </a>
          </Button>
          <Button
            disabled={
              blocked || query.isError || query.isPending || action.isPending
            }
            onClick={() => setEditing('new')}
          >
            <Plus />
            新建版本
          </Button>
        </>
      }
    >
      {blocked ? (
        <RequestError error={denied || query.error} />
      ) : (
        <>
          <div className='mb-6 flex flex-wrap gap-3'>
            <Input
              aria-label='搜索版本'
              placeholder='搜索版本号'
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              className='w-full sm:w-72'
            />
            <Select
              value={status}
              onValueChange={(value) => {
                setStatus(value)
                setPage(1)
              }}
            >
              <SelectTrigger aria-label='版本状态' className='w-40'>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value='all'>全部状态</SelectItem>
                {Object.entries(releaseStatusNames).map(([value, name]) => (
                  <SelectItem key={value} value={value}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {query.isPending && <LoadingState />}
          {query.isError && (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          )}
          {!query.isError && query.data && (
            <ServerTable
              items={query.data.items}
              columns={columns}
              total={query.data.total}
              page={page}
              onPage={setPage}
              empty='尚无客户端版本，请新建版本。'
              renderItems={
                mobile
                  ? (items) => (
                      <div className='flex flex-col gap-3'>
                        {items.length ? (
                          items.map((row) => (
                            <Card key={row.id}>
                              <CardHeader>
                                <CardTitle>
                                  v{row.version} ·{' '}
                                  {releaseStatusNames[row.status]}
                                </CardTitle>
                              </CardHeader>
                              <CardContent className='flex flex-col gap-3'>
                                <p className='text-sm text-muted-foreground'>
                                  {row.release_date}
                                </p>
                                <PackageLabels
                                  row={row}
                                  recommendations={recommendations}
                                />
                                <Actions row={row} />
                              </CardContent>
                            </Card>
                          ))
                        ) : (
                          <p className='py-10 text-center text-muted-foreground'>
                            尚无客户端版本，请新建版本。
                          </p>
                        )}
                      </div>
                    )
                  : undefined
              }
            />
          )}
          {editing && (
            <ClientReleaseEditor
              key={editing === 'new' ? 'new' : editing.id}
              saved={editing === 'new' ? null : editing}
              recommendations={recommendations}
              onClose={() => setEditing(null)}
              onChanged={refresh}
              onDenied={onDenied}
            />
          )}
          <ConfirmDialog
            open={!!confirmation}
            onOpenChange={(open) => {
              if (!open && !action.isPending) setConfirmation(null)
            }}
            title={
              confirmation?.action === 'withdraw'
                ? '下架客户端版本'
                : '删除版本草稿'
            }
            desc={
              confirmation?.action === 'withdraw'
                ? '下架后该版本的下载入口和推荐设置将被移除。'
                : '删除此草稿及安装包配置，已发布版本不受影响。'
            }
            confirmText={action.isPending ? '处理中…' : '确认'}
            cancelBtnText='取消'
            destructive
            isLoading={action.isPending}
            handleConfirm={() => {
              if (confirmation) action.mutate(confirmation)
            }}
          >
            {action.isError && <RequestError error={action.error} />}
          </ConfirmDialog>
        </>
      )}
    </PageShell>
  )
}

function PackageLabels({
  row,
  recommendations,
}: {
  row: Release
  recommendations: Recommendation[]
}) {
  return (
    <div className='flex flex-wrap gap-1'>
      {row.assets.length ? (
        row.assets.map((asset) => (
          <Badge key={targetName(asset)} variant='outline'>
            {targetName(asset)}
            {recommendations.some(
              (r) =>
                r.release_id === row.id &&
                r.platform === asset.platform &&
                r.architecture === asset.architecture
            )
              ? ' · 推荐'
              : ''}
          </Badge>
        ))
      ) : (
        <span className='text-muted-foreground'>未添加安装包</span>
      )}
    </div>
  )
}
