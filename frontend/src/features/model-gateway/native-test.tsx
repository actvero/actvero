import { useEffect, useMemo } from 'react'
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from '@tanstack/react-query'
import { NativeChannelsProvider } from '@/vendor/newapi/features/channels/components/channels-provider'
import { ChannelTestDialog } from '@/vendor/newapi/features/channels/components/dialogs/channel-test-dialog'
import {
  bindNativeChannelSnapshot,
  bindNativeSession,
} from '@/vendor/newapi/lib/api'
import { useOrganization } from '@/features/auth/session'
import { type Channel, type GatewayState, useGatewayRefresh } from './api'

export function NativeChannelTest({
  channel,
  onClose,
}: {
  channel: Channel
  onClose: () => void
}) {
  const { csrf, organization } = useOrganization()
  const host = useQueryClient()
  const refresh = useGatewayRefresh()
  const queryClient = useMemo(
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
  const consoleUrl =
    host.getQueryData<GatewayState>([
      'model-gateway',
      organization.tenant_id,
      'status',
    ])?.console_url ?? ''
  useEffect(() => {
    bindNativeSession(csrf, consoleUrl)
    bindNativeChannelSnapshot(channel)
    return () => {
      void queryClient.cancelQueries()
      queryClient.clear()
    }
  }, [channel, csrf, consoleUrl, queryClient])
  const close = () => {
    void refresh()
    onClose()
  }
  return (
    <QueryClientProvider client={queryClient}>
      <NativeChannelsProvider currentRow={channel} onClose={close}>
        <ChannelTestDialog
          open
          onOpenChange={(open) => {
            if (!open) close()
          }}
        />
      </NativeChannelsProvider>
    </QueryClientProvider>
  )
}
