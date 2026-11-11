import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { api, dateTime } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { WorkbenchRuntimeConfig } from './runtime-config'
import { WorkbenchMetadataForm, WorkbenchScopeForm } from './settings'
import { audiences, useWorkbenches, type Workbench } from './shared'
import { WorkbenchStatusBadge } from './status-badge'
import { UploadWorkbenchDialog } from './upload-dialog'
import { WorkbenchVersions } from './versions'

export function WorkbenchDetail({ workbenchId }: { workbenchId: string }) {
  const { key } = useWorkbenches()
  const query = useQuery({
    queryKey: [...key, 'detail', workbenchId],
    queryFn: ({ signal }) =>
      api<Workbench>(
        `/workbenches/${workbenchId}`,
        'GET',
        undefined,
        undefined,
        signal
      ),
  })
  if (query.isPending)
    return (
      <PageShell title='工作台'>
        <LoadingState />
      </PageShell>
    )
  if (query.isError)
    return (
      <PageShell title='工作台'>
        <BackToWorkbenches />
        <RequestError error={query.error} retry={() => void query.refetch()} />
      </PageShell>
    )
  return <WorkbenchDetails key={workbenchId} item={query.data} />
}

function BackToWorkbenches() {
  return (
    <Button variant='ghost' size='sm' className='self-start' asChild>
      <Link to='/workbenches'>
        <ArrowLeft />
        返回工作台列表
      </Link>
    </Button>
  )
}

function WorkbenchDetails({ item }: { item: Workbench }) {
  const [tab, setTab] = useState('versions')
  return (
    <PageShell
      title={item.display_name}
      titleAfter={<WorkbenchStatusBadge status={item.status} />}
      description={item.package_name}
      action={
        <UploadWorkbenchDialog
          workbench={item}
          onUploaded={() => setTab('versions')}
        />
      }
    >
      <BackToWorkbenches />
      <dl className='grid gap-4 rounded-md border p-4 sm:grid-cols-3'>
        <div className='flex min-w-0 flex-col gap-1'>
          <dt className='text-sm text-muted-foreground'>当前发布版本</dt>
          <dd className='font-medium break-all'>
            {item.current_version ?? '暂无'}
          </dd>
        </div>
        <div className='flex flex-col gap-1'>
          <dt className='text-sm text-muted-foreground'>使用范围</dt>
          <dd className='font-medium'>
            {audiences[item.audience]}
            {item.audience === 'selected'
              ? `（${item.member_ids.length} 人）`
              : ''}
          </dd>
        </div>
        <div className='flex flex-col gap-1'>
          <dt className='text-sm text-muted-foreground'>更新时间</dt>
          <dd className='font-medium'>{dateTime(item.updated_at)}</dd>
        </div>
      </dl>
      <Tabs value={tab} onValueChange={setTab} className='gap-4'>
        <TabsList className='max-w-full'>
          <TabsTrigger value='versions'>版本管理</TabsTrigger>
          <TabsTrigger value='metadata'>基本资料</TabsTrigger>
          <TabsTrigger value='scope'>使用范围</TabsTrigger>
          <TabsTrigger value='config'>运行配置</TabsTrigger>
        </TabsList>
        <TabsContent value='versions'>
          <WorkbenchVersions item={item} />
        </TabsContent>
        <TabsContent value='metadata'>
          <WorkbenchMetadataForm key={item.revision} item={item} />
        </TabsContent>
        <TabsContent value='scope'>
          <WorkbenchScopeForm key={item.revision} item={item} />
        </TabsContent>
        <TabsContent value='config'>
          <WorkbenchRuntimeConfig item={item} />
        </TabsContent>
      </Tabs>
    </PageShell>
  )
}
