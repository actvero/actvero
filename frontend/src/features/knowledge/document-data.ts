import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { busy, useKnowledge, type Document } from './shared'

export function documentNeedsAttention(doc: Document) {
  return ['failed', 'uncertain', 'unconfigured'].includes(doc.status)
}

export function documentNeedsProcessing(doc: Document) {
  return busy(doc.status) || documentNeedsAttention(doc)
}

export function useDocuments(baseId: string, enabled: boolean) {
  const { key } = useKnowledge()
  const path = `/knowledge/${baseId}/documents`
  return useQuery({
    queryKey: [...key, path],
    queryFn: ({ signal }) =>
      api<Document[]>(path, 'GET', undefined, undefined, signal),
    enabled,
    refetchInterval: ({ state }) =>
      state.data?.some((doc) => busy(doc.status)) ? 2000 : 15000,
  })
}
