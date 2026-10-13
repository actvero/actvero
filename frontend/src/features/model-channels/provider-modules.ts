import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'
import { providerAvatarPicker } from './provider-avatars'

export type ReferenceCatalog = NonNullable<
  Schema['ProviderView']['reference_catalog']
>

export type ProviderModule = Required<
  Omit<Schema['ProviderView'], 'reference_catalog'>
> &
  Pick<Schema['ProviderView'], 'reference_catalog'>

export function useProviderModules() {
  const { organization } = useOrganization()
  return useQuery({
    queryKey: ['organization', organization.tenant_id, 'llm-providers'],
    queryFn: ({ signal }) =>
      api<ProviderModule[]>(
        '/llm/providers',
        'GET',
        undefined,
        undefined,
        signal
      ),
    staleTime: 60_000,
  })
}

export function providerImage(provider?: ProviderModule) {
  return providerAvatarPicker.options.find(
    (item) => item.id === provider?.icon_key
  )?.image
}

export const apiLabels: Record<string, string> = {
  chat_completions: '对话',
  responses: 'Responses',
  embeddings: '文本向量',
  rerank: '重排',
}
