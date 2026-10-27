import { useEffect, useMemo, useState } from 'react'
import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from '@tanstack/react-query'
import { NativeChannelsProvider } from '@/vendor/newapi/features/channels/components/channels-provider'
import { ChannelMutateDrawer } from '@/vendor/newapi/features/channels/components/drawers/channel-mutate-drawer'
import zh from '@/vendor/newapi/zh.json'
import nativeI18n from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { LoadingState } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { useGatewayRefresh, type Channel, type GatewayState } from './api'
import { bindNativeAdministrator } from './native-session'

export function NativeChannelEditor({
  channel,
  onClose,
}: {
  channel?: Channel
  onClose: () => void
}) {
  const { csrf, organization } = useOrganization()
  const refresh = useGatewayRefresh()
  const hostClient = useQueryClient()
  const consoleUrl =
    hostClient.getQueryData<GatewayState>([
      'model-gateway',
      organization.tenant_id,
      'status',
    ])?.console_url ?? ''
  const [ready, setReady] = useState(false)
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
  const i18n = useMemo(() => nativeI18n, [])
  useEffect(() => {
    let active = true
    bindNativeAdministrator(csrf, consoleUrl)
    void i18n
      .use(initReactI18next)
      .init({
        lng: 'zh',
        fallbackLng: 'zh',
        resources: { zh },
        keySeparator: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      })
      .then(() => {
        if (active) setReady(true)
      })
    return () => {
      active = false
      void queryClient.cancelQueries()
      queryClient.clear()
    }
  }, [csrf, i18n, queryClient, consoleUrl])
  const close = () => {
    void refresh()
    onClose()
  }
  if (!ready) return <LoadingState />
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <NativeChannelsProvider onClose={close} currentRow={channel}>
          <ChannelMutateDrawer
            open
            onOpenChange={(open) => {
              if (!open) close()
            }}
            currentRow={channel}
          />
        </NativeChannelsProvider>
      </QueryClientProvider>
    </I18nextProvider>
  )
}
