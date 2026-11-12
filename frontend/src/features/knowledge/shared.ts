import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api, type Schema } from '@/lib/api'
import { useOrganization } from '@/features/auth/session'

export type Base = Schema['KnowledgeView']
export type BaseInput = Schema['KnowledgeCreate']
export type Chunking = Schema['Chunking']
export type Document = Schema['DocumentView']
export type Citation = Schema['CitationView']
export const initial: BaseInput = {
  name: '',
  description: '',
  audience: 'administrators',
  member_ids: [],
  department_grants: [],
  chunking: {
    mode: 'smart',
    target_chars: 1200,
    max_chars: 1800,
    overlap_chars: 100,
  },
}
export const states: Record<string, string> = {
  empty: '暂无文档',
  queued: '等待处理',
  parsing: '解析中',
  chunking: '切片中',
  indexing: '建立索引',
  waiting: '等待服务',
  ready: '可检索',
  processing: '处理中',
  attention: '需处理',
  unconfigured: '待配置向量',
  failed: '处理失败',
  uncertain: '待核对',
  cancelled: '已取消',
}
export const busy = (status: string) =>
  ['queued', 'parsing', 'chunking', 'indexing', 'waiting'].includes(status)
export function useKnowledge() {
  const { organization, user, csrf } = useOrganization()
  const client = useQueryClient()
  const key = ['organization', organization.tenant_id, user.id, 'knowledge']
  return {
    key,
    csrf,
    admin: organization.role === 'administrator',
    refresh: () => client.invalidateQueries({ queryKey: key }),
  }
}
export function useKnowledgeData<T>(
  path: string,
  poll = false,
  keepPrevious = false
) {
  const { key } = useKnowledge()
  return useQuery({
    queryKey: [...key, path],
    queryFn: ({ signal }) => api<T>(path, 'GET', undefined, undefined, signal),
    refetchInterval: poll ? 2000 : false,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  })
}
export function locationLabel(s: Schema['SourceLocation']) {
  return (
    [
      s.page ? `第 ${s.page} 页` : null,
      s.sheet,
      s.cell_range,
      s.line ? `第 ${s.line} 段 / 行` : null,
      s.heading,
    ]
      .filter(Boolean)
      .join(' · ') || `原文块 ${Number(s.block_id) + 1}`
  )
}
