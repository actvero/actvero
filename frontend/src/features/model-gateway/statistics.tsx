import { useEffect, useMemo, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Dashboard } from '@/vendor/newapi/features/dashboard'
import type { DashboardSectionId } from '@/vendor/newapi/features/dashboard/section-registry'
import { statusQueryOptions } from '@/vendor/newapi/lib/status-query'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { useGatewayStatus } from './api'
import { NativeLanguage } from './native-language'
import { bindNativeAdministrator } from './native-session'

export function GatewayStatistics() {
  const { csrf, organization } = useOrganization()
  const status = useGatewayStatus()
  const [section, setSection] = useState<DashboardSectionId>('models')
  const [bootstrap, setBootstrap] = useState<{
    client: QueryClient
    error?: unknown
  }>()
  const [revision, setRevision] = useState(0)
  const client = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            meta: { organizationId: organization.tenant_id },
          },
        },
      }),
    [organization.tenant_id]
  )
  const ready = bootstrap?.client === client && !bootstrap.error
  const error = bootstrap?.client === client ? bootstrap.error : undefined
  useEffect(() => {
    if (!status.data?.connected) return
    let active = true
    bindNativeAdministrator(csrf, status.data.console_url ?? '')
    void client
      .fetchQuery(statusQueryOptions)
      .then(() => {
        if (active) setBootstrap({ client })
      })
      .catch((e: unknown) => {
        if (active) setBootstrap({ client, error: e })
      })
    return () => {
      active = false
      client.clear()
    }
  }, [client, csrf, status.data?.connected, status.data?.console_url, revision])
  if (status.isPending)
    return (
      <PageShell title='数据看板'>
        <LoadingState />
      </PageShell>
    )
  if (
    status.error ||
    error ||
    (status.data?.configured && !status.data.connected)
  )
    return (
      <PageShell title='数据看板'>
        <RequestError
          error={
            status.error ??
            error ??
            new Error(status.data?.error ?? '模型网关暂不可用')
          }
          retry={() => {
            setBootstrap(undefined)
            setRevision((value) => value + 1)
            void status.refetch()
          }}
        />
      </PageShell>
    )
  if (!status.data?.connected)
    return (
      <PageShell title='数据看板'>
        <Alert>
          <AlertDescription>
            连接 New API
            网关后可查看原生统计。成员积分与额度可在相应管理页面查看。
          </AlertDescription>
        </Alert>
      </PageShell>
    )
  if (!ready)
    return (
      <PageShell title='数据看板'>
        <LoadingState />
      </PageShell>
    )
  return (
    <PageShell title='数据看板' compact>
      <NativeLanguage>
        <QueryClientProvider key={organization.tenant_id} client={client}>
          <Dashboard section={section} onSectionChange={setSection} />
        </QueryClientProvider>
      </NativeLanguage>
    </PageShell>
  )
}
