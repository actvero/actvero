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
export type RetrievalPolicy = Schema['RetrievalPolicy']
export type Defaults = Schema['KnowledgeDefaultsView']
export const defaultsPath = '/knowledge/defaults'
export const retrievalLabels = {
  keyword: '关键词检索',
  vector: '向量检索',
  hybrid: '混合检索',
} as const
export function organizationRetrieval(data: Defaults): RetrievalPolicy {
  return {
    mode: data.embedding_model_id ? 'hybrid' : 'keyword',
    embedding_model_id: data.embedding_model_id ?? null,
    rerank_model_id: data.rerank_enabled ? data.rerank_model_id : null,
    vector_weight: 50,
  }
}
export function retrievalError(value: RetrievalPolicy, data: Defaults) {
  if (
    value.mode !== 'keyword' &&
    !data.models.some(
      (model) =>
        model.kind === 'embedding' && model.id === value.embedding_model_id
    )
  )
    return '请选择可用的向量模型'
  if (
    value.rerank_model_id &&
    !data.models.some(
      (model) => model.kind === 'rerank' && model.id === value.rerank_model_id
    )
  )
    return '请选择可用的重排模型，或关闭重排序'
}
export type Document = Schema['DocumentView']
export type Citation = Schema['CitationView']
export const initial: BaseInput = {
  name: '',
  description: '',
  audience: 'administrators',
  member_ids: [],
  department_grants: [],
  chunking: {
    structure: 'general',
    mode: 'smart',
    target_chars: 1200,
    max_chars: 1800,
    overlap_chars: 100,
    child_chars: 500,
  },
}
export const chunkNumbers = {
  target_chars: { initial: 1200, min: 100, max: 6000 },
  max_chars: { initial: 1800, min: 100, max: 10000 },
  child_chars: { initial: 350, min: 50, max: 2000 },
  overlap_chars: { initial: 100, min: 0, max: 1000 },
}

export function chunkingError(value: Chunking) {
  const number = (key: keyof typeof chunkNumbers) =>
    value[key] ?? chunkNumbers[key].initial
  for (const key of Object.keys(
    chunkNumbers
  ) as (keyof typeof chunkNumbers)[]) {
    const { min, max } = chunkNumbers[key]
    if (
      !Number.isInteger(number(key)) ||
      number(key) < min ||
      number(key) > max
    )
      return { key, message: `请输入 ${min}–${max} 之间的整数。` }
  }
  if (value.mode !== 'normal' && number('target_chars') > number('max_chars'))
    return { key: 'max_chars', message: '上限须大于或等于目标字数。' }
  if (
    value.structure === 'parent_child' &&
    number('child_chars') >= number('max_chars')
  )
    return { key: 'child_chars', message: '子片须短于父片。' }
  const window =
    value.structure === 'parent_child'
      ? number('child_chars')
      : number('max_chars')
  if (value.mode === 'normal' && number('overlap_chars') >= window)
    return { key: 'overlap_chars', message: '重叠须短于切片。' }
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
  uncertain: '处理失败',
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
