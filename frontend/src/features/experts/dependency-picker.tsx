import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { LoadingState, RequestError } from '@/components/request-state'
import { ResourceIcon } from '@/components/resource-icon'
import { ServiceIcon } from '@/features/mcp/presentation'
import { useExperts } from './shared'

export function DependencyPicker({
  kind,
  close,
  select,
}: {
  kind: 'skills' | 'connectors'
  close: () => void
  select: (item: Schema['ExpertDependencyOption']) => void
}) {
  const { key } = useExperts()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [...key, 'dependencies', kind, q, page],
    queryFn: ({ signal }) =>
      api<Schema['ExpertDependencyPage']>(
        `/experts/dependencies?${new URLSearchParams({ kind, q, page: String(page) })}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className='flex max-h-[85dvh] flex-col sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>
            {kind === 'skills' ? '添加技能' : '添加连接器'}
          </DialogTitle>
          <DialogDescription>
            {kind === 'skills'
              ? '选择当前生效版本，发布后锁定此版本。'
              : '选择已登记的连接器，个人连接由使用者完成。'}
          </DialogDescription>
        </DialogHeader>
        <Input
          aria-label='搜索能力'
          placeholder='搜索…'
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setPage(1)
          }}
          maxLength={100}
        />
        <div className='flex min-h-0 flex-col gap-3 overflow-y-auto'>
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : query.data.items.length ? (
            query.data.items.map((item) => (
              <Card key={item.id} density='compact'>
                <CardHeader layout='row' className='gap-3 py-1'>
                  {kind === 'skills' ? (
                    <ResourceIcon image={item.icon} name={item.name} />
                  ) : (
                    <ServiceIcon icon={item.icon} name={item.name} size='md' />
                  )}
                  <div className='min-w-0 flex-1'>
                    <div className='flex flex-wrap items-center gap-2'>
                      <CardTitle size='body' className='break-words'>
                        {item.name}
                      </CardTitle>
                      {item.version && (
                        <Badge variant='secondary'>v{item.version}</Badge>
                      )}
                      {kind === 'connectors' && (
                        <Badge variant='outline'>
                          {item.status === 'unavailable'
                            ? '已关闭'
                            : `${(item.tools ?? []).filter((t) => t.enabled).length} 个可用工具`}
                        </Badge>
                      )}
                    </div>
                    <CardDescription className='mt-1 line-clamp-2 break-words'>
                      {item.description || '暂无简介'}
                    </CardDescription>
                  </div>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={() => {
                      select(item)
                      close()
                    }}
                    aria-label={`选择${item.name}`}
                  >
                    选择
                  </Button>
                </CardHeader>
              </Card>
            ))
          ) : (
            <p className='py-4 text-muted-foreground'>没有可选能力</p>
          )}
        </div>
        <DialogFooter>
          <Button
            type='button'
            variant='outline'
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
          >
            上一页
          </Button>
          <Button
            type='button'
            variant='outline'
            disabled={!query.data || page * 20 >= query.data.total}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
