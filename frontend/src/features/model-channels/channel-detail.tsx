import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Pencil, RefreshCw } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { channelPath } from './api'
import { ChannelDiagnostics } from './channel-diagnostics'
import { DetailConnection } from './detail-connection'
import { DetailHealth } from './detail-health'
import { ModelInventory } from './model-inventory'
import { useProviderModules } from './provider-modules'
import {
  ChannelAvatar,
  HealthBadge,
  ManualBadge,
  type Channel,
  type Detail,
  type Discovery,
} from './shared'
import type { TestOperation } from './test-operations'

const tabs = ['connection', 'models', 'test', 'health']

export function ChannelDetail({
  id,
  initialTab,
  close,
  changed,
  edit,
  copy,
  status,
  archive,
  onTabChange,
  restoreFocus,
}: {
  id: string
  initialTab: string
  close: () => void
  changed: (channel: Detail) => void
  edit: (channel: Channel) => void
  copy?: (channel: Detail) => void
  status?: (channel: Detail) => void
  archive?: (channel: Detail) => void
  onTabChange?: (tab: string) => void
  restoreFocus: () => void
}) {
  const { csrf, organization } = useOrganization()
  const query = useQuery({
    queryKey: ['organization', organization.tenant_id, 'model-channels', id],
    queryFn: ({ signal }) =>
      api<Detail>(channelPath(id), 'GET', undefined, undefined, signal),
  })
  const [tab, setTab] = useState(
    tabs.includes(initialTab) ? initialTab : 'connection'
  )
  const [historyOpen, setHistoryOpen] = useState(false)
  const [testSelection, setTestSelection] = useState<{
    id: string
    operation: TestOperation
    bindingId?: string
    nonce: number
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [testBusy, setTestBusy] = useState(false)
  const controlsBusy = busy || testBusy
  const [error, setError] = useState<unknown>(null)
  const [permissionLost, setPermissionLost] = useState(false)
  const channel = query.data
  const providers = useProviderModules()
  const provider = providers.data?.find((item) => item.id === channel?.provider)
  // Administrators may explicitly diagnose an operation not opened to members.
  const testOperations = provider?.test_operations ?? []

  function changeTab(next: string) {
    if (busy) return
    setTab(next)
    onTabChange?.(next)
  }

  function updated(value: Detail) {
    changed(value)
    // Mutation responses omit read-only binding and diagnostic projections.
    void query.refetch()
  }
  async function check() {
    if (!channel || !provider?.model_discovery) return
    setBusy(true)
    setError(null)
    try {
      const result = await api<Discovery>(
        channelPath(id) + '/check',
        'POST',
        { version: channel.version },
        csrf
      )
      updated(result.channel)
      if (!result.ok) setError(new Error(result.message))
    } catch (cause) {
      setError(cause)
      if (cause instanceof ApiError && cause.status === 403) {
        setPermissionLost(true)
        void query.refetch()
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open && !busy) close()
      }}
    >
      <SheetContent
        className='w-full sm:max-w-3xl'
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          restoreFocus()
        }}
      >
        <SheetHeader>
          <div className='flex items-center gap-3 pr-6'>
            {channel && <ChannelAvatar channel={channel} />}
            <div className='min-w-0'>
              <SheetTitle className='truncate'>
                {channel?.name ?? '渠道详情'}
              </SheetTitle>
              <SheetDescription>
                {provider?.name ?? channel?.provider ?? '渠道配置'}
                {channel && ` · 配置 v${channel.version}`}
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>
        <div className='flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-6'>
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <RequestError
              error={query.error}
              retry={() => void query.refetch()}
            />
          ) : permissionLost ? (
            <RequestError
              error={error ?? new Error('管理权限已变化，请返回渠道列表。')}
            />
          ) : (
            channel && (
              <>
                <div className='flex flex-wrap items-center justify-between gap-3'>
                  <div className='flex flex-wrap items-center gap-2'>
                    <ManualBadge channel={channel} />
                    <HealthBadge channel={channel} />
                    {channel.archived && (
                      <span className='text-sm text-muted-foreground'>
                        已归档
                      </span>
                    )}
                  </div>
                  <div className='flex flex-wrap gap-2'>
                    {provider?.model_discovery && (
                      <Button
                        size='sm'
                        variant='outline'
                        disabled={controlsBusy || channel.archived}
                        onClick={() => void check()}
                      >
                        <RefreshCw />
                        {busy ? '处理中…' : '检查目录'}
                      </Button>
                    )}
                    {copy && (
                      <Button
                        size='sm'
                        variant='outline'
                        disabled={controlsBusy}
                        onClick={() => copy(channel)}
                      >
                        <Copy />
                        复制
                      </Button>
                    )}
                    <Button
                      size='sm'
                      variant='outline'
                      disabled={controlsBusy || channel.archived}
                      onClick={() => edit(channel)}
                    >
                      <Pencil />
                      编辑
                    </Button>
                    {status && !channel.archived && (
                      <Button
                        size='sm'
                        variant='outline'
                        disabled={controlsBusy}
                        onClick={() => status(channel)}
                      >
                        {channel.manual_enabled ? '停用' : '启用'}
                      </Button>
                    )}
                    {archive && (
                      <Button
                        size='sm'
                        variant='outline'
                        disabled={controlsBusy}
                        onClick={() => archive(channel)}
                      >
                        {channel.archived ? '恢复渠道' : '归档渠道'}
                      </Button>
                    )}
                  </div>
                </div>
                {!channel.binding_references?.some(
                  (reference) =>
                    !reference.model_archived &&
                    reference.model_enabled &&
                    reference.operation_enabled &&
                    reference.binding_enabled
                ) && (
                  <p className='text-sm text-muted-foreground'>
                    未关联可调用模型；库存登记不自动开放成员调用。
                  </p>
                )}
                {!!error && <RequestError error={error} />}
                <Tabs value={tab} onValueChange={changeTab} className='min-w-0'>
                  <div className='min-w-0 overflow-x-auto'>
                    <TabsList className='min-w-max'>
                      <TabsTrigger
                        value='connection'
                        disabled={busy && tab !== 'connection'}
                      >
                        连接信息
                      </TabsTrigger>
                      <TabsTrigger
                        value='models'
                        disabled={busy && tab !== 'models'}
                      >
                        上游模型（{channel.model_count}）
                      </TabsTrigger>
                      <TabsTrigger
                        value='test'
                        disabled={busy && tab !== 'test'}
                      >
                        测试与历史
                      </TabsTrigger>
                      <TabsTrigger
                        value='health'
                        disabled={busy && tab !== 'health'}
                      >
                        健康
                      </TabsTrigger>
                    </TabsList>
                  </div>
                  <TabsContent value='connection'>
                    <DetailConnection
                      channel={channel}
                      provider={provider}
                      showHistory={() => {
                        setHistoryOpen(true)
                        changeTab('test')
                      }}
                    />
                  </TabsContent>
                  <TabsContent value='models' className='min-w-0 pt-4'>
                    {provider ? (
                      <ModelInventory
                        channel={channel}
                        modelDiscovery={provider.model_discovery}
                        hasReferenceCatalog={!!provider.reference_catalog}
                        changed={updated}
                        busy={controlsBusy}
                        setBusy={setBusy}
                      />
                    ) : providers.isError ? (
                      <RequestError
                        error={providers.error}
                        retry={() => void providers.refetch()}
                      />
                    ) : (
                      <LoadingState />
                    )}
                  </TabsContent>
                  <TabsContent value='test' className='min-w-0 pt-4'>
                    <ChannelDiagnostics
                      key={`${channel.id}-${testSelection?.nonce ?? 0}`}
                      channel={channel}
                      operations={testOperations}
                      busy={controlsBusy}
                      setBusy={setTestBusy}
                      historyOpen={historyOpen}
                      initialModelId={testSelection?.id}
                      initialOperation={testSelection?.operation}
                      initialBindingId={testSelection?.bindingId}
                      onFinished={() => void query.refetch()}
                      onRefreshChannel={() => void query.refetch()}
                    />
                  </TabsContent>
                  <TabsContent value='health'>
                    <DetailHealth
                      channel={channel}
                      testOperations={testOperations}
                      showTest={(id, operation, bindingId) => {
                        setTestSelection((previous) => ({
                          id,
                          operation,
                          bindingId,
                          nonce: (previous?.nonce ?? 0) + 1,
                        }))
                        changeTab('test')
                      }}
                      onChanged={() => void query.refetch()}
                    />
                  </TabsContent>
                </Tabs>
              </>
            )
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
