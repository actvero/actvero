import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, messageOf, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type Service = Schema['McpServiceView']
export type Capability = Schema['McpCapability']
export const kindNames = {
  tools: '工具',
  prompts: '提示词',
  resources: '资源',
  templates: '资源模板',
} as const
export const authNames = {
  none: '无需凭据',
  organization: '组织凭据',
  personal: '个人凭据',
  oauth: '个人 OAuth',
}
export function useMcp() {
  const { organization, user, csrf } = useOrganization()
  const client = useQueryClient()
  const key = ['organization', organization.tenant_id, user.id, 'mcp']
  return {
    key,
    csrf,
    rememberSaved: (services: Service[]) => {
      client.setQueryData<Schema['McpServicePage']>(
        [...key, 'services'],
        (page) => ({
          items: [
            ...(page?.items ?? []).map(
              (item) => services.find((s) => s.id === item.id) ?? item
            ),
            ...services.filter(
              (s) => !page?.items.some((item) => item.id === s.id)
            ),
          ],
        })
      )
    },
    discoverSaved: async (services: Service[]) => {
      // Discovery outlives the configuration dialog, scoped to this member and tenant.
      const ready = services.filter(
        (service) =>
          service.configured &&
          !client.getQueryData<DiscoveryState>([
            ...key,
            service.id,
            'discovery',
          ])?.connecting
      )
      for (const service of ready)
        client.setQueryData<DiscoveryState>([...key, service.id, 'discovery'], {
          connecting: true,
          error: null,
        })
      let failed = 0
      let next = 0
      await Promise.all(
        Array.from({ length: Math.min(3, ready.length) }, async () => {
          while (next < ready.length) {
            const service = ready[next++]
            let error: string | null
            try {
              const catalog = await api<Schema['McpCapabilities']>(
                '/mcp/services/' + service.id + '/discover',
                'POST',
                undefined,
                csrf
              )
              client.setQueryData([...key, service.id, 'capabilities'], catalog)
              error = catalog.error ?? null
            } catch (e) {
              error = messageOf(e)
            }
            if (error) failed++
            await Promise.all([
              client.invalidateQueries({ queryKey: [...key, 'services'] }),
              client.invalidateQueries({
                queryKey: [...key, service.id, 'capabilities'],
              }),
            ])
            client.setQueryData<DiscoveryState>(
              [...key, service.id, 'discovery'],
              { connecting: false, error }
            )
          }
        })
      )
      return failed
    },
    invalidate: () => client.invalidateQueries({ queryKey: key }),
    write: <T>(path: string, method: string, body?: unknown) =>
      api<T>('/mcp' + path, method, body, csrf),
  }
}

type DiscoveryState = { connecting: boolean; error: string | null }
export function useDiscovery(id: string) {
  const { key } = useMcp()
  return useQuery<DiscoveryState>({
    queryKey: [...key, id, 'discovery'],
    queryFn: () => ({ connecting: false, error: null }),
    enabled: false,
    gcTime: Infinity,
  }).data
}

export { useReturnFocus } from '@/hooks/use-return-focus'

export function serviceInput(service: Service): Schema['McpServiceInput'] {
  const {
    id: _id,
    version: _version,
    configured: _configured,
    checked_at: _checked,
    health_checked_at: _healthChecked,
    health_error: _healthError,
    error: _error,
    protocol: _protocol,
    counts: _counts,
    ...input
  } = service
  return input
}
export const serviceName = (service: Service) =>
  service.display_name || service.name
