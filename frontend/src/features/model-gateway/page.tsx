import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { ModelCatalogPage } from '@/features/model-catalog/page'
import { ModelChannelsPage } from '@/features/model-channels/page'
import { useGatewayStatus } from './api'
import { GatewayChannels } from './channels'
import { GatewayModels } from './models'

export function GatewayPage({ view }: { view: 'models' | 'channels' }) {
  const state = useGatewayStatus()
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
