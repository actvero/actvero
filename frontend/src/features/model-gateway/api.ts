import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type GatewayState = {
  configured: boolean
  connected: boolean
  error: string | null
  console_url?: string | null
}
export type Channel = {
  id: number
  name: string
  type: number
  base_url: string | null
  status: number
  models: string
  model_mapping: string | null
  group: string
  priority: number | null
  weight: number
  tag: string | null
  test_model: string | null
  auto_ban: number
  param_override: string | null
  status_code_mapping: string | null
  response_time: number
  test_time: number
  created_time?: number
  balance?: number | null
  used_quota?: number | null
  revision: string
}
export type Model = {
  id: number
  model_name: string
  description: string
  icon: string
  tags: string
  vendor_id: number
  endpoints: string
  status: number
  sync_official: number
  name_rule: number
  revision: string
  has_metadata: boolean
  bound_channels: { name: string; type: number }[] | null
  enable_groups: string[] | null
  configured_channel_count: number
  square_state: string
}
export type Page<T> = { items: T[]; total: number }
export type Directory = { models: string[]; fetched_at: string | null }
export type Mapping = {
  channel: Channel
  associated: boolean
  upstream_id: string
}
export type Vendor = { id: number; name: string }
export type Reference = {
  source: { version: string }
  candidates: {
    model_name: string
    kind: string
    record_version: string
    fields: { field: string; local: unknown; upstream: unknown }[]
    upstream: {
      description: string
      icon: string
      tags: string
      vendor: string
      endpoints: string
      name_rule: number
      status: number
    }
  }[]
}
export type PriceValues = Record<
  string,
  number | string | Record<string, string>
>
export type PriceEntry = {
  model_name: string
  version: string
  configured: PriceValues
  effective: PriceValues
  billing_details: unknown
}
export type Prices = {
  entries: PriceEntry[]
  quota_per_unit: number
  empty_version: string
}
export async function gateway<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  csrf?: string
): Promise<T> {
  const result = await api<{ data: T }>(
    '/model-gateway' + path,
    method,
    body,
    csrf
  )
  return result.data
}
export function useGateway<T>(
  path: string,
  enabled = true,
  retainPrevious = false
) {
  const { organization } = useOrganization()
  return useQuery({
    queryKey: ['model-gateway', organization.tenant_id, path],
    queryFn: () => gateway<T>(path),
    enabled,
    retry: false,
    placeholderData: (previous, previousQuery) =>
      retainPrevious && previousQuery?.queryKey[1] === organization.tenant_id
        ? previous
        : undefined,
  })
}
export function useGatewayRefresh() {
  const client = useQueryClient()
  return () => client.invalidateQueries({ queryKey: ['model-gateway'] })
}
export const splitNames = (value: string) => [
  ...new Set(
    value
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter(Boolean)
  ),
]
export const channelTypes = [
  [1, 'OpenAI / OpenAI 兼容'],
  [43, 'DeepSeek'],
  [14, 'Anthropic'],
  [24, 'Google Gemini'],
  [17, '阿里云百炼'],
  [45, '火山方舟'],
  [40, '硅基流动'],
  [25, 'Moonshot'],
  [26, '智谱'],
  [20, 'OpenRouter'],
  [48, 'xAI'],
  [42, 'Mistral'],
  [35, 'MiniMax'],
  [34, 'Cohere'],
  [38, 'Jina'],
  [60, 'New API'],
  [62, 'vLLM'],
  [63, 'SGLang'],
] as const
export const channelTypeName = (type: number) =>
  channelTypes.find((x) => x[0] === type)?.[1] ?? `渠道类型 ${type}`
