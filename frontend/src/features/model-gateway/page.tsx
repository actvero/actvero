import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { ModelCatalogPage } from '@/features/model-catalog/page'
import { ModelChannelsPage } from '@/features/model-channels/page'
import { type GatewayState } from './api'
import { GatewayChannels } from './channels'
import { GatewayModels } from './models'

export function GatewayPage({ view }: { view: 'models' | 'channels' }) {
  const { organization } = useOrganization()
  const state = useQuery({
    queryKey: ['model-gateway', organization.tenant_id, 'status'],
    queryFn: () => api<GatewayState>('/model-gateway/status'),
    retry: false,
  })
  if (state.isPending)
    return (
      <PageShell>
        <LoadingState />
      </PageShell>
    )
  if (state.error || (state.data.configured && !state.data.connected))
    return (
      <PageShell title='模型网关'>
        <RequestError
          error={
            state.error ?? new Error(state.data.error ?? '模型网关暂不可用')
          }
          retry={() => void state.refetch()}
        />
      </PageShell>
    )
  if (!state.data.configured)
    return view === 'models' ? <ModelCatalogPage /> : <ModelChannelsPage />
  return view === 'models' ? <GatewayModels /> : <GatewayChannels />
}
