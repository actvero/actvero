import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { api, messageOf, type Schema } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { TableCell, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PageBack } from '@/components/layout/page-header'
import { PageShell } from '@/components/layout/page-shell'
import { ListPagination } from '@/components/list-pagination'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ApplicationCalls, ConnectionSettings } from './connection'
import {
  applicationPermissions,
  applications,
  timestamp,
  type Application,
} from './data'
import { ApplicationKeys } from './keys'
import { ApplicationPermissions } from './permissions'
import { IntegrationTable, NoItems } from './shared'

export function IntegrationsPage({
  appId,
  openApplication,
}: {
  appId?: string
  openApplication: (id?: string) => void
}) {
  const { organization, csrf } = useOrganization()
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, 'integrations', page],
    queryFn: ({ signal }) =>
      api<Schema['ApplicationPage']>(
        applications + '?page=' + page,
        'GET',
        undefined,
        undefined,
        signal
      ),
    enabled: !appId,
  })
  const client = useQueryClient()
  if (appId)
    return (
      <ApplicationDetail
        key={organization.tenant_id + appId}
        appId={appId}
        back={() => openApplication()}
      />
    )
  return (
    <PageShell
      title='应用集成'
      action={
        <Button onClick={() => setCreating(true)}>
          <Plus data-icon='inline-start' />
          创建应用
        </Button>
      }
    >
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : query.data.items.length === 0 ? (
        <NoItems
          title='暂无应用'
          detail='创建应用，为 Odoo、机器人或其他服务分配独立的访问权限。'
        />
      ) : (
        <>
          <IntegrationTable
            headers={['应用名称', '状态', '已授权能力', '最近使用', '操作']}
          >
            {query.data.items.map((app) => (
              <TableRow key={app.id}>
                <TableCell>
                  <Button
                    variant='link'
                    className='h-auto px-0'
                    onClick={() => openApplication(app.id)}
                  >
                    {app.name}
                  </Button>
                </TableCell>
                <TableCell>
                  <ApplicationBadge app={app} />
                </TableCell>
                <TableCell>
                  {applicationPermissions
                    .filter(({ read, write }) => app[read] || app[write])
                    .map(({ name }) => name)
                    .join('、') || '—'}
                </TableCell>
                <TableCell>{timestamp(app.last_used_at)}</TableCell>
                <TableCell>
                  <Button
                    variant='ghost'
                    size='icon-sm'
                    aria-label={`打开 ${app.name}`}
                    onClick={() => openApplication(app.id)}
                  >
                    <ArrowUpRight />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </IntegrationTable>
          <ListPagination
            total={query.data.total}
            page={page}
            pageCount={Math.ceil(query.data.total / 20)}
            onPage={setPage}
            unit='个应用'
          />
        </>
      )}
      {creating && (
        <CreateApplication
          csrf={csrf}
          close={() => setCreating(false)}
          created={(app) => {
            setCreating(false)
            void client.invalidateQueries({
              queryKey: [
                'organization',
                organization.tenant_id,
                'integrations',
              ],
            })
            openApplication(app.id)
          }}
        />
      )}
    </PageShell>
  )
}

function ApplicationBadge({ app }: { app: Application }) {
  return (
    <Badge variant={app.enabled ? 'success' : 'secondary'}>
      {app.enabled ? '启用' : '停用'}
    </Badge>
  )
}

function CreateApplication({
  csrf,
  close,
  created,
}: {
  csrf: string | undefined
  close: () => void
  created: (app: Application) => void
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) close()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建应用</DialogTitle>
        </DialogHeader>
        <form
          className='flex flex-col gap-4'
          onSubmit={async (event) => {
            event.preventDefault()
            if (!name.trim() || busy) return
            setBusy(true)
            try {
              created(
                await api<Application>(
                  applications,
                  'POST',
                  { name: name.trim() },
                  csrf
                )
              )
            } catch (error) {
              toast.error(messageOf(error))
            } finally {
              setBusy(false)
            }
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor='application-name'>应用名称</FieldLabel>
              <Input
                id='application-name'
                value={name}
                maxLength={100}
                placeholder='例如 Odoo 生产环境'
                onChange={(event) => setName(event.target.value)}
                required
              />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button
              variant='outline'
              type='button'
              onClick={close}
              disabled={busy}
            >
              取消
            </Button>
            <Button disabled={busy || !name.trim()}>
              {busy ? '创建中…' : '创建应用'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function ApplicationDetail({
  appId,
  back,
}: {
  appId: string
  back: () => void
}) {
  const { organization, csrf } = useOrganization()
  const client = useQueryClient()
  const path = applications + '/' + appId
  const queryKey = ['organization', organization.tenant_id, 'integration', path]
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      api<Application>(path, 'GET', undefined, undefined, signal),
  })
  const app = query.data
  const [tab, setTab] = useState('permissions')
  async function save(input: Schema['ApplicationUpdate']) {
    const result = await api<Application>(path, 'PUT', input, csrf)
    client.setQueryData<Application>(queryKey, (previous) => ({
      ...result,
      last_used_at: previous?.last_used_at ?? null,
    }))
    void client.invalidateQueries({
      queryKey: ['organization', organization.tenant_id, 'integrations'],
    })
  }
  return (
    <PageShell
      title={app?.name ?? '应用集成'}
      titleBefore={<PageBack onClick={back} label='返回应用集成' />}
      titleAfter={app && <ApplicationBadge app={app} />}
    >
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <RequestError error={query.error} retry={() => void query.refetch()} />
      ) : (
        app && (
          <Tabs value={tab} onValueChange={setTab} className='min-w-0 gap-5'>
            <TabsList
              variant='line'
              className='max-w-full flex-wrap self-start'
            >
              <TabsTrigger value='connection'>接入</TabsTrigger>
              <TabsTrigger value='permissions'>权限</TabsTrigger>
              <TabsTrigger value='keys'>密钥</TabsTrigger>
              <TabsTrigger value='calls'>调用记录</TabsTrigger>
            </TabsList>
            <TabsContent value='connection'>
              <ConnectionSettings app={app} save={save} />
            </TabsContent>
            <TabsContent value='permissions'>
              <ApplicationPermissions app={app} save={save} />
            </TabsContent>
            <TabsContent value='keys'>
              <ApplicationKeys app={app} />
            </TabsContent>
            <TabsContent value='calls'>
              <ApplicationCalls app={app} />
            </TabsContent>
          </Tabs>
        )
      )}
    </PageShell>
  )
}
