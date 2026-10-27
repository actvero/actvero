import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  MutationCache,
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { PageFooterProvider } from '@/vendor/newapi/components/layout/components/page-footer'
import { Button } from '@/vendor/newapi/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/vendor/newapi/components/ui/tabs'
import { ModelsDialogs } from '@/vendor/newapi/features/models/components/models-dialogs'
import { ModelsPrimaryButtons } from '@/vendor/newapi/features/models/components/models-primary-buttons'
import {
  ModelsProvider,
  useModels,
} from '@/vendor/newapi/features/models/components/models-provider'
import { ModelsTable } from '@/vendor/newapi/features/models/components/models-table'
import { VendorsTable } from '@/vendor/newapi/features/models/components/vendors-table'
import type { Model } from '@/vendor/newapi/features/models/types'
import { statusQueryOptions } from '@/vendor/newapi/lib/status-query'
import { Plus } from 'lucide-react'
import { PageShell } from '@/components/layout/page-shell'
import { LoadingState, RequestError } from '@/components/request-state'
import { useOrganization } from '@/features/auth/session'
import { useAccessColumns } from './access-columns'
import type { GatewayState } from './api'
import { bindNativeAdministrator } from './native-session'
import { ModelPublication } from './publication'

const route = getRouteApi('/_authenticated/models')

export function NativeModelManagement() {
  const { csrf, organization } = useOrganization()
  const hostClient = useQueryClient()
  const consoleUrl =
    hostClient.getQueryData<GatewayState>([
      'model-gateway',
      organization.tenant_id,
      'status',
    ])?.console_url ?? ''
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<unknown>()
  const [accessRequest, setAccessRequest] = useState<Model | null>(null)
  const handledAccess = useCallback(() => setAccessRequest(null), [])
  const { accessColumns, onModelsVisible } = useAccessColumns(setAccessRequest)
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            meta: { organizationId: organization.tenant_id },
          },
        },
        mutationCache: new MutationCache({
          onSuccess: () => {
            void hostClient.invalidateQueries({ queryKey: ['model-gateway'] })
          },
        }),
      }),
    [organization.tenant_id, hostClient]
  )
  useEffect(() => {
    let active = true
    bindNativeAdministrator(csrf, consoleUrl)
    void queryClient
      .fetchQuery(statusQueryOptions)
      .then(() => {
        if (active) setReady(true)
      })
      .catch((err: unknown) => {
        if (active) setError(err)
      })
    return () => {
      active = false
      void queryClient.cancelQueries()
      queryClient.clear()
    }
  }, [csrf, consoleUrl, queryClient])
  if (error) return <RequestError error={error} />
  if (!ready) return <LoadingState />
  return (
    <>
      <QueryClientProvider client={queryClient}>
        <ModelsProvider
          onManageAccess={setAccessRequest}
          accessColumns={accessColumns}
          onModelsVisible={onModelsVisible}
          renderAccess={(model, controls) => (
            <QueryClientProvider client={hostClient}>
              <ModelPublication model={model.model_name} {...controls} />
            </QueryClientProvider>
          )}
        >
          <NativeModelsContent />
          {accessRequest && (
            <OpenModelAccess model={accessRequest} onHandled={handledAccess} />
          )}
        </ModelsProvider>
      </QueryClientProvider>
    </>
  )
}

function OpenModelAccess({
  model,
  onHandled,
}: {
  model: Model
  onHandled: () => void
}) {
  const { setCurrentRow, setOpen } = useModels()
  useEffect(() => {
    setCurrentRow(model)
    setOpen('access-model')
    onHandled()
  }, [model, onHandled, setCurrentRow, setOpen])
  return null
}

function NativeModelsContent() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const section = search.section === 'vendors' ? 'vendors' : 'metadata'
  const { setOpen, setCurrentVendor, setTabCategory } = useModels()
  const [footer, setFooter] = useState<HTMLDivElement | null>(null)
  useEffect(() => setTabCategory(section), [section, setTabCategory])
  return (
    <PageFooterProvider container={footer}>
      <PageShell
        compact
        fixedContent
        title={section === 'vendors' ? '供应商管理' : '模型管理'}
        action={
          <div className='flex flex-wrap items-center gap-2'>
            {section === 'vendors' ? (
              <Button
                size='sm'
                onClick={() => {
                  setCurrentVendor(null)
                  setOpen('create-vendor')
                }}
              >
                <Plus />
                添加供应商
              </Button>
            ) : (
              <ModelsPrimaryButtons />
            )}
          </div>
        }
      >
        <Tabs
          value={section}
          onValueChange={(value) => {
            void navigate({
              search: (previous) => ({
                ...previous,
                section: value === 'vendors' ? 'vendors' : 'metadata',
              }),
            })
          }}
        >
          <TabsList>
            <TabsTrigger value='metadata'>模型</TabsTrigger>
            <TabsTrigger value='vendors'>供应商</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className='min-h-0 flex-1'>
          {section === 'vendors' ? <VendorsTable /> : <ModelsTable />}
        </div>
        <div ref={setFooter} className='shrink-0' />
      </PageShell>
      <ModelsDialogs />
    </PageFooterProvider>
  )
}
