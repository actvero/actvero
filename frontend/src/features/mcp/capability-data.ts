import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, type Schema } from '@/lib/api'
import { useMcp, type Capability } from './shared'

export function useCapabilities(id: string) {
  const { key } = useMcp()
  return useQuery({
    queryKey: [...key, id, 'capabilities'],
    queryFn: ({ signal }) =>
      api<Schema['McpCapabilities']>(
        `/mcp/services/${id}/capabilities`,
        'GET',
        undefined,
        undefined,
        signal
      ),
    staleTime: 30_000,
  })
}
export function toolDefinition(item: Capability) {
  return {
    name: item.name,
    description: item.description,
    inputSchema: item.definition.inputSchema ?? {},
  }
}
export function useTokenCounts(items: Capability[] | undefined) {
  const { key } = useMcp()
  return useQuery({
    queryKey: [
      ...key,
      'token-estimates',
      items
        ?.filter((c) => c.kind === 'tools')
        .map((c) => [c.key, toolDefinition(c)]),
    ],
    enabled: !!items,
    staleTime: Infinity,
    queryFn: async () => {
      const { countTokens } = await import('gpt-tokenizer/encoding/cl100k_base')
      return Object.fromEntries(
        (items ?? [])
          .filter((c) => c.kind === 'tools')
          .map((c) => [
            c.key,
            countTokens(JSON.stringify(toolDefinition(c)), {
              disallowedSpecial: new Set(),
            }),
          ])
      )
    },
  }).data
}
export const shortTokens = (n: number) =>
  n >= 1000 ? `${Number((n / 1000).toFixed(1))}k` : String(n)
export async function copyText(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(`已复制${label}`)
  } catch {
    toast.error('复制失败，请检查浏览器剪贴板权限')
  }
}
