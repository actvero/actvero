import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

type DefaultedParameters =
  | 'capabilities'
  | 'retrieval'
  | 'speech'
  | 'image'
  | 'transcription'
  | 'chat_policy'
// Nested request fields accept the server's defaults, while generated response types are complete.
export type PublicationDraft = Omit<
  Schema['PublicationInput'],
  DefaultedParameters | 'reserve_usd'
> & {
  [K in DefaultedParameters]?: Partial<
    NonNullable<Schema['PublicationInput'][K]>
  >
}

export function usePublicationPreview(
  draft: PublicationDraft,
  memberId?: string
) {
  const { organization, csrf } = useOrganization()
  const serialized = JSON.stringify(draft)
  const [debounced, setDebounced] = useState(serialized)
  useEffect(() => {
    const timeout = window.setTimeout(() => setDebounced(serialized), 350)
    return () => clearTimeout(timeout)
  }, [serialized])
  const pending = debounced !== serialized
  // The CSRF token authenticates this read and is excluded from cache identity.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const query = useQuery({
    queryKey: [
      'model-gateway',
      organization.tenant_id,
      'publication-preview',
      debounced,
      memberId ?? null,
    ],
    queryFn: () =>
      api<Schema['PublicationPreview']>(
        '/model-gateway/publication/preview',
        'POST',
        { draft: JSON.parse(debounced), member_id: memberId || null },
        csrf
      ),
    enabled: !pending,
    retry: false,
    staleTime: 5000,
  })
  return { query, pending }
}
